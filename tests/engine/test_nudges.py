from context_service.engine.nudges import (
    NUDGE_TEMPLATES,
    Nudge,
    NudgeType,
    format_nudge,
    prioritize_nudges,
)


def test_nudge_types_have_templates():
    for nudge_type in NudgeType:
        assert nudge_type in NUDGE_TEMPLATES


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


def test_prioritize_nudges_sorts_and_caps():
    nudges = [
        Nudge(type=NudgeType.FORM_BELIEF, prompt="a", priority=3),
        Nudge(type=NudgeType.PENDING_MARKERS, prompt="b", priority=0),
        Nudge(type=NudgeType.STORAGE_GAP, prompt="c", priority=2),
        Nudge(type=NudgeType.STALE_HYPOTHESIS, prompt="d", priority=1),
    ]

    result = prioritize_nudges(nudges)

    assert len(result) == 3  # Capped at MAX_NUDGES
    assert result[0].type == NudgeType.PENDING_MARKERS  # Priority 0 first
    assert result[1].type == NudgeType.STALE_HYPOTHESIS  # Priority 1
    assert result[2].type == NudgeType.STORAGE_GAP  # Priority 2
