# Write Quality Gate Spec

Date: 2026-06-06
Status: Approved design, ready for implementation planning
Related: context/plans/2026-06-04-enforcement-architecture-design.md

## Overview

A write-path quality system that enforces layer discipline, validates structural requirements, emits telemetry, and enriches responses with quality signals. The goal is KG quality assurance: prevent garbage from getting in, track what does, and create feedback loops that improve agent behavior over time.

## Problem Statement

Agents don't always pick the right layer or provide required inputs:
- `learn` called without real evidence
- `believe` called without valid about-refs
- Duplicates created instead of supersession
- No recall before store (missing context)

This degrades KG quality. The system should validate, enforce where appropriate, and measure compliance.

## Design Principles

1. **Structural checks only** - no LLM in write path (economic viability)
2. **Soft by default, hard opt-in** - warn don't block, unless configured
3. **Telemetry for understanding** - measure to improve, not just block
4. **Feedback in responses** - agents learn from quality signals
5. **Layer policy on read** - quality affects surfacing, creating natural pressure

## Architecture

### Module Location

`src/context_service/sage/quality_gate.py`

### Integration Point

Wraps `sage.transactions.*` functions, not MCP tools. The gate sits between MCP tools and the transaction layer:

```
MCP tool (learn)
    -> sage.transactions.store_claim()
        -> QualityGate.assess()   # sync: structural validation
        -> actual store logic
        -> QualityGate.record()   # async: emit telemetry
    -> response with quality_signals
```

### Core Types

```python
@dataclass
class QualityContext:
    tool: str                           # remember, learn, believe, reason
    layer: str                          # memory, knowledge, wisdom, intelligence
    session_id: str
    silo_id: str
    content: str
    evidence_refs: list[str] | None = None
    about_refs: list[str] | None = None
    supersedes: str | None = None

@dataclass
class CheckResult:
    passed: bool
    name: str
    message: str | None = None

@dataclass
class QualityResult:
    outcome: Literal["passed", "warned", "downgraded", "rejected"]
    checks: list[CheckResult]
    reason: str | None = None
    suggestions: list[str] = field(default_factory=list)
    original_layer: str | None = None   # if downgraded

class WriteQualityGate:
    def __init__(self, settings: QualityGateSettings): ...
    async def assess(self, ctx: QualityContext) -> QualityResult: ...
    async def record(self, ctx: QualityContext, result: QualityResult) -> None: ...
```

## Structural Checks

### Memory Layer (remember)

No checks. Catch-all layer. Record telemetry for baseline metrics.

### Knowledge Layer (learn)

| Check | Function | Outcome |
|-------|----------|---------|
| Evidence non-empty | `_check_evidence_present()` | warned or downgraded (if enforce=True) |
| Evidence format valid | `_check_evidence_format()` | warned |
| Evidence nodes exist | `_check_evidence_resolvable()` | warned |

Evidence format: must match `node:<uuid>` or valid URI pattern (`file://`, `https://`, etc.)

### Wisdom Layer (believe)

| Check | Function | Outcome |
|-------|----------|---------|
| About refs non-empty | `_check_about_present()` | rejected |
| About refs exist | `_check_about_resolvable()` | rejected |
| No self-reference | `_check_no_self_ref()` | rejected |
| About refs are Knowledge/Memory | `_check_about_layers()` | warned |

About-ref checks are hard by default. Beliefs without grounding are meaningless.

### Intelligence Layer (reason)

Schema validation handles steps structure. Record metrics only: step_count, evidence_per_step.

### Cross-Cutting (all layers)

| Check | Function | Outcome |
|-------|----------|---------|
| Recall-before-store | `_check_recall_first()` | telemetry flag only |
| Duplicate content | `_check_content_hash()` | warned, suggest supersedes |

Recall-before-store: check Redis key `session:{session_id}:recall_called`, set by recall tool.

## Telemetry

### Event Type

Add `WRITE_QUALITY` to `reactions/events.py`:

```python
class ReactionEventType(StrEnum):
    WRITE_QUALITY = "WRITE_QUALITY"
```

### Event Payload

```python
@dataclass
class WriteQualityPayload:
    tool: str
    layer: str
    original_layer: str | None
    silo_id: str
    session_id: str
    agent_id: str | None
    outcome: str
    checks_failed: list[str]
    evidence_count: int
    about_node_count: int
    recall_before_store: bool
    supersedes_used: bool
    duplicate_detected: bool
    timestamp: datetime
```

### Storage

Postgres table `write_quality_events`:

```sql
CREATE TABLE write_quality_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id UUID NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    tool TEXT NOT NULL,
    layer TEXT NOT NULL,
    original_layer TEXT,
    outcome TEXT NOT NULL,
    checks_failed TEXT[],
    evidence_count INT NOT NULL DEFAULT 0,
    about_node_count INT NOT NULL DEFAULT 0,
    recall_before_store BOOLEAN NOT NULL DEFAULT FALSE,
    supersedes_used BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_detected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wqe_silo_created ON write_quality_events(silo_id, created_at);
CREATE INDEX idx_wqe_outcome ON write_quality_events(outcome);
CREATE INDEX idx_wqe_tool ON write_quality_events(tool);
```

### Reaction Handler

```python
@broker.task("write_quality_task")
async def write_quality_task(payload: dict, silo_id: str) -> None:
    async with get_postgres_pool().acquire() as conn:
        await conn.execute(INSERT_WRITE_QUALITY_EVENT, payload)
```

## Configuration

### Settings Class

```python
class QualityGateSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    
    enabled: bool = Field(default=True)
    
    # Enforcement posture
    enforce_evidence: bool = Field(default=False)
    enforce_about_refs: bool = Field(default=True)
    
    # Behavioral checks
    check_recall_first: bool = Field(default=True)
    check_duplicates: bool = Field(default=True)
    check_evidence_resolvable: bool = Field(default=True)
    check_about_layers: bool = Field(default=True)
    
    # Telemetry
    emit_telemetry: bool = Field(default=True)
    
    # Performance
    resolvability_cache_ttl_seconds: int = Field(default=60)
```

### Environment Overrides

```bash
# Soft mode (default)
QUALITY_GATE__ENABLED=true
QUALITY_GATE__ENFORCE_EVIDENCE=false

# Hard mode
QUALITY_GATE__ENFORCE_EVIDENCE=true

# Disable for testing
QUALITY_GATE__ENABLED=false
```

## Response Enrichment

Every write response includes `quality_signals`:

```python
@dataclass
class QualitySignals:
    outcome: str
    layer_stored: str
    checks: list[CheckDetail]
    suggestions: list[str]
    recall_before_store: bool

@dataclass
class CheckDetail:
    name: str
    passed: bool
    message: str | None
```

### Example: Warned Write

```json
{
  "node_id": "abc123",
  "layer": "knowledge",
  "quality_signals": {
    "outcome": "warned",
    "layer_stored": "knowledge",
    "checks": [
      {"name": "evidence_present", "passed": false,
       "message": "No evidence refs provided"}
    ],
    "suggestions": [
      "Add file:// or node: refs for higher confidence"
    ],
    "recall_before_store": false
  }
}
```

### Example: Downgraded Write

```json
{
  "node_id": "def456",
  "layer": "memory",
  "quality_signals": {
    "outcome": "downgraded",
    "layer_stored": "memory",
    "checks": [
      {"name": "evidence_present", "passed": false,
       "message": "Knowledge layer requires evidence; stored as memory"}
    ],
    "suggestions": [
      "Call learn again with evidence refs to promote to knowledge"
    ]
  }
}
```

### Example: Rejected Write

```json
{
  "error": "quality_rejected",
  "quality_signals": {
    "outcome": "rejected",
    "checks": [
      {"name": "about_present", "passed": false,
       "message": "Beliefs require about: refs to supporting knowledge"}
    ],
    "suggestions": [
      "Pass about=[node:xxx] referencing supporting facts"
    ]
  }
}
```

## Layer Policy (Read Side)

Quality affects ambient surfacing via the existing trust gate.

### Surfacing Rules

| Layer | Ambient | Explicit | Rationale |
|-------|---------|----------|-----------|
| Memory | No | Yes | Raw observations |
| Knowledge (passed) | Yes | Yes | Verified claims |
| Knowledge (warned) | Flagged | Yes | Lower trust |
| Wisdom | Yes | Yes | Conclusions |
| Intelligence | No | Yes | Verbose chains |

### Trust Gate Extension

Add `withhold_unverified_knowledge` to `TrustGateConfig`:

```python
withhold_unverified_knowledge: bool = Field(
    default=False,
    description="Withhold knowledge nodes lacking evidence from ambient recall"
)
```

### Node Metadata

Persist quality outcome on nodes:

```python
node_properties["quality_outcome"] = quality.outcome
node_properties["evidence_count"] = len(evidence_refs)
node_properties["pending_promotion"] = quality.outcome == "downgraded"
```

- `evidence_count`: enables trust gate to filter on "2+ evidence refs" not just "any"
- `pending_promotion`: flags nodes that were downgraded from knowledge to memory, enabling optional Dagster sweep to surface unresolved downgrades

### Withheld Reasons

Extend `withheld.by_reason`:

```json
{
  "withheld": {
    "count": 5,
    "by_reason": {
      "unresolved_conflict": 1,
      "low_confidence": 2,
      "unverified_knowledge": 2
    }
  }
}
```

## Feedback Loop

1. Agent calls `learn` without evidence
2. Stored with `quality_outcome: warned`, `has_evidence: false`
3. Later recall withholds node (if `withhold_unverified_knowledge=True`)
4. Agent sees "2 unverified_knowledge withheld"
5. Agent learns: evidence matters for surfacing

Natural pressure toward quality without hard blocking.

## Async Quality Reactions

Some checks are too expensive for the sync write path but valuable for telemetry.

### Semantic Duplicate Check

After write completes, emit `CHECK_SEMANTIC_DUPLICATE` reaction:

```python
@broker.task("check_semantic_duplicate_task")
async def check_semantic_duplicate_task(node_id: str, silo_id: str) -> None:
    """Check for semantic near-duplicates via embedding similarity."""
    embedding = await get_node_embedding(node_id)
    similar = await qdrant.search(embedding, threshold=0.95, limit=5)
    
    if similar:
        # Record in telemetry, don't modify the node
        await record_semantic_duplicate_detected(node_id, similar, silo_id)
```

This surfaces in telemetry dashboards ("20% of writes have semantic near-duplicates") without blocking writes.

### Pending Promotion Sweep

Optional Dagster job to surface downgraded nodes that never got promoted:

```python
@asset
def pending_promotion_report(context) -> pd.DataFrame:
    """Find memory nodes with pending_promotion=True older than 7 days."""
    return query("""
        SELECT id, content, created_at, silo_id
        FROM nodes 
        WHERE layer = 'memory' 
          AND pending_promotion = TRUE
          AND created_at < NOW() - INTERVAL '7 days'
    """)
```

Enables periodic review: "these were meant to be knowledge but lacked evidence."

## Performance Considerations

- Sync checks are structural only (no LLM, no embedding)
- Node existence checks use batch queries
- Results cached with TTL (default 60s)
- Telemetry emission is fire-and-forget (async)
- Semantic duplicate check is async reaction (does not block write)
- Target: < 50ms added latency to sync write path

## Files to Create/Modify

### New Files

- `src/context_service/sage/quality_gate.py` - core gate logic
- `src/context_service/db/quality_queries.py` - Postgres queries
- `tests/sage/test_quality_gate.py` - unit tests
- `tests/integration/test_quality_gate.py` - integration tests

### Modified Files

- `src/context_service/config/settings.py` - add QualityGateSettings
- `src/context_service/reactions/events.py` - add WRITE_QUALITY, CHECK_SEMANTIC_DUPLICATE events
- `src/context_service/reactions/tasks.py` - add write_quality_task, check_semantic_duplicate_task
- `src/context_service/sage/transactions.py` - integrate gate calls
- `src/context_service/mcp/tools/trust_gate.py` - extend withhold reasons
- `src/context_service/mcp/tools/recall.py` - set recall_called flag
- `src/context_service/pipelines/assets/` - add pending_promotion_report asset (optional)

### Migrations

- Alembic migration for `write_quality_events` table
- Alembic migration for node properties (quality_outcome, evidence_count, pending_promotion)

## Success Criteria

1. All write transactions pass through quality gate
2. Telemetry events recorded to Postgres
3. Response enrichment visible in MCP tool responses
4. Recall-before-store tracking functional
5. Duplicate detection suggests supersession
6. Trust gate filters unverified knowledge (when enabled)
7. < 50ms added write latency
8. Aggregation queries return meaningful metrics

## Non-Goals

- LLM-based semantic quality assessment
- Per-silo configuration (future scope)
- Real-time dashboards (telemetry is for offline analysis)
- Hyperedge support (stashed)

## Amendments (Post-Review)

The following were added after design self-reflection:

1. **evidence_count on node** - Store count not just boolean, enabling richer trust gate filtering ("2+ authoritative refs")

2. **pending_promotion flag** - Track downgraded nodes for optional Dagster sweep, surfaces unresolved quality issues

3. **Async semantic duplicate check** - Embedding similarity as a reaction (not sync), surfaces in telemetry without blocking writes
