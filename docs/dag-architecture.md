# DAG Architecture

**Status:** Shipped (v1-beta)
**Date:** 2026-04-28

## Shipped DAG Shape

The pipeline follows Option B (parallel embed + extract) from the original discussion. Both extraction and embedding run in parallel, sensor-driven, as soon as documents arrive. All assets are partitioned by `silo_id`.

```
Document Ingested (via MCP context_remember / REST ingest)
    |
    |  document_arrival_sensor (polls every 60s per silo)
    |
    +-------------------+
    |                   |
    v                   v
extraction          embedding
(sensor-driven,     (sensor-driven,
 batched, ~5min)     batched, ~5min)
    |                   |
    +--------+----------+
             |
             v
      custodian_visit
      (scheduled, */15 * * * *)
             |
    +--------+----------+
    |                   |
    v                   v
custodian_finalize  claim_to_fact_promotion
(waits on visit)    (scheduled hourly,
                     waits on visit)
    |
    v
clustering
(scheduled daily 04:00 UTC,
 waits on custodian_finalize)
```

Note: extraction and embedding run in parallel with no inter-dependency. custodian_visit waits for both to complete before running.

## Asset Cadences

| Asset                    | Trigger                             | Cron / cadence             |
|--------------------------|-------------------------------------|----------------------------|
| extraction               | document_arrival_sensor             | Every ~5 min or N docs     |
| embedding                | document_arrival_sensor             | Every ~5 min (parallel)    |
| custodian_visit          | custodian_visit_schedule            | `*/15 * * * *` (15 min)    |
| custodian_finalize       | Depends on custodian_visit          | Follows visit schedule     |
| claim_to_fact_promotion  | fact_promotion_schedule             | `0 * * * *` (hourly)       |
| clustering               | clustering_schedule                 | `0 4 * * *` (daily 04 UTC) |
| heat                     | heat_schedule                       | `0 * * * *` (hourly)       |
| reasoning_compaction     | reasoning_compaction_schedule       | `0 * * * *` (hourly)       |
| retention_sweep          | retention_schedule                  | `0 3 * * *` (daily 03 UTC) |
| pattern_detection        | pattern_detection_schedule          | `0 5 * * *` (daily 05 UTC) |
| llm_pattern_detection    | Depends on pattern_detection        | Follows pattern_detection  |
| belief_synthesis         | belief_synthesis_sensor             | Event-driven (cluster density >= threshold) |
| causal_tombstone         | Manual / admin-triggered            | On demand                  |

## Concurrency Model

- **Per-asset concurrency key**: Each asset has a static `dagster/concurrency_key` tag (e.g. `extraction`, `embedding`, `clustering`). These keys bound concurrent runs of each asset type globally. Configure pool sizes in `dagster.yaml` under `concurrency`.
- **Per-silo isolation at run-request time**: Both schedules and the document-arrival sensor emit `RunRequest` objects with `tags={"dagster/concurrency_key": silo_id}`. This means a single noisy silo cannot starve runs for other silos. Both tags co-exist on each `RunRequest`.
- **LLM cap**: Bind `dagster/concurrency_key=llm_calls` in `dagster.yaml` to a small pool (e.g. 4). Assets that call LLMs (extraction, custodian_visit, clustering) respect this through the per-asset key.

## Retry Policy

All assets use `RetryPolicy(max_retries=3, delay=10.0, backoff=Backoff.EXPONENTIAL)`. Transient failures (network, timeouts) retry up to three times with exponential backoff starting at 10 seconds. After retries are exhausted the `poison_queue_sensor` fires on `DagsterRunStatus.FAILURE` and writes the run id, step key, and error message to Redis with a 7-day TTL under `dagster:poison:{asset_key}:{run_id}`.

## Real-time vs Batch Split

MCP tool writes (`context_remember`, `context_assert`, `context_commit`, `context_reflect`) bypass Dagster entirely — they go through `services/context.py::store()` synchronously. The DAG handles bulk ingest, custodian sweeps, and periodic clustering only.
