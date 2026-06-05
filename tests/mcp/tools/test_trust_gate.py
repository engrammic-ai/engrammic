from context_service.mcp.tools.trust_gate import apply_trust_gate


def _node(node_id, confidence=1.0, conflict_status="none"):
    return {"node_id": node_id, "confidence": confidence, "conflict_status": conflict_status}


def test_passes_warranted_nodes():
    items = [_node("a"), _node("b")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.0, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a", "b"]
    assert withheld["count"] == 0


def test_withholds_unresolved_conflict():
    items = [_node("a"), _node("bad", conflict_status="unresolved")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.0, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a"]
    assert withheld["count"] == 1
    assert withheld["by_reason"]["unresolved_conflict"] == 1


def test_withholds_below_floor():
    items = [_node("a", confidence=0.9), _node("low", confidence=0.1)]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.3, withhold_conflicts=True, include_withheld=False
    )
    assert [n["node_id"] for n in surfaced] == ["a"]
    assert withheld["by_reason"]["low_confidence"] == 1


def test_include_withheld_bypasses():
    items = [_node("a"), _node("bad", conflict_status="unresolved")]
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.5, withhold_conflicts=True, include_withheld=True
    )
    assert len(surfaced) == 2
    assert withheld["count"] == 0


def test_missing_confidence_is_not_withheld():
    items = [{"node_id": "a", "conflict_status": "none"}]  # no confidence key
    surfaced, withheld = apply_trust_gate(
        items, confidence_floor=0.5, withhold_conflicts=True, include_withheld=False
    )
    assert len(surfaced) == 1


def test_empty_input():
    surfaced, withheld = apply_trust_gate(
        [], confidence_floor=0.5, withhold_conflicts=True, include_withheld=False
    )
    assert surfaced == []
    assert withheld["count"] == 0
