# SAGE System

**SAGE** (Synthesis, Aggregation, and Graph Evolution) is Engrammic's internal agent system responsible for autonomous knowledge graph maintenance.

## Overview

SAGE operates as a set of background jobs that process, synthesize, and maintain the epistemic graph. It runs independently of user requests, ensuring the knowledge graph stays healthy and beliefs crystallize from accumulated facts.

## Sub-agents

### sage.custodian - "The Receiver"

Ingests raw input and processes it into structured knowledge.

**Responsibilities:**
- Document extraction and embedding
- Initial fact formation from observations
- Claim-to-fact promotion (corroboration)
- Cluster detection for synthesis candidates

**Cadence:** Every 10 minutes

### sage.synthesizer - "The Distiller"

Crystallizes higher-order knowledge from accumulated facts.

**Responsibilities:**
- Belief synthesis from fact clusters
- Overlapping belief merging
- Causal transitivity inference
- Pattern detection (heuristic and LLM-based)
- Reasoning chain stitching

**Cadence:** Every 30 minutes

### sage.groundskeeper - "The Maintainer"

Keeps the graph healthy over time.

**Responsibilities:**
- Heat score computation and diffusion
- Edge weight maintenance
- Retention enforcement
- Compaction and garbage collection
- Prewarm sweep for hot nodes

**Cadence:** Every 15 minutes

### sage.validator - "The Verifier"

Checks quality and tracks confidence. Surfaces engagement markers for agent review.

**Responsibilities:**
- Contradiction detection (confirms flagged candidates via LLM, writes Contradiction markers)
- Stale commitment detection (monitors Commitments for undermining evidence, writes StaleCommitment markers)
- Marker cleanup (expires old unresolved markers)
- Cascade review (belief invalidation propagation)

**Cadence:** Every 5 minutes

## Architecture

Each SAGE agent maps to a Dagster scheduled job:

```
sage_custodian_schedule (*/10 * * * *)
    |
    +-> query silos with pending ingestion work
    +-> trigger sage_custodian_job per silo partition

sage_synthesizer_schedule (*/30 * * * *)
    |
    +-> query silos with pending synthesis work
    +-> trigger sage_synthesizer_job per silo partition

sage_groundskeeper_schedule (*/15 * * * *)
    |
    +-> query silos with stale heat/maintenance needs
    +-> trigger sage_groundskeeper_job per silo partition

sage_validator_schedule (*/5 * * * *)
    |
    +-> query silos with pending validation work (flagged candidates, stale commitments)
    +-> trigger sage_validator_job per silo partition
```

Jobs use Dagster's partition system. Each silo is a partition, enabling parallel processing and isolated failure handling.

## Error handling

- Jobs continue on individual asset/silo failures
- Failed work gets retried on next scheduled run
- Individual assets have their own retry policies
- Poison queue captures persistent failures for manual review

## Relationship to MCP tools

SAGE operates independently of user-facing MCP tools. The tools handle real-time reads/writes; SAGE handles background processing:

| Concern | MCP tools | SAGE |
|---------|-----------|------|
| Store observation | context_store | - |
| Process into facts | - | sage.custodian |
| Recall knowledge | context_recall | - |
| Synthesize beliefs | - | sage.synthesizer |
| Update heat scores | - | sage.groundskeeper |
| Accept/reject beliefs | accept / reject | - |

## Monitoring

Each job emits metrics via Dagster:
- Run duration
- Assets materialized
- Silos processed
- Errors encountered

Metabase dashboards (backed by PostgreSQL telemetry tables) track SAGE health across all sub-agents.
