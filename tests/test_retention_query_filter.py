"""Tests that tombstoned nodes are excluded from key read queries."""

from context_service.db import queries


def test_read_queries_exclude_tombstoned() -> None:
    """Key read queries should filter out tombstoned nodes."""
    read_queries_to_check = [
        getattr(queries, name)
        for name in dir(queries)
        if (name.startswith("GET_") or name.startswith("FETCH_") or name.startswith("SEARCH_"))
        and isinstance(getattr(queries, name), str)
    ]

    all_queries = "\n".join(read_queries_to_check)
    assert "tombstoned_at" in all_queries or len(read_queries_to_check) == 0


def test_find_entity_by_name_excludes_tombstoned() -> None:
    """FIND_ENTITY_BY_NAME must filter tombstoned entities."""
    assert "tombstoned_at" in queries.FIND_ENTITY_BY_NAME


def test_find_entities_by_name_tokens_excludes_tombstoned() -> None:
    """FIND_ENTITIES_BY_NAME_TOKENS must filter tombstoned entities."""
    assert "tombstoned_at" in queries.FIND_ENTITIES_BY_NAME_TOKENS


def test_find_entity_by_qualified_name_excludes_tombstoned() -> None:
    """FIND_ENTITY_BY_QUALIFIED_NAME must filter tombstoned entities."""
    assert "tombstoned_at" in queries.FIND_ENTITY_BY_QUALIFIED_NAME


def test_temporal_query_excludes_tombstoned() -> None:
    """TEMPORAL_QUERY must filter tombstoned nodes."""
    assert "tombstoned_at" in queries.TEMPORAL_QUERY


def test_check_belief_coverage_excludes_tombstoned() -> None:
    """CHECK_BELIEF_COVERAGE must filter tombstoned beliefs."""
    assert "tombstoned_at" in queries.CHECK_BELIEF_COVERAGE


def test_belief_history_by_subject_excludes_tombstoned() -> None:
    """BELIEF_HISTORY_BY_SUBJECT must filter tombstoned nodes."""
    assert "tombstoned_at" in queries.BELIEF_HISTORY_BY_SUBJECT


def test_get_pattern_by_type_and_subject_excludes_tombstoned() -> None:
    """GET_PATTERN_BY_TYPE_AND_SUBJECT must filter tombstoned patterns."""
    assert "tombstoned_at" in queries.GET_PATTERN_BY_TYPE_AND_SUBJECT


def test_get_seed_heat_batch_excludes_tombstoned() -> None:
    """GET_SEED_HEAT_BATCH must filter tombstoned nodes."""
    assert "tombstoned_at" in queries.GET_SEED_HEAT_BATCH
