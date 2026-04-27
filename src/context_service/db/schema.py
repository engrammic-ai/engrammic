"""Graph schema constants: labels, edge types, and Cypher predicate helpers.

These constants are the canonical string values used in Cypher queries.
They bridge the RAG-era label scheme (Document/Passage/Claim/Entity) with
the CITE primitives.schema enums. Import from here for all query construction.
"""

from __future__ import annotations

from primitives.schema import CITEEdgeType, KnowledgeLabel, MemoryLabel, RegistryLabel

# --- Content node labels (RAG-era / Memory layer) ---
LABEL_DOCUMENT = MemoryLabel.DOCUMENT.value  # "Document"
LABEL_PASSAGE = MemoryLabel.PASSAGE.value  # "Passage"
LABEL_CLAIM = KnowledgeLabel.CLAIM.value  # "Claim"
LABEL_ENTITY = RegistryLabel.ENTITY.value  # "Entity" — registry pivot

CORE_CONTENT_LABELS: tuple[str, ...] = (LABEL_DOCUMENT, LABEL_PASSAGE, LABEL_CLAIM)

# --- Edge type constants (O-30) ---
EDGE_DERIVED_FROM = CITEEdgeType.DERIVED_FROM.value  # "DERIVED_FROM"
EDGE_EXTRACTED_FROM = CITEEdgeType.EXTRACTED_FROM.value  # "EXTRACTED_FROM"
EDGE_MENTIONS = CITEEdgeType.MENTIONS.value  # "MENTIONS"
EDGE_REFERENCES = CITEEdgeType.REFERENCES.value  # "REFERENCES" — Claim -> Document


def content_union_predicate(var: str = "n") -> str:
    """Return a Cypher predicate matching any Document|Passage|Claim.

    Use in ``MATCH (n) WHERE {content_union_predicate("n")} AND ...`` where
    the caller is genuinely label-agnostic over content nodes.
    """
    return "(" + " OR ".join(f"{var}:{lbl}" for lbl in CORE_CONTENT_LABELS) + ")"
