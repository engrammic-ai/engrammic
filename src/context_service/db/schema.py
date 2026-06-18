"""Graph schema constants: labels, edge types, and Cypher predicate helpers.

CITE v2 schema: 5 content nodes, 6 edge types.
See context/specs/2026-06-18-coherence-layer-v2.md for rationale.
"""

from __future__ import annotations

from primitives.schema import (
    CITEEdgeType,
    IntelligenceLabel,
    KnowledgeLabel,
    MemoryLabel,
    RegistryLabel,
    WisdomLabel,
)

# --- Content node labels (v2 schema) ---
LABEL_MEMORY = MemoryLabel.MEMORY.value  # "Memory" - raw observations
LABEL_CLAIM = KnowledgeLabel.CLAIM.value  # "Claim" - evidence-backed assertions
LABEL_FACT = KnowledgeLabel.FACT.value  # "Fact" - SAGE-promoted claims
LABEL_BELIEF = WisdomLabel.BELIEF.value  # "Belief" - SAGE-synthesized
LABEL_COMMITMENT = WisdomLabel.COMMITMENT.value  # "Commitment" - agent decisions

# Core content labels for retrieval (excludes Intelligence - passive layer)
CORE_CONTENT_LABELS: tuple[str, ...] = (
    LABEL_MEMORY,
    LABEL_CLAIM,
    LABEL_FACT,
    LABEL_BELIEF,
    LABEL_COMMITMENT,
)

# Agent-writable labels (via MCP tools)
AGENT_WRITABLE_LABELS: tuple[str, ...] = (
    LABEL_MEMORY,  # remember()
    LABEL_CLAIM,  # learn()
    LABEL_COMMITMENT,  # decide()
)

# System-created labels (SAGE)
SYSTEM_CREATED_LABELS: tuple[str, ...] = (
    LABEL_FACT,
    LABEL_BELIEF,
    IntelligenceLabel.EPISTEMIC_STATE.value,
    IntelligenceLabel.BREAKTHROUGH.value,
)

# All CITE v2 node labels (for edge creation)
CITE_NODE_LABELS: tuple[str, ...] = (
    # Memory layer
    MemoryLabel.MEMORY.value,
    # Knowledge layer
    KnowledgeLabel.CLAIM.value,
    KnowledgeLabel.FACT.value,
    # Wisdom layer
    WisdomLabel.BELIEF.value,
    WisdomLabel.COMMITMENT.value,
    # Intelligence layer (passive, system-created)
    IntelligenceLabel.EPISTEMIC_STATE.value,
    IntelligenceLabel.BREAKTHROUGH.value,
    # Registry (system-managed)
    RegistryLabel.AGENT.value,
)

# --- Edge type constants (v2 schema: 6 types) ---
EDGE_DERIVED_FROM = CITEEdgeType.DERIVED_FROM.value  # provenance
EDGE_SYNTHESIZED_FROM = CITEEdgeType.SYNTHESIZED_FROM.value  # Belief -> Fact
EDGE_SUPERSEDES = CITEEdgeType.SUPERSEDES.value  # version chain
EDGE_SUPPORTS = CITEEdgeType.SUPPORTS.value  # positive epistemology
EDGE_CONTRADICTS = CITEEdgeType.CONTRADICTS.value  # negative epistemology
EDGE_ABOUT = CITEEdgeType.ABOUT.value  # meta-structure


def content_union_predicate(var: str = "n") -> str:
    """Return a Cypher predicate matching any content node.

    Matches: Memory, Claim, Fact, Belief, Commitment.
    """
    return "(" + " OR ".join(f"{var}:{lbl}" for lbl in CORE_CONTENT_LABELS) + ")"


def cite_union_predicate(var: str = "n") -> str:
    """Return a Cypher predicate matching any CITE v2 node type.

    Use for edge creation where endpoints can be any layer.
    """
    return "(" + " OR ".join(f"{var}:{lbl}" for lbl in CITE_NODE_LABELS) + ")"


# --- Legacy label constants (for migration) ---
# Aliases for v1 labels. Remove after all callers updated to v2.
LABEL_DOCUMENT = LABEL_MEMORY  # v1 -> v2 alias
LABEL_PASSAGE = LABEL_MEMORY  # v1 -> v2 alias
LABEL_ENTITY = LABEL_MEMORY  # v1 -> v2 alias (entities become Memory nodes)

# These map old labels to new. Remove after migration complete.
LEGACY_LABEL_MAP: dict[str, str] = {
    "Document": LABEL_MEMORY,
    "Passage": LABEL_MEMORY,
    "Utterance": LABEL_MEMORY,
    "Event": LABEL_MEMORY,
    "Observation": LABEL_MEMORY,
    "ProposedBelief": LABEL_BELIEF,
}

LEGACY_EDGE_MAP: dict[str, str | None] = {
    "EXTRACTED_FROM": EDGE_DERIVED_FROM,
    "REFERENCES": EDGE_DERIVED_FROM,
    "PROMOTED_FROM": EDGE_DERIVED_FROM,
    "CORROBORATES": EDGE_SUPPORTS,
    "MEMBER_OF": None,  # killed
    "MENTIONS": None,  # killed
}
