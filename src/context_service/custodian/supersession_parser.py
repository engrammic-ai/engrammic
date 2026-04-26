"""Supersession prompt renderer + response parser.

The prompt template lives in ``config/prompts/custodian/supersession.yaml``;
this module renders it with the cluster's node/created_at/content block and
parses the LLM's JSON response into :class:`SupersessionPair` records.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from context_service.custodian.prompt_loader import load_prompt

_PROMPTS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "config" / "prompts" / "custodian"
)
_SUPERSESSION_PROMPT_PATH = _PROMPTS_DIR / "supersession.yaml"


@dataclass(frozen=True)
class SupersessionPair:
    """One detected supersession relationship."""

    superseding_id: str
    superseded_id: str
    confidence: float
    reason: str


def build_supersession_prompt(nodes: list[dict[str, Any]]) -> str:
    """Render the detection prompt for a cluster.

    ``nodes`` must be a list of dicts with keys ``id`` (str), ``content`` (str),
    and ``created_at`` (datetime or ISO 8601 string).
    """
    lines: list[str] = []
    for n in nodes:
        ts = n["created_at"]
        ts_str = ts.date().isoformat() if isinstance(ts, datetime) else str(ts)[:10]
        lines.append(f"- id={n['id']} created_at={ts_str}\n  content: {n['content']}")
    nodes_block = "\n".join(lines)
    return load_prompt(_SUPERSESSION_PROMPT_PATH, nodes_block=nodes_block)


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?\s*```\s*$", re.MULTILINE)


def parse_supersession_response(response: str) -> list[SupersessionPair]:
    """Parse the LLM response into a list of SupersessionPair.

    Returns [] on any parse failure. Strips markdown fences if present.
    Filters out entries missing required fields.
    """
    if not response or not response.strip():
        return []

    cleaned = _FENCE_RE.sub("", response).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, dict) or "supersessions" not in data:
        return []

    raw_list = data.get("supersessions")
    if not isinstance(raw_list, list):
        return []

    pairs: list[SupersessionPair] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        required = ("superseding_id", "superseded_id", "confidence", "reason")
        if not all(k in item for k in required):
            continue
        try:
            pairs.append(
                SupersessionPair(
                    superseding_id=str(item["superseding_id"]),
                    superseded_id=str(item["superseded_id"]),
                    confidence=float(item["confidence"]),
                    reason=str(item["reason"]),
                )
            )
        except (TypeError, ValueError):
            continue
    return pairs


__all__ = [
    "SupersessionPair",
    "build_supersession_prompt",
    "parse_supersession_response",
]
