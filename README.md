# Engrammic Context Service

Others store memories. We adjudicate claims.

---

## What this is

Engrammic is a memory backend for AI agents that treats knowledge as something to be earned, not just stored. When an agent writes a fact, the system validates it, tracks where it came from, detects contradictions, and promotes it through epistemic layers only when corroboration warrants it.

The result is a knowledge graph where every node has a trust level, a provenance chain, and a lifecycle — not just a vector embedding.

## What this is not

- A vector database wrapper. Qdrant is one storage layer; the graph and epistemic machinery are the product.
- A RAG pipeline. Retrieval is one part of a larger write-time and read-time architecture.
- A scratchpad. Unverified observations decay. Claims require evidence. Beliefs require corroboration.
- Drop-in compatible with systems that treat memory as a key-value store.

---

## Architecture overview

Two surfaces sit on top of a shared service layer:

```
Agents / Clients
       |
+------+------+
|             |
MCP Server    FastAPI REST
(primary)     (admin)
|             |
+------+------+
       |
Service Layer (ContextService, SiloService)
       |
+------+------+------+
|             |      |
Memgraph   Qdrant   Redis
(graph)    (vector) (cache)
```

The **MCP server** is the primary agent surface. Tools are intent-based verbs (`remember`, `learn`, `recall`, etc.). Tool names and descriptions are config, not code: `src/context_service/config/mcp_tools.yaml`.

The **FastAPI REST** surface handles admin operations (silo management, health, metrics).

**SAGE** (Synthesis, Aggregation, Graph Evolution) is a background Dagster system:

- `custodian_pipeline` - extracts, validates, and promotes claims to facts (every 15 min)
- `knowledge_pipeline` - causal transitivity and pattern detection (hourly)
- `clustering_pipeline` - fact clustering and belief synthesis (daily at 04:00 UTC)
- `heat_pipeline` - heat scoring and link review (daily at 02:00 UTC)
- `groundskeeper_nightly` - retention and compaction (daily at 01:00 UTC)

Full architecture: [`context/architecture.md`](context/architecture.md)

---

## Quick evaluation

Requires Docker Compose.

```bash
# Clone and install
git clone https://github.com/engrammic-ai/engrammic
cd context-service
uv sync --all-extras          # requires uv: https://github.com/astral-sh/uv

# Start local stack (Memgraph, Qdrant, Redis)
just up

# Run the service
just dev
```

The MCP server starts at `http://localhost:8000/mcp`. Connect any MCP-compatible client.

Self-hosted deployment docs: [`docs/self-hosted/`](docs/self-hosted/)

---

## Key concepts

### Epistemic layers

Every node in the graph has a layer that reflects its trust level:

| Layer | Type | How it forms |
|-------|------|-------------|
| Memory | Observation | Agent writes via `remember`. Decays over time. |
| Knowledge | Claim / Fact | Agent writes via `learn` with an evidence URI. Promoted to Fact by custodian after corroboration. |
| Wisdom | Belief / Commitment | Belief: synthesized by SAGE from corroborated facts. Commitment: deferred (not yet implemented). |

### Write-gate

Claims (Knowledge layer) require an evidence URI at write time. The custodian validates citations, checks business rules, and either promotes the claim to a Fact or rejects it. This is not optional — the system will reject writes to the knowledge layer without evidence.

### Supersession

Updates create version chains rather than overwrites. The old node stays in the graph with a `valid_to` timestamp; queries return only the chain head. Use `trace(node_id)` to walk provenance.

### SAGE synthesis flow

```
Agent writes learn()
       |
AsyncBatchTrigger (batches writes)
       |
custodian_pipeline (every 15 min)
  - SPO extraction
  - Citation validation
  - Business rule check
  - Claim -> Fact promotion
       |
clustering_pipeline (daily)
  - Fact clustering via semantic corroboration
  - Cluster -> Belief (Wisdom layer)
```

### MCP tool surface

| Tool | What it does |
|------|-------------|
| `remember` | Store an observation (Memory layer, no evidence required) |
| `learn` | Record a claim with evidence (Knowledge layer) |
| `recall` | Retrieve by semantic query, node ID, or fusion mode |
| `trace` | Provenance: walk backward to sources or forward to dependents |
| `forget` | Request node deletion with optional cascade |
| `tick` | Lightweight engagement check without full recall |
| `update` | Update existing knowledge by superseding with new content |

---

## Repository structure

```
src/context_service/
├── mcp/           # MCP server + tools (primary agent surface)
├── api/           # FastAPI admin routes
├── engine/        # Storage protocols (depend on this, not concrete stores)
├── stores/        # Memgraph, Qdrant, Redis implementations
├── services/      # Business logic (ContextService, SiloService, ...)
├── custodian/     # SAGE pipeline (custodian, synthesizer agents)
├── pipelines/     # Scheduled jobs (groundskeeper, validator, ...)
├── config/        # Settings, mcp_tools.yaml, prompt templates
├── auth/          # WorkOS + OAuth
├── embeddings/    # Embedding clients (Jina, Vertex, SPLADE)
└── signals/       # Heat, freshness, priority scoring
```

Key files:

- `src/context_service/config/mcp_tools.yaml` - MCP tool surface (source of truth for names and descriptions)
- `src/context_service/engine/protocols.py` - storage interfaces (depend on these, not concrete stores)
- `context/architecture.md` - full service architecture
- `context/plans/` - active implementation plans

---

## Development commands

All Python runs via `uv run`. See `justfile` for the full list.

| Command | What it does |
|---------|-------------|
| `just install` | `uv sync --all-extras` |
| `just check` | Lint + typecheck (must pass before merge) |
| `just test` | Run pytest (`just test -k name` for filtering) |
| `just ci` | check + test (pre-push) |
| `just db-migrate` | Run Alembic migrations |
| `just dev` | FastAPI with reload |
| `just up / down` | Local stack (Memgraph, Qdrant, Redis) |

---

## Known limitations

- **Evidence validation is best-effort.** The custodian fetches evidence URIs to validate them, but auth-gated or private URLs cannot be verified. Content hash verification is planned but not yet implemented.
- **SAGE synthesis latency.** Beliefs do not form in real time. A claim written now may not surface as a synthesized belief for 10-40 minutes depending on cluster thresholds and SAGE cadence.
- **Memgraph clustering requires MAGE.** The Leiden algorithm used for fact clustering requires the `memgraph-mage` image, not the standard Memgraph image.
- **Multi-silo coordination is deferred.** The current architecture assumes one active silo per session. Cross-silo operations and agent workspace resolution are not yet implemented.
- **Mypy strict mode has pre-existing errors.** `just check` enforces ruff + mypy strict, but ~76 pre-existing mypy errors remain. New code must pass; the backlog is fixed opportunistically.

---

## Related

- [primitives](https://github.com/engrammic-ai/primitives) - Schema library (`primitives.schema.*`, `primitives.eag.*`)
- [mcp client](https://github.com/engrammic-ai/mcp) - Thin MCP proxy client
- [`../primitives/docs/`](../primitives/docs/) - EAG paradigm documentation

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) if it exists, or open an issue.

Rules for contributors:
1. `just check` must pass before any merge (mypy strict + ruff)
2. Depend on `engine/protocols.py`, not concrete stores
3. New knowledge-layer writes require evidence URIs
4. No commits directly to `main`

---

## License

Apache 2.0. See [`LICENSE`](LICENSE).
