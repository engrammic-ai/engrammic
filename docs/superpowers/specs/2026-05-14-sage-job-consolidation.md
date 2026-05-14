# SAGE Job Consolidation

Consolidate 8 Dagster sensors into 3 cron-scheduled jobs under the SAGE umbrella system.

## Problem

Current state: 9 individual sensors triggering assets reactively. This creates:
- Unpredictable triggering cascades
- Complex debugging (which sensor fired what?)
- Many moving parts to monitor

## Solution

Replace sensors with 3 scheduled jobs that query for pending work and trigger partition runs.

## SAGE System

**SAGE** (Synthesis, Aggregation, and Graph Evolution) is the umbrella name for Engrammic's internal agent system. Sub-agents:

| Agent | Identity | Purpose |
|-------|----------|---------|
| sage.custodian | The Receiver | Ingests raw input, processes into structured knowledge |
| sage.synthesizer | The Distiller | Crystallizes higher-order knowledge from facts |
| sage.groundskeeper | The Maintainer | Keeps the graph healthy over time |
| sage.validator | The Verifier | Checks quality, tracks confidence (future) |

## Jobs

### sage_custodian_job

**Cadence:** Every 10 minutes

**Purpose:** Ingestion pipeline - gets things into the system correctly

**DAG chain:**
```
extraction
    |
embedding
    |
custodian_visit
    |
claim_to_fact_promotion
    |
custodian_finalize
    |
clustering
    |
proposal_detection
```

**Pending work query:** Silos with unprocessed documents or pending visits

### sage_synthesizer_job

**Cadence:** Every 30 minutes

**Purpose:** Belief formation - turns facts into wisdom

**DAG chain:**
```
causal_transitivity
    |
pattern_detection
    |
llm_pattern_detection
    |
belief_synthesis
    |
belief_merge
    |
chain_stitch
```

**Pending work query:** Silos with facts not yet synthesized into beliefs

### sage_groundskeeper_job

**Cadence:** Every 15 minutes

**Purpose:** Heat and maintenance - keeps the graph's vitals updated

**DAG chain:**
```
heat
    |
edge_heat
    |
heat_diffusion
    |
prewarm_sweep
```

**Pending work query:** Silos with stale heat scores or pending cleanup

## Implementation

### Schedule structure

```python
@dg.schedule(
    name="sage_custodian_schedule",
    cron_schedule="*/10 * * * *",
    execution_timezone="UTC",
)
def sage_custodian_schedule(context):
    silos = query_silos_with_pending_custodian_work()
    
    for silo_id in silos:
        yield dg.RunRequest(
            run_key=f"sage_custodian:{silo_id}:{context.scheduled_execution_time}",
            partition_key=silo_id,
            tags={"sage_job": "custodian"},
        )
```

### Job definition

```python
sage_custodian_job = dg.define_asset_job(
    name="sage_custodian_job",
    selection=[
        "extraction", "embedding", "custodian_visit",
        "claim_to_fact_promotion", "custodian_finalize",
        "clustering", "proposal_detection",
    ],
    partitions_def=silo_partitions,
)
```

### Error handling

- Each asset catches its own exceptions, logs, and returns partial results
- Job continues to next silo on failure
- Failed silos get picked up on next scheduled run
- Dagster's retry_policy on individual assets still applies

## Sensor cleanup

### Remove (replaced by jobs)

- `document_arrival_sensor` - replaced by sage_custodian
- `causal_transitivity_sensor` - replaced by sage_synthesizer
- `chain_stitch_sensor` - replaced by sage_synthesizer
- `belief_synthesis_sensor` - replaced by sage_synthesizer
- `belief_merge_sensor` - replaced by sage_synthesizer
- `synthesizer_threshold_sensor` - replaced by sage_synthesizer
- `confidence_drift_sensor` - replaced by sage_groundskeeper
- `session_autoclose_sensor` - replaced by sage_groundskeeper

### Keep

- `poison_queue_sensor` - separate concern (error recovery)
- `cascade_review_sensor` - future sage_validator territory

## Migration

1. Create job definitions and schedules
2. Deploy with sensors still active (jobs run alongside)
3. Verify jobs pick up work correctly
4. Disable old sensors one by one
5. Remove sensor code

## Future: sage_validator_job

When validation features are built out:
- Cascade review
- Contradiction detection
- Confidence drift (epistemic, not operational)
- Cross-silo consistency checks
