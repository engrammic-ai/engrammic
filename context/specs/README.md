# context-service specs

Service-level specifications for the context-service. These cover implementation details, API contracts, and operational concerns that are specific to this service.

## Index

| Spec | Status | Contents |
|------|--------|----------|
| [auth-per-request.md](auth-per-request.md) | Stable (v1-β1) | Per-request auth resolution + silo-ownership enforcement |
| [mcp-tool-surface.md](mcp-tool-surface.md) | Stable | MCP tool contracts |
| [silo-portability.md](silo-portability.md) | Stable (v1-β4) | Silo export/import JSONL format |
| [signals-port.md](signals-port.md) | Draft 2026-04-30 | Heat / freshness / priority port from prototype (phased) |
| [supersession-pointer-spec.md](supersession-pointer-spec.md) | Draft | O(1) chain head resolution via tail_id/head_id pointers |

## Relationship to primitives docs

EAG (Epistemic Augmented Generation) paradigm documentation (layers, transitions, epistemology) lives in `primitives/context/specs/`. This directory covers what the service layer adds on top: storage integration, MCP interface, Custodian workers, extraction pipeline, and operational config.

## Relationship to prototype (original prototype)

The RAG-era specs that informed this service — cache, custodian, extraction, heatmap, ingest, retrieval — were authored in the `prototype` prototype repo (`NovusEdge/CTXR`, private). The ported docs live in `context/specs/rag/` within the `primitives` package (split out during the 2026-04-26 port session). When tracing the rationale for a shipped code path, the relevant spec is in `primitives/context/specs/rag/` rather than here.
