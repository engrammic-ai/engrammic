"""Tool descriptions and server instructions must carry the forcing-function language."""

from context_service.mcp.tools.registry import (
    get_mcp_instructions,
    get_tool_description,
)


def test_recall_description_mentions_session_start_and_withholding():
    desc = get_tool_description("recall").lower()
    assert "session start" in desc or "start of" in desc
    assert "withheld" in desc or "include_withheld" in desc


def test_learn_description_drives_evidence_and_supersession():
    desc = get_tool_description("learn").lower()
    assert "evidence" in desc
    assert "supersedes" in desc


def test_instructions_lead_with_recall_first():
    instr = get_mcp_instructions().lower()
    assert "recall" in instr
    assert "before" in instr  # recall-before-store guidance present
