# Wanderer Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 bugs discovered during codebase exploration: ID collision in revise/split, magnitude_pct always 0.0, and naive word overlap in belief merge.

**Architecture:** Three independent fixes in the belief/revision subsystem. Bug 1 and 2 are in `engine/revision.py`. Bug 3 replaces the word-based overlap detection in `pipelines/assets/belief_merge.py` with embedding cosine similarity computed in Python.

**Tech Stack:** Python, Memgraph (Cypher), pytest, existing `_cosine_distance` helper

**Spec:** `docs/superpowers/specs/2026-05-20-wanderer-bugfixes-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/context_service/engine/revision.py` | Modify | Bug 1: add operation param; Bug 2: add cosine_distance param |
| `src/context_service/pipelines/assets/cascade_review.py` | Modify | Bug 2: pass cosine_distance to revise_belief |
| `src/context_service/pipelines/assets/belief_merge.py` | Modify | Bug 3: replace word overlap with embedding similarity |
| `src/context_service/config/settings.py` | Modify | Bug 3: add belief_merge_threshold setting |
| `tests/unit/test_revision_id_collision.py` | Create | Bug 1: test ID uniqueness |
| `tests/unit/test_revision_magnitude.py` | Create | Bug 2: test magnitude_pct threading |
| `tests/unit/test_belief_merge_similarity.py` | Create | Bug 3: test embedding similarity detection |

---

## Task 1: Bug 1 - Fix ID Collision (Test)

**Files:**
- Create: `tests/unit/test_revision_id_collision.py`

- [ ] **Step 1: Write failing test for ID collision**

```python
"""Test that revision and split IDs never collide."""

from context_service.engine.revision import _make_revised_belief_id


def test_revision_and_split_ids_never_collide():
    """If belief revised once then split, all IDs must be unique."""
    belief_id = "test-belief-123"
    
    # Revision with count=1 (first revision)
    revision_id = _make_revised_belief_id(belief_id, 1, operation="revision")
    
    # Split children with indices 0, 1 -> counter 1, 2
    split_id_0 = _make_revised_belief_id(belief_id, 1, operation="split")
    split_id_1 = _make_revised_belief_id(belief_id, 2, operation="split")
    
    all_ids = [revision_id, split_id_0, split_id_1]
    assert len(all_ids) == len(set(all_ids)), f"ID collision detected: {all_ids}"


def test_make_revised_belief_id_deterministic():
    """Same inputs produce same output."""
    id1 = _make_revised_belief_id("belief-a", 5, operation="revision")
    id2 = _make_revised_belief_id("belief-a", 5, operation="revision")
    assert id1 == id2


def test_make_revised_belief_id_different_operations():
    """Different operations produce different IDs even with same counter."""
    revision = _make_revised_belief_id("belief-a", 1, operation="revision")
    split = _make_revised_belief_id("belief-a", 1, operation="split")
    assert revision != split
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_revision_id_collision.py -v`
Expected: FAIL with TypeError (operation parameter doesn't exist yet)

- [ ] **Step 3: Commit test**

```bash
git add tests/unit/test_revision_id_collision.py
git commit -m "test: add failing tests for revision/split ID collision"
```

---

## Task 2: Bug 1 - Fix ID Collision (Implementation)

**Files:**
- Modify: `src/context_service/engine/revision.py:169-173`

- [ ] **Step 1: Update `_make_revised_belief_id` signature**

Change from:
```python
def _make_revised_belief_id(old_belief_id: str, revision_count: int) -> str:
    """Deterministic id for the revised belief derived from its predecessor."""
    return hashlib.blake2b(
        f"revision:{old_belief_id}:{revision_count}".encode(), digest_size=32
    ).hexdigest()
```

To:
```python
def _make_revised_belief_id(
    old_belief_id: str,
    counter: int,
    operation: Literal["revision", "split"] = "revision",
) -> str:
    """Deterministic id for revised/split belief derived from its predecessor.
    
    Args:
        old_belief_id: Parent belief ID.
        counter: Revision count or split child index.
        operation: "revision" for revise_belief, "split" for split_belief.
    """
    return hashlib.blake2b(
        f"{operation}:{old_belief_id}:{counter}".encode(), digest_size=32
    ).hexdigest()
```

- [ ] **Step 2: Add Literal import at top of file**

Add to imports (around line 5):
```python
from typing import Literal
```

- [ ] **Step 3: Update `split_belief` call site (line 543)**

Change from:
```python
child_id = _make_revised_belief_id(belief_id, i + 1)
```

To:
```python
child_id = _make_revised_belief_id(belief_id, i + 1, operation="split")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_revision_id_collision.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/ -x -q --tb=short`
Expected: No new failures

- [ ] **Step 6: Commit implementation**

```bash
git add src/context_service/engine/revision.py
git commit -m "fix: prevent ID collision between revision and split operations

Add operation parameter to _make_revised_belief_id to namespace IDs.
Revision uses 'revision:' prefix, split uses 'split:' prefix.
Fixes silent data overwrite when belief is revised then split."
```

---

## Task 3: Bug 2 - Fix magnitude_pct (Test)

**Files:**
- Create: `tests/unit/test_revision_magnitude.py`

- [ ] **Step 1: Write failing test for magnitude_pct**

```python
"""Test that revise_belief correctly threads cosine_distance to auto-reflection."""

from unittest.mock import AsyncMock, patch

import pytest

from context_service.engine.revision import revise_belief


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[
        {
            "belief_id": "old-belief",
            "content": "Old belief content",
            "confidence": 0.9,
            "revision_count": 0,
        }
    ])
    store.transaction = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
    store.execute_write = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="New belief content from LLM")
    return llm


@pytest.fixture
def mock_embedding():
    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[[0.1] * 768])
    return embedding


@pytest.mark.asyncio
async def test_revise_belief_passes_cosine_distance_to_reflection(
    mock_store, mock_llm, mock_embedding
):
    """Verify cosine_distance is passed through to make_revision_content."""
    # Mock cluster query
    mock_store.execute_query.side_effect = [
        [{"belief_id": "old-belief", "content": "Old", "confidence": 0.9, "revision_count": 0}],
        [{"cluster_id": "cluster-1"}],
        [{"fact_id": "f1", "content": "Fact 1", "confidence": 0.95, "valid_from": "2026-01-01"}],
    ]
    
    with patch("context_service.engine.revision.create_auto_reflection") as mock_reflect, \
         patch("context_service.engine.revision.get_settings") as mock_settings, \
         patch("context_service.engine.revision.make_revision_content") as mock_content:
        
        settings = mock_settings.return_value
        settings.auto_reflect.enabled = True
        settings.auto_reflect.on_revision = True
        
        mock_content.return_value = "Belief revised with 15.0% drift"
        mock_reflect.return_value = None
        
        await revise_belief(
            store=mock_store,
            old_belief_id="old-belief",
            silo_id="test-silo",
            llm_client=mock_llm,
            embedding_client=mock_embedding,
            cosine_distance=0.15,
        )
        
        # Verify make_revision_content was called with correct magnitude
        mock_content.assert_called_once()
        call_kwargs = mock_content.call_args.kwargs
        assert call_kwargs["magnitude_pct"] == pytest.approx(15.0, rel=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_revision_magnitude.py -v`
Expected: FAIL with TypeError (cosine_distance parameter doesn't exist)

- [ ] **Step 3: Commit test**

```bash
git add tests/unit/test_revision_magnitude.py
git commit -m "test: add failing test for magnitude_pct in revise_belief"
```

---

## Task 4: Bug 2 - Fix magnitude_pct (Implementation)

**Files:**
- Modify: `src/context_service/engine/revision.py:301-307, 442`
- Modify: `src/context_service/pipelines/assets/cascade_review.py:63`

- [ ] **Step 1: Update `revise_belief` signature**

Change line 301-307 from:
```python
async def revise_belief(
    store: HyperGraphStore,
    old_belief_id: str,
    silo_id: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService,
) -> str:
```

To:
```python
async def revise_belief(
    store: HyperGraphStore,
    old_belief_id: str,
    silo_id: str,
    llm_client: LLMProvider,
    embedding_client: EmbeddingService,
    cosine_distance: float = 0.0,
) -> str:
```

- [ ] **Step 2: Update magnitude_pct calculation**

Change line 442 from:
```python
        magnitude_pct = 0.0
```

To:
```python
        magnitude_pct = cosine_distance * 100.0
```

- [ ] **Step 3: Update cascade_review.py to pass cosine_distance**

Change line 63 from:
```python
                    await revise_belief(store, belief_id, silo_id, llm_client, embedding_client)
```

To:
```python
                    await revise_belief(
                        store, belief_id, silo_id, llm_client, embedding_client,
                        cosine_distance=result.cosine_distance,
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_revision_magnitude.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/ -x -q --tb=short`
Expected: No new failures

- [ ] **Step 6: Commit implementation**

```bash
git add src/context_service/engine/revision.py src/context_service/pipelines/assets/cascade_review.py
git commit -m "fix: thread cosine_distance through revise_belief to auto-reflection

Add cosine_distance parameter to revise_belief(). Caller passes value from
check_belief_revision result. magnitude_pct now shows actual drift percentage
instead of hardcoded 0.0."
```

---

## Task 5: Bug 3 - Add belief_merge_threshold Setting

**Files:**
- Modify: `src/context_service/config/settings.py:87-98`

- [ ] **Step 1: Add belief_merge_threshold to SynthesizerIdentityConfig**

After line 96 (`min_facts_for_synthesis: int = 3`), add:
```python
    belief_merge_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity between belief embeddings to consider merge",
    )
    belief_merge_max_pairs: int = Field(
        default=50,
        description="Maximum belief pairs to process per merge run",
    )
```

- [ ] **Step 2: Run typecheck**

Run: `uv run mypy src/context_service/config/settings.py --no-error-summary`
Expected: No errors

- [ ] **Step 3: Commit setting**

```bash
git add src/context_service/config/settings.py
git commit -m "feat: add belief_merge_similarity_threshold and max_pairs settings"
```

---

## Task 6: Bug 3 - Fix Word Overlap (Test)

**Files:**
- Create: `tests/unit/test_belief_merge_similarity.py`

- [ ] **Step 1: Write test for cosine similarity helper**

```python
"""Test embedding-based belief overlap detection."""

import math

import pytest


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_overlapping_pairs(
    beliefs: list[dict],
    threshold: float = 0.85,
    max_pairs: int = 50,
) -> list[tuple[str, str, float]]:
    """Return (belief1_id, belief2_id, similarity) for pairs above threshold."""
    from itertools import combinations
    
    pairs: list[tuple[str, str, float]] = []
    for b1, b2 in combinations(beliefs, 2):
        sim = cosine_similarity(b1["embedding"], b2["embedding"])
        if sim >= threshold:
            pairs.append((b1["belief_id"], b2["belief_id"], sim))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:max_pairs]


def test_cosine_similarity_identical_vectors():
    """Identical vectors have similarity 1.0."""
    vec = [0.5, 0.5, 0.5]
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    """Orthogonal vectors have similarity 0.0."""
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    """Opposite vectors have similarity -1.0."""
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_find_overlapping_pairs_above_threshold():
    """Pairs above threshold are returned."""
    beliefs = [
        {"belief_id": "b1", "embedding": [1.0, 0.0, 0.0]},
        {"belief_id": "b2", "embedding": [0.99, 0.1, 0.0]},  # Similar to b1
        {"belief_id": "b3", "embedding": [0.0, 1.0, 0.0]},  # Orthogonal to b1
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.9)
    
    assert len(pairs) == 1
    assert pairs[0][0] == "b1"
    assert pairs[0][1] == "b2"
    assert pairs[0][2] > 0.9


def test_find_overlapping_pairs_respects_max():
    """Max pairs limit is respected."""
    # Create 5 nearly identical beliefs
    beliefs = [
        {"belief_id": f"b{i}", "embedding": [1.0, 0.01 * i, 0.0]}
        for i in range(5)
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.9, max_pairs=3)
    
    assert len(pairs) == 3


def test_find_overlapping_pairs_sorted_by_similarity():
    """Results are sorted by similarity descending."""
    beliefs = [
        {"belief_id": "b1", "embedding": [1.0, 0.0, 0.0]},
        {"belief_id": "b2", "embedding": [0.9, 0.1, 0.0]},
        {"belief_id": "b3", "embedding": [0.95, 0.05, 0.0]},
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.8)
    
    # b1-b3 should be first (higher similarity than b1-b2)
    assert pairs[0][2] >= pairs[1][2]
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_belief_merge_similarity.py -v`
Expected: PASS (tests use local implementations)

- [ ] **Step 3: Commit test**

```bash
git add tests/unit/test_belief_merge_similarity.py
git commit -m "test: add tests for embedding-based belief overlap detection"
```

---

## Task 7: Bug 3 - Fix Word Overlap (Implementation)

**Files:**
- Modify: `src/context_service/pipelines/assets/belief_merge.py`

- [ ] **Step 1: Replace `_LIST_OVERLAP_SUBJECTS` query**

Replace lines 13-23:
```python
_LIST_OVERLAP_SUBJECTS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.status IS NULL OR b.status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH subject, count(b) AS belief_count
WHERE belief_count >= 2
RETURN subject, belief_count
ORDER BY belief_count DESC
LIMIT $max_subjects
"""

_MAX_SUBJECTS_PER_RUN = 30
```

With:
```python
_FETCH_BELIEFS_WITH_EMBEDDINGS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE (b.status IS NULL OR b.status <> 'stale')
  AND b.centroid_embedding IS NOT NULL
RETURN b.id AS belief_id, b.content AS content, b.centroid_embedding AS embedding
"""
```

- [ ] **Step 2: Add cosine_similarity and find_overlapping_pairs helpers**

Add after imports (around line 12):
```python
import math
from itertools import combinations

from context_service.config.settings import get_settings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_overlapping_pairs(
    beliefs: list[dict[str, Any]],
    threshold: float,
    max_pairs: int,
) -> list[tuple[str, str, float]]:
    """Return (belief1_id, belief2_id, similarity) for pairs above threshold."""
    pairs: list[tuple[str, str, float]] = []
    for b1, b2 in combinations(beliefs, 2):
        sim = _cosine_similarity(b1["embedding"], b2["embedding"])
        if sim >= threshold:
            pairs.append((str(b1["belief_id"]), str(b2["belief_id"]), sim))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:max_pairs]
```

- [ ] **Step 3: Update the asset function**

Replace the `_run` function (lines 47-99) with:
```python
    async def _run() -> dict[str, Any]:
        from context_service.engine.synthesis import merge_beliefs
        from context_service.stores import MemgraphClient

        settings = get_settings()
        threshold = settings.synthesizer.belief_merge_similarity_threshold
        max_pairs = settings.synthesizer.belief_merge_max_pairs

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()
        llm_client = llm.get_client()

        rows = await client.execute_query(
            _FETCH_BELIEFS_WITH_EMBEDDINGS,
            {"silo_id": silo_id},
        )

        beliefs = [
            {
                "belief_id": str(r["belief_id"]),
                "content": str(r["content"]),
                "embedding": list(r["embedding"]),
            }
            for r in rows
            if r.get("embedding")
        ]

        if len(beliefs) < 2:
            context.log.info(f"belief_merge: fewer than 2 beliefs with embeddings for silo={silo_id}")
            return {"merged_count": 0, "skipped_count": 0, "total": 0, "merged_ids": []}

        pairs = _find_overlapping_pairs(beliefs, threshold, max_pairs)

        if not pairs:
            context.log.info(f"belief_merge: no overlapping pairs above threshold={threshold} for silo={silo_id}")
            return {"merged_count": 0, "skipped_count": 0, "total": 0, "merged_ids": []}

        context.log.info(f"belief_merge: processing {len(pairs)} overlapping pairs for silo={silo_id}")

        merged_count = 0
        skipped_count = 0
        merged_ids: list[str] = []

        for belief1_id, belief2_id, similarity in pairs:
            try:
                merged_id = await merge_beliefs(store, silo_id, [belief1_id, belief2_id], llm_client)
                merged_ids.append(merged_id)
                merged_count += 1
                context.log.info(
                    f"beliefs_merged pair=({belief1_id}, {belief2_id}) similarity={similarity:.3f} "
                    f"merged_belief={merged_id}"
                )
            except Exception as e:
                context.log.error(f"belief_merge failed pair=({belief1_id}, {belief2_id}) error={e}")
                skipped_count += 1

        return {
            "merged_count": merged_count,
            "skipped_count": skipped_count,
            "total": len(pairs),
            "merged_ids": merged_ids,
        }
```

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/context_service/pipelines/assets/belief_merge.py --no-error-summary`
Expected: No errors

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_belief_merge_similarity.py tests/ -x -q --tb=short -k "belief"` 
Expected: PASS

- [ ] **Step 6: Commit implementation**

```bash
git add src/context_service/pipelines/assets/belief_merge.py
git commit -m "fix: replace word overlap with embedding cosine similarity

Remove naive word-based overlap detection that triggered false positives
on common words. Now uses centroid_embedding cosine similarity with
configurable threshold (default 0.85).

Pairs below threshold are not considered for merge.
Beliefs without embeddings are skipped gracefully."
```

---

## Task 8: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2: Run type check**

Run: `just check`
Expected: No errors

- [ ] **Step 3: Run audit query for existing collisions**

Note: Run this after deployment to check for historical data issues:
```cypher
MATCH (b:Belief)-[r:REVISED_FROM]->(parent:Belief)
WHERE b.id = parent.id
RETURN b.id, b.silo_id, b.created_at
```

- [ ] **Step 4: Create PR**

```bash
git push -u origin HEAD
gh pr create --title "fix: wanderer-discovered bugs in belief/revision" --body "$(cat <<'EOF'
## Summary
- Fix ID collision between revision and split operations
- Thread cosine_distance through revise_belief to auto-reflection
- Replace word overlap with embedding cosine similarity in belief_merge

## Test plan
- [x] Unit tests for ID collision
- [x] Unit tests for magnitude_pct threading
- [x] Unit tests for embedding similarity
- [x] Full test suite passes
- [ ] Run audit query after deploy to check for historical collisions

Spec: docs/superpowers/specs/2026-05-20-wanderer-bugfixes-design.md
EOF
)"
```
