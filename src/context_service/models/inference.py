"""Pydantic models for inference storage: ReasoningChain and Commitment.

ReasoningChain is a provenance artifact (own label, not multi-labeled on Claim).
Commitment is an interpretive frame (multi-labeled on Claim, reserved predicates).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from functools import lru_cache
from typing import Final, Literal

from primitives.schema.labels import IntelligenceLabel, KnowledgeLabel
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Commitment predicate registry (ported from prototype predicate_registry)
# ---------------------------------------------------------------------------

COMMITMENT_PREDICATES_V1: Final[frozenset[str]] = frozenset(
    [
        "refers_to",
        "means_in_context",
        "is_alias_of",
        "interpretation_of",
        "scope_equals",
    ]
)


@lru_cache(maxsize=8)
def _load_predicate_registry(version: str) -> frozenset[str]:
    if version == "v1":
        return COMMITMENT_PREDICATES_V1
    raise ValueError(f"Unknown predicate registry version: {version}")


def _is_valid_commitment_predicate(predicate: str, *, version: str = "v1") -> bool:
    return predicate in _load_predicate_registry(version)


# ---------------------------------------------------------------------------
# Claim ID computation (ported from prototype engine.queries.compute_claim_id)
# ---------------------------------------------------------------------------


def _canonical(value: str) -> str:
    return value.strip().lower()


def _compute_claim_id(
    *,
    subject: str,
    predicate: str,
    object: str,
    valid_from: datetime | None,
    valid_to: datetime | None,
    source_doc_id: str | None,
    label_tier: str = KnowledgeLabel.CLAIM,
) -> str:
    """O-12 claim-ID hash extended with label_tier per R16-12."""
    parts = [
        _canonical(subject),
        predicate,
        _canonical(object),
        str(int(valid_from.timestamp() * 1e6)) if valid_from else "",
        str(int(valid_to.timestamp() * 1e6)) if valid_to else "",
        source_doc_id or "",
        label_tier,
    ]
    return hashlib.blake2b("|".join(parts).encode(), digest_size=32).hexdigest()


# ---------------------------------------------------------------------------
# Chain ID computation
# ---------------------------------------------------------------------------


def _step_semantic_hash(step: ChainStep, index: int) -> str:
    parts = [
        str(index),
        step.operation,
        step.conclusion.strip().lower(),
        "|".join(sorted(step.premise_refs)),
    ]
    return hashlib.blake2b("|".join(parts).encode(), digest_size=16).hexdigest()


def _compute_chain_id(
    silo_id: str,
    steps: list[ChainStep],
    produced_by_agent_id: str,
    query_context_hash: str | None,
) -> str:
    """Content-addressed chain ID per R16-3."""
    step_hashes = [_step_semantic_hash(s, idx) for idx, s in enumerate(steps)]
    all_premises = sorted({p for s in steps for p in s.premise_refs})
    parts = [
        silo_id,
        "|".join(step_hashes),
        "|".join(all_premises),
        produced_by_agent_id,
        query_context_hash or "",
    ]
    return hashlib.blake2b("|".join(parts).encode(), digest_size=32).hexdigest()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ChainStep(BaseModel):
    """A single reasoning step within a hot :ReasoningChain."""

    model_config = {"extra": "forbid"}

    step_index: int = Field(ge=0)
    premise_refs: list[str] = Field(default_factory=list)
    operation: str  # NL descriptor: deduction, synthesis, analogy, etc.
    conclusion: str
    confidence: float = Field(ge=0.0, le=1.0)


class CommitmentScope(BaseModel):
    """Scope binding for a :Claim:Commitment."""

    model_config = {"extra": "forbid"}

    type: Literal["silo", "document", "cluster", "entity", "time_range"]
    id: str | None = None
    from_: datetime | None = Field(None, alias="from")
    to: datetime | None = None

    @model_validator(mode="after")
    def _validate_scope_fields(self) -> CommitmentScope:
        if self.type in ("document", "cluster", "entity") and self.id is None:
            raise ValueError(f"scope type '{self.type}' requires 'id'")
        if self.type == "time_range" and (self.from_ is None or self.to is None):
            raise ValueError("scope type 'time_range' requires 'from' and 'to'")
        return self


class ReasoningChain(BaseModel):
    """A :ReasoningChain node — provenance artifact with tiered hot/cold storage.

    Node label: IntelligenceLabel.REASONING_CHAIN
    """

    model_config = {"extra": "forbid"}

    node_label: str = IntelligenceLabel.REASONING_CHAIN

    silo_id: str
    tier: Literal["hot", "cold"] = "hot"
    produced_by_model: str
    produced_by_agent_id: str
    query_context_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Hot form
    steps: list[ChainStep] | None = None

    # Cold form
    compact_summary: str | None = None
    compacted_at: datetime | None = None
    compacted_by_model: str | None = None

    # Lifecycle
    status: Literal["draft", "published", "superseded", "retracted"] = "draft"
    source: Literal["agent_explicit", "session_trace_inferred"] = "agent_explicit"
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None

    # Heat / scale
    access_count: int = 0
    last_accessed_at: datetime | None = None
    heat_score: float = 0.0

    # Computed
    id: str | None = None

    @model_validator(mode="after")
    def _compute_id(self) -> ReasoningChain:
        if self.id is None and self.steps:
            self.id = _compute_chain_id(
                self.silo_id,
                self.steps,
                self.produced_by_agent_id,
                self.query_context_hash,
            )
        if self.id is None and self.tier == "cold":
            self.id = hashlib.blake2b(
                f"{self.tier}:{self.silo_id}:{self.created_at.isoformat()}:{self.produced_by_agent_id}".encode(),
                digest_size=32,
            ).hexdigest()
        return self

    @model_validator(mode="after")
    def _tier_invariants(self) -> ReasoningChain:
        if self.tier == "hot" and not self.steps:
            raise ValueError("hot chain must have steps")
        if self.tier == "cold" and not self.compact_summary:
            raise ValueError("cold chain must have compact_summary")
        return self


class Conclusion(BaseModel):
    """A :Conclusion node - aggregates reasoning chains with consolidation."""

    model_config = {"extra": "forbid"}

    node_label: str = "Conclusion"
    silo_id: str
    query_context_hash: str
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["active", "consolidated"] = "active"
    created_by_agent_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None


class Commitment(BaseModel):
    """A :Claim:Commitment node — interpretive frame with reserved predicates.

    Multi-labeled on :Claim. Reuses full claim lifecycle (SUPERSEDES, O-14 gate,
    Finding promotion).

    Node labels: KnowledgeLabel.CLAIM + KnowledgeLabel.COMMITMENT
    """

    model_config = {"extra": "forbid"}

    node_labels: tuple[str, str] = (KnowledgeLabel.CLAIM, KnowledgeLabel.COMMITMENT)

    silo_id: str
    subject: str
    predicate: str
    object: str
    scope: CommitmentScope
    produced_by_agent_id: str
    rationale_chain_id: str | None = None

    # Inherited from :Claim
    status: Literal["draft", "published", "superseded", "retracted"] = "draft"
    source: Literal["agent_explicit", "alias_registry", "extraction"] = "agent_explicit"
    confidence_tier: Literal["high", "medium", "low"] = "medium"
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None

    # Commitment-specific
    distinct_agent_count: int = 1
    fit_signal_base: float = 0.5
    predicate_version: str = "v1"

    # Computed
    id: str | None = None
    label_tier: str = KnowledgeLabel.COMMITMENT

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, v: str) -> str:
        if not _is_valid_commitment_predicate(v, version="v1"):
            raise ValueError(
                f"predicate '{v}' is not in the reserved commitment predicate registry"
            )
        return v

    @model_validator(mode="after")
    def _compute_commitment_id(self) -> Commitment:
        if self.id is None:
            self.id = _compute_claim_id(
                subject=self.subject,
                predicate=self.predicate,
                object=self.object,
                valid_from=self.valid_from,
                valid_to=self.valid_to,
                source_doc_id=None,
                label_tier=self.label_tier,
            )
        return self


__all__ = [
    "ChainStep",
    "Commitment",
    "CommitmentScope",
    "Conclusion",
    "ReasoningChain",
]
