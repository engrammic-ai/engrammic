"""Tests for v1.3e causal completion: transitive invalidation and partial revision."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _load_invalidation_queries() -> tuple[str, str]:
    """Extract invalidation query strings from causal_invalidation.py."""
    causal_path = (
        Path(__file__).parent.parent
        / "src"
        / "context_service"
        / "engine"
        / "causal_invalidation.py"
    )
    source = causal_path.read_text()

    import re

    find_match = re.search(r'_FIND_DERIVED_EDGES\s*=\s*"""(.+?)"""', source, re.DOTALL)
    find_query = find_match.group(1) if find_match else ""

    tombstone_match = re.search(r'_TOMBSTONE_DERIVED_EDGE\s*=\s*"""(.+?)"""', source, re.DOTALL)
    tombstone_query = tombstone_match.group(1) if tombstone_match else ""

    return find_query, tombstone_query


_FIND_DERIVED_EDGES, _TOMBSTONE_DERIVED_EDGE = _load_invalidation_queries()


# ---------------------------------------------------------------------------
# CausalConfig: max_invalidation_depth field
# ---------------------------------------------------------------------------


class TestMaxInvalidationDepthConfig:
    """max_invalidation_depth is present on CausalConfig with sane defaults."""

    def test_field_exists(self) -> None:
        from context_service.config.settings import CausalConfig

        cfg = CausalConfig()
        assert hasattr(cfg, "max_invalidation_depth")

    def test_default_is_three(self) -> None:
        from context_service.config.settings import CausalConfig

        cfg = CausalConfig()
        assert cfg.max_invalidation_depth == 3

    def test_accepts_custom_value(self) -> None:
        from context_service.config.settings import CausalConfig

        cfg = CausalConfig(max_invalidation_depth=5)
        assert cfg.max_invalidation_depth == 5

    def test_minimum_is_one(self) -> None:
        import pytest
        from pydantic import ValidationError

        from context_service.config.settings import CausalConfig

        with pytest.raises(ValidationError):
            CausalConfig(max_invalidation_depth=0)

    def test_maximum_is_ten(self) -> None:
        import pytest
        from pydantic import ValidationError

        from context_service.config.settings import CausalConfig

        with pytest.raises(ValidationError):
            CausalConfig(max_invalidation_depth=11)


# ---------------------------------------------------------------------------
# _FIND_DERIVED_EDGES query structure
# ---------------------------------------------------------------------------


class TestFindDerivedEdgesQuery:
    """Verify the reverse-lookup query for derived edges is structurally correct."""

    def test_query_filters_by_silo(self) -> None:
        assert "$silo_id" in _FIND_DERIVED_EDGES

    def test_query_filters_inferred_only(self) -> None:
        assert "inferred" in _FIND_DERIVED_EDGES

    def test_query_uses_inferred_from_edge_ids(self) -> None:
        assert "inferred_from_edge_ids" in _FIND_DERIVED_EDGES

    def test_query_returns_derived_edge_id(self) -> None:
        assert "derived_edge_id" in _FIND_DERIVED_EDGES

    def test_query_matches_superseded_param(self) -> None:
        assert "$superseded_edge_id" in _FIND_DERIVED_EDGES


# ---------------------------------------------------------------------------
# _TOMBSTONE_DERIVED_EDGE query structure
# ---------------------------------------------------------------------------


class TestTombstoneDerivedEdgeQuery:
    """Verify the tombstone SET query marks the correct fields."""

    def test_sets_invalidated_flag(self) -> None:
        assert "invalidated = true" in _TOMBSTONE_DERIVED_EDGE

    def test_sets_invalidated_at(self) -> None:
        assert "invalidated_at" in _TOMBSTONE_DERIVED_EDGE

    def test_sets_invalidation_reason(self) -> None:
        assert "invalidation_reason" in _TOMBSTONE_DERIVED_EDGE

    def test_filters_by_silo(self) -> None:
        assert "$silo_id" in _TOMBSTONE_DERIVED_EDGE

    def test_matches_by_edge_id(self) -> None:
        assert "$edge_id" in _TOMBSTONE_DERIVED_EDGE


# ---------------------------------------------------------------------------
# invalidate_derived_edges: async helper
# ---------------------------------------------------------------------------


class TestInvalidateDerivedEdges:
    """Unit tests for the invalidate_derived_edges async function."""

    async def test_no_derived_edges_returns_zero(self) -> None:
        from context_service.engine.causal_invalidation import invalidate_derived_edges

        client = AsyncMock()
        client.execute_query.return_value = []

        result = await invalidate_derived_edges(client, "edge-abc", "silo-1", max_depth=3)

        assert result == 0
        client.execute_write.assert_not_called()

    async def test_single_derived_edge_tombstoned(self) -> None:
        from context_service.engine.causal_invalidation import invalidate_derived_edges

        client = AsyncMock()
        client.execute_query.side_effect = [
            [{"derived_edge_id": "derived-1"}],  # first call finds one derived edge
            [],  # second call: no further derived edges from derived-1
        ]
        client.execute_write.return_value = None

        result = await invalidate_derived_edges(client, "edge-abc", "silo-1", max_depth=3)

        assert result == 1
        client.execute_write.assert_called_once()

    async def test_cascade_limited_by_max_depth(self) -> None:
        from context_service.engine.causal_invalidation import invalidate_derived_edges

        # Each hop returns one new derived edge, ad infinitum.
        call_count = 0

        async def side_effect(query: str, params: dict) -> list:
            nonlocal call_count
            call_count += 1
            return [{"derived_edge_id": f"derived-{call_count}"}]

        client = AsyncMock()
        client.execute_query.side_effect = side_effect
        client.execute_write.return_value = None

        result = await invalidate_derived_edges(client, "edge-root", "silo-1", max_depth=2)

        # max_depth=2: root finds derived-1, derived-1 finds derived-2 — 2 total
        assert result == 2

    async def test_does_not_revisit_already_visited_edges(self) -> None:
        from context_service.engine.causal_invalidation import invalidate_derived_edges

        client = AsyncMock()
        # Both hops return the same derived edge — should only tombstone once.
        client.execute_query.side_effect = [
            [{"derived_edge_id": "derived-1"}],
            [{"derived_edge_id": "derived-1"}],  # already visited
        ]
        client.execute_write.return_value = None

        result = await invalidate_derived_edges(client, "edge-root", "silo-1", max_depth=3)

        assert result == 1

    async def test_reason_passed_to_tombstone(self) -> None:
        from context_service.engine.causal_invalidation import invalidate_derived_edges

        client = AsyncMock()
        client.execute_query.side_effect = [
            [{"derived_edge_id": "derived-1"}],
            [],
        ]
        client.execute_write.return_value = None

        await invalidate_derived_edges(
            client, "edge-abc", "silo-1", max_depth=3, reason="fact_contradiction"
        )

        call_kwargs = client.execute_write.call_args[0][1]
        assert call_kwargs["reason"] == "fact_contradiction"


# ---------------------------------------------------------------------------
# CORROBORATES semantics verification
# ---------------------------------------------------------------------------


class TestCorroboratesSemantics:
    """CORROBORATES is directed (A supports B) in both queries and extraction config."""

    def test_extraction_config_documents_direction(self) -> None:
        config_path = Path(__file__).parent.parent / "config" / "extraction.yaml"
        if not config_path.exists():
            return  # Config absent in CI — skip gracefully.
        text = config_path.read_text()
        assert "source supports target" in text or "A CORROBORATES B means A supports B" in text


# ---------------------------------------------------------------------------
# SplitBeliefResult dataclass
# ---------------------------------------------------------------------------


class TestSplitBeliefResult:
    """SplitBeliefResult is importable and has expected fields."""

    def test_importable(self) -> None:
        from context_service.engine.revision import SplitBeliefResult

        result = SplitBeliefResult(
            parent_belief_id="p-1",
            child_belief_ids=["c-1", "c-2"],
            child_count=2,
        )
        assert result.parent_belief_id == "p-1"
        assert result.child_count == 2
        assert len(result.child_belief_ids) == 2

    def test_is_frozen(self) -> None:
        import pytest

        from context_service.engine.revision import SplitBeliefResult

        result = SplitBeliefResult(
            parent_belief_id="p-1",
            child_belief_ids=[],
            child_count=0,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.parent_belief_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# split_belief: LLM-based partial revision
# ---------------------------------------------------------------------------


class TestSplitBelief:
    """Unit tests for split_belief using mocked store and LLM."""

    def _make_store(self, belief_content: str = "A causes B, and C holds.") -> AsyncMock:
        store = AsyncMock()
        store.execute_query.return_value = [
            {
                "belief_id": "belief-1",
                "content": belief_content,
                "confidence": 0.8,
                "centroid_embedding": [0.1, 0.2, 0.3],
                "revision_count": 0,
                "wisdom_status": "active",
            }
        ]
        store.execute_write.return_value = None
        # transaction() must be a regular callable that returns an async context manager.
        # AsyncMock makes transaction() itself awaitable (a coroutine), which is wrong.
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=None)
        cm.__aexit__ = AsyncMock(return_value=False)
        store.transaction = MagicMock(return_value=cm)
        return store

    async def test_returns_split_result(self) -> None:
        from context_service.engine.revision import split_belief

        store = self._make_store()
        llm = AsyncMock()
        llm.complete.return_value = (
            json.dumps({"children": ["A causes B.", "C no longer holds."]}),
            {},
        )
        embedding = AsyncMock()
        embedding.embed.return_value = [[0.1, 0.2, 0.3]]

        result = await split_belief(
            store, "belief-1", "silo-1", "C is no longer supported", llm, embedding
        )

        assert result.parent_belief_id == "belief-1"
        assert result.child_count == 2
        assert len(result.child_belief_ids) == 2

    async def test_raises_if_belief_not_found(self) -> None:
        import pytest

        from context_service.engine.revision import split_belief

        store = AsyncMock()
        store.execute_query.return_value = []
        llm = AsyncMock()
        embedding = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await split_belief(store, "missing", "silo-1", "note", llm, embedding)

    async def test_raises_if_llm_returns_empty_children(self) -> None:
        import pytest

        from context_service.engine.revision import split_belief

        store = self._make_store()
        llm = AsyncMock()
        llm.complete.return_value = (json.dumps({"children": []}), {})
        embedding = AsyncMock()
        embedding.embed.return_value = [[0.1]]

        with pytest.raises(ValueError, match="no child beliefs"):
            await split_belief(store, "belief-1", "silo-1", "note", llm, embedding)

    async def test_fallback_non_json_llm_response(self) -> None:
        from context_service.engine.revision import split_belief

        store = self._make_store()
        llm = AsyncMock()
        # LLM returns plain text instead of JSON.
        llm.complete.return_value = ("A causes B only.", {})
        embedding = AsyncMock()
        embedding.embed.return_value = [[0.1, 0.2]]

        result = await split_belief(
            store, "belief-1", "silo-1", "partial revision note", llm, embedding
        )

        # Should produce exactly one child from the raw text.
        assert result.child_count == 1
        assert result.child_belief_ids[0] is not None

    async def test_child_beliefs_linked_via_revised_from(self) -> None:
        from context_service.engine.revision import split_belief

        store = self._make_store()
        llm = AsyncMock()
        llm.complete.return_value = (
            json.dumps({"children": ["X.", "Y."]}),
            {},
        )
        embedding = AsyncMock()
        embedding.embed.return_value = [[0.1, 0.2]]

        await split_belief(store, "belief-1", "silo-1", "note", llm, embedding)

        # execute_write is called per child: CREATE_CHILD_BELIEF + UPDATE_BELIEF_CENTROID
        # + CREATE_REVISED_FROM = 3 calls per child.
        assert store.execute_write.call_count == 6

        # Verify at least one call references REVISED_FROM pattern.
        all_queries = [call.args[0] for call in store.execute_write.call_args_list]
        assert any("REVISED_FROM" in q for q in all_queries)

    async def test_revision_note_stored_on_edge(self) -> None:
        from context_service.engine.revision import split_belief

        store = self._make_store()
        llm = AsyncMock()
        llm.complete.return_value = (json.dumps({"children": ["X."]}), {})
        embedding = AsyncMock()
        embedding.embed.return_value = [[0.1]]

        await split_belief(store, "belief-1", "silo-1", "partial evidence lost", llm, embedding)

        all_params = [call.args[1] for call in store.execute_write.call_args_list]
        revised_from_params = [p for p in all_params if p.get("revision_note")]
        assert revised_from_params
        assert revised_from_params[0]["revision_note"] == "partial evidence lost"
