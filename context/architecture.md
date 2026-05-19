# Context Service Architecture

> Service-level architecture for the Engrammic context-service backend.

## System Overview

```
                              Agents / Clients
                                     |
                    +----------------+----------------+
                    |                                 |
               MCP Server                      FastAPI REST
            (primary surface)                  (admin surface)
                    |                                 |
                    +----------------+----------------+
                                     |
                              Service Layer
                         (ContextService, SiloService)
                                     |
                    +----------------+----------------+
                    |                |                |
              HyperGraphStore   QdrantClient    RedisClient
               (protocol)        (vector)        (cache)
                    |
              MemgraphStore
             (implementation)
```

## Surfaces

### MCP Server (Primary)

Agent-facing tool surface via FastMCP. Tools are intent/verb-based (`remember`, `learn`, `believe`, etc.).

| Component | Path | Responsibility |
|-----------|------|----------------|
| Server | `mcp/server.py` | FastMCP setup, service wiring |
| Tools | `mcp/tools/` | Tool handlers (thin, delegate to services) |
| Auth | `mcp/auth.py` | Per-request auth resolution from headers |
| Presets | `mcp/preset_resolver.py` | ICP preset lookup for tool profiles |

**Request flow:**
```
MCP Request -> Auth extraction -> Preset resolution -> Tool handler -> Service -> Stores
```

### FastAPI REST (Admin)

Admin/internal HTTP API. Not the agent surface.

| Component | Path | Responsibility |
|-----------|------|----------------|
| App | `api/app.py` | FastAPI app, middleware, lifespan |
| Routes | `api/routes/` | HTTP endpoints by domain |
| Deps | `api/deps.py` | Dependency injection |
| Auth | `api/auth_dep.py` | Request auth dependency |

**Endpoints:** Silo CRUD, usage metrics, health checks, admin operations.

## Service Layer

Services contain business logic. They depend on storage protocols, not implementations.

```
src/context_service/services/
├── context.py          # Core CRUD: store, query, lookup, delete
├── silo.py             # Silo lifecycle, ownership
├── evidence.py         # Evidence validation for knowledge layer
├── skills.py           # Skill/pattern management
├── auto_tagging.py     # Content classification
└── models.py           # Service-level DTOs
```

### ContextService

Primary service for all context operations.

```python
class ContextService:
    def __init__(
        self,
        memgraph: HyperGraphStore,    # Graph storage (protocol)
        qdrant: QdrantClient,         # Vector storage
        embedding: EmbeddingService,  # Embedding generation
        cache: RedisClient | None,    # Optional cache
        splade: SpladeEncoder | None, # Sparse vectors
        auto_tagging: AutoTaggingService | None,
    ): ...
```

**Key methods:**
- `store()` - Write node (Memory/Knowledge/Wisdom layer)
- `query()` - Semantic search with hybrid retrieval
- `lookup()` - Direct node fetch by ID
- `delete()` - Soft/hard delete with cascade options
- `link()` - Create typed edges between nodes
- `get_provenance()` - Trace node lineage

### SiloService

Multi-tenant isolation via `silo_id`.

```python
class SiloService:
    def __init__(
        self,
        memgraph: HyperGraphStore,
        ownership_cache: SiloOwnershipCache | None,
    ): ...
```

**Key methods:**
- `create_silo()` - Provision new tenant silo
- `get_silo()` - Fetch silo metadata
- `verify_ownership()` - Auth check (org owns silo)

## Storage Layer

### Protocol-Based Design

All storage access goes through protocols defined in `engine/protocols.py`. Product code depends on protocols, not concrete stores.

```python
@runtime_checkable
class HyperGraphStore(Protocol):
    """Domain-agnostic graph storage interface."""
    
    async def upsert_node(self, node: Node) -> None: ...
    async def get_node(self, node_id: UUID, silo_id: str) -> Node | None: ...
    async def batch_get_nodes(self, node_ids: list[UUID], silo_id: str) -> dict[UUID, Node]: ...
    async def delete_node(self, node_id: UUID, silo_id: str) -> bool: ...
    async def create_supersedes_edge(...) -> bool: ...
    async def filter_superseded_at(...) -> dict[UUID, UUID]: ...
    # ... edge operations, silo operations, etc.
```

### Implementations

| Store | Path | Backend | Purpose |
|-------|------|---------|---------|
| MemgraphStore | `stores/memgraph.py` | Memgraph | Graph storage (nodes, edges, traversals) |
| QdrantClient | `stores/qdrant.py` | Qdrant | Vector storage (embeddings, similarity search) |
| RedisClient | `stores/redis.py` | Redis | Caching, rate limiting, Custodian batching |

### Query Organization

Graph queries live in dedicated modules:

| Module | Path | Contents |
|--------|------|----------|
| Engine queries | `engine/queries.py` | Content node CRUD, supersession, version chains |
| DB queries | `db/queries.py` | Belief/Commitment/Pattern queries, synthesis |

## Custodian Pipeline

Background synthesis system that promotes, consolidates, and maintains the knowledge graph.

```
src/context_service/custodian/
├── pipeline.py           # Validation pipeline (citation + business rules)
├── agents.py             # LLM agents (Synthesizer, Custodian)
├── dispatch.py           # Job dispatch to Dagster
├── handlers/             # Stage handlers (extraction, synthesis, etc.)
├── identities/           # Trigger systems (batch, async)
├── sensors/              # Dagster sensors
├── validators.py         # Citation validation
├── business_rules.py     # Acceptance criteria
└── models.py             # Custodian DTOs
```

### Synthesis Flow

```
[Knowledge write] -> AsyncBatchTrigger -> Custodian Identity
                                               |
                                               v
                                     Extraction (LLM)
                                               |
                                               v
                                     Citation Validation
                                               |
                                               v
                                     Business Rule Check
                                               |
                                               v
                                     [Accept/Reject]
                                               |
                              +----------------+----------------+
                              |                                 |
                        Fact Promotion                  Belief Synthesis
                     (Knowledge -> Fact)            (Facts -> ProposedBelief)
```

### Key Components

**Validators:**
- `CitationValidator` - Verifies claims cite existing nodes
- `BusinessRuleValidator` - Enforces acceptance thresholds

**Agents (LLM-powered):**
- `Synthesizer` - Generates beliefs from corroborated facts
- `Custodian` - Extracts claims from documents

**Triggers:**
- `AsyncBatchTrigger` - Batches writes, fires Custodian on threshold

## Dagster Integration

Batch jobs and scheduled maintenance run via Dagster.

```
src/context_service/pipelines/
├── definitions.py     # Top-level Definitions (entry point)
├── assets/            # Dagster assets
├── jobs/              # Job definitions
├── schedules.py       # Cron schedules
├── sensors/           # Event-driven sensors
├── resources.py       # Shared resources (stores, clients)
└── partitions.py      # Partition definitions
```

### Jobs

| Job | Purpose | Trigger |
|-----|---------|---------|
| `groundskeeper_nightly` | Decay, cleanup, maintenance | Schedule (nightly) |
| `causal_tombstone_job` | Cascade deletes from source | Manual |
| Custodian synthesis | Process extraction batches | Sensor (on batch ready) |

### Resources

Dagster resources wrap store clients for job context:

```python
def build_default_resources() -> dict[str, Any]:
    return {
        "memgraph": MemgraphResource(),
        "qdrant": QdrantResource(),
        "redis": RedisResource(),
        "settings": SettingsResource(),
    }
```

## Multi-Tenancy

All data is isolated by `silo_id`. Every node, edge, and query is scoped.

```
Silo
├── org_id (WorkOS org owner)
├── silo_id (unique identifier)
├── created_at
└── metadata

Node
├── id
├── silo_id  <- isolation key
├── content
├── type
└── ...
```

**Enforcement points:**
1. MCP auth extracts `silo_id` from request context
2. Services require `silo_id` on all operations
3. Store queries include `silo_id` in WHERE clauses
4. Ownership cache validates org->silo relationship

## Data Flow

### Write Path (Agent -> Storage)

```
Agent calls `remember` / `learn` / `believe`
           |
           v
    MCP Tool Handler
           |
           v
    ContextService.store()
           |
    +------+------+
    |             |
    v             v
MemgraphStore  QdrantClient
(graph node)   (embedding)
    |
    v
AsyncBatchTrigger (if Knowledge layer)
    |
    v
Custodian Pipeline (async)
```

### Read Path (Agent <- Storage)

```
Agent calls `recall`
           |
           v
    MCP Tool Handler
           |
           v
    ContextService.query()
           |
    +------+------+------+
    |             |      |
    v             v      v
RedisCache   QdrantClient  MemgraphStore
(if cached)  (vector search) (graph lookup)
    |             |             |
    +------+------+------+------+
                  |
                  v
           Reranking + Fusion
                  |
                  v
           filter_superseded_at()
                  |
                  v
           Return results
```

## Key Invariants

1. **Protocol dependency** - Services depend on `HyperGraphStore` protocol, not `MemgraphStore`
2. **Silo isolation** - All queries scoped by `silo_id`
3. **Supersession chains** - Superseded nodes have `valid_to` set; queries return chain heads
4. **Evidence requirement** - Knowledge layer writes require `evidence_uri`
5. **Async synthesis** - Custodian runs async, doesn't block writes

## Configuration

| Config | Source | Contents |
|--------|--------|----------|
| `config/settings.py` | Env + defaults | All service settings (Pydantic) |
| `config/mcp_tools.yaml` | File | MCP tool surface definitions |
| `config/prompts/` | Files | LLM prompt templates |

## Related Docs

- `../primitives/context/specs/` - EAG paradigm (layers, transitions)
- `context/specs/` - Service-level specs
- `context/plans/` - Implementation plans
