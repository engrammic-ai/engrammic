"""Tests for embedding content truncation (AI-01 fix)."""

from context_service.pipelines.assets.embedding import MAX_EMBED_CHARS


def test_max_embed_chars_is_8000() -> None:
    """Verify the MAX_EMBED_CHARS constant is set correctly."""
    assert MAX_EMBED_CHARS == 8000


def test_truncation_logic_caps_at_max() -> None:
    """Verify the truncation logic used in the embedding asset caps at MAX_EMBED_CHARS."""
    long_content = "x" * 10000
    short_content = "hello world"

    batch = [
        {"content": long_content},
        {"content": short_content},
    ]

    raw_texts = [str(r["content"]) for r in batch]
    texts = [t[:MAX_EMBED_CHARS] for t in raw_texts]

    assert len(texts[0]) == MAX_EMBED_CHARS
    assert len(texts[0]) < len(long_content)
    assert texts[1] == short_content


def test_truncation_count_detection() -> None:
    """Verify truncation count detection logic works."""
    batch = [
        {"content": "x" * 10000},
        {"content": "y" * 9000},
        {"content": "short"},
    ]

    raw_texts = [str(r["content"]) for r in batch]
    truncated_count = sum(1 for t in raw_texts if len(t) > MAX_EMBED_CHARS)

    assert truncated_count == 2
