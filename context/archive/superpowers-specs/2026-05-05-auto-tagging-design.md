# Auto-Tagging System Design

**Date:** 2026-05-05  
**Status:** Approved  
**Review Flag:** Revisit 2026-06 to evaluate vocabulary bootstrapping approach

## Storage Strategy Analysis

### Current System Data Distribution

| Store | Data | Access Pattern | Why Here |
|-------|------|----------------|----------|
| **Memgraph** | Content nodes, relationships, claims, facts | Graph traversal, semantic queries | Graph structure, relationship-heavy |
| **Qdrant** | Embeddings, vectors | Similarity search | Purpose-built for vector search |
| **Redis** | Sessions, caches, access events, streams | High-frequency read/write, TTL | Speed, ephemeral data |
| **Postgres** | (planned) Silo config, tag config | CRUD, dashboard, audit | Relational, cheap, admin-friendly |

### Cost at Scale

| Store | Cost Driver | 1M Silos | 100M Nodes |
|-------|-------------|----------|------------|
| Memgraph | RAM (in-memory) | $$$ | $$$$ |
| Qdrant | Disk + RAM cache | $$ | $$$ |
| Redis | RAM | $$$ | $$ (TTL helps) |
| Postgres | Disk | $ | $ |

### Data Placement Principles

1. **Graph data** (nodes, edges, traversals) → Memgraph
2. **Vectors** (embeddings, similarity) → Qdrant  
3. **Ephemeral** (sessions, caches, streams) → Redis
4. **Config/metadata** (silo settings, tag vocab, audit) → Postgres
5. **High-churn temp data** (tag candidates) → Redis with TTL

### Why Postgres for Tag Config

- Dashboard/UI: trivial CRUD APIs with SQLAlchemy
- Schema enforcement: Pydantic + Alembic migrations
- Audit trails: updated_at, version history
- Cost: pennies at scale vs RAM-bound stores
- Tooling: pgAdmin, Retool, countless admin UIs

## Overview

Automatic tag suggestion for stored content using hybrid sync/async approach. Sync cosine matching provides immediate tags (~0.1ms), async LLM refinement adds nuanced tags within 30 minutes.

## Goals

- Cost-effective: reuse existing embeddings, batch LLM calls
- Low-latency: sync path adds <1ms to store
- Accurate: LLM handles nuanced/abstract tags
- Self-organizing: per-silo vocabulary bootstraps from usage

## Non-Goals

- Real-time LLM tagging (too slow/expensive)
- Global vocabulary (too domain-specific)
- Manual curation workflows (out of scope for v1)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      STORE TIME (sync)                       │
├─────────────────────────────────────────────────────────────┤
│  content → embed() → cosine match vs TAG_VECTORS            │
│                     ↓                                        │
│            auto_tags (immediate, ~0.1ms)                     │
│            + user_tags (passed in)                           │
│            + mark: auto_tagged_at = NULL (needs refinement)  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  ASYNC (Dagster, every 30m)                  │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch nodes WHERE auto_tagged_at IS NULL (limit 50)      │
│  2. Batch → LLMProvider → refined tags + candidates          │
│  3. Merge: keep user_tags, enhance with LLM suggestions      │
│  4. Candidate handling:                                      │
│     - similar to existing (>0.8) → map to existing           │
│     - distinct + seen 3x → promote to dynamic vocab          │
│  5. Set auto_tagged_at = now()                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              MAINTENANCE (Dagster, daily 03:00)              │
├─────────────────────────────────────────────────────────────┤
│  - Demote dynamic tags unused for 30 days                    │
│  - Merge drifted synonyms (cosine > 0.85)                    │
│  - Prune orphan candidates (seen once, older than 7 days)    │
│  - Core tags: never touched                                  │
└─────────────────────────────────────────────────────────────┘
```

## Data Model

### Silo Tag Config (Postgres)

```python
# models/silo_tag_config.py

class SiloTagConfig(Base):
    __tablename__ = "silo_tag_configs"
    
    silo_id: Mapped[UUID] = mapped_column(primary_key=True)
    core_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=[])
    dynamic_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=[])
    settings: Mapped[dict] = mapped_column(JSONB, default={
        "min_tags": 2,
        "max_tags": 5,
        "cosine_threshold": 0.4,
        "promotion_threshold": 3,
        "demotion_days": 30,
        "synonym_threshold": 0.85
    })
    constraints: Mapped[dict] = mapped_column(JSONB, default={
        "hierarchy": {},
        "layer_hints": {},
        "mutual_exclusion": []
    })
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(onupdate=func.now())
```

Dashboard-friendly: REST CRUD, Alembic migrations, audit trail via updated_at.

### Tag Candidate Tracking (Redis)

```python
# High-churn, TTL-based
# Key: tag_candidate:{silo_id}:{tag_hash}
# Value: {"tag": "...", "count": N, "first_seen": ts, "embedding": [...]}
# TTL: 7 days (orphan candidates expire automatically)
```

Redis handles the churn; promoted tags move to Postgres.

### Node Tag Fields

```cypher
(n:Node {
  ...
  tags: ["research", "verified"],   # Final merged tags
  auto_tagged_at: timestamp | null, # Null = needs refinement
  user_tags: ["verified"],          # Preserved user input
  auto_tags: ["research"]           # System-suggested
})
```

## Tag Vocabulary

### Two-Tier Model

- **Core tags:** Protected, never auto-demoted. Set by client via `context_admin`.
- **Dynamic tags:** Auto-promoted from candidates when seen 3+ times. Can be demoted if unused 30+ days.

### Per-Silo (No Global Defaults)

Each silo bootstraps its own vocabulary from usage. Clients can seed via:

```
context_admin(action: "seed_tags", tags: ["research", "meeting", ...])
context_admin(action: "protect_tags", tags: ["verified", "archived"])
```

## Tag Constraints (YAML Config)

```yaml
# config/tags.yaml

defaults:
  min_tags: 2
  max_tags: 5
  cosine_threshold: 0.4
  promotion_threshold: 3
  demotion_days: 30
  synonym_threshold: 0.85

# Per-silo constraints stored in Memgraph
# Example structure:
#
# hierarchy:
#   postgres: database
#   redis: database
#
# layer_hints:
#   observation: memory
#   decision: wisdom
#
# mutual_exclusion:
#   - [bug-fix, feature, refactor]
```

Constraint types:
- **Hierarchy:** child implies parent (e.g., `postgres` → `database`)
- **Layer hints:** suggests layer (not enforced)
- **Mutual exclusion:** cannot coexist

## Sync Cosine Matching

```python
@dataclass(slots=True)
class VocabCache:
    tags: list[str]
    matrix: np.ndarray  # (n_tags, dim), pre-normalized
    loaded_at: float
    
    def match(self, content_vec: np.ndarray, threshold: float, max_tags: int) -> list[str]:
        vec = content_vec / np.linalg.norm(content_vec)
        scores = self.matrix @ vec
        indices = np.argsort(-scores)
        return [self.tags[i] for i in indices if scores[i] > threshold][:max_tags]


class AutoTaggingService:
    CACHE_TTL = 300  # 5 minutes
    
    async def suggest_tags(
        self,
        content_vector: list[float],
        silo_id: str,
        threshold: float = 0.4,
        max_tags: int = 5,
    ) -> list[str]:
        vocab = await self.load_vocabulary(silo_id)
        if not vocab:
            return []
        vec = np.array(content_vector, dtype=np.float32)
        return vocab.match(vec, threshold, max_tags)
```

Performance: ~0.1ms for 100 tags (numpy matrix multiply).

## Async LLM Refinement

### Dagster Asset

```python
@dg.asset(
    name="auto_tagging",
    partitions_def=silo_partitions,
    description="LLM-based tag refinement for untagged nodes",
)
def auto_tagging_asset(...):
    # 1. Fetch untagged nodes (limit 50)
    # 2. Batch LLM call
    # 3. Dedupe suggestions against vocabulary
    # 4. Apply tags, track candidates
    # 5. Promote candidates hitting threshold
```

### Schedule

Every 30 minutes per active silo.

### LLM Prompt

```
Given these content snippets, suggest 2-5 tags for each.
Return JSON: {"node_id": ["tag1", "tag2"], ...}

Existing vocabulary (prefer these): [...]

Content:
- id_1: "..."
- id_2: "..."
```

Uses existing `LLMProvider` for client-configurable LLM selection.

## Tag Maintenance

### Dagster Asset

Daily at 03:00 UTC:
1. Demote dynamic tags unused 30+ days
2. Merge synonyms (cosine > 0.85)
3. Prune orphan candidates (seen once, older than 7 days)

## Key Files

| File | Purpose |
|------|---------|
| `config/tags.yaml` | System defaults (thresholds, no vocabulary) |
| `models/silo_tag_config.py` | Postgres model for per-silo config |
| `services/auto_tagging.py` | Sync cosine matching + vocab cache |
| `services/tag_config.py` | CRUD for silo tag config (Postgres) |
| `pipelines/assets/auto_tagging.py` | Async LLM refinement |
| `pipelines/assets/tag_maintenance.py` | Vocabulary pruning + candidate promotion |
| `api/routes/tag_config.py` | REST endpoints for dashboard |

## Tag Precedence

1. `user_tags` always preserved
2. `auto_tags` merged in, respecting `max_tags`
3. `tags` = union, deduplicated

## Testing Strategy

- Unit: VocabCache.match() with mock vectors
- Unit: candidate promotion/demotion logic
- Integration: end-to-end store → async tagging cycle
- Load: cosine matching at 1000 tags

## Open Questions

None - all resolved during design.

## Review Notes

**2026-06 Review:** Evaluate per-silo vocabulary bootstrapping. Questions to answer:
- Are silos naturally developing coherent vocabularies?
- Is promotion threshold (3) appropriate?
- Should we add cross-silo vocabulary suggestions?
