"""Regression test for S-005 — SPARQL literal escaping in wikidata filter.
See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

from context_service.extraction.filter.wikidata import _escape_sparql_literal


def test_escape_double_quote() -> None:
    assert _escape_sparql_literal('he said "hi"') == r"he said \"hi\""


def test_escape_backslash_first() -> None:
    assert _escape_sparql_literal(r"path\\to") == r"path\\\\to"


def test_escape_newline_carriage_tab() -> None:
    assert _escape_sparql_literal("a\nb\rc\td") == r"a\nb\rc\td"


def test_escape_keeps_payload_inside_literal() -> None:
    """The hostile keyword survives in the output — that's fine, it's just data.
    What must NOT survive is a way to terminate the surrounding "..." literal.
    """
    payload = '"} . DROP GRAPH <urn:x> . #'
    escaped = _escape_sparql_literal(payload)
    # No unescaped double-quote — every " is preceded by \\
    for i, ch in enumerate(escaped):
        if ch == '"':
            assert i > 0 and escaped[i - 1] == "\\", f"unescaped quote at index {i} in {escaped!r}"


def test_escape_neutralizes_backslash_quote_attack() -> None:
    """Naive single-pass escape that only handled " would turn \\" into \\\\"
    and let the closing " through. Confirm backslash-first ordering blocks it.
    """
    payload = r"a\"b"
    escaped = _escape_sparql_literal(payload)
    # backslash itself doubled, original \" becomes \\\\\" (4 backslashes + ")
    assert escaped == r"a\\\"b"


def test_escape_idempotent_on_clean_input() -> None:
    assert _escape_sparql_literal("plain string") == "plain string"
