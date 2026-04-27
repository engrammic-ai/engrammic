"""Pydantic models for Custodian structured outputs and commit payloads.

Every model here is a pydantic v2 ``BaseModel`` with ``ConfigDict(extra="forbid")``
so that hallucinated extra fields from an agent's structured output are rejected
outright rather than silently accepted. The validators in this module are
**structural only** -- they enforce shape, vocabulary, and internal consistency.
Citation-existence checking (does the cited ``node_id`` actually live in Memgraph
and belong to the calling visit's silo?) lives in the Task 5 citation validator,
not here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from context_service.extraction.models import EXTRACTION_SCHEMA, RelationshipType


def _remap_enum_cases(data: Any) -> Any:
    """Lowercase short string fields before pydantic validates Literal/enum constraints.

    Gemini returns uppercase/titlecase enum variants ("Low", "MEDIUM") when the
    schema requires lowercase. Guard: only apply to short strings unlikely to be
    free-form content (len <= 32).
    """
    if not isinstance(data, dict):
        return data
    return {
        k: (v.lower() if isinstance(v, str) and v != v.lower() and len(v) <= 32 else v)
        for k, v in data.items()
    }

# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class PassStatus(StrEnum):
    """Terminal and running states for a Custodian pass."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CRASHED = "crashed"
    BUDGET_EXCEEDED = "budget_exceeded"


class VisitStatus(StrEnum):
    """Terminal and running states for an individual cluster visit within a pass."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BUDGET_SKIPPED = "budget_skipped"
    FAILED = "failed"
    CRASHED = "crashed"


# ---------------------------------------------------------------------------
# Citations and claims
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """A single citation attached to a claim.

    Snippets are rendered at read time (see brainstorm, Data Model / Deleted-citation
    ghosts), so the citation stores only the referenced ``node_id``, its ``kind``,
    and an optional ``snippet_hash`` used for change detection during the nightly
    stale-citation sweep.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: Literal["primary", "supporting"]
    snippet_hash: str | None = None

    @model_validator(mode="before")
    @classmethod
    def fix_enum_cases(cls, data: Any) -> Any:
        return _remap_enum_cases(data)


class Claim(BaseModel):
    """A single cited claim committed by the Custodian agent."""

    model_config = ConfigDict(extra="forbid")

    text: str
    citations: list[Citation]

    @field_validator("citations")
    @classmethod
    def must_have_primary(cls, v: list[Citation]) -> list[Citation]:
        """Reject claims with zero citations or no ``primary`` citation."""
        if len(v) < 1 or not any(c.kind == "primary" for c in v):
            raise ValueError("claim needs >=1 citation and >=1 primary")
        return v


# ---------------------------------------------------------------------------
# Phase 1 / 2 / 3 intermediate structured outputs
# ---------------------------------------------------------------------------


class FastPassObservation(BaseModel):
    """Phase 1 output: cheap reconnaissance over a cluster."""

    model_config = ConfigDict(extra="forbid")

    cluster_character: str
    interesting_nodes: list[str]
    suspected_themes: list[str]
    complexity: Literal["low", "medium", "high"]
    needs_deep_pass: bool

    @model_validator(mode="before")
    @classmethod
    def fix_enum_cases(cls, data: Any) -> Any:
        return _remap_enum_cases(data)


class VisitPlan(BaseModel):
    """Phase 2 output: the strategy the deep pass will execute."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["confirm_naive", "deepen", "cross_reference", "skip"]
    tool_call_sequence: list[str]
    stop_conditions: list[str]
    skip_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def fix_enum_cases(cls, data: Any) -> Any:
        return _remap_enum_cases(data)


class BudgetStatus(BaseModel):
    """Budget telemetry injected into every tool response during a visit.

    **Scoped to the current phase's envelope**, not the whole visit. Phase 4
    (stitch) always reports ``tool_calls_remaining = 0`` -- stitch never calls
    tools and only includes ``BudgetStatus`` in its tool responses for schema
    uniformity.
    """

    model_config = ConfigDict(extra="forbid")

    tokens_remaining: int
    tool_calls_remaining: int
    wrap_up_signal: bool


# ---------------------------------------------------------------------------
# Proposed edges (inferred relations)
# ---------------------------------------------------------------------------


class ProposedEdge(BaseModel):
    """An inferred semantic edge committed by the Custodian agent.

    Uses the same closed 9-vocab as extraction (:class:`RelationshipType`). The
    ``validate_all`` model validator enforces three structural rules:

    1. ``confidence >= 0.7`` (Custodian is conservative by default).
    2. ``(source_type, type, target_type)`` is in the 9-vocab schema.
    3. ``supporting_node_ids`` names at least one id matching each side.
    """

    model_config = ConfigDict(extra="forbid")

    source_node_id: str
    target_node_id: str
    type: RelationshipType
    source_type: str
    target_type: str
    rationale: str
    supporting_node_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_all(self) -> ProposedEdge:
        if self.confidence < 0.7:
            raise ValueError(f"confidence {self.confidence} < 0.7")
        if not EXTRACTION_SCHEMA.is_valid(self.source_type, self.type, self.target_type):
            raise ValueError(
                f"({self.source_type}, {self.type}, {self.target_type}) "
                f"not in 9-vocab extraction schema"
            )
        supporting = set(self.supporting_node_ids)
        if self.source_node_id not in supporting:
            raise ValueError("rationale must cite source_node_id in supporting_node_ids")
        if self.target_node_id not in supporting:
            raise ValueError("rationale must cite target_node_id in supporting_node_ids")
        return self


# ---------------------------------------------------------------------------
# Stitch output (Phase 4)
# ---------------------------------------------------------------------------


class StitchedSentence(BaseModel):
    """A single sentence in a stitched summary, tied back to committed claims.

    ``claim_refs`` holds indices into the visit's committed claims buffer, so
    every sentence is traceable to its citations without re-emitting them.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    claim_refs: list[int]


class StitchedSummary(BaseModel):
    """Output of the stitch phase: 2-4 paragraphs assembled from committed claims."""

    model_config = ConfigDict(extra="forbid")

    summary: list[StitchedSentence]


# ---------------------------------------------------------------------------
# Finding output (what a visit produces end-to-end)
# ---------------------------------------------------------------------------


class FindingOutput(BaseModel):
    """The full finding an agent produces during one visit.

    ``scope`` distinguishes cluster-scope findings (``cluster_id`` set) from
    silo-scope findings produced by silo synthesis (``cluster_id`` is ``None``).
    """

    model_config = ConfigDict(extra="forbid")

    cluster_id: str | None
    silo_id: str
    scope: Literal["cluster", "silo"]
    claims: list[Claim]
    inferred_relations: list[ProposedEdge]
    summary: StitchedSummary | None = None

    @model_validator(mode="before")
    @classmethod
    def fix_enum_cases(cls, data: Any) -> Any:
        return _remap_enum_cases(data)

    @model_validator(mode="after")
    def validate_scope(self) -> FindingOutput:
        if self.scope == "cluster" and self.cluster_id is None:
            raise ValueError("cluster-scope finding must have a cluster_id")
        if self.scope == "silo" and self.cluster_id is not None:
            raise ValueError("silo-scope finding must not have a cluster_id")
        return self


# ---------------------------------------------------------------------------
# Pass budget (kill switches)
# ---------------------------------------------------------------------------


class PassBudget(BaseModel):
    """Pass-level hard kill switches.

    Defaults mirror the design in the brainstorm Budget Model. They are
    expected to be overridden from :class:`context_service.core.settings.CustodianSettings`
    at orchestration time; the defaults here are a safety net only.
    """

    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float = 5.0
    max_visits: int = 300
    max_total_tokens: int = 5_000_000
    per_visit_token_ceiling: int = 17_000
    max_wall_clock_seconds: int = 3_600
