"""Supersession detection for batch learn operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

MAX_SPO_ENTRIES = 100_000


@dataclass
class BatchLearnItem:
    content: str
    evidence: list[str] = field(default_factory=list)
    user_id: str | None = None
    timestamp: str | None = None
    document_id: str | None = None
    confidence: float = 0.8
    tags: list[str] = field(default_factory=list)
    source_tier: str | None = None
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    supersedes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    array_index: int = 0

    # Set by detect_supersession
    supersedes_document_id: str | None = None
    _supersedes_array_index: int | None = None
    skip: bool = False
    error: str | None = None


@dataclass
class _SPOEntry:
    node_id: str | None
    object_value: str | None
    timestamp: str | None
    document_id: str | None
    is_existing: bool
    item: BatchLearnItem | None
    array_index: int


async def detect_supersession(
    items: list[BatchLearnItem],
    silo_id: str,
    conflict_mode: Literal["skip", "supersede", "error"],
    graph_store: HyperGraphStore,
) -> None:
    """Detect and set supersession for all items. Mutates items in place."""
    spo_items = [i for i in items if i.subject and i.predicate and not i.supersedes]
    if not spo_items:
        return

    sp_pairs: list[tuple[str, str]] = list(
        {(i.subject, i.predicate) for i in spo_items if i.subject and i.predicate}
    )

    existing = await graph_store.query_spo_pairs(silo_id, sp_pairs)

    index: dict[tuple[str, str], list[_SPOEntry]] = defaultdict(list)

    for (s, p), nodes in existing.items():
        for node in nodes:
            index[(s, p)].append(
                _SPOEntry(
                    node_id=node["node_id"],
                    object_value=node["object"],
                    timestamp=node.get("timestamp"),
                    document_id=node.get("document_id"),
                    is_existing=True,
                    item=None,
                    array_index=-1,
                )
            )

    total_existing = sum(len(v) for v in index.values())
    if total_existing + len(spo_items) > MAX_SPO_ENTRIES:
        raise ValueError(
            f"SPO entry limit exceeded ({total_existing + len(spo_items)} > {MAX_SPO_ENTRIES}). "
            "Chunk request by user_id or conversation_id."
        )

    for item in spo_items:
        assert item.subject is not None
        assert item.predicate is not None
        index[(item.subject, item.predicate)].append(
            _SPOEntry(
                node_id=None,
                object_value=item.object,
                timestamp=item.timestamp,
                document_id=item.document_id,
                is_existing=False,
                item=item,
                array_index=item.array_index,
            )
        )

    for entries in index.values():
        sorted_entries = sorted(
            entries,
            key=lambda e: (
                e.timestamp or "9999-99-99",  # null sorts LAST
                e.document_id or "",
                e.array_index if e.array_index >= 0 else 999999,
            ),
        )

        for i in range(1, len(sorted_entries)):
            current = sorted_entries[i]
            previous = sorted_entries[i - 1]

            if current.is_existing:
                continue
            if current.object_value == previous.object_value:
                continue

            assert current.item is not None

            if previous.is_existing:
                if conflict_mode == "error":
                    current.item.error = f"Existing (S,P) conflict: {previous.node_id}"
                elif conflict_mode == "skip":
                    current.item.skip = True
                else:
                    current.item.supersedes = previous.node_id
            else:
                if previous.document_id:
                    current.item.supersedes_document_id = previous.document_id
                else:
                    current.item._supersedes_array_index = previous.array_index
