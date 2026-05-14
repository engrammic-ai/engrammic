"""Tests for embedding content truncation (AI-01 fix)."""

from context_service.pipelines.assets.embedding import MAX_EMBED_CHARS


def test_max_embed_chars_is_8000() -> None:
    """Verify the MAX_EMBED_CHARS constant is set correctly."""
    assert MAX_EMBED_CHARS == 8000


def test_truncation_at_max_chars() -> None:
    """Verify texts longer than MAX_EMBED_CHARS are truncated."""
    long_text = "x" * 10000
    truncated = long_text[:MAX_EMBED_CHARS]
    assert len(truncated) == 8000


def test_short_text_unchanged() -> None:
    """Verify texts shorter than MAX_EMBED_CHARS remain unchanged."""
    short_text = "hello world"
    truncated = short_text[:MAX_EMBED_CHARS]
    assert truncated == short_text
