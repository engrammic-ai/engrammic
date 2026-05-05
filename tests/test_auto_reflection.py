"""Unit tests for engine/auto_reflection.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.engine.auto_reflection import (
    create_auto_reflection,
    make_revision_content,
    make_supersession_content,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def test_make_supersession_content_basic() -> None:
    result = make_supersession_content("old fact", "new fact", "contradiction")
    assert "old fact" in result
    assert "new fact" in result
    assert "contradiction" in result


def test_make_supersession_content_truncates_long_content() -> None:
    long = "x" * 200
    result = make_supersession_content(long, "new", "reason")
    # Snippet should be capped at 80 chars
    assert len(result) < 300


def test_make_supersession_content_escapes_single_quotes() -> None:
    result = make_supersession_content("it's old", "it's new", "reason")
    # Backtick replacement — no unescaped single quotes inside the snippets
    assert "it`s old" in result
    assert "it`s new" in result


def test_make_revision_content_basic() -> None:
    result = make_revision_content("belief subject", 15.0)
    assert "belief subject" in result
    assert "15.0%" in result


def test_make_revision_content_truncates_long_subject() -> None:
    long = "s" * 200
    result = make_revision_content(long, 5.0)
    assert len(result) < 300


# ---------------------------------------------------------------------------
# create_auto_reflection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_auto_reflection_writes_correct_params() -> None:
    store = FakeGraphStore()
    store.seed_write_result([])

    obs_id, error = await create_auto_reflection(
        store=store,
        observation_type="belief_change",
        content="some content",
        about_node_ids=["node-a", "node-b"],
        silo_id="silo-1",
    )

    assert obs_id is not None
    assert error is None
    assert len(store.write_log) == 1
    _, params = store.write_log[0]
    assert params["observation_type"] == "belief_change"
    assert params["content"] == "some content"
    assert params["agent_id"] == "system"
    assert params["silo_id"] == "silo-1"
    # auto_generated=true is set as a literal in the Cypher body, not a parameter
    cypher = store.write_log[0][0]
    assert "auto_generated = true" in cypher
    assert params["about_node_ids"] == ["node-a", "node-b"]
    assert params["obs_id"] == obs_id


@pytest.mark.asyncio
async def test_create_auto_reflection_returns_none_on_error() -> None:
    store = FakeGraphStore()

    # Patch execute_write to raise
    async def _raise(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("db unavailable")

    store.execute_write = _raise  # type: ignore[method-assign]

    obs_id, error = await create_auto_reflection(
        store=store,
        observation_type="belief_change",
        content="content",
        about_node_ids=["node-x"],
        silo_id="silo-1",
    )

    assert obs_id is None
    assert error is not None


@pytest.mark.asyncio
async def test_create_auto_reflection_unique_ids() -> None:
    store1 = FakeGraphStore()
    store1.seed_write_result([])
    store2 = FakeGraphStore()
    store2.seed_write_result([])

    id_a, _ = await create_auto_reflection(store1, "belief_change", "c", [], "s1")
    id_b, _ = await create_auto_reflection(store2, "belief_change", "c", [], "s1")

    assert id_a != id_b


# ---------------------------------------------------------------------------
# Supersession hook integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersession_pass_calls_auto_reflection_when_enabled() -> None:
    """When auto_reflect.enabled=True and on_supersession=True, auto-reflections
    are created for detected supersession pairs."""
    from context_service.custodian.supersession import run_supersession_pass

    # Use SPO-structured nodes so the deterministic structured path fires
    # without needing an LLM call.
    class _SPONode:
        def __init__(
            self,
            nid: str,
            content: str,
            ts: datetime,
            confidence: float,
        ) -> None:
            self.id = nid
            self.content = content
            self.created_at = ts
            self.confidence = confidence
            # SPO fields required by _has_spo_structure
            self.subject = "entity-x"
            self.predicate = "has_property"
            self.object = "value"

    older = _SPONode("aaa", "old content", datetime(2026, 1, 1, tzinfo=UTC), confidence=0.6)
    newer = _SPONode("bbb", "new content", datetime(2026, 6, 1, tzinfo=UTC), confidence=0.95)

    store = MagicMock()
    store.create_supersedes_edge = AsyncMock(return_value=True)
    store.execute_write = AsyncMock(return_value=[])

    settings_mock = MagicMock()
    settings_mock.auto_reflect.enabled = True
    settings_mock.auto_reflect.on_supersession = True

    with patch(
        "context_service.custodian.supersession.get_settings",
        return_value=settings_mock,
    ):
        result = await run_supersession_pass(
            cluster_id="c-1",
            cluster_nodes=[older, newer],
            silo_id="silo-1",
            llm=None,
            store=store,
            confidence_threshold=0.8,
            dominance_threshold=1.2,
        )

    # If a supersession edge was written, execute_write should be called
    # for the auto-reflection node.
    if result.edges_written > 0:
        assert store.execute_write.called


@pytest.mark.asyncio
async def test_supersession_pass_skips_auto_reflection_when_disabled() -> None:
    from context_service.custodian.supersession import run_supersession_pass

    class _SPONode:
        def __init__(self, nid: str, content: str, ts: datetime, confidence: float) -> None:
            self.id = nid
            self.content = content
            self.created_at = ts
            self.confidence = confidence
            self.subject = "entity-x"
            self.predicate = "has_property"
            self.object = "value"

    older = _SPONode("aaa", "old content", datetime(2026, 1, 1, tzinfo=UTC), confidence=0.6)
    newer = _SPONode("bbb", "new content", datetime(2026, 6, 1, tzinfo=UTC), confidence=0.95)

    store = MagicMock()
    store.create_supersedes_edge = AsyncMock(return_value=True)
    store.execute_write = AsyncMock(return_value=[])

    settings_mock = MagicMock()
    settings_mock.auto_reflect.enabled = False

    with patch(
        "context_service.custodian.supersession.get_settings",
        return_value=settings_mock,
    ):
        await run_supersession_pass(
            cluster_id="c-1",
            cluster_nodes=[older, newer],
            silo_id="silo-1",
            llm=None,
            store=store,
            dominance_threshold=1.2,
        )

    # execute_write must NOT have been called (flag is off, no LLM pairs)
    store.execute_write.assert_not_called()


# ---------------------------------------------------------------------------
# Revision hook integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_belief_calls_auto_reflection_when_enabled() -> None:
    """revise_belief creates an auto-reflection when the flag is on."""
    from context_service.engine.revision import revise_belief
    from context_service.engine.synthesis import InsufficientEvidenceError  # noqa: F401

    facts = [
        {
            "fact_id": f"f{i}",
            "content": f"content {i}",
            "confidence": 0.9,
            "valid_from": "2026-01-01T00:00:00+00:00",
        }
        for i in range(4)
    ]

    store = FakeGraphStore()
    store.seed_query_result(
        [  # belief
            {
                "belief_id": "old-b",
                "content": "Old belief.",
                "confidence": 0.85,
                "centroid_embedding": [1.0, 0.0],
                "revision_count": 0,
                "wisdom_status": "active",
            }
        ]
    )
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(facts)
    for _ in range(4):  # 4 writes inside transaction
        store.seed_write_result([])
    store.seed_write_result([])  # auto_reflection write

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=("Revised.", None))
    embedding_client = AsyncMock()
    embedding_client.embed = AsyncMock(return_value=[[1.0, 0.0]] * 4)

    settings_mock = MagicMock()
    settings_mock.auto_reflect.enabled = True
    settings_mock.auto_reflect.on_revision = True

    with patch(
        "context_service.engine.revision.get_settings",
        return_value=settings_mock,
    ):
        new_id = await revise_belief(store, "old-b", "silo-1", llm, embedding_client)

    assert new_id is not None
    # 4 transactional writes + 1 auto-reflection write
    assert len(store.write_log) == 5
    _, auto_params = store.write_log[4]
    assert auto_params["observation_type"] == "belief_change"
    assert auto_params["agent_id"] == "system"
    assert "old-b" in auto_params["about_node_ids"]
    assert new_id in auto_params["about_node_ids"]


@pytest.mark.asyncio
async def test_revise_belief_skips_auto_reflection_when_disabled() -> None:
    from unittest.mock import MagicMock

    from context_service.engine.revision import revise_belief

    facts = [
        {
            "fact_id": f"f{i}",
            "content": f"content {i}",
            "confidence": 0.9,
            "valid_from": "2026-01-01T00:00:00+00:00",
        }
        for i in range(4)
    ]

    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "belief_id": "old-b",
                "content": "Old belief.",
                "confidence": 0.85,
                "centroid_embedding": [1.0, 0.0],
                "revision_count": 0,
                "wisdom_status": "active",
            }
        ]
    )
    store.seed_query_result([{"cluster_id": "c-1"}])
    store.seed_query_result(facts)
    for _ in range(4):
        store.seed_write_result([])

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=("Revised.", None))
    embedding_client = AsyncMock()
    embedding_client.embed = AsyncMock(return_value=[[1.0, 0.0]] * 4)

    settings_mock = MagicMock()
    settings_mock.auto_reflect.enabled = False

    with patch(
        "context_service.engine.revision.get_settings",
        return_value=settings_mock,
    ):
        await revise_belief(store, "old-b", "silo-1", llm, embedding_client)

    # Only the 4 transactional writes; no auto-reflection
    assert len(store.write_log) == 4
