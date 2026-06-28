"""Tests for supersession detection."""

from __future__ import annotations

import pytest

from context_service.services.supersession import BatchLearnItem, detect_supersession


class MockGraphStore:
    """Minimal mock for HyperGraphStore that returns SPO pairs."""

    def __init__(self, existing: dict[tuple[str, str], list[dict]] | None = None) -> None:
        self._existing: dict[tuple[str, str], list[dict]] = existing or {}

    async def query_spo_pairs(
        self, silo_id: str, sp_pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], list[dict]]:
        return {k: v for k, v in self._existing.items() if k in sp_pairs}


def make_item(
    subject: str,
    predicate: str,
    object_: str,
    timestamp: str | None = None,
    document_id: str | None = None,
    array_index: int = 0,
) -> BatchLearnItem:
    return BatchLearnItem(
        content=f"{subject} {predicate} {object_}",
        subject=subject,
        predicate=predicate,
        object=object_,
        timestamp=timestamp,
        document_id=document_id,
        array_index=array_index,
    )


@pytest.mark.asyncio
async def test_intra_batch_supersession_links_items() -> None:
    items = [
        BatchLearnItem(
            content="User is 25",
            subject="user",
            predicate="age",
            object="25",
            timestamp="2024-01-01T00:00:00Z",
            array_index=0,
        ),
        BatchLearnItem(
            content="User is 26",
            subject="user",
            predicate="age",
            object="26",
            timestamp="2024-01-02T00:00:00Z",
            array_index=1,
        ),
    ]

    mock_store = MockGraphStore()
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    assert items[0].supersedes is None
    assert items[1].supersedes_document_id is None
    assert items[1]._supersedes_array_index == 0


@pytest.mark.asyncio
async def test_intra_batch_no_supersession_same_object() -> None:
    items = [
        make_item("user", "age", "25", timestamp="2024-01-01T00:00:00Z", array_index=0),
        make_item("user", "age", "25", timestamp="2024-01-02T00:00:00Z", array_index=1),
    ]

    mock_store = MockGraphStore()
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    assert items[0]._supersedes_array_index is None
    assert items[1]._supersedes_array_index is None
    assert not items[0].skip
    assert not items[1].skip


@pytest.mark.asyncio
async def test_supersede_existing_node() -> None:
    items = [
        make_item("user", "age", "26", timestamp="2024-01-02T00:00:00Z", array_index=0),
    ]

    mock_store = MockGraphStore(
        existing={
            ("user", "age"): [
                {
                    "node_id": "existing-node-abc",
                    "object": "25",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "document_id": None,
                }
            ]
        }
    )
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    assert items[0].supersedes == "existing-node-abc"
    assert not items[0].skip


@pytest.mark.asyncio
async def test_conflict_mode_skip() -> None:
    items = [
        make_item("user", "age", "26", timestamp="2024-01-02T00:00:00Z", array_index=0),
    ]

    mock_store = MockGraphStore(
        existing={
            ("user", "age"): [
                {
                    "node_id": "existing-node-abc",
                    "object": "25",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "document_id": None,
                }
            ]
        }
    )
    await detect_supersession(items, "silo-1", "skip", mock_store)

    assert items[0].skip is True
    assert items[0].supersedes is None


@pytest.mark.asyncio
async def test_conflict_mode_error() -> None:
    items = [
        make_item("user", "age", "26", timestamp="2024-01-02T00:00:00Z", array_index=0),
    ]

    mock_store = MockGraphStore(
        existing={
            ("user", "age"): [
                {
                    "node_id": "existing-node-abc",
                    "object": "25",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "document_id": None,
                }
            ]
        }
    )
    await detect_supersession(items, "silo-1", "error", mock_store)

    assert items[0].error is not None
    assert "existing-node-abc" in items[0].error
    assert not items[0].skip


@pytest.mark.asyncio
async def test_null_timestamp_sorts_last() -> None:
    """Items with null timestamps come after timestamped items."""
    items = [
        make_item("user", "age", "25", timestamp=None, array_index=0),
        make_item("user", "age", "26", timestamp="2024-01-02T00:00:00Z", array_index=1),
    ]

    mock_store = MockGraphStore()
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    # item[1] has an earlier timestamp in sort order (null sorts last),
    # so item[0] (null ts) supersedes item[1]
    assert items[0]._supersedes_array_index == 1
    assert items[1]._supersedes_array_index is None


@pytest.mark.asyncio
async def test_items_without_spo_are_skipped() -> None:
    items = [
        BatchLearnItem(content="Some generic content", array_index=0),
        make_item("user", "age", "25", timestamp="2024-01-01T00:00:00Z", array_index=1),
    ]

    mock_store = MockGraphStore()
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    assert not items[0].skip
    assert items[0].supersedes is None
    assert items[0]._supersedes_array_index is None


@pytest.mark.asyncio
async def test_spo_limit_raises_value_error() -> None:
    from context_service.services.supersession import MAX_SPO_ENTRIES

    # 10 items with unique (entity, prop_N) SP pairs
    items = [
        make_item("entity", f"prop_{i}", str(i), timestamp="2024-01-01T00:00:00Z", array_index=i)
        for i in range(10)
    ]

    # Each SP pair returns enough existing entries to push total over the limit
    per_pair = (MAX_SPO_ENTRIES // 10) + 2
    existing_entries: dict[tuple[str, str], list[dict]] = {
        ("entity", f"prop_{i}"): [
            {"node_id": f"node-{i}-{j}", "object": "val", "timestamp": None, "document_id": None}
            for j in range(per_pair)
        ]
        for i in range(10)
    }

    mock_store = MockGraphStore(existing=existing_entries)

    with pytest.raises(ValueError, match="SPO entry limit exceeded"):
        await detect_supersession(items, "silo-1", "supersede", mock_store)


@pytest.mark.asyncio
async def test_intra_batch_with_document_id() -> None:
    items = [
        make_item(
            "user",
            "age",
            "25",
            document_id="doc-abc",
            timestamp="2024-01-01T00:00:00Z",
            array_index=0,
        ),
        make_item("user", "age", "26", timestamp="2024-01-02T00:00:00Z", array_index=1),
    ]

    mock_store = MockGraphStore()
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    assert items[1].supersedes_document_id == "doc-abc"
    assert items[1]._supersedes_array_index is None


@pytest.mark.asyncio
async def test_explicit_supersedes_not_overridden() -> None:
    """Items with explicit supersedes set are excluded from detection."""
    items = [
        BatchLearnItem(
            content="User is 26",
            subject="user",
            predicate="age",
            object="26",
            timestamp="2024-01-02T00:00:00Z",
            array_index=0,
            supersedes="existing-node-xyz",
        ),
    ]

    mock_store = MockGraphStore(
        existing={
            ("user", "age"): [
                {
                    "node_id": "other-node",
                    "object": "25",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "document_id": None,
                }
            ]
        }
    )
    await detect_supersession(items, "silo-1", "supersede", mock_store)

    # supersedes should remain the original value, not be overridden
    assert items[0].supersedes == "existing-node-xyz"
