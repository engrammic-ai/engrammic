"""Embedding classifier that maps free-form entity_type strings to TypeClass values.

Classification strategy (ordered, first match wins):
1. Exact match against centroid tokens.
2. Token-level substring match (e.g. "software_engineer" contains "engineer").
3. N-gram cosine similarity fallback; returns None when cosine < THRESHOLD.
"""

from __future__ import annotations

import json
import math
import re
from enum import StrEnum
from pathlib import Path

_CENTROID_PATH = Path(__file__).parent / "class_centroids.json"
_THRESHOLD = 0.15


class TypeClass(StrEnum):
    """Six coarse semantic classes used by the extraction type matrix."""

    AGENT = "Agent"
    ORGANIZATION = "Organization"
    ARTIFACT = "Artifact"
    CONCEPT = "Concept"
    EVENT = "Event"
    LOCATION = "Location"


def _load_centroids() -> dict[TypeClass, list[str]]:
    raw: dict[str, list[str]] = json.loads(_CENTROID_PATH.read_text())
    return {TypeClass(k): v for k, v in raw.items()}


def _tokenize(text: str) -> list[str]:
    """Lower-case and split on non-alphanumeric boundaries."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _char_ngrams(text: str, n: int = 3) -> dict[str, int]:
    padded = f"#{text}#"
    ngrams: dict[str, int] = {}
    for i in range(len(padded) - n + 1):
        gram = padded[i : i + n]
        ngrams[gram] = ngrams.get(gram, 0) + 1
    return ngrams


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * v for k, v in b.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class TypeClassifier:
    """Classifies free-form entity_type strings into :class:`TypeClass` values."""

    def __init__(self) -> None:
        self._centroids: dict[TypeClass, list[str]] = _load_centroids()
        # Pre-compute ngram vectors for each centroid token.
        self._centroid_ngrams: dict[TypeClass, list[dict[str, int]]] = {
            cls: [_char_ngrams(tok) for tok in tokens] for cls, tokens in self._centroids.items()
        }
        # Flat token set for exact and substring lookups.
        self._token_to_class: dict[str, TypeClass] = {
            tok: cls for cls, tokens in self._centroids.items() for tok in tokens
        }

    def classify(self, entity_type: str) -> TypeClass | None:
        """Return the :class:`TypeClass` for *entity_type*, or ``None`` if unclassifiable."""
        if not entity_type:
            return None

        normalized = entity_type.lower().strip()
        tokens = _tokenize(normalized)

        # 1. Exact match
        if normalized in self._token_to_class:
            return self._token_to_class[normalized]

        # 2. Token-level match: any token in entity_type matches a centroid token
        for tok in tokens:
            if tok in self._token_to_class:
                return self._token_to_class[tok]

        # 3. N-gram cosine similarity
        query_ngrams = _char_ngrams(normalized)
        best_class: TypeClass | None = None
        best_score = 0.0

        for cls, ngram_list in self._centroid_ngrams.items():
            for centroid_ngrams in ngram_list:
                score = _cosine(query_ngrams, centroid_ngrams)
                if score > best_score:
                    best_score = score
                    best_class = cls

        if best_score >= _THRESHOLD:
            return best_class
        return None

    def classify_batch(self, entity_types: list[str]) -> list[TypeClass | None]:
        """Classify a list of entity_type strings."""
        return [self.classify(t) for t in entity_types]
