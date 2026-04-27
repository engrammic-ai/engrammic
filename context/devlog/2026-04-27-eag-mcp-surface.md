# 2026-04-27: EAG MCP Tool Surface Implementation

## Summary

Designed and implemented intent-based MCP tool surface for EAG paradigm. Replaced CRUD-style tools (`context_store`, `context_get`, `context_lookup`) with epistemology-aware verbs reflecting agent cognition.

## Design Session

Brainstormed MCP tool design with these key decisions:

1. **Intent-based verbs** over CRUD: `remember`, `assert`, `commit`, `reflect`
2. **Evidence required for Knowledge layer** — no hallucinated sources; must be `node:<uuid>` or URI
3. **Layer-aware reads, layer-inferred writes** — agents filter by layer on read; writes route to correct layer by verb
4. **Agent-scoped commitments** — beliefs tied to declaring agent via `DECLARED_BY`
5. **Evidence validation pipeline** — URI reachability checks, node ref validation, configurable per-silo

## Implementation

Executed via 4-agent Sonnet team (`eag-mcp-tools`):

| Agent | Deliverables |
|-------|--------------|
| `foundation` | Pydantic models (`models/mcp.py`), EvidenceValidator (`services/evidence.py`) |
| `write-tools` | `context_remember`, `context_assert`, `context_commit`, `context_reflect` |
| `read-tools` | `context_query`, `context_link`, `context_graph` |
| `meta-tools` | `context_provenance`, `context_history`, `context_reason` |

### Tool Catalogue (13 total)

| Tool | Layer | Purpose |
|------|-------|---------|
| `context_remember` | Memory | Store experiences with decay semantics |
| `context_assert` | Knowledge | Assert claims with grounded evidence |
| `context_commit` | Wisdom | Declare beliefs (agent-scoped) |
| `context_reflect` | Meta | Store meta-observations |
| `context_link` | Cross | Create typed relationships |
| `context_query` | Read | Semantic search + layer/time filtering |
| `context_get` | Read | Retrieve by ID with optional edges |
| `context_graph` | Read | Graph traversal from semantic seed |
| `context_provenance` | Meta | Trace citation chain to Memory sources |
| `context_history` | Meta | Belief evolution via SUPERSEDES chain |
| `context_reason` | Intelligence | Store reasoning chains with crystallizations |
| `silo_create` | Admin | Create tenancy boundary |
| `silo_list` | Admin | List silos for org |

### Evidence Pipeline

```
URI -> Cache -> Allowlist -> Reachability -> [Fetch] -> [Ingest] -> Result
```

- Node refs validated against Memgraph (must exist in silo)
- URIs validated via HEAD request
- Configurable per-silo: `allowlist`, `auto_ingest`, `require_reachable`

### Key Files

**New:**
- `src/context_service/models/mcp.py` — Pydantic models (DecayClass, SourceType, SPOClaim, etc.)
- `src/context_service/services/evidence.py` — EvidenceValidator
- `src/context_service/services/context_meta.py` — Meta-memory result types
- `src/context_service/mcp/tools/context_*.py` — 11 new tool modules

**Modified:**
- `src/context_service/services/context.py` — Added `remember`, `assert_claim`, `commit_belief`, `reflect`, `query`, `link`, `graph_traversal`, `provenance`, `history`, `reason`
- `src/context_service/db/queries.py` — Added provenance/history Cypher queries

**Removed:**
- `src/context_service/mcp/tools/context_store.py` (deprecated)
- `src/context_service/mcp/tools/context_lookup.py` (deprecated)

## P0 Fixes (Earlier Session)

Also resolved 6 P0s from codebase review via separate team (`review-fixes`):

- Wired 5 existing MCP tools to backing services
- Added missing indexes (Cluster, Entity, Document, Passage)
- Fixed N+1 in `lookup()` with `batch_get_nodes`
- Wired embedding cache in Jina/Vertex clients
- Added retry to `execute_write` with transient error handling
- Fixed consensus promotion atomicity (deterministic ID, MERGE, transaction)

## Specs

- `context/specs/mcp-tool-surface.md` — Full design with signatures
- `../primitives/context/specs/05-mcp-contract.md` — Paradigm-level contract

## Verification

- 84 tests passing
- ruff clean
- mypy strict clean
- All tools register and return structured responses

## Commits

**context-service:**
- `2da68c8`: feat: MCP tool surface design + P0 fixes
- `54ea6ae`: docs: add EAG MCP tools implementation plan
- `60ed535`: feat(mcp): add Pydantic models for EAG tool surface
- `0170d2b`: feat(services): add evidence validation pipeline
- `bb31501`: feat(mcp): add write + read tools
- `edde774`: feat(mcp): add meta-memory tools
- `c74a3ba`: feat(mcp): wire all EAG tools, remove deprecated CRUD tools

**primitives:**
- `96ac015`: docs: add MCP contract spec (05-mcp-contract.md)

## Next

- Update `context/api-examples.md` to reflect new tool signatures
- Wire remaining tools documented in spec (`context_store_chain` equivalent via `context_reason` + crystallizations)
- Integration tests with live Memgraph/Qdrant
