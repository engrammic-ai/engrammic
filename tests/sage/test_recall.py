"""Tests for Phase 6 RECALL transaction and scoring functions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from context_service.sage.recall import (
    Layer,
    RecallOptions,
    RecallResult,
    compute_recall_score,
    gaussian_decay,
    recall,
    traverse_graph,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_embedding_service() -> AsyncMock:
    service = AsyncMock()
    service.embed_query = AsyncMock(return_value=[0.1] * 768)
    return service


def make_uuid() -> str:
    return str(uuid.uuid4())


class TestGaussianDecay:
    """Tests for gaussian_decay scoring function."""

    def test_returns_one_at_zero_age(self) -> None:
        result = gaussian_decay(0.0)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_decreases_with_age(self) -> None:
        score_recent = gaussian_decay(10.0)
        score_old = gaussian_decay(100.0)
        assert score_recent > score_old

    def test_respects_sigma_parameter(self) -> None:
        # A wider sigma means slower decay at the same age
        narrow_sigma = gaussian_decay(50.0, sigma=30)
        wide_sigma = gaussian_decay(50.0, sigma=120)
        assert wide_sigma > narrow_sigma


class TestComputeRecallScore:
    """Tests for compute_recall_score."""

    def test_memory_layer_applies_freshness_decay(self) -> None:
        # Fresh node should score higher than a stale one
        fresh_node = {
            "layer": Layer.MEMORY,
            "confidence": 1.0,
            "created_at": datetime.now(UTC) - timedelta(days=1),
        }
        stale_node = {
            "layer": Layer.MEMORY,
            "confidence": 1.0,
            "created_at": datetime.now(UTC) - timedelta(days=300),
        }
        fresh_score = compute_recall_score(fresh_node, similarity=0.9)
        stale_score = compute_recall_score(stale_node, similarity=0.9)
        assert fresh_score > stale_score

    def test_knowledge_layer_boosts_corroboration(self) -> None:
        base_node = {
            "layer": Layer.KNOWLEDGE,
            "confidence": 0.8,
            "corroboration_count": 0,
        }
        corroborated_node = {
            "layer": Layer.KNOWLEDGE,
            "confidence": 0.8,
            "corroboration_count": 5,
        }
        base_score = compute_recall_score(base_node, similarity=0.8)
        boosted_score = compute_recall_score(corroborated_node, similarity=0.8)
        assert boosted_score > base_score

    def test_wisdom_layer_penalizes_stale(self) -> None:
        from context_service.sage.transactions import SynthesisState

        fresh_wisdom = {
            "layer": Layer.WISDOM,
            "confidence": 0.9,
            "synthesis_state": SynthesisState.FRESH,
        }
        stale_wisdom = {
            "layer": Layer.WISDOM,
            "confidence": 0.9,
            "synthesis_state": SynthesisState.STALE,
        }
        fresh_score = compute_recall_score(fresh_wisdom, similarity=0.9)
        stale_score = compute_recall_score(stale_wisdom, similarity=0.9)
        assert fresh_score > stale_score

    def test_heat_boost_applied(self) -> None:
        node = {
            "layer": Layer.KNOWLEDGE,
            "confidence": 0.8,
            "corroboration_count": 0,
        }
        no_heat = compute_recall_score(node, similarity=0.8, heat=0.0)
        with_heat = compute_recall_score(node, similarity=0.8, heat=5.0)
        assert with_heat > no_heat

    def test_score_clamped_to_zero_one(self) -> None:
        node = {
            "layer": Layer.KNOWLEDGE,
            "confidence": 1.0,
            "corroboration_count": 1000,
        }
        score = compute_recall_score(node, similarity=1.0, heat=100.0)
        assert 0.0 <= score <= 1.0

        node_low = {
            "layer": Layer.MEMORY,
            "confidence": 0.0,
            "created_at": datetime.now(UTC) - timedelta(days=10000),
        }
        score_low = compute_recall_score(node_low, similarity=0.0)
        assert score_low >= 0.0


class TestRecall:
    """Tests for the recall() async query function."""

    def _make_node(
        self,
        node_id: str | None = None,
        layer: str = Layer.MEMORY,
        state: str = "ACTIVE",
        confidence: float = 0.9,
    ) -> dict:
        return {
            "id": node_id or make_uuid(),
            "content": "test content",
            "layer": layer,
            "state": state,
            "confidence": confidence,
            "created_at": datetime.now(UTC) - timedelta(days=5),
            "properties": {},
        }

    @pytest.mark.asyncio
    async def test_returns_results_from_vector_search(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        node_id = make_uuid()
        node = self._make_node(node_id=node_id)

        mock_vector_store.search = AsyncMock(return_value=[{"id": node_id, "score": 0.85}])
        mock_store.execute_query = AsyncMock(side_effect=[[node], []])

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="silo-1",
        )

        assert isinstance(result, RecallResult)
        assert len(result.results) == 1
        assert result.results[0].node_id == node_id

    @pytest.mark.asyncio
    async def test_filters_tombstoned_nodes(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        node_id = make_uuid()
        tombstoned = self._make_node(node_id=node_id, state="TOMBSTONED")

        mock_vector_store.search = AsyncMock(return_value=[{"id": node_id, "score": 0.9}])
        mock_store.execute_query = AsyncMock(side_effect=[[tombstoned], []])

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="silo-1",
        )

        assert len(result.results) == 0

    @pytest.mark.asyncio
    async def test_filters_by_layer(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        memory_id = make_uuid()
        wisdom_id = make_uuid()
        memory_node = self._make_node(node_id=memory_id, layer=Layer.MEMORY)
        wisdom_node = self._make_node(node_id=wisdom_id, layer=Layer.WISDOM)

        mock_vector_store.search = AsyncMock(
            return_value=[
                {"id": memory_id, "score": 0.8},
                {"id": wisdom_id, "score": 0.7},
            ]
        )
        # First call is batch query returning all nodes, second is GET_CLUSTERS_FOR_NODES
        mock_store.execute_query = AsyncMock(side_effect=[[memory_node, wisdom_node], []])

        options = RecallOptions(layers=[Layer.WISDOM])
        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="silo-1",
            options=options,
        )

        assert len(result.results) == 1
        assert result.results[0].node_id == wisdom_id

    @pytest.mark.asyncio
    async def test_respects_min_confidence(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        low_id = make_uuid()
        high_id = make_uuid()
        low_conf = self._make_node(node_id=low_id, confidence=0.2)
        high_conf = self._make_node(node_id=high_id, confidence=0.9)

        mock_vector_store.search = AsyncMock(
            return_value=[
                {"id": low_id, "score": 0.85},
                {"id": high_id, "score": 0.75},
            ]
        )
        # First call is batch query returning all nodes, second is GET_CLUSTERS_FOR_NODES
        mock_store.execute_query = AsyncMock(side_effect=[[low_conf, high_conf], []])

        options = RecallOptions(min_confidence=0.5)
        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="silo-1",
            options=options,
        )

        assert len(result.results) == 1
        assert result.results[0].node_id == high_id

    @pytest.mark.asyncio
    async def test_heat_score_affects_ranking(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Verify nodes with higher heat_score rank higher when similarity is equal."""
        low_heat_id = make_uuid()
        high_heat_id = make_uuid()

        low_heat_node = {
            **self._make_node(node_id=low_heat_id, layer=Layer.KNOWLEDGE),
            "heat_score": 0.1,
        }
        high_heat_node = {
            **self._make_node(node_id=high_heat_id, layer=Layer.KNOWLEDGE),
            "heat_score": 0.9,
        }

        # Equal similarity scores
        mock_vector_store.search = AsyncMock(
            return_value=[
                {"id": low_heat_id, "score": 0.8},
                {"id": high_heat_id, "score": 0.8},
            ]
        )
        mock_store.execute_query = AsyncMock(side_effect=[[low_heat_node, high_heat_node], []])

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="silo-1",
        )

        assert len(result.results) == 2
        # High heat node should rank first due to heat boost
        assert result.results[0].node_id == high_heat_id
        assert result.results[1].node_id == low_heat_id

    @pytest.mark.asyncio
    async def test_raises_on_empty_query(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        with pytest.raises(ValueError, match="query is required"):
            await recall(
                store=mock_store,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding_service,
                query="   ",
                silo_id="silo-1",
            )

    @pytest.mark.asyncio
    async def test_raises_on_missing_silo(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        with pytest.raises(ValueError, match="silo_id is required"):
            await recall(
                store=mock_store,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding_service,
                query="test query",
                silo_id="",
            )


class TestTraverseGraph:
    """Tests for traverse_graph."""

    @pytest.mark.asyncio
    async def test_returns_immediate_neighbors(self, mock_store: AsyncMock) -> None:
        node_id = make_uuid()
        neighbor_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": neighbor_id,
                    "edge_type": "RELATED_TO",
                    "direction": "outgoing",
                    "properties": {},
                }
            ]
        )

        results = await traverse_graph(
            store=mock_store,
            node_id=node_id,
            silo_id="silo-1",
            max_depth=1,
        )

        assert len(results) == 1
        assert results[0].node_id == neighbor_id
        assert results[0].depth == 1

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, mock_store: AsyncMock) -> None:
        root_id = make_uuid()
        child_id = make_uuid()
        grandchild_id = make_uuid()

        # First call: root's neighbors -> [child]
        # Second call: child's neighbors (if depth allows) -> [grandchild]
        # Third call: grandchild's neighbors -> [] (depth exceeded)
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": child_id,
                        "edge_type": "RELATED_TO",
                        "direction": "outgoing",
                        "properties": {},
                    }
                ],
                [],  # max_depth=1 prevents recursion into child
            ]
        )

        results = await traverse_graph(
            store=mock_store,
            node_id=root_id,
            silo_id="silo-1",
            max_depth=1,
        )

        # Only root->child edge; grandchild should not appear
        node_ids = [r.node_id for r in results]
        assert child_id in node_ids
        assert grandchild_id not in node_ids
