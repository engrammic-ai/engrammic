# DAG Architecture

**Status:** Shipped (v1-beta, consolidated 2026-05-13)
**Date:** 2026-05-13

## Design Principles

MCP tool writes (`context_store`, etc.) handle embedding inline and bypass Dagster entirely. The DAG handles background enrichment: custodian synthesis, fact promotion, clustering, and heat scoring.

## Consolidated Pipeline Chains

Assets are grouped into logical chains that respect dependencies. Each chain runs as a unit.

```
                    MCP context_store (inline embedding)
                              |
                              v
                    Memgraph + Qdrant (immediate)
                              |
      +-----------------------+-----------------------+
      |                       |                       |
      v                       v                       v
CUSTODIAN PIPELINE     KNOWLEDGE PIPELINE      HEAT PIPELINE
(every 15min)          (hourly)                (daily 02:00)
      |                       |                       |
custodian_visit        claim_to_fact_promotion       heat
      |                       |                       |
      v                       +---------+             v
custodian_finalize            |         |         edge_heat
      |                       v         v             |
      |              causal_transitivity              v
      |                       |         |      weak_link_review
      |                       v         v
      |              pattern_detection
      |                       |
      |                       v
      |              llm_pattern_detection
      |
      +---> CLUSTERING PIPELINE (daily 04:00)
                    |
               clustering
                    |
                    v
              chain_stitch
                    |
                    v
           proposal_detection
```

## Schedule Summary

| Schedule                      | Assets                                                                 | Cron               |
|-------------------------------|------------------------------------------------------------------------|--------------------|
| `custodian_pipeline_schedule` | custodian_visit -> custodian_finalize                                  | `*/15 * * * *`     |
| `knowledge_pipeline_schedule` | claim_to_fact_promotion -> causal_transitivity -> pattern_detection -> llm_pattern_detection | `0 * * * *` |
| `clustering_pipeline_schedule`| clustering -> chain_stitch -> proposal_detection                       | `0 4 * * *`        |
| `heat_pipeline_schedule`      | heat -> edge_heat -> weak_link_review                                  | `0 2 * * *`        |

### Maintenance Schedules (independent)

| Schedule                      | Asset                | Cron               |
|-------------------------------|----------------------|--------------------|
| `reasoning_compaction_schedule` | reasoning_compaction | `0 * * * *`      |
| `retention_schedule`          | retention_sweep      | `0 3 * * *`        |
| `auto_tagging_schedule`       | auto_tagging         | `*/30 * * * *`     |
| `tag_maintenance_schedule`    | tag_maintenance      | `0 3 * * *`        |
| `reconciliation_gc_schedule`  | reconciliation_gc    | `*/15 * * * *`     |
| `proposal_cleanup_schedule`   | proposal_cleanup     | `0 6 * * *`        |
| `groundskeeper_gc_schedule`   | groundskeeper_nightly (job) | `0 1 * * *`  |

## Concurrency Model

- **Per-silo isolation**: Schedules emit `RunRequest` with `tags={"dagster/concurrency_key": silo_id}` so one noisy silo cannot starve others.
- **LLM cap**: Assets calling LLMs respect a shared concurrency pool configured in `dagster.yaml`.

## Retry Policy

All assets use `RetryPolicy(max_retries=3, delay=10.0, backoff=Backoff.EXPONENTIAL)`. After retries exhaust, `poison_queue_sensor` writes failure info to Redis with 7-day TTL.

## Real-time vs Batch Split

| Path | Embedding | Use case |
|------|-----------|----------|
| MCP tools | Inline (sync) | Agent writes, needs immediate recall |
| Dagster | Backfill only | Bulk ingest, catchup |
