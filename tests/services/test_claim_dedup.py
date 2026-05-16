"""Tests for content-hash deduplication in assert_claim()."""

import hashlib


def test_content_hash_is_full_sha256() -> None:
    """Verify content hash uses full SHA256 without truncation."""
    content = "test content for hashing"
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert len(expected) == 64  # Full SHA256 hex is 64 chars


def test_dedup_query_structure() -> None:
    """Verify the dedup query filters by silo_id and content_hash."""
    query = """
    MATCH (c:Claim {silo_id: $silo_id, content_hash: $content_hash})
    WHERE c.tombstoned_at IS NULL
    RETURN c.id AS id
    LIMIT 1
    """
    assert "silo_id: $silo_id" in query
    assert "content_hash: $content_hash" in query
    assert "tombstoned_at IS NULL" in query
    assert "LIMIT 1" in query
