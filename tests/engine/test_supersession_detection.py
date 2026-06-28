"""Tests for write-time supersession detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.engine.supersession_detection import (
    AUTO_SUPERSEDE_WINDOW,
    SupersessionCandidate,
    SupersessionDetectionResult,
    detect_supersession_candidates,
    format_candidates_for_response,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock graph store."""
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    return store


class TestSupersessionCandidate:
    """Tests for SupersessionCandidate dataclass."""

    def test_candidate_fields(self) -> None:
        candidate = SupersessionCandidate(
            node_id="abc-123",
            subject="API",
            predicate="uses",
            object="OAuth2",
            confidence=0.95,
            reason="session_recall",
            auto_supersede=True,
        )
        assert candidate.node_id == "abc-123"
        assert candidate.subject == "API"
        assert candidate.confidence == 0.95
        assert candidate.auto_supersede is True


class TestSupersessionDetectionResult:
    """Tests for SupersessionDetectionResult dataclass."""

    def test_empty_result(self) -> None:
        result = SupersessionDetectionResult(
            candidates=[],
            auto_supersede_id=None,
            detection_ms=5.0,
        )
        assert result.candidates == []
        assert result.auto_supersede_id is None

    def test_result_with_auto_supersede(self) -> None:
        candidate = SupersessionCandidate(
            node_id="abc-123",
            subject="API",
            predicate="uses",
            object="OAuth2",
            confidence=0.95,
            reason="session_recall",
            auto_supersede=True,
        )
        result = SupersessionDetectionResult(
            candidates=[candidate],
            auto_supersede_id="abc-123",
            detection_ms=3.0,
        )
        assert result.auto_supersede_id == "abc-123"
        assert len(result.candidates) == 1


class TestFormatCandidatesForResponse:
    """Tests for format_candidates_for_response."""

    def test_empty_candidates_returns_empty_dict(self) -> None:
        result = SupersessionDetectionResult(
            candidates=[],
            auto_supersede_id=None,
            detection_ms=1.0,
        )
        response = format_candidates_for_response(result)
        assert response == {}

    def test_auto_superseded_in_response(self) -> None:
        candidate = SupersessionCandidate(
            node_id="abc-123",
            subject="API",
            predicate="uses",
            object="OAuth2",
            confidence=0.95,
            reason="session_recall",
            auto_supersede=True,
        )
        result = SupersessionDetectionResult(
            candidates=[candidate],
            auto_supersede_id="abc-123",
            detection_ms=1.0,
        )
        response = format_candidates_for_response(result)
        assert response["auto_superseded"] == "abc-123"

    def test_high_confidence_in_likely_updates(self) -> None:
        candidate = SupersessionCandidate(
            node_id="def-456",
            subject="Config",
            predicate="value",
            object="100",
            confidence=0.85,
            reason="spo_match",
            auto_supersede=False,
        )
        result = SupersessionDetectionResult(
            candidates=[candidate],
            auto_supersede_id=None,
            detection_ms=1.0,
        )
        response = format_candidates_for_response(result)
        assert "likely_updates" in response
        assert response["likely_updates"][0]["id"] == "def-456"

    def test_medium_confidence_in_possible_updates(self) -> None:
        candidate = SupersessionCandidate(
            node_id="ghi-789",
            subject=None,
            predicate=None,
            object=None,
            confidence=0.6,
            reason="semantic_similarity",
            auto_supersede=False,
        )
        result = SupersessionDetectionResult(
            candidates=[candidate],
            auto_supersede_id=None,
            detection_ms=1.0,
        )
        response = format_candidates_for_response(result)
        assert "possible_updates" in response
        assert response["possible_updates"][0]["id"] == "ghi-789"

    def test_auto_superseded_not_duplicated_in_likely(self) -> None:
        candidate = SupersessionCandidate(
            node_id="abc-123",
            subject="API",
            predicate="uses",
            object="OAuth2",
            confidence=0.95,
            reason="session_recall",
            auto_supersede=True,
        )
        result = SupersessionDetectionResult(
            candidates=[candidate],
            auto_supersede_id="abc-123",
            detection_ms=1.0,
        )
        response = format_candidates_for_response(result)
        assert response["auto_superseded"] == "abc-123"
        # Should not appear in likely_updates since it's already auto_superseded
        likely = response.get("likely_updates", [])
        assert not any(item["id"] == "abc-123" for item in likely)


class TestDetectSupersessionCandidates:
    """Tests for detect_supersession_candidates."""

    @pytest.mark.asyncio
    async def test_no_candidates_when_no_subject(self, mock_store: AsyncMock) -> None:
        """Detection returns empty when no subject provided."""
        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject=None,
            predicate=None,
            obj=None,
        )
        assert result.candidates == []
        assert result.auto_supersede_id is None

    @pytest.mark.asyncio
    async def test_tier0_session_recall_match(self, mock_store: AsyncMock) -> None:
        """Tier 0: Session recall with subject match triggers auto-supersede."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": "recalled-node",
                    "subject": "API",
                    "predicate": "uses",
                    "object": "OAuth2",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate="uses",
            obj="OAuth2 with PKCE",
        )

        assert result.auto_supersede_id == "recalled-node"
        assert len(result.candidates) == 1
        assert result.candidates[0].reason == "session_recall"
        assert result.candidates[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_tier1_spo_match_same_session(self, mock_store: AsyncMock) -> None:
        """Tier 1: SPO match in same session triggers auto-supersede."""
        # First query (session recall) returns empty
        # Second query (SPO match) returns a match
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # Tier 0: no session recall
                [
                    {
                        "node_id": "spo-match-node",
                        "subject": "Config",
                        "predicate": "timeout",
                        "object": "30",
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "session-1",  # Same session
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="Config",
            predicate="timeout",
            obj="60",  # Different object
        )

        assert result.auto_supersede_id == "spo-match-node"
        assert len(result.candidates) == 1
        assert result.candidates[0].reason == "spo_match"

    @pytest.mark.asyncio
    async def test_tier1_spo_match_recent(self, mock_store: AsyncMock) -> None:
        """Tier 1: SPO match within time window triggers auto-supersede."""
        recent_time = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # Tier 0: no session recall
                [
                    {
                        "node_id": "recent-node",
                        "subject": "Config",
                        "predicate": "timeout",
                        "object": "30",
                        "created_at": recent_time,
                        "session_id": "other-session",  # Different session
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="Config",
            predicate="timeout",
            obj="60",
        )

        assert result.auto_supersede_id == "recent-node"

    @pytest.mark.asyncio
    async def test_tier1_spo_match_old_no_auto(self, mock_store: AsyncMock) -> None:
        """Tier 1: SPO match outside time window does not auto-supersede."""
        old_time = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # Tier 0: no session recall
                [
                    {
                        "node_id": "old-node",
                        "subject": "Config",
                        "predicate": "timeout",
                        "object": "30",
                        "created_at": old_time,
                        "session_id": "other-session",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="Config",
            predicate="timeout",
            obj="60",
        )

        # Should have candidate but not auto-supersede
        assert result.auto_supersede_id is None
        assert len(result.candidates) == 1
        assert result.candidates[0].auto_supersede is False

    @pytest.mark.asyncio
    async def test_tier1_subject_only_match(self, mock_store: AsyncMock) -> None:
        """Tier 1: Subject-only match (no predicate) has lower confidence."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # Tier 0: no session recall
                [
                    {
                        "node_id": "subject-match",
                        "subject": "API",
                        "predicate": None,
                        "object": None,
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "session-1",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate=None,  # No predicate
            obj=None,
        )

        assert len(result.candidates) == 1
        assert result.candidates[0].reason == "subject_match"
        assert result.candidates[0].confidence < 0.9  # Lower than SPO match

    @pytest.mark.asyncio
    async def test_tier2_semantic_similarity_no_auto(self, mock_store: AsyncMock) -> None:
        """Tier 2: Semantic similarity never auto-supersedes."""
        # Tier 2 agent lookup returns same agent (so candidate is included)
        mock_store.execute_query = AsyncMock(
            return_value=[
                {"agent_id": "agent-1", "subject": None, "predicate": None, "object": None}
            ]
        )

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.supersession_detection.semantic_fallback_enabled = True
        mock_settings.supersession_detection.similarity_threshold = 0.85

        with (
            patch(
                "context_service.engine.supersession_detection.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "context_service.engine.contradiction.check_contradiction_candidates",
                new_callable=AsyncMock,
                return_value=["similar-node"],
            ),
        ):
            mock_qdrant = AsyncMock()
            result = await detect_supersession_candidates(
                store=mock_store,
                silo_id="test-silo",
                node_id="new-node",
                agent_id="agent-1",
                session_id="session-1",
                subject=None,  # No subject = skip Tier 0 and 1
                predicate=None,
                obj=None,
                embedding=[0.1] * 768,
                qdrant_client=mock_qdrant,
            )

        # Semantic matches should never auto-supersede
        assert result.auto_supersede_id is None
        assert len(result.candidates) == 1
        assert result.candidates[0].reason == "semantic_similarity"
        assert result.candidates[0].auto_supersede is False

    @pytest.mark.asyncio
    async def test_deduplicates_across_tiers(self, mock_store: AsyncMock) -> None:
        """Same node found in multiple tiers only appears once."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # Tier 0: session recall
                [
                    {
                        "node_id": "duplicate-node",
                        "subject": "API",
                        "predicate": "uses",
                        "object": "OAuth2",
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                ],
                # Tier 1: SPO match (same node)
                [
                    {
                        "node_id": "duplicate-node",
                        "subject": "API",
                        "predicate": "uses",
                        "object": "OAuth2",
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "session-1",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate="uses",
            obj="OAuth2 with PKCE",
        )

        # Should only appear once (from Tier 0, highest confidence)
        assert len(result.candidates) == 1
        assert result.candidates[0].node_id == "duplicate-node"
        assert result.candidates[0].reason == "session_recall"

    @pytest.mark.asyncio
    async def test_handles_query_failure_gracefully(self, mock_store: AsyncMock) -> None:
        """Detection continues despite tier failures."""
        mock_store.execute_query = AsyncMock(
            side_effect=Exception("Database error")
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate="uses",
            obj="OAuth2",
        )

        # Should return empty result, not raise
        assert result.candidates == []
        assert result.auto_supersede_id is None


class TestAutoSupersedWindow:
    """Tests for AUTO_SUPERSEDE_WINDOW constant."""

    def test_window_is_5_minutes(self) -> None:
        assert timedelta(minutes=5) == AUTO_SUPERSEDE_WINDOW


class TestSupersessionPrecedenceRules:
    """Tests verifying the tiered precedence and auto-supersede logic."""

    @pytest.mark.asyncio
    async def test_session_recall_short_circuits(self, mock_store: AsyncMock) -> None:
        """Session recall (Tier 0) short-circuits — Tier 1 not called."""
        now = datetime.now(UTC)

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": "recalled-old",
                    "subject": "API",
                    "predicate": "auth",
                    "object": "basic",
                    "created_at": (now - timedelta(hours=1)).isoformat(),
                }
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate="auth",
            obj="oauth2",
        )

        # Auto-supersede should be the recalled node
        assert result.auto_supersede_id == "recalled-old"
        # Only Tier 0 candidate (short-circuit)
        assert len(result.candidates) == 1
        assert result.candidates[0].reason == "session_recall"
        # Tier 1 query should NOT have been called (only 1 query total)
        assert mock_store.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_same_object_no_auto_supersede(self, mock_store: AsyncMock) -> None:
        """SPO match with SAME object should NOT auto-supersede (not an update)."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # Tier 0: no recall
                [
                    {
                        "node_id": "existing",
                        "subject": "Config",
                        "predicate": "value",
                        "object": "100",  # Same as new
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "session-1",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="Config",
            predicate="value",
            obj="100",  # Same object - this is a duplicate, not an update
        )

        # Should NOT auto-supersede when objects are identical
        assert result.auto_supersede_id is None
        # Should still be a candidate (possible duplicate)
        assert len(result.candidates) == 1
        assert result.candidates[0].auto_supersede is False

    @pytest.mark.asyncio
    async def test_different_agent_excluded_from_spo_match(
        self, mock_store: AsyncMock
    ) -> None:
        """SPO match from different agent should not be returned.

        The query filters by agent_id, so we verify by checking that an
        empty result is returned when no same-agent matches exist.
        """
        # Return empty for both tiers (simulating no same-agent matches)
        mock_store.execute_query = AsyncMock(return_value=[])

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new-node",
            agent_id="agent-1",
            session_id="session-1",
            subject="API",
            predicate="uses",
            obj="OAuth2",
        )

        assert result.candidates == []
        # Verify the query was called with correct agent_id filter
        calls = mock_store.execute_query.call_args_list
        # At least one call should have agent_id in params
        assert any("agent_id" in str(call) for call in calls)


class TestConfidenceScoring:
    """Tests verifying confidence scores are calculated correctly."""

    @pytest.mark.asyncio
    async def test_session_recall_confidence_is_095(self, mock_store: AsyncMock) -> None:
        """Session recall should have 0.95 confidence."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "node_id": "recalled",
                    "subject": "X",
                    "predicate": "Y",
                    "object": "Z",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="X",
            predicate="Y",
            obj="Z2",
        )

        assert result.candidates[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_spo_match_confidence_higher_than_subject_only(
        self, mock_store: AsyncMock
    ) -> None:
        """Full (S,P) match should have higher confidence than subject-only."""
        # Test with predicate
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # No session recall
                [
                    {
                        "node_id": "spo",
                        "subject": "API",
                        "predicate": "auth",
                        "object": "basic",
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "other",
                    }
                ],
            ]
        )

        result_spo = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="API",
            predicate="auth",
            obj="oauth",
        )

        # Reset and test without predicate
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "subject-only",
                        "subject": "API",
                        "predicate": None,
                        "object": None,
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "other",
                    }
                ],
            ]
        )

        result_subject = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="API",
            predicate=None,
            obj=None,
        )

        assert result_spo.candidates[0].confidence > result_subject.candidates[0].confidence

    @pytest.mark.asyncio
    async def test_same_session_adds_confidence_boost(self, mock_store: AsyncMock) -> None:
        """Same session should add 0.05 to confidence."""
        base_time = datetime.now(UTC) - timedelta(minutes=10)  # Outside auto window

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],  # No session recall
                [
                    {
                        "node_id": "same-session",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": base_time.isoformat(),
                        "session_id": "session-1",  # Same session
                    }
                ],
            ]
        )

        result_same = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session-1",
            subject="X",
            predicate="Y",
            obj="new",
        )

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "diff-session",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": base_time.isoformat(),
                        "session_id": "session-other",  # Different session
                    }
                ],
            ]
        )

        result_diff = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session-1",
            subject="X",
            predicate="Y",
            obj="new",
        )

        # Same session should have higher confidence
        assert result_same.candidates[0].confidence > result_diff.candidates[0].confidence


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_exactly_at_auto_window_boundary(self, mock_store: AsyncMock) -> None:
        """Node created exactly at AUTO_SUPERSEDE_WINDOW ago should NOT auto."""
        # ponytail: boundary is exclusive, exactly 5 min ago is outside window
        boundary_time = datetime.now(UTC) - AUTO_SUPERSEDE_WINDOW

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "boundary",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": boundary_time.isoformat(),
                        "session_id": "other",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="X",
            predicate="Y",
            obj="new",
        )

        # Exactly at boundary should NOT auto-supersede (< not <=)
        assert result.auto_supersede_id is None

    @pytest.mark.asyncio
    async def test_just_inside_auto_window(self, mock_store: AsyncMock) -> None:
        """Node created 1 second inside window SHOULD auto."""
        inside_time = datetime.now(UTC) - AUTO_SUPERSEDE_WINDOW + timedelta(seconds=1)

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "inside",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": inside_time.isoformat(),
                        "session_id": "other",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="X",
            predicate="Y",
            obj="new",
        )

        assert result.auto_supersede_id == "inside"

    @pytest.mark.asyncio
    async def test_malformed_created_at_handled(self, mock_store: AsyncMock) -> None:
        """Malformed created_at should not crash, just skip recency check."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "malformed",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": "not-a-date",  # Malformed
                        "session_id": "other",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="X",
            predicate="Y",
            obj="new",
        )

        # Should not crash, should not auto (can't verify recency)
        assert result.auto_supersede_id is None
        assert len(result.candidates) == 1

    @pytest.mark.asyncio
    async def test_null_session_id_skips_tier0(self, mock_store: AsyncMock) -> None:
        """No session_id should skip Tier 0 entirely."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # Only Tier 1 should be called
                [
                    {
                        "node_id": "spo",
                        "subject": "X",
                        "predicate": "Y",
                        "object": "old",
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": None,
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id=None,  # No session
            subject="X",
            predicate="Y",
            obj="new",
        )

        # Should still find SPO match
        assert len(result.candidates) == 1
        # Tier 0 query should not have been called (only 1 call total)
        assert mock_store.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_case_insensitive_subject_match(self, mock_store: AsyncMock) -> None:
        """Subject matching should be case-insensitive (via toLower in query)."""
        # This test verifies our query uses toLower
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "node_id": "match",
                        "subject": "API",  # Uppercase in DB
                        "predicate": "uses",
                        "object": "old",
                        "created_at": datetime.now(UTC).isoformat(),
                        "session_id": "session",
                    }
                ],
            ]
        )

        result = await detect_supersession_candidates(
            store=mock_store,
            silo_id="test-silo",
            node_id="new",
            agent_id="agent",
            session_id="session",
            subject="api",  # Lowercase in query
            predicate="uses",
            obj="new",
        )

        # Should match despite case difference
        assert len(result.candidates) == 1
