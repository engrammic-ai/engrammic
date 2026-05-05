"""Tests for CAUSES and CORROBORATES edge queries and RelationshipType coverage."""

from __future__ import annotations

import pytest

from context_service.extraction.models import RelationshipType as ExtractionRelType
from context_service.models.mcp import RelationshipType as McpRelType


class TestRelationshipTypeEnums:
    def test_extraction_has_causes(self) -> None:
        assert ExtractionRelType.CAUSES == "CAUSES"

    def test_extraction_has_corroborates(self) -> None:
        assert ExtractionRelType.CORROBORATES == "CORROBORATES"

    def test_mcp_has_causes(self) -> None:
        assert McpRelType.CAUSES == "CAUSES"

    def test_mcp_has_corroborates(self) -> None:
        assert McpRelType.CORROBORATES == "CORROBORATES"

    def test_extraction_coerces_causes_from_string(self) -> None:
        from context_service.extraction.models import ExtractedRelationship

        rel = ExtractedRelationship(
            source="A",
            target="B",
            relationship_type="CAUSES",  # type: ignore[arg-type]
            confidence=0.9,
        )
        assert rel.relationship_type is ExtractionRelType.CAUSES
        assert rel.directed is True  # not in SYMMETRIC set

    def test_extraction_coerces_corroborates_from_string(self) -> None:
        from context_service.extraction.models import ExtractedRelationship

        rel = ExtractedRelationship(
            source="A",
            target="B",
            relationship_type="CORROBORATES",  # type: ignore[arg-type]
            confidence=0.75,
        )
        assert rel.relationship_type is ExtractionRelType.CORROBORATES
        assert rel.directed is True  # not in SYMMETRIC set


class TestMcpRelationshipTypeValidity:
    """Verify context_link validation accepts the new types."""

    @pytest.mark.parametrize("rel", ["CAUSES", "CORROBORATES"])
    def test_valid_enum_values(self, rel: str) -> None:
        parsed = McpRelType(rel)
        assert parsed.value == rel
