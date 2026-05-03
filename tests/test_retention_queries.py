from context_service.retention.queries import (
    FIND_TOMBSTONE_CANDIDATES,
    TOMBSTONE_NODE,
    FIND_HARD_DELETE_CANDIDATES,
    HARD_DELETE_NODE,
    FIND_EXCESS_META_OBSERVATIONS,
    MARK_HEAT_DIRTY,
)


def test_queries_are_valid_cypher_syntax():
    """Basic validation that queries are importable strings."""
    assert "MATCH" in FIND_TOMBSTONE_CANDIDATES
    assert "silo_id" in FIND_TOMBSTONE_CANDIDATES
    assert "$silo_id" in TOMBSTONE_NODE
    assert "$grace_cutoff" in FIND_HARD_DELETE_CANDIDATES
    assert "DETACH DELETE" in HARD_DELETE_NODE
    assert "SKIP $keep_count" in FIND_EXCESS_META_OBSERVATIONS
    assert "heat_dirty" in MARK_HEAT_DIRTY
