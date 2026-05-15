"""Hard query detection for semantic reranking."""

from __future__ import annotations

import re
import string

ABSTRACT_VERBS = frozenset({
    "rejected",
    "approved",
    "denied",
    "accepted",
    "failed",
    "succeeded",
    "postponed",
    "cancelled",
    "confirmed",
    "dismissed",
    "granted",
    "abandoned",
    "dropped",
    "removed",
    "added",
    "changed",
    "decided",
})

QUESTION_PATTERNS = [
    re.compile(r"^what (was|were|got|is|are) \w+\??$", re.IGNORECASE),
    re.compile(r"^why did .+\??$", re.IGNORECASE),
    re.compile(r"^(is|are|was|were) .+ (approved|rejected|denied)\??$", re.IGNORECASE),
    re.compile(r"^which .+ (was|were|got) \w+\??$", re.IGNORECASE),
]


def is_hard_query(query: str) -> bool:
    """Detect queries requiring semantic reasoning.

    Args:
        query: The search query.

    Returns:
        True if the query likely requires semantic reasoning beyond similarity.
    """
    if not query:
        return False

    query_lower = query.lower().strip()
    words = query_lower.split()

    # Short queries with abstract verbs
    if len(words) <= 5 and any(w.rstrip(string.punctuation) in ABSTRACT_VERBS for w in words):
        return True

    # Question patterns that need inference
    return any(pattern.match(query_lower) for pattern in QUESTION_PATTERNS)
