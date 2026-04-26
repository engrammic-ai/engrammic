"""Data models for clustering operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any


class ClusterLevel(IntEnum):
    """Leiden resolution levels for hierarchical clustering.

    Values are passed to ``igraphalg.community_leiden``'s
    ``resolution_parameter``. On a ~3k-vertex graph, these produce roughly:
    FINE ~ 1200 communities, MEDIUM ~ 220, COARSE ~ 110.
    """

    FINE = 1  # resolution_parameter=0.1
    MEDIUM = 2  # resolution_parameter=0.01
    COARSE = 3  # resolution_parameter=0.001


LEVEL_GAMMA_MAP: dict[ClusterLevel, float] = {
    ClusterLevel.FINE: 0.1,
    ClusterLevel.MEDIUM: 0.01,
    ClusterLevel.COARSE: 0.001,
}


class ClusteringStatus(StrEnum):
    """Status of a clustering job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Cluster:
    """A community cluster detected by Leiden algorithm."""

    id: str
    level: int
    community_id: int
    summary: str | None = None
    key_topics: list[str] = field(default_factory=list)
    node_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Null until the first Custodian pass touches this cluster.
    last_custodian_pass_id: str | None = None
    last_custodian_run_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/response."""
        return {
            "id": self.id,
            "level": self.level,
            "community_id": self.community_id,
            "summary": self.summary,
            "key_topics": self.key_topics,
            "node_count": self.node_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_custodian_pass_id": self.last_custodian_pass_id,
            "last_custodian_run_at": (
                self.last_custodian_run_at.isoformat()
                if self.last_custodian_run_at is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cluster:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(UTC)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now(UTC)

        key_topics = data.get("key_topics", [])
        if isinstance(key_topics, str):
            import json

            try:
                key_topics = json.loads(key_topics)
            except (json.JSONDecodeError, TypeError):
                key_topics = []

        last_custodian_run_at = data.get("last_custodian_run_at")
        if isinstance(last_custodian_run_at, str):
            last_custodian_run_at = datetime.fromisoformat(last_custodian_run_at)

        return cls(
            id=data["id"],
            level=data["level"],
            community_id=data.get("community_id", 0),
            summary=data.get("summary"),
            key_topics=key_topics,
            node_count=data.get("node_count", 0),
            created_at=created_at,
            updated_at=updated_at,
            last_custodian_pass_id=data.get("last_custodian_pass_id"),
            last_custodian_run_at=last_custodian_run_at,
        )


@dataclass
class ClusterMembership:
    """Tracks a node's membership in a cluster."""

    node_id: str
    cluster_id: str
    weight: float = 1.0


@dataclass
class ClusteringJob:
    """Tracks the status of a clustering job."""

    id: str
    silo_id: str
    status: ClusteringStatus = ClusteringStatus.PENDING
    level_counts: dict[int, int] = field(default_factory=dict)
    total_clusters: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/response."""
        return {
            "id": self.id,
            "silo_id": self.silo_id,
            "status": self.status.value,
            "level_counts": self.level_counts,
            "total_clusters": self.total_clusters,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClusteringJob:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(UTC)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        level_counts = data.get("level_counts", {})
        level_counts = {int(k): v for k, v in level_counts.items()}

        return cls(
            id=data["id"],
            silo_id=data["silo_id"],
            status=ClusteringStatus(data.get("status", "pending")),
            level_counts=level_counts,
            total_clusters=data.get("total_clusters", 0),
            error=data.get("error"),
            created_at=created_at,
            completed_at=completed_at,
        )
