# tests/mcp/tools/test_learn_evidence.py
"""Tests for D1: Evidence enforcement in learn tool."""

from __future__ import annotations

import pytest
from primitives.eag.transitions import MissingEvidenceError, validate_evidence_non_empty


class TestValidateEvidenceNonEmpty:
    """Tests for the evidence validation predicate."""

    def test_empty_list_returns_false(self) -> None:
        assert validate_evidence_non_empty([]) is False

    def test_none_returns_false(self) -> None:
        assert validate_evidence_non_empty(None) is False

    def test_non_empty_list_returns_true(self) -> None:
        assert validate_evidence_non_empty(["node:abc123"]) is True
        assert validate_evidence_non_empty(["https://example.com"]) is True

    def test_multiple_items_returns_true(self) -> None:
        assert validate_evidence_non_empty(["a", "b", "c"]) is True


class TestMissingEvidenceError:
    """Tests for the structured error."""

    def test_error_message(self) -> None:
        err = MissingEvidenceError()
        assert "remember" in str(err).lower()

    def test_is_exception(self) -> None:
        with pytest.raises(MissingEvidenceError):
            raise MissingEvidenceError()
