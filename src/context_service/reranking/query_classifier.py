"""Hard query detection for semantic reranking."""

from __future__ import annotations

import re
import string

ABSTRACT_VERBS = frozenset(
    {
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
    }
)

# Question words that indicate value-seeking queries
QUESTION_WORDS = frozenset({"what", "where", "when", "how", "which", "who", "why", "true", "is", "are", "does", "do", "can", "should"})

# Patterns for specific hard query types
QUESTION_PATTERNS = [
    # Original patterns (kept for backwards compat)
    re.compile(r"^what (was|were|got|is|are) \w+\??$", re.IGNORECASE),
    re.compile(r"^why did .+\??$", re.IGNORECASE),
    re.compile(r"^(is|are|was|were) .+ (approved|rejected|denied)\??$", re.IGNORECASE),
    re.compile(r"^which .+ (was|were|got) \w+\??$", re.IGNORECASE),
    # Value-seeking questions (What was my X, What is the Y)
    re.compile(r"^what (was|were|is|are) (my|the|our) .+\??$", re.IGNORECASE),
    # "My" possessive queries (personal data recall)
    re.compile(r"^(my|our) .+\??$", re.IGNORECASE),
    # How many/much questions
    re.compile(r"^how (many|much|long|often|far) .+\??$", re.IGNORECASE),
    # When/where questions
    re.compile(r"^(when|where) (did|was|were|is|are|have|has) .+\??$", re.IGNORECASE),
]


def is_hard_query(query: str) -> bool:
    """Detect queries requiring semantic reasoning.

    Hard queries benefit from query expansion because the answer may be
    phrased differently than the question. Examples:
    - "What was my 5K time?" -> answer: "hoping to beat 25:50"
    - "Where is the config?" -> answer: "stored in ~/.config/app"

    Args:
        query: The search query.

    Returns:
        True if the query likely requires semantic reasoning beyond similarity.
    """
    if not query:
        return False

    query_lower = query.lower().strip()
    words = query_lower.split()

    # Any query containing "?" is a question - expand it
    if "?" in query:
        return True

    # "True or false" style questions
    if "true or false" in query_lower:
        return True

    # Short queries with abstract verbs
    if len(words) <= 5 and any(w.rstrip(string.punctuation) in ABSTRACT_VERBS for w in words):
        return True

    # Any question starting with question word is considered hard
    # (embedding search often fails when query is a question and answer is a statement)
    if words and words[0].rstrip(string.punctuation) in QUESTION_WORDS:
        return True

    # Specific patterns for complex hard queries
    return any(pattern.match(query_lower) for pattern in QUESTION_PATTERNS)
