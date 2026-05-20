"""Test that revision and split IDs never collide."""

from context_service.engine.revision import _make_revised_belief_id


def test_revision_and_split_ids_never_collide():
    """If belief revised once then split, all IDs must be unique."""
    belief_id = "test-belief-123"

    # Revision with count=1 (first revision)
    revision_id = _make_revised_belief_id(belief_id, 1, operation="revision")

    # Split children with indices 0, 1 -> counter 1, 2
    split_id_0 = _make_revised_belief_id(belief_id, 1, operation="split")
    split_id_1 = _make_revised_belief_id(belief_id, 2, operation="split")

    all_ids = [revision_id, split_id_0, split_id_1]
    assert len(all_ids) == len(set(all_ids)), f"ID collision detected: {all_ids}"


def test_make_revised_belief_id_deterministic():
    """Same inputs produce same output."""
    id1 = _make_revised_belief_id("belief-a", 5, operation="revision")
    id2 = _make_revised_belief_id("belief-a", 5, operation="revision")
    assert id1 == id2


def test_make_revised_belief_id_different_operations():
    """Different operations produce different IDs even with same counter."""
    revision = _make_revised_belief_id("belief-a", 1, operation="revision")
    split = _make_revised_belief_id("belief-a", 1, operation="split")
    assert revision != split
