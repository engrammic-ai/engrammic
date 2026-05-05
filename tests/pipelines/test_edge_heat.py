# tests/pipelines/test_edge_heat.py
from context_service.pipelines.assets.edge_heat import (
    APPLY_EDGE_HEAT_CYPHER,
    EDGE_HEAT_HALF_LIFE_DAYS,
)


def test_edge_heat_constants():
    assert EDGE_HEAT_HALF_LIFE_DAYS == 7


def test_apply_edge_heat_cypher_structure():
    assert "UNWIND $updates AS u" in APPLY_EDGE_HEAT_CYPHER
    assert "WeakLink" in APPLY_EDGE_HEAT_CYPHER
    assert "edge_heat" in APPLY_EDGE_HEAT_CYPHER
