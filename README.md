<p align="center">
  <img src="https://engrammic.ai/logo.svg" alt="Engrammic" width="200" />
</p>

<h1 align="center">Engrammic Context Service</h1>

<p align="center">
  <em>Others store memories. We adjudicate claims.</em>
</p>

<p align="center">
  <a href="https://github.com/engrammic-ai/context-service/actions"><img src="https://github.com/engrammic-ai/context-service/actions/workflows/ci.yaml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/engrammic-ai/context-service/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://pypi.org/project/engrammic-primitives/"><img src="https://img.shields.io/pypi/v/engrammic-primitives.svg" alt="PyPI" /></a>
</p>

---

## What this is

Engrammic is a memory backend for AI agents that treats knowledge as something to be earned, not just stored. When an agent writes a fact, the system validates it, tracks where it came from, detects contradictions, and promotes it through epistemic layers only when corroboration warrants it.

The result is a knowledge graph where every node has a trust level, a provenance chain, and a lifecycle.

## What this is not

- **Not a vector database wrapper.** Qdrant is one storage layer; the graph and epistemic machinery are the product.
- **Not a RAG pipeline.** Retrieval is one part of a larger write-time and read-time architecture.
- **Not a scratchpad.** Unverified observations decay. Claims require evidence. Beliefs require corroboration.
- **Not drop-in compatible** with systems that treat memory as a key-value store.

---

## Architecture

```
Agents / Clients
       │
┌──────┴──────┐
│             │
MCP Server    FastAPI REST
(primary)     (admin)
│             │
└──────┬──────┘
       │
Service Layer
       │
┌──────┼──────┐
│      │      │
Memgraph  Qdrant  Redis
(graph)   (vector) (cache)
```

| Surface | Purpose |
|---------|---------|
| **MCP Server** | Primary agent surface. Intent-based verbs (`remember`, `learn`, `recall`). |
| **FastAPI REST** | Admin operations (silo management, health, metrics). |
| **SAGE** | Background Dagster pipelines for synthesis, validation, and maintenance. |

Full architecture: [`context/architecture.md`](context/architecture.md)

---

## Quick start

Requires Docker Compose and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/engrammic-ai/context-service
cd context-service
uv sync --all-extras

just up   # Start Memgraph, Qdrant, Redis
just dev  # Start the service
```

MCP server starts at `http://localhost:8000/mcp`.

Self-hosted deployment: [`docs/self-hosted/`](docs/self-hosted/)

---

## Epistemic layers

Every node has a layer reflecting its trust level:

| Layer | Type | How it forms |
|-------|------|--------------|
| **Memory** | Observation | Agent writes via `remember`. Decays over time. |
| **Knowledge** | Claim | Agent writes via `learn` with evidence URI. |
| **Knowledge** | Fact | Promoted from Claim after corroboration (3+ sources). |
| **Wisdom** | Belief | Synthesized by SAGE from clustered Facts. |
| **Intelligence** | Commitment | Agent-declared or system-derived goals. |

### Write-gate

Claims require an evidence URI. The custodian validates citations and either promotes to Fact or rejects. No evidence = no write to knowledge layer.

### Supersession

Updates create version chains, not overwrites. Old nodes stay with `valid_to` timestamps. Use `trace(node_id)` to walk provenance.

---

## MCP tools

| Tool | Purpose |
|------|---------|
| `remember` | Store observation (Memory layer, no evidence required) |
| `learn` | Record claim with evidence (Knowledge layer) |
| `recall` | Retrieve by semantic query, node ID, or fusion |
| `trace` | Walk provenance chain |
| `forget` | Request deletion with optional cascade |
| `tick` | Lightweight engagement check |
| `update` | Supersede existing knowledge |

Full reference: [`docs/api/mcp-tools-reference.md`](docs/api/mcp-tools-reference.md)

---

## Links

|  |  |
|--|--|
| [engrammic.ai](https://engrammic.ai) | Website |
| [docs.engrammic.ai](https://docs.engrammic.ai) | Documentation |
| [research](https://github.com/engrammic-ai/research) | Papers and benchmarks |
| [primitives](https://github.com/engrammic-ai/primitives) | Schema library |
| [mcp](https://github.com/engrammic-ai/mcp) | MCP proxy client |

---

## Contributing

1. `just check` must pass (mypy strict + ruff)
2. Depend on `engine/protocols.py`, not concrete stores
3. Knowledge-layer writes require evidence URIs
4. No commits directly to `main`

---

## License

Apache 2.0. See [`LICENSE`](LICENSE).
