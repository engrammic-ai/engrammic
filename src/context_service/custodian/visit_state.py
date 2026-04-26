"""Append-only event log + replayable state for a single custodian visit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VisitEvent: ...


@dataclass(frozen=True)
class NodeSeen(VisitEvent):
    node_id: str


@dataclass(frozen=True)
class ClaimCommitted(VisitEvent):
    claim_id: str
    subject: str
    predicate: str
    object_: str


@dataclass(frozen=True)
class BudgetDebited(VisitEvent):
    phase: str
    tool_calls: int
    tokens: int


@dataclass(frozen=True)
class PhaseStarted(VisitEvent):
    phase: str


@dataclass(frozen=True)
class VisitFinalized(VisitEvent):
    reason: str


@dataclass
class VisitState:
    org_id: str
    silo_id: str
    cluster_id: str
    events: list[VisitEvent] = field(default_factory=list)
    seen_node_ids: set[str] = field(default_factory=set)
    claims: list[dict[str, Any]] = field(default_factory=list)
    finalized: bool = False

    def emit(self, ev: VisitEvent) -> None:
        self.events.append(ev)
        self._apply(ev)

    def _apply(self, ev: VisitEvent) -> None:
        if isinstance(ev, NodeSeen):
            self.seen_node_ids.add(ev.node_id)
        elif isinstance(ev, ClaimCommitted):
            self.claims.append(
                {
                    "subject": ev.subject,
                    "predicate": ev.predicate,
                    "object": ev.object_,
                }
            )
        elif isinstance(ev, VisitFinalized):
            self.finalized = True

    def snapshot(self) -> dict[str, Any]:
        return {"events": list(self.events)}

    @classmethod
    def replay(
        cls,
        events: list[VisitEvent],
        *,
        org_id: str,
        silo_id: str,
        cluster_id: str,
    ) -> VisitState:
        s = cls(org_id=org_id, silo_id=silo_id, cluster_id=cluster_id)
        for ev in events:
            s.emit(ev)
        return s
