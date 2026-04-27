# context-service specs

Service-level specifications for the context-service. These cover implementation details, API contracts, and operational concerns that are specific to this service.

## Index

| Spec | Status | Contents |
|------|--------|----------|
| (none yet) | — | First specs to be added as service-layer features stabilise |

## Relationship to primitives docs

CAG paradigm documentation (layers, transitions, epistemology) lives in `primitives/context/specs/`. This directory covers what the service layer adds on top: storage integration, MCP interface, Custodian workers, extraction pipeline, and operational config.

## Relationship to contextr (original prototype)

The RAG-era specs that informed this service — cache, custodian, extraction, heatmap, ingest, retrieval — were authored in the `contextr` prototype repo (`NovusEdge/CTXR`, private). The ported docs live in `context/specs/rag/` within the `primitives` package (split out during the 2026-04-26 port session). When tracing the rationale for a shipped code path, the relevant spec is in `primitives/context/specs/rag/` rather than here.
