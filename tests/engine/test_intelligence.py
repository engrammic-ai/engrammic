"""Tests for intelligence layer stuck detection."""

from datetime import UTC, datetime, timedelta

from context_service.engine.intelligence import (
    STUCK_QUERY_COUNT,
    _query_similarity,
    detect_stuck_pattern,
)
from context_service.engine.session_state import QueryRecord, SessionState


def test_query_similarity_identical():
    assert _query_similarity("hello world", "hello world") == 1.0


def test_query_similarity_different():
    assert _query_similarity("hello", "goodbye") < 0.5


def test_query_similarity_case_insensitive():
    assert _query_similarity("Hello World", "hello world") == 1.0


def test_detect_stuck_pattern_not_enough_queries():
    session = SessionState(session_id="test")
    session.recent_queries = [
        QueryRecord(query="what is X", timestamp=datetime.now(UTC)),
        QueryRecord(query="what is X", timestamp=datetime.now(UTC)),
    ]
    assert detect_stuck_pattern(session) is None


def test_detect_stuck_pattern_with_writes():
    session = SessionState(session_id="test")
    now = datetime.now(UTC)
    session.recent_queries = [
        QueryRecord(query="what is X", timestamp=now, had_write=True),
        QueryRecord(query="what is X", timestamp=now),
        QueryRecord(query="what is X", timestamp=now),
    ]
    # First query had a write, so only 2 without writes
    assert detect_stuck_pattern(session) is None


def test_detect_stuck_pattern_too_old():
    session = SessionState(session_id="test")
    old = datetime.now(UTC) - timedelta(minutes=10)
    session.recent_queries = [
        QueryRecord(query="what is X", timestamp=old),
        QueryRecord(query="what is X", timestamp=old),
        QueryRecord(query="what is X", timestamp=old),
    ]
    assert detect_stuck_pattern(session) is None


def test_detect_stuck_pattern_success():
    session = SessionState(session_id="test")
    now = datetime.now(UTC)
    # Use highly similar queries that meet the 0.7 threshold
    session.recent_queries = [
        QueryRecord(query="what is the authentication method", timestamp=now),
        QueryRecord(query="what is the authentication system", timestamp=now),
        QueryRecord(query="what is the authentication process", timestamp=now),
    ]
    result = detect_stuck_pattern(session)
    assert result is not None
    assert len(result) >= STUCK_QUERY_COUNT


def test_detect_stuck_pattern_dissimilar_queries():
    session = SessionState(session_id="test")
    now = datetime.now(UTC)
    session.recent_queries = [
        QueryRecord(query="what is X", timestamp=now),
        QueryRecord(query="how to Y", timestamp=now),
        QueryRecord(query="where is Z", timestamp=now),
    ]
    assert detect_stuck_pattern(session) is None


def test_query_similarity_for_hints():
    """Test similarity used for breakthrough hint matching."""
    # Similar queries should match
    assert _query_similarity("how to authenticate users", "how to authenticate a user") > 0.6
    # Very different queries should not match
    assert _query_similarity("how to authenticate", "database migration") < 0.3


# Phase 3 tests

def test_volatility_query_has_required_params():
    """Volatility query should have silo_id filtering."""
    from context_service.engine.intelligence import FIND_VOLATILE_TOPICS

    assert "$silo_id" in FIND_VOLATILE_TOPICS
    assert "SUPERSEDES" in FIND_VOLATILE_TOPICS


def test_gap_query_has_required_params():
    """Gap detection queries should have silo_id filtering."""
    from context_service.engine.intelligence import (
        FIND_KNOWLEDGE_GAPS,
        RECORD_UNANSWERED_QUERY,
    )

    assert "$silo_id" in RECORD_UNANSWERED_QUERY
    assert "$silo_id" in FIND_KNOWLEDGE_GAPS


def test_provenance_query_has_required_params():
    """Provenance queries should have silo_id filtering."""
    from context_service.engine.intelligence import (
        FIND_AGENT_CONTRIBUTIONS,
        FIND_BELIEF_CONTRIBUTORS,
    )

    assert "$silo_id" in FIND_BELIEF_CONTRIBUTORS
    assert "$silo_id" in FIND_AGENT_CONTRIBUTIONS
