from context_service.engine.nudges import (
    NUDGE_TEMPLATES,
    NudgeType,
    format_nudge,
)


def test_nudge_types_have_templates():
    for nudge_type in NudgeType:
        assert nudge_type.value in NUDGE_TEMPLATES


def test_format_nudge_markers():
    nudge = format_nudge(
        nudge_type=NudgeType.PENDING_MARKERS,
        count=3,
    )
    assert nudge.type == NudgeType.PENDING_MARKERS
    assert "3" in nudge.prompt
    assert nudge.suggested_tool is None


def test_format_nudge_form_belief():
    nudge = format_nudge(
        nudge_type=NudgeType.FORM_BELIEF,
        topic="OAuth authentication",
        about_nodes=["node_a", "node_b", "node_c"],
        count=3,
    )
    assert nudge.type == NudgeType.FORM_BELIEF
    assert "OAuth" in nudge.prompt
    assert nudge.suggested_tool == "believe"
    assert nudge.about_nodes == ["node_a", "node_b", "node_c"]
