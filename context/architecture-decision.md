# Architecture Decision: Hot-Swappable Knowledge Primitives

**Date:** 2026-04-26
**Status:** draft

## Context

The contextr codebase has two mental models colliding:

1. **EAG spec (architecture/)**: Four-layer cognitive model (Memory, Knowledge, Wisdom, Intelligence) with transition workers (T1-T9), a work queue, and a deterministic epistemology library. `:Claim` promotes to `:Fact`.

2. **Shipped RAG-era code (app/custodian/)**: A 4-phase visit runner (fast, plan, deep, stitch) that produces `:Finding` nodes per cluster.

The EAG spec describes a Custodian that doesn't exist. The code ships a different architecture. Anyone reading the spec is misled.

## Decision

Extract the GraphRAG primitives into a separate open-source library. The product (Delta Prime) imports this library and implements product-specific wiring (Dagster, MCP, auth, billing).

The library is designed to be **hot-swappable**: the product defines protocols (interfaces), and the library implements them. If a better paradigm emerges, swap the implementation without rewriting product code.

## Architecture

```
delta-prime/
├── primitives/              # THIS REPO (open-source)
│   ├── schema/              # Node types, edge types, layers
│   ├── epistemology/        # Confidence, promotion, supersession
│   ├── signals/             # Heat, freshness, decay
│   └── queries/             # Parameterized Cypher templates
│
└── product/                 # Private repo (or contextr refactored)
    ├── protocols/           # Interfaces the product needs
    ├── dagster/             # Pipeline orchestration
    ├── mcp/                 # Agent-facing tools
    └── api/                 # Admin/dashboard REST
```

## Protocol Design

The product repo owns the protocols. The primitives library implements them. This inverts the dependency: the library depends on protocol definitions, not the other way around.

### Core Protocols

```python
@runtime_checkable
class KnowledgeStore(Protocol):
    """Store and retrieve knowledge."""
    async def ingest(self, content: str, metadata: dict) -> IngestResult: ...
    async def query(self, q: str, scope: Scope) -> list[KnowledgeNode]: ...
    async def get(self, node_id: str) -> KnowledgeNode | None: ...
    async def delete(self, node_id: str, cascade: bool = False) -> DeleteResult: ...


@runtime_checkable
class LifecycleManager(Protocol):
    """Knowledge lifecycle transitions."""
    async def promote(self, node_id: str) -> PromoteResult: ...
    async def supersede(self, old_id: str, new_id: str, reason: str) -> SupersedeResult: ...
    async def decay(self, scope: Scope, threshold: float) -> DecayResult: ...
    def should_promote(self, node: KnowledgeNode) -> tuple[bool, str]: ...


@runtime_checkable
class SignalProvider(Protocol):
    """Knowledge signals (heat, confidence, freshness)."""
    def confidence(self, node: KnowledgeNode) -> float: ...
    def heat(self, node: KnowledgeNode) -> float: ...
    def freshness(self, node: KnowledgeNode) -> float: ...
    def priority(self, node: KnowledgeNode) -> float: ...


@runtime_checkable
class ProvenanceTracker(Protocol):
    """Track derivation and citation chains."""
    async def derive(self, target_id: str, source_ids: list[str]) -> None: ...
    async def cite(self, target_id: str, source_ids: list[str], kind: str) -> None: ...
    async def trace(self, node_id: str, depth: int) -> ProvenanceChain: ...
```

### Hot-Swap Example

```python
# Product startup - current paradigm
from primitives.eag import EAGKnowledgeStore, EAGLifecycleManager

store = EAGKnowledgeStore(memgraph, qdrant)
lifecycle = EAGLifecycleManager(store)
app = build_app(store=store, lifecycle=lifecycle)

# Future swap - new paradigm
from primitives.newparadigm import NewStore, NewLifecycle

store = NewStore(memgraph, qdrant)
lifecycle = NewLifecycle(store)
app = build_app(store=store, lifecycle=lifecycle)  # same product code
```

## What Goes in the Library

### Schema (primitives/schema/)
- Node types: `:Claim`, `:Fact`, `:Belief`, `:ReasoningChain`, `:Passage`, `:Document`
- Edge types: `DERIVED_FROM`, `SUPERSEDES`, `MEMBER_OF`, `CITES`
- Layer enum: Memory, Knowledge, Wisdom, Intelligence

### Epistemology (primitives/epistemology/)
- `combined_confidence(claim, tier, corroboration, method)` - per-claim confidence
- `aggregate_confidence(confidences)` - noisy-OR across claims
- `should_promote_r1(claim)` - single authoritative source rule
- `should_promote_r2(claims)` - multi-source corroboration rule
- `detect_contradiction(fact_a, fact_b)` - same (s,p), different o
- `supersede(winner, loser, reason)` - write SUPERSEDES edge

### Signals (primitives/signals/)
- `heat(node, retrieval_events)` - usage-based temperature
- `freshness(node, now)` - time-based decay
- `priority(node)` - composite for work ordering

### Queries (primitives/queries/)
- Parameterized Cypher templates for all graph operations
- No string concatenation with user input
- Designed for Memgraph (adaptable to Neo4j)

## What Stays in the Product

- Dagster assets and sensors
- MCP tool implementations
- FastAPI routes
- Silo/tenancy management
- Auth (WorkOS) and billing (Stripe)
- Embedding integrations (Jina, Vertex, SPLADE)
- Vector store integrations (Qdrant)
- Dashboard

## Migration Path

1. **Week 1**: Create primitives repo structure, define protocols, stub implementations
2. **Week 2**: Move schema types and epistemology from contextr to primitives
3. **Week 3**: Product repo imports primitives, wires up existing Dagster/MCP
4. **Post-MVP**: Clean up contextr → product repo migration

## Rejected Alternatives

### A. Incremental Retrofit (the spec approach)
Add EAG concepts to existing RAG-era code. Results in `:Finding` AND `:Fact`, two supersession modules, growing complexity. Same destination but more tangled.

### B. Full Rewrite
Throw away contextr, rebuild from scratch. Too slow given investor timeline.

### C. No Abstraction
Build EAG directly in contextr, accept coupling. Locks in the paradigm, no swap path.

## Consequences

- **Open-source artifact**: primitives library is publishable, good for credibility/hiring
- **Clean product repo**: no RAG-era archaeology
- **Swap path exists**: if paradigm shifts, change imports not architecture
- **Protocol design is load-bearing**: get it wrong, swap becomes rewrite anyway
- **Two repos to maintain**: coordination overhead

## References

- `contextr/context/plans/cag/2026-04-26-custodian-reconciliation-spec.md` - the retrofit spec this replaces
- `contextr/architecture/` - EAG paradigm docs
- `contextr/context/specs/rag/` - RAG-era specs
