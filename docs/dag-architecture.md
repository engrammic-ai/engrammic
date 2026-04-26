# DAG Architecture Discussion

**Status:** draft, needs discussion
**Date:** 2026-04-26

## Current State (contextr)

The existing Dagster setup has these assets:

```
ingestion_outbox_sensor
    └── triggers: ingest_asset
                      └── triggers: extraction_asset
                                        └── triggers: clustering_asset

custodian_sensor (separate)
    └── triggers: custodian_pass_result

heat_sensor (separate)
    └── triggers: heat_asset
```

**Problems with current DAG:**
1. Sensors trigger on outbox tables, not asset completion
2. Custodian runs independently, not chained to extraction
3. Heat runs on schedule, disconnected from usage
4. No clear "document lifecycle" path

## Proposed DAG Structure

### Option A: Linear Pipeline

```
Document Ingested
    │
    ▼
┌─────────────────┐
│  chunk_asset    │  Split into passages
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  embed_asset    │  Generate embeddings
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ extract_asset   │  Extract :Claim nodes
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ promote_asset   │  :Claim → :Fact (R1/R2)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ cluster_asset   │  Leiden clustering
└─────────────────┘

Parallel track (retrieval-driven):
┌─────────────────┐
│  heat_asset     │  Compute heat from retrieval events
└─────────────────┘
```

**Pros:** Clear, debuggable, each step observable
**Cons:** Sequential latency, can't parallelize embed+extract

### Option B: Parallel Where Possible

```
Document Ingested
    │
    ▼
┌─────────────────┐
│  chunk_asset    │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────────┐
│ embed │ │ extract   │   (parallel)
└───┬───┘ └─────┬─────┘
    │           │
    └─────┬─────┘
          ▼
   ┌─────────────────┐
   │ promote_asset   │   (needs both)
   └────────┬────────┘
            │
            ▼
   ┌─────────────────┐
   │ cluster_asset   │
   └─────────────────┘
```

**Pros:** Faster, embed and extract don't depend on each other
**Cons:** More complex dependency management

### Option C: Event-Driven (Outbox Pattern)

Keep the outbox sensor pattern but make it cleaner:

```
MCP ingest → writes to outbox → sensor picks up → triggers pipeline

Pipeline is a single job with partitioned assets:
- Partition by silo_id
- Each asset checks its upstream completion
```

**Pros:** Decoupled, scales horizontally
**Cons:** Harder to debug, outbox table management

## Questions to Decide

1. **Linear vs parallel?** (B is probably right)

2. **Where does Custodian fit?**
   - After clustering (visits clusters)?
   - Or is it replaced by promote_asset?

3. **Heat — scheduled or event-driven?**
   - Scheduled: simple, periodic refresh
   - Event-driven: recompute on retrieval (more accurate, more compute)

4. **Partitioning strategy?**
   - By silo_id (tenant isolation)
   - By document_id (fine-grained)
   - Hybrid?

5. **Backpressure?**
   - What happens when ingestion outpaces extraction?
   - Queue depth limits? Rate limiting?

## Recommendation

Start with **Option B** (parallel embed+extract), with:
- Partition by silo_id
- Custodian becomes promote_asset (simpler)
- Heat on 15-min schedule (not event-driven yet)
- Backpressure via Dagster's built-in concurrency limits

Revisit event-driven heat once retrieval volume justifies it.
