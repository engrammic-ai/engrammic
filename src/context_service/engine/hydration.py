"""Centralized hydration registry for Memgraph node records.

Hydrators convert raw Cypher result dicts into typed Node instances.
Each hydrator is registered against its node label string.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from context_service.db.schema import (
    LABEL_CLAIM,
    LABEL_DOCUMENT,
    LABEL_ENTITY,
    LABEL_PASSAGE,
)
from context_service.engine.models import Node
from context_service.utils.json import loads

_HYDRATORS: dict[str, Callable[[dict[str, Any]], Node]] = {}

_CONTENT_LABEL_SET: frozenset[str] = frozenset(
    {LABEL_DOCUMENT, LABEL_PASSAGE, LABEL_CLAIM, LABEL_ENTITY}
)

_SYSTEM_DOC_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "silo_id",
        "committed",
        "current_version",
        "version",
        "created_at",
        "updated_at",
        "valid_from",
        "valid_to",
        "supersedes_id",
        "content",
        "type",
        "_labels",
        "labels",
        "uri",
        "mime",
        "source_type",
        "content_hash",
        "content_class",
        "ingest_class",
        "last_reset_at",
        "raw_payload",
        "raw_payload_truncated",
        "properties",
    }
)


def register_hydrator(node_type: str, fn: Callable[[dict[str, Any]], Node]) -> None:
    """Register a hydrator function for a node label."""
    _HYDRATORS[node_type] = fn


def _parse_dt(value: Any) -> datetime:
    """Parse a datetime from Memgraph -- handles str, native datetime, neo4j DateTime, and epoch-ms int."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Memgraph timestamp() returns epoch-microseconds (not ms)
        return datetime.fromtimestamp(value / 1_000_000.0, tz=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    # neo4j driver returns neo4j.time.DateTime -- convert via iso_format()
    if hasattr(value, "iso_format"):
        return datetime.fromisoformat(value.iso_format())
    if hasattr(value, "to_native"):
        native = value.to_native()
        if not isinstance(native, datetime):
            raise TypeError(f"to_native() returned {type(native).__name__!r}, expected datetime")
        return native
    return datetime.fromisoformat(str(value))


def _hydrate_node_record(n: dict[str, Any], label: str | None, props: Any) -> Node:
    """Build a Node from a raw property dict, resolved label, and decoded props."""
    supersedes_raw = n.get("supersedes_id")

    if label == "document":
        node_type = "document"
        content = n.get("content") or n.get("raw_payload")
        version = int(n.get("current_version") or n.get("version") or 1)
        # Documents are written with flat top-level keys via UPSERT_DOCUMENT_AND_PASSAGES;
        # surface non-system keys as a `properties` dict for callers.
        props = {k: v for k, v in n.items() if k not in _SYSTEM_DOC_KEYS}
    elif label == "passage":
        node_type = "passage"
        content = n.get("content") or n.get("text")
        version = int(n.get("current_version") or n.get("version") or 1)
    else:
        # Legacy :Node rows (and tests that fabricate them) plus
        # :Claim / :Entity which still use the flat shape.
        node_type = n["type"]
        content = n.get("content")
        version = int(n.get("version", 1))

    return Node(
        id=uuid.UUID(n["id"]),
        type=node_type,
        content=content,
        properties=props,
        silo_id=uuid.UUID(n["silo_id"]),
        source_uri=n.get("source_uri") or n.get("uri"),
        content_hash=n.get("content_hash"),
        stale=n.get("stale", False),
        version=version,
        created_at=_parse_dt(n["created_at"]),
        updated_at=_parse_dt(n["updated_at"]),
        last_accessed_at=_parse_dt(n["last_accessed_at"]) if n.get("last_accessed_at") else None,
        valid_from=_parse_dt(n["valid_from"]) if n.get("valid_from") else datetime.now(UTC),
        valid_to=_parse_dt(n["valid_to"]) if n.get("valid_to") else None,
        supersedes_id=uuid.UUID(supersedes_raw) if supersedes_raw else None,
        label=label,
        ingest_class=n.get("ingest_class") or "standard",
        content_class=n.get("content_class") or "default",
        last_reset_at=_parse_dt(n["last_reset_at"]) if n.get("last_reset_at") else None,
        reclassified_at=_parse_dt(n["reclassified_at"]) if n.get("reclassified_at") else None,
    )


def _node_hydrator(record: dict[str, Any]) -> Node:
    """Default hydrator for content nodes (Document, Passage, Claim, Entity, legacy Node)."""
    n = record["n"]
    props = n.get("properties", "{}")
    if isinstance(props, str):
        props = loads(props)

    raw_labels: list[str] = (
        record.get("_labels") or record.get("labels") or n.get("_labels") or n.get("labels") or []
    )
    label = next(
        (lbl.lower() for lbl in raw_labels if lbl in _CONTENT_LABEL_SET),
        None,
    )

    return _hydrate_node_record(n, label, props)


def node_from_record(record: dict[str, Any]) -> Node:
    """Hydrate a Memgraph record into a Node.

    Resolves the label from the record and delegates to the registered
    hydrator if one exists, otherwise falls through to the default node
    hydrator.
    """
    n = record.get("n", {})
    raw_labels: list[str] = (
        record.get("_labels") or record.get("labels") or n.get("_labels") or n.get("labels") or []
    )
    label = next(
        (lbl.lower() for lbl in raw_labels if lbl in _CONTENT_LABEL_SET),
        None,
    )
    hydrator = _HYDRATORS.get(label or "") if label else None
    if hydrator:
        result: Node = hydrator(record)
        return result
    return _node_hydrator(record)


# Register default hydrators for each known content label.
for _label in ("document", "passage", "claim", "entity"):
    register_hydrator(_label, _node_hydrator)
