"""Data models for entity/relationship extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ExtractionStatus(StrEnum):
    """Status of an extraction job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RelationshipType(StrEnum):
    """Closed vocabulary of relationship types (edge labels).

    This is a domain-agnostic set that applies to code, meeting notes,
    research, agent memory, and any other knowledge domain the service stores.
    The free-form specific verb is captured on the edge's ``kind`` property,
    not as a new label.
    """

    COMPOSES = "COMPOSES"  # X is part of / contains Y
    DEPENDS_ON = "DEPENDS_ON"  # X requires Y to function
    DERIVES_FROM = "DERIVES_FROM"  # X is produced / extracted from Y
    SPECIALIZES = "SPECIALIZES"  # X is a kind / refinement of Y
    INSTANTIATES = "INSTANTIATES"  # X is an instance of type Y
    CAUSES = "CAUSES"  # X triggers / leads to Y
    PREVENTS = "PREVENTS"  # X blocks / inhibits Y from occurring
    CORROBORATES = "CORROBORATES"  # X supports / confirms Y
    CONTRADICTS = "CONTRADICTS"  # X opposes / supersedes Y (symmetric)
    REFERENCES = "REFERENCES"  # X mentions / describes Y
    RELATED_TO = "RELATED_TO"  # fallback, unclear but related (symmetric)


class ExtractionSchema:
    """Source of truth for allowed ``(source_type, edge_label, target_type)`` tuples.

    The 10-vocab :class:`RelationshipType` enum defines the closed set of edge labels.
    The extraction prompt describes the semantics of each label but does **not** encode
    which node-type pairings are allowed per label — ``entity_type`` is a free-form
    noun chosen by the LLM ("person", "module", "decision", "metric", ...), so there
    is no fixed matrix to parse.

    Until a curated matrix exists, this schema is intentionally permissive: every
    :class:`RelationshipType` allows ``(ANY, label, ANY)``. The Custodian
    ``ProposedEdge.validate_all`` validator calls :meth:`is_valid` so the moment a
    stricter matrix lands, rejection kicks in automatically without touching the
    agent surface.

    TODO: Tighten per-label source/target type pairings once a curated matrix is agreed.
    """

    #: Sentinel meaning "any ``entity_type`` string is allowed in this slot".
    ANY: str = "*"

    #: Currently every edge label maps to ``(ANY, label, ANY)``. Replace with a
    #: concrete ``frozenset[tuple[str, RelationshipType, str]]`` once the matrix
    #: is curated; :meth:`is_valid` will then fall through to exact-tuple lookup.
    ALLOWED_TUPLES: frozenset[tuple[str, RelationshipType, str]] = frozenset()

    @classmethod
    def is_valid(cls, source_type: str, edge_label: RelationshipType, target_type: str) -> bool:
        """Return True if ``(source_type, edge_label, target_type)`` is permitted."""
        if not source_type or not target_type:
            return False
        if not isinstance(edge_label, RelationshipType):
            try:
                RelationshipType(edge_label)
            except ValueError:
                return False
        if cls.ALLOWED_TUPLES:
            return (source_type, edge_label, target_type) in cls.ALLOWED_TUPLES
        return True


#: Module-level singleton used by the Custodian ProposedEdge validator.
EXTRACTION_SCHEMA = ExtractionSchema()


#: Relationship types whose default directionality is symmetric (non-directed).
SYMMETRIC_RELATIONSHIP_TYPES: frozenset[RelationshipType] = frozenset(
    {RelationshipType.CONTRADICTS, RelationshipType.RELATED_TO}
)

#: Allowed values for the temporal edge property.
_ALLOWED_TEMPORAL: frozenset[str] = frozenset({"past", "future"})


class RelationshipValidationError(ValueError):
    """Raised when an ExtractedRelationship has invalid field values."""


@dataclass
class ExtractedEntity:
    """An entity extracted from context content."""

    name: str
    entity_type: str
    description: str
    qualified_name: str | None = None
    file_path: str | None = None


# Sentinel used so we can distinguish "caller did not pass directed" from
# "caller explicitly passed True" — this lets us default directionality based
# on the relationship type while still honoring explicit overrides.
_DIRECTED_UNSET: Any = object()


@dataclass
class ExtractedRelationship:
    """A relationship extracted between two entities.

    ``relationship_type`` is restricted to the closed :class:`RelationshipType`
    vocabulary. Domain-specific nuance lives on ``kind`` (a free-form snake_case
    verb chosen by the LLM) and ``temporal`` (``"past"`` / ``"future"`` / ``None``).
    """

    source: str
    target: str
    relationship_type: RelationshipType
    kind: str = ""
    directed: bool = field(default=_DIRECTED_UNSET)
    confidence: float = 1.0
    temporal: str | None = None
    source_node_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Coerce string labels into the enum; raise if not in the closed set.
        if not isinstance(self.relationship_type, RelationshipType):
            try:
                self.relationship_type = RelationshipType(self.relationship_type)
            except ValueError as e:
                raise RelationshipValidationError(
                    f"Unknown relationship_type: {self.relationship_type!r}. "
                    f"Must be one of {[t.value for t in RelationshipType]}."
                ) from e

        # Default directionality by type when caller did not specify.
        if self.directed is _DIRECTED_UNSET:
            self.directed = self.relationship_type not in SYMMETRIC_RELATIONSHIP_TYPES

        if self.temporal is not None and self.temporal not in _ALLOWED_TEMPORAL:
            raise RelationshipValidationError(
                f"Invalid temporal value: {self.temporal!r}. Must be None, 'past', or 'future'."
            )

        if not (0.0 <= float(self.confidence) <= 1.0):
            raise RelationshipValidationError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )


@dataclass
class ClaimTriple:
    """A structured triple produced by Stage 4 (semantic extraction).

    Each triple corresponds to one :Claim node in the graph. Subject/predicate/
    object represent the canonical semantic content; entity_mentions are the
    named entities the claim refers to; ref_doc_id is set when the object IS a
    document (triggers a REFERENCES edge per O-30).
    """

    subject: str
    predicate: str
    object: str
    source_passage_id: str
    source_doc_id: str
    valid_from: str
    valid_to: str | None = None
    confidence: float = 1.0
    entity_mentions: list[EntityMention] = field(default_factory=list)
    ref_doc_id: str | None = None


@dataclass
class EntityMention:
    """A named entity referenced in a ClaimTriple."""

    entity_id: str
    name: str
    entity_type: str = "unknown"


@dataclass
class ContradictsPair:
    """Two claims whose content is in logical contradiction."""

    fingerprint_a: str
    fingerprint_b: str
    claim_id_a: str
    claim_id_b: str


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)


@dataclass
class ExtractionJob:
    """Tracks the status of an extraction job."""

    id: str
    node_id: str
    silo_id: str
    status: ExtractionStatus = ExtractionStatus.PENDING
    entity_count: int = 0
    relationship_count: int = 0
    claim_node_ids: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/response."""
        return {
            "id": self.id,
            "node_id": self.node_id,
            "silo_id": self.silo_id,
            "status": self.status.value,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractionJob:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(UTC)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            id=data["id"],
            node_id=data["node_id"],
            silo_id=data["silo_id"],
            status=ExtractionStatus(data.get("status", "pending")),
            entity_count=data.get("entity_count", 0),
            relationship_count=data.get("relationship_count", 0),
            error=data.get("error"),
            created_at=created_at,
            completed_at=completed_at,
            cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
        )
