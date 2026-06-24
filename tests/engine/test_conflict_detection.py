"""Tests for cross-agent conflict detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.auth.identity import IdentityContext
from context_service.engine.conflict_detection import (
    _cosine,
    create_contradicts_edge,
    detect_conflicts,
    is_same_subject,
)


@pytest.fixture
def identity() -> IdentityContext:
    return IdentityContext(
        tenant_id="silo-abc",
        agent_id="agent-A",
        session_id="session-1",
    )


class TestCosine:
    def test_identical_vectors(self) -> None:
        assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_empty_returns_zero(self) -> None:
        assert _cosine([], []) == 0.0

    def test_length_mismatch_returns_zero(self) -> None:
        assert _cosine([1.0], [1.0, 0.0]) == 0.0


class TestIsSameSubject:
    @pytest.mark.asyncio
    async def test_matching_spo_subjects(self) -> None:
        node_a = {"spo": {"subject": "Python", "predicate": "is", "object": "a language"}}
        node_b = {"spo": {"subject": "python", "predicate": "has", "object": "GIL"}}
        assert await is_same_subject(node_a, node_b) is True

    @pytest.mark.asyncio
    async def test_different_spo_subjects(self) -> None:
        node_a = {"spo": {"subject": "Python", "predicate": "is", "object": "a language"}}
        node_b = {"spo": {"subject": "Java", "predicate": "has", "object": "JVM"}}
        assert await is_same_subject(node_a, node_b) is False

    @pytest.mark.asyncio
    async def test_fallback_high_similarity_same_label(self) -> None:
        emb = [1.0, 0.0, 0.0]
        node_a = {"embedding": emb, "labels": ["Claim"]}
        node_b = {"embedding": emb, "labels": ["Claim"]}
        assert await is_same_subject(node_a, node_b) is True

    @pytest.mark.asyncio
    async def test_fallback_high_similarity_different_label(self) -> None:
        emb = [1.0, 0.0, 0.0]
        node_a = {"embedding": emb, "labels": ["Memory"]}
        node_b = {"embedding": emb, "labels": ["Claim"]}
        assert await is_same_subject(node_a, node_b) is False

    @pytest.mark.asyncio
    async def test_fallback_low_similarity(self) -> None:
        node_a = {"embedding": [1.0, 0.0, 0.0], "labels": ["Claim"]}
        node_b = {"embedding": [0.0, 1.0, 0.0], "labels": ["Claim"]}
        assert await is_same_subject(node_a, node_b) is False

    @pytest.mark.asyncio
    async def test_missing_spo_subject_falls_back(self) -> None:
        emb = [1.0, 0.0, 0.0]
        node_a = {
            "spo": {"subject": "", "predicate": "", "object": ""},
            "embedding": emb,
            "labels": ["Claim"],
        }
        node_b = {
            "spo": {"subject": "", "predicate": "", "object": ""},
            "embedding": emb,
            "labels": ["Claim"],
        }
        # Empty subjects with SPO -> returns False (spo branch returns False)
        assert await is_same_subject(node_a, node_b) is False


class TestCreateContradictsEdge:
    @pytest.mark.asyncio
    async def test_creates_edge_successfully(self) -> None:
        store = AsyncMock()
        store.execute_write.return_value = [{"edge_id": "some-edge-id"}]

        edge_id = await create_contradicts_edge(
            store=store,
            source_id="node-1",
            target_id="node-2",
            silo_id="silo-abc",
        )

        assert edge_id is not None
        store.execute_write.assert_called_once()
        call_params = store.execute_write.call_args[0][1]
        assert call_params["source_id"] == "node-1"
        assert call_params["target_id"] == "node-2"
        assert call_params["silo_id"] == "silo-abc"
        assert call_params["detected_by"] == "system"
        assert call_params["resolution_status"] == "unresolved"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_result(self) -> None:
        store = AsyncMock()
        store.execute_write.return_value = []

        edge_id = await create_contradicts_edge(
            store=store,
            source_id="node-1",
            target_id="node-2",
            silo_id="silo-abc",
        )

        assert edge_id is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self) -> None:
        store = AsyncMock()
        store.execute_write.side_effect = Exception("DB error")

        edge_id = await create_contradicts_edge(
            store=store,
            source_id="node-1",
            target_id="node-2",
            silo_id="silo-abc",
        )

        assert edge_id is None


class TestDetectConflicts:
    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self, identity: IdentityContext) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.conflict_detection.get_settings",
                lambda: MagicMock(conflict_detection=MagicMock(enabled=False)),
            )
            result = await detect_conflicts(
                store=store,
                node_id="new-node",
                node_embedding=[1.0, 0.0],
                ctx=identity,
                qdrant_client=qdrant,
            )

        assert result == []
        qdrant.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_without_qdrant(self, identity: IdentityContext) -> None:
        store = AsyncMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.conflict_detection.get_settings",
                lambda: MagicMock(
                    conflict_detection=MagicMock(
                        enabled=True,
                        similarity_threshold=0.7,
                        check_other_agents_only=True,
                    )
                ),
            )
            result = await detect_conflicts(
                store=store,
                node_id="new-node",
                node_embedding=[1.0, 0.0],
                ctx=identity,
                qdrant_client=None,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_creates_edge_when_same_subject(self, identity: IdentityContext) -> None:
        store = AsyncMock()
        store.execute_write.return_value = [{"edge_id": "edge-1"}]

        emb = [1.0, 0.0, 0.0]
        spo = {"subject": "Python", "predicate": "is", "object": "good"}

        # new node props returned from graph
        store.execute_query.side_effect = [
            [{"id": "new-node", "embedding": emb, "labels": ["Claim"], "spo": spo}],
            [{"id": "candidate-1", "embedding": emb, "labels": ["Claim"], "spo": spo}],
        ]

        qdrant = AsyncMock()
        hit = MagicMock()
        hit.payload = {"node_id": "candidate-1", "agent_id": "agent-B"}
        hit.score = 0.9
        qdrant.search.return_value = [hit]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.conflict_detection.get_settings",
                lambda: MagicMock(
                    conflict_detection=MagicMock(
                        enabled=True,
                        similarity_threshold=0.7,
                        check_other_agents_only=True,
                    )
                ),
            )
            result = await detect_conflicts(
                store=store,
                node_id="new-node",
                node_embedding=emb,
                ctx=identity,
                qdrant_client=qdrant,
            )

        assert len(result) == 1
        store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_different_subject(self, identity: IdentityContext) -> None:
        store = AsyncMock()

        emb = [1.0, 0.0, 0.0]
        spo_a = {"subject": "Python", "predicate": "is", "object": "good"}
        spo_b = {"subject": "Java", "predicate": "is", "object": "fast"}

        store.execute_query.side_effect = [
            [{"id": "new-node", "embedding": emb, "labels": ["Claim"], "spo": spo_a}],
            [{"id": "candidate-1", "embedding": emb, "labels": ["Claim"], "spo": spo_b}],
        ]

        qdrant = AsyncMock()
        hit = MagicMock()
        hit.payload = {"node_id": "candidate-1", "agent_id": "agent-B"}
        hit.score = 0.9
        qdrant.search.return_value = [hit]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.conflict_detection.get_settings",
                lambda: MagicMock(
                    conflict_detection=MagicMock(
                        enabled=True,
                        similarity_threshold=0.7,
                        check_other_agents_only=True,
                    )
                ),
            )
            result = await detect_conflicts(
                store=store,
                node_id="new-node",
                node_embedding=emb,
                ctx=identity,
                qdrant_client=qdrant,
            )

        assert result == []
        store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_search_error(self, identity: IdentityContext) -> None:
        store = AsyncMock()
        qdrant = AsyncMock()
        qdrant.search.side_effect = Exception("Qdrant error")

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "context_service.engine.conflict_detection.get_settings",
                lambda: MagicMock(
                    conflict_detection=MagicMock(
                        enabled=True,
                        similarity_threshold=0.7,
                        check_other_agents_only=True,
                    )
                ),
            )
            result = await detect_conflicts(
                store=store,
                node_id="new-node",
                node_embedding=[1.0, 0.0],
                ctx=identity,
                qdrant_client=qdrant,
            )

        assert result == []
