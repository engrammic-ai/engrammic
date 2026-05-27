"""Nudge detection rules and template formatting for tick()."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class NudgeType(StrEnum):
    PENDING_MARKERS = "pending_markers"
    STALE_HYPOTHESIS = "stale_hypothesis"
    STORAGE_GAP = "storage_gap"
    FORM_BELIEF = "form_belief"
    RELEVANT_CONTEXT = "relevant_context"
    OPEN_REASONING = "open_reasoning"


NUDGE_PRIORITY = [
    NudgeType.PENDING_MARKERS,
    NudgeType.STALE_HYPOTHESIS,
    NudgeType.STORAGE_GAP,
    NudgeType.FORM_BELIEF,
    NudgeType.RELEVANT_CONTEXT,
    NudgeType.OPEN_REASONING,
]

NUDGE_TEMPLATES = {
    NudgeType.PENDING_MARKERS: "You have {count} marker(s) to address.",
    NudgeType.STALE_HYPOTHESIS: "Hypothesis '{hypothesis_id}' open for {turns} turns. Commit or revise?",
    NudgeType.STORAGE_GAP: "Nothing stored in {turns} turns. Consider checkpointing.",
    NudgeType.FORM_BELIEF: "{count} related observations about {topic}. Consider believe().",
    NudgeType.RELEVANT_CONTEXT: "Relevant to your work: {summaries}",
    NudgeType.OPEN_REASONING: "Reasoning chain open. Conclude with reason()?",
}

NUDGE_SUGGESTED_TOOLS = {
    NudgeType.PENDING_MARKERS: None,
    NudgeType.STALE_HYPOTHESIS: "commit",
    NudgeType.STORAGE_GAP: "remember",
    NudgeType.FORM_BELIEF: "believe",
    NudgeType.RELEVANT_CONTEXT: None,
    NudgeType.OPEN_REASONING: "reason",
}

MAX_NUDGES = 3


class Nudge(BaseModel):
    """A nudge to show the agent."""

    type: NudgeType
    prompt: str
    suggested_tool: str | None = None
    about_nodes: list[str] | None = None
    priority: int = 0


def format_nudge(nudge_type: NudgeType, **kwargs: Any) -> Nudge:
    """Format a nudge from template with given parameters."""
    template = NUDGE_TEMPLATES[nudge_type]
    prompt = template.format(**kwargs)
    priority = NUDGE_PRIORITY.index(nudge_type)

    return Nudge(
        type=nudge_type,
        prompt=prompt,
        suggested_tool=NUDGE_SUGGESTED_TOOLS[nudge_type],
        about_nodes=kwargs.get("about_nodes"),
        priority=priority,
    )


def prioritize_nudges(nudges: list[Nudge]) -> list[Nudge]:
    """Sort nudges by priority and cap at MAX_NUDGES."""
    sorted_nudges = sorted(nudges, key=lambda n: n.priority)
    return sorted_nudges[:MAX_NUDGES]
