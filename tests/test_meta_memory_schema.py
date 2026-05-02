"""Verify MetaMemory schema additions are importable and correctly valued."""

from primitives.schema.edges import CITEEdgeType
from primitives.schema.labels import MetaMemoryLabel


def test_meta_memory_label_value() -> None:
    assert MetaMemoryLabel.META_OBSERVATION == "MetaObservation"


def test_about_edge_in_cite_edge_type() -> None:
    assert CITEEdgeType.ABOUT == "ABOUT"


def test_about_edge_in_all_cite_edges() -> None:
    from primitives.schema.edges import ALL_CITE_EDGES

    assert "ABOUT" in ALL_CITE_EDGES
