"""Regex-based key sentence extraction for embedding quality."""
import re


def score_sentence(sent: str, position: float) -> float:
    """Score sentence 0-1 based on heuristics."""
    score = 0.0

    # Position: first/last sentences weighted higher
    score += 0.3 * (1 - abs(position - 0.5) * 2)

    # Cue phrases: "found", "key", "because", etc.
    if re.search(r'\b(found|discovered|key|important|actually|because)\b', sent, re.I):
        score += 0.25

    # Specificity: code, paths, numbers
    if re.search(r'`[^`]+`|/[\w/]+\.\w+|\d+', sent):
        score += 0.2

    # Entity density: capitalized words
    caps = len(re.findall(r'\b[A-Z][a-z]+\b', sent))
    score += min(0.15, caps * 0.05)

    # Length: 20-150 chars is sweet spot
    if 20 <= len(sent) <= 150:
        score += 0.1

    return score


def extract_key_sentences(content: str, budget: int = 512) -> str:
    """Extract highest-value sentences up to budget chars.

    Returns the original content if it's already under budget.
    """
    if len(content) <= budget:
        return content

    sentences = re.split(r'(?<=[.!?])\s+', content)
    if not sentences:
        return content[:budget]

    scored = [(s, score_sentence(s, i / len(sentences))) for i, s in enumerate(sentences)]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected: list[str] = []
    total = 0
    for sent, _ in scored:
        sep = 1 if selected else 0  # space added by ' '.join
        if total + sep + len(sent) <= budget:
            selected.append(sent)
            total += sep + len(sent)

    if not selected:
        # Fallback: take first sentence truncated
        return sentences[0][:budget]

    # Restore original order
    selected.sort(key=lambda s: content.index(s))
    return ' '.join(selected)
