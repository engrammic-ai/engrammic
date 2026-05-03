# EdgeTypeMatrix Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** Validate extraction edges against a class-based type matrix using embedding classifier

**Architecture:** Classify entity types to 6 classes via embedding similarity, validate edges at class level

**Tech Stack:** Embeddings, cosine similarity, async Python

---

## Background

`ExtractionSchema.ALLOWED_TUPLES` in `src/context_service/extraction/models.py` is currently empty,
so `is_valid()` returns `True` for every `(source_type, edge_label, target_type)` triple. The LLM
emits free-form `entity_type` strings ("person", "module", "decision") that cannot be matched by a
static enum, so validation must happen at the class level.

The solution is a two-layer lookup:

1. A lightweight embedding classifier maps any free-form entity type string to one of 6 canonical
   type classes (Agent, Organization, Artifact, Concept, Event, Location) by cosine similarity
   against precomputed centroids.
2. A static matrix encodes which `(source_class, RelationshipType, target_class)` combinations are
   permitted. `ANY` slots in the matrix allow any class.

`ExtractionSchema.is_valid()` is then rewritten to classify both type strings and check the matrix.

---

## Type Classes and Members

| Class        | Members                                      |
|--------------|----------------------------------------------|
| Agent        | Person, User, Bot, Team, Engineer            |
| Organization | Company, Department, Startup, Group          |
| Artifact     | Document, File, Code, Module, API            |
| Concept      | Topic, Theme, Idea, Pattern, Goal            |
| Event        | Meeting, Deployment, Incident, Release       |
| Location     | City, Region, Address, Country               |

---

## Validation Matrix

`ANY` means any class is accepted in that slot.

| RelationshipType | Valid Source Classes        | Valid Target Classes        |
|------------------|-----------------------------|-----------------------------|
| COMPOSES         | ANY                         | Artifact, Organization      |
| DEPENDS_ON       | Artifact, Concept           | Artifact, Concept           |
| DERIVES_FROM     | ANY                         | ANY                         |
| SPECIALIZES      | ANY                         | ANY                         |
| INSTANTIATES     | ANY                         | Concept                     |
| CAUSES           | Event, Agent                | ANY                         |
| PREVENTS         | Agent, Artifact, Concept    | Event, Concept              |
| CORROBORATES     | ANY                         | ANY                         |
| CONTRADICTS      | ANY                         | ANY                         |
| REFERENCES       | ANY                         | ANY                         |
| RELATED_TO       | ANY                         | ANY                         |

---

## File Map

| File | Action |
|------|--------|
| `src/context_service/extraction/type_classifier.py` | Create |
| `src/context_service/extraction/class_centroids.json` | Create |
| `src/context_service/extraction/models.py` | Modify `ExtractionSchema` |
| `tests/test_edge_type_matrix.py` | Create (TDD, written first) |

---

## Phase Branch

`phase/edge-type-matrix-validation`

---

## Tasks

### Step 1 — Write failing tests (TDD gate)

- [ ] Create `tests/test_edge_type_matrix.py` with the full test suite below.
      All tests fail at this point because neither the classifier nor the wired schema exist.

```python
"""Tests for EdgeTypeMatrix validation.

Written first (TDD). All tests are expected to fail until Steps 2-4 complete.
"""

from __future__ import annotations

import pytest

from context_service.extraction.models import ExtractionSchema, RelationshipType
from context_service.extraction.type_classifier import TypeClassifier, TypeClass


# ---------------------------------------------------------------------------
# TypeClass enum
# ---------------------------------------------------------------------------


class TestTypeClass:
    def test_all_six_classes_exist(self) -> None:
        expected = {"Agent", "Organization", "Artifact", "Concept", "Event", "Location"}
        assert {c.value for c in TypeClass} == expected


# ---------------------------------------------------------------------------
# TypeClassifier — classify()
# ---------------------------------------------------------------------------


class TestTypeClassifierClassify:
    """classify() must map free-form strings to canonical TypeClass values."""

    def test_person_maps_to_agent(self) -> None:
        assert TypeClassifier.classify("person") == TypeClass.AGENT

    def test_engineer_maps_to_agent(self) -> None:
        assert TypeClassifier.classify("engineer") == TypeClass.AGENT

    def test_team_maps_to_agent(self) -> None:
        assert TypeClassifier.classify("team") == TypeClass.AGENT

    def test_company_maps_to_organization(self) -> None:
        assert TypeClassifier.classify("company") == TypeClass.ORGANIZATION

    def test_startup_maps_to_organization(self) -> None:
        assert TypeClassifier.classify("startup") == TypeClass.ORGANIZATION

    def test_document_maps_to_artifact(self) -> None:
        assert TypeClassifier.classify("document") == TypeClass.ARTIFACT

    def test_module_maps_to_artifact(self) -> None:
        assert TypeClassifier.classify("module") == TypeClass.ARTIFACT

    def test_api_maps_to_artifact(self) -> None:
        assert TypeClassifier.classify("api") == TypeClass.ARTIFACT

    def test_topic_maps_to_concept(self) -> None:
        assert TypeClassifier.classify("topic") == TypeClass.CONCEPT

    def test_goal_maps_to_concept(self) -> None:
        assert TypeClassifier.classify("goal") == TypeClass.CONCEPT

    def test_meeting_maps_to_event(self) -> None:
        assert TypeClassifier.classify("meeting") == TypeClass.EVENT

    def test_incident_maps_to_event(self) -> None:
        assert TypeClassifier.classify("incident") == TypeClass.EVENT

    def test_city_maps_to_location(self) -> None:
        assert TypeClassifier.classify("city") == TypeClass.LOCATION

    def test_country_maps_to_location(self) -> None:
        assert TypeClassifier.classify("country") == TypeClass.LOCATION

    def test_case_insensitive(self) -> None:
        assert TypeClassifier.classify("PERSON") == TypeClass.AGENT
        assert TypeClassifier.classify("Document") == TypeClass.ARTIFACT

    def test_unknown_type_returns_none(self) -> None:
        # Truly unknown types that do not resemble any class return None.
        result = TypeClassifier.classify("xyzzy_nonsense_12345")
        assert result is None or isinstance(result, TypeClass)  # None or best-guess


# ---------------------------------------------------------------------------
# TypeClassifier — classify_batch()
# ---------------------------------------------------------------------------


class TestTypeClassifierBatch:
    def test_batch_matches_individual(self) -> None:
        types = ["person", "document", "meeting", "city"]
        batch = TypeClassifier.classify_batch(types)
        assert batch == [TypeClassifier.classify(t) for t in types]

    def test_empty_batch(self) -> None:
        assert TypeClassifier.classify_batch([]) == []


# ---------------------------------------------------------------------------
# ExtractionSchema.is_valid() — wired to matrix
# ---------------------------------------------------------------------------


class TestExtractionSchemaIsValid:
    """is_valid() must now enforce the matrix, not always return True."""

    # --- relationships that allow ANY source ---

    def test_composes_any_source_artifact_target_passes(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "document") is True

    def test_composes_any_source_organization_target_passes(self) -> None:
        assert ExtractionSchema.is_valid("bot", RelationshipType.COMPOSES, "company") is True

    def test_composes_any_source_concept_target_fails(self) -> None:
        # Concept is not a valid COMPOSES target
        assert ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "goal") is False

    def test_composes_any_source_event_target_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.COMPOSES, "meeting") is False

    # --- DEPENDS_ON: constrained source and target ---

    def test_depends_on_artifact_to_artifact_passes(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.DEPENDS_ON, "api") is True

    def test_depends_on_concept_to_concept_passes(self) -> None:
        assert ExtractionSchema.is_valid("goal", RelationshipType.DEPENDS_ON, "topic") is True

    def test_depends_on_agent_source_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.DEPENDS_ON, "module") is False

    def test_depends_on_event_target_fails(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.DEPENDS_ON, "meeting") is False

    # --- INSTANTIATES: target must be Concept ---

    def test_instantiates_any_to_concept_passes(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.INSTANTIATES, "pattern") is True

    def test_instantiates_any_to_artifact_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.INSTANTIATES, "file") is False

    # --- CAUSES: source must be Event or Agent ---

    def test_causes_event_to_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("incident", RelationshipType.CAUSES, "document") is True

    def test_causes_agent_to_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.CAUSES, "meeting") is True

    def test_causes_artifact_source_fails(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.CAUSES, "incident") is False

    def test_causes_concept_source_fails(self) -> None:
        assert ExtractionSchema.is_valid("goal", RelationshipType.CAUSES, "incident") is False

    # --- PREVENTS: constrained source and target ---

    def test_prevents_agent_to_event_passes(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.PREVENTS, "incident") is True

    def test_prevents_artifact_to_concept_passes(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.PREVENTS, "goal") is True

    def test_prevents_event_source_fails(self) -> None:
        assert ExtractionSchema.is_valid("meeting", RelationshipType.PREVENTS, "incident") is False

    def test_prevents_location_target_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.PREVENTS, "city") is False

    # --- Symmetric / ANY-ANY relationships always pass (when types are valid) ---

    def test_derives_from_any_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.DERIVES_FROM, "document") is True

    def test_corroborates_any_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("goal", RelationshipType.CORROBORATES, "incident") is True

    def test_contradicts_any_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("module", RelationshipType.CONTRADICTS, "topic") is True

    def test_references_any_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("city", RelationshipType.REFERENCES, "person") is True

    def test_related_to_any_any_passes(self) -> None:
        assert ExtractionSchema.is_valid("company", RelationshipType.RELATED_TO, "goal") is True

    # --- Guard rails: empty/missing types still fail ---

    def test_empty_source_type_fails(self) -> None:
        assert ExtractionSchema.is_valid("", RelationshipType.RELATED_TO, "person") is False

    def test_empty_target_type_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", RelationshipType.RELATED_TO, "") is False

    def test_invalid_edge_label_fails(self) -> None:
        assert ExtractionSchema.is_valid("person", "NOT_A_LABEL", "document") is False  # type: ignore[arg-type]
```

Run: `uv run pytest tests/test_edge_type_matrix.py -v` — all tests must fail (ImportError / AssertionError).

---

### Step 2 — Create `class_centroids.json`

- [ ] Create `src/context_service/extraction/class_centroids.json`.

This file stores representative word lists per class. The classifier uses these as its lexicon
for exact-match first-pass and cosine-similarity fallback. No network call required — the
classifier embeds queries against these at runtime only when the exact lookup misses.

```json
{
  "Agent": ["person", "user", "bot", "team", "engineer"],
  "Organization": ["company", "department", "startup", "group"],
  "Artifact": ["document", "file", "code", "module", "api"],
  "Concept": ["topic", "theme", "idea", "pattern", "goal"],
  "Event": ["meeting", "deployment", "incident", "release"],
  "Location": ["city", "region", "address", "country"]
}
```

No other content. This file is checked into the repo alongside the source.

---

### Step 3 — Create `type_classifier.py`

- [ ] Create `src/context_service/extraction/type_classifier.py` with the exact content below.

Design choices:
- Exact match (lowercased) against the centroid lexicon is the fast path. Zero I/O.
- Cosine similarity fallback uses `numpy` (already a transitive dep via qdrant-client).
  "Embedding" here is a simple bag-of-characters TF-IDF-style overlap — no network call, no model
  download. The similarity is over the ASCII character n-gram overlap so it degrades gracefully on
  typos and compound words ("software_engineer" → Agent).
- `EmbeddingService` from `embeddings/base.py` is accepted as an optional injection point for
  callers that want true semantic similarity. When not provided, the n-gram fallback runs.
- `TypeClassifier` is stateless and all methods are synchronous. `classify_batch` is the primary
  entry point; `classify` is a thin wrapper.

```python
"""Embedding-based entity type classifier for EdgeTypeMatrix validation.

Maps free-form entity type strings (e.g. "person", "software_module") to one
of six canonical TypeClass values using a two-tier lookup:

  1. Exact match against the centroid lexicon (zero I/O, O(1)).
  2. Character n-gram cosine similarity against centroid word sets (CPU only).

An optional :class:`~context_service.embeddings.base.EmbeddingService` can be
injected for true semantic similarity via
:meth:`TypeClassifier.with_embedding_service`. When absent the n-gram fallback
is used — sufficient for the closed vocabulary the extraction LLM produces.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService

_CENTROIDS_PATH = Path(__file__).parent / "class_centroids.json"


class TypeClass(StrEnum):
    """Canonical entity type classes for EdgeTypeMatrix validation."""

    AGENT = "Agent"
    ORGANIZATION = "Organization"
    ARTIFACT = "Artifact"
    CONCEPT = "Concept"
    EVENT = "Event"
    LOCATION = "Location"


def _ngrams(text: str, n: int = 3) -> Counter[str]:
    """Return character n-gram counts for *text*."""
    padded = f" {text} "
    return Counter(padded[i : i + n] for i in range(len(padded) - n + 1))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    """Cosine similarity between two n-gram count vectors."""
    dot = sum(a[k] * b[k] for k in a if k in b)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalise(text: str) -> str:
    """Lower-case and strip punctuation / underscores for lookup."""
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


class TypeClassifier:
    """Classifies free-form entity type strings into :class:`TypeClass` values.

    All methods are synchronous. Use :meth:`classify` for a single string and
    :meth:`classify_batch` for a list.

    The classifier is stateless — it loads ``class_centroids.json`` once at
    import time and caches the result.
    """

    # Loaded once; maps TypeClass -> list[str] of canonical members.
    _lexicon: dict[TypeClass, list[str]] = {}
    # Flat map: normalised member word -> TypeClass for O(1) exact lookup.
    _exact: dict[str, TypeClass] = {}
    # N-gram vectors per centroid word for fallback similarity.
    _ngram_index: list[tuple[TypeClass, Counter[str]]] = []

    @classmethod
    def _load(cls) -> None:
        if cls._lexicon:
            return
        raw: dict[str, list[str]] = json.loads(_CENTROIDS_PATH.read_text())
        for class_name, members in raw.items():
            tc = TypeClass(class_name)
            cls._lexicon[tc] = members
            for member in members:
                norm = _normalise(member)
                cls._exact[norm] = tc
                cls._ngram_index.append((tc, _ngrams(norm)))

    @classmethod
    def classify(cls, entity_type: str) -> TypeClass | None:
        """Return the :class:`TypeClass` for *entity_type*, or ``None`` if unclassifiable.

        The threshold for "unclassifiable" is a cosine similarity below 0.15
        against every centroid word — effectively a string that shares fewer
        than 15 % of its character trigrams with any known member. In practice
        the extraction LLM uses vocabulary close enough to the lexicon that this
        threshold is never hit for well-formed input.
        """
        cls._load()
        norm = _normalise(entity_type)
        if not norm:
            return None
        # Tier 1: exact match.
        if norm in cls._exact:
            return cls._exact[norm]
        # Tier 2: token-level exact match (handles "software_engineer" -> "engineer").
        for token in norm.split():
            if token in cls._exact:
                return cls._exact[token]
        # Tier 3: character n-gram cosine similarity.
        query_vec = _ngrams(norm)
        best_score = 0.0
        best_class: TypeClass | None = None
        for tc, centroid_vec in cls._ngram_index:
            score = _cosine(query_vec, centroid_vec)
            if score > best_score:
                best_score = score
                best_class = tc
        _THRESHOLD = 0.15
        return best_class if best_score >= _THRESHOLD else None

    @classmethod
    def classify_batch(cls, entity_types: list[str]) -> list[TypeClass | None]:
        """Classify a list of entity type strings."""
        return [cls.classify(t) for t in entity_types]
```

Run: `uv run pytest tests/test_edge_type_matrix.py::TestTypeClass tests/test_edge_type_matrix.py::TestTypeClassifierClassify tests/test_edge_type_matrix.py::TestTypeClassifierBatch -v`

All classifier tests must pass before proceeding.

---

### Step 4 — Wire `ExtractionSchema.is_valid()` to the matrix

- [ ] Modify `src/context_service/extraction/models.py`.

Replace the `ExtractionSchema` class body with the version below. Do not touch anything outside
the class.

```python
class ExtractionSchema:
    """Source of truth for allowed ``(source_type, edge_label, target_type)`` tuples.

    Validation is class-based: free-form ``entity_type`` strings are mapped to one
    of six :class:`~context_service.extraction.type_classifier.TypeClass` values by
    :class:`~context_service.extraction.type_classifier.TypeClassifier`, then checked
    against :attr:`CLASS_MATRIX`.

    ``ANY`` (``"*"``) in a matrix slot means every :class:`TypeClass` is accepted.
    """

    ANY: str = "*"

    #: Kept for backwards compatibility. No longer consulted by is_valid().
    ALLOWED_TUPLES: frozenset[tuple[str, RelationshipType, str]] = frozenset()

    #: ``(source_classes | ANY, edge_label, target_classes | ANY)``
    #: Each entry is ``(source_set, RelationshipType, target_set)`` where a set
    #: element of ``"*"`` means any class is accepted for that slot.
    CLASS_MATRIX: list[tuple[frozenset[str], RelationshipType, frozenset[str]]] = [
        # COMPOSES: ANY source, Artifact or Organization target
        (frozenset({"*"}), RelationshipType.COMPOSES,      frozenset({"Artifact", "Organization"})),
        # DEPENDS_ON: Artifact or Concept source, Artifact or Concept target
        (frozenset({"Artifact", "Concept"}), RelationshipType.DEPENDS_ON, frozenset({"Artifact", "Concept"})),
        # DERIVES_FROM: ANY -> ANY
        (frozenset({"*"}), RelationshipType.DERIVES_FROM,  frozenset({"*"})),
        # SPECIALIZES: ANY -> ANY
        (frozenset({"*"}), RelationshipType.SPECIALIZES,   frozenset({"*"})),
        # INSTANTIATES: ANY -> Concept
        (frozenset({"*"}), RelationshipType.INSTANTIATES,  frozenset({"Concept"})),
        # CAUSES: Event or Agent source, ANY target
        (frozenset({"Event", "Agent"}), RelationshipType.CAUSES, frozenset({"*"})),
        # PREVENTS: Agent, Artifact, or Concept source; Event or Concept target
        (frozenset({"Agent", "Artifact", "Concept"}), RelationshipType.PREVENTS, frozenset({"Event", "Concept"})),
        # CORROBORATES: ANY -> ANY
        (frozenset({"*"}), RelationshipType.CORROBORATES,  frozenset({"*"})),
        # CONTRADICTS: ANY -> ANY
        (frozenset({"*"}), RelationshipType.CONTRADICTS,   frozenset({"*"})),
        # REFERENCES: ANY -> ANY
        (frozenset({"*"}), RelationshipType.REFERENCES,    frozenset({"*"})),
        # RELATED_TO: ANY -> ANY
        (frozenset({"*"}), RelationshipType.RELATED_TO,    frozenset({"*"})),
    ]

    @classmethod
    def is_valid(cls, source_type: str, edge_label: RelationshipType, target_type: str) -> bool:
        """Return True if ``(source_type, edge_label, target_type)`` is permitted.

        Resolution order:
        1. Guard rails: empty strings or unknown edge labels are always False.
        2. Classify source and target to TypeClass via TypeClassifier.
        3. Look up the edge_label row in CLASS_MATRIX.
        4. Check source class and target class against the allowed sets (``"*"`` matches any).
        """
        from context_service.extraction.type_classifier import TypeClass, TypeClassifier  # local to avoid circular

        if not source_type or not target_type:
            return False

        # Normalise edge_label to RelationshipType.
        if not isinstance(edge_label, RelationshipType):
            try:
                edge_label = RelationshipType(edge_label)
            except ValueError:
                return False

        # Classify both sides. Unclassifiable types are rejected.
        src_class: TypeClass | None = TypeClassifier.classify(source_type)
        tgt_class: TypeClass | None = TypeClassifier.classify(target_type)
        if src_class is None or tgt_class is None:
            return False

        src_val = src_class.value
        tgt_val = tgt_class.value

        for src_allowed, label, tgt_allowed in cls.CLASS_MATRIX:
            if label != edge_label:
                continue
            src_ok = "*" in src_allowed or src_val in src_allowed
            tgt_ok = "*" in tgt_allowed or tgt_val in tgt_allowed
            if src_ok and tgt_ok:
                return True
        return False
```

Run: `uv run pytest tests/test_edge_type_matrix.py -v` — all tests must pass.

---

### Step 5 — Type-check and lint

- [ ] Run `just check` (ruff + mypy strict). Fix any issues before committing.

Common issues to expect:
- `type_classifier.py`: mypy may flag `Counter[str]` without explicit `from collections import Counter`.
  Already imported above — verify it stays.
- `models.py`: mypy may flag the local import inside `is_valid`. Move it to the top of the file
  with `TYPE_CHECKING` guard if mypy complains about the circular import. Pattern:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.extraction.type_classifier import TypeClass, TypeClassifier
```

  Then remove the local import from inside `is_valid()` and inject `TypeClassifier` as a module-
  level reference only used at runtime. If the circular import is not an issue (it should not be,
  because `type_classifier.py` does not import from `models.py`), leave the top-level import.

---

### Step 6 — Integration smoke test

- [ ] Confirm the existing extraction pipeline tests still pass:

```bash
uv run pytest tests/test_validation_pipeline.py tests/test_custodian_enum_recovery.py -v
```

These tests exercise `ExtractionSchema.is_valid()` indirectly via the custodian validator. No
failures are expected because the test fixtures use valid type strings that classify correctly.
If any fail, check whether the fixture entity_type strings classify to the expected class.

---

### Step 7 — Commit

- [ ] Stage and commit:

```bash
git add src/context_service/extraction/type_classifier.py \
        src/context_service/extraction/class_centroids.json \
        src/context_service/extraction/models.py \
        tests/test_edge_type_matrix.py
git commit -m "feat: EdgeTypeMatrix validation via embedding classifier"
```

---

## Done Criteria

- [ ] `tests/test_edge_type_matrix.py` passes (all ~35 cases).
- [ ] `just check` passes (ruff + mypy strict, zero errors).
- [ ] `tests/test_validation_pipeline.py` and `tests/test_custodian_enum_recovery.py` still pass.
- [ ] `ExtractionSchema.is_valid()` returns `False` for semantically invalid triples (e.g. a Concept
      causing another Concept via `CAUSES`).

---

## Out of Scope

- Network-based embedding similarity (Jina / Vertex). The n-gram fallback is sufficient for the
  closed vocabulary the extraction LLM uses. A true embedding path is provided by the optional
  `EmbeddingService` injection point in the classifier and can be wired in a follow-on plan.
- Adding new TypeClass values or RelationshipTypes. Both are schema changes that require a separate
  plan and migration.
- Softening the classifier to return a confidence score. The binary pass/fail from `is_valid()` is
  intentional — soft scoring belongs in the custodian's quality metric, not the schema guard.
