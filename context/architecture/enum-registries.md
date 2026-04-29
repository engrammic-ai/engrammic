# Enum Registries: extraction vs EAG schema

## `extraction.models.RelationshipType` vs `primitives.schema.edges.CITEEdgeType`

These two enums intentionally overlap (both define `CAUSES`, for example) but serve different purposes:

| Enum | Purpose | Origin |
|------|---------|--------|
| `RelationshipType` | LLM extraction vocabulary. Guides the extraction pipeline prompts and the relationship types the model is asked to emit. | `context_service.extraction.models` |
| `CITEEdgeType` | Graph edge registry. The canonical set of edge types that the EAG paradigm recognizes at the graph layer. | `primitives.schema.edges` |

### Why not merge?

1. **Different lifecycles.** Extraction vocabulary can evolve faster than the paradigm contract. Adding a new extraction relationship doesn't require a primitives release.

2. **Different consumers.** The extraction pipeline uses `RelationshipType` to constrain LLM outputs and map them to graph edges. Downstream EAG logic uses `CITEEdgeType` for traversal, querying, and semantic reasoning. The mapping layer between them is explicit and auditable.

3. **Semantic drift.** An extraction "CAUSES" relationship might not always map 1:1 to an EAG `CAUSES` edge. The extraction layer may emit a relationship that needs post-processing (e.g., normalization, deduplication) before landing as a graph edge.

### Recommendation

Keep the enums separate. Map explicitly where the extraction output meets the graph layer. If a new extraction relationship is added, decide whether it warrants a new `CITEEdgeType` in primitives or should be mapped to an existing one.

### Audit reference

Closes EAG integration audit item #7 (`eag-integration-audit.md`).
