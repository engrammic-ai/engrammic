# Phase 5: Layer Movement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement TX18 PROMOTE and TX19 DEMOTE in the sage layer for Claim/Fact layer movement.

**Architecture:** Extend `sage/transactions.py` with promotion/demotion transactions. TX18 promotes Claims to Facts when corroboration threshold is met; TX19 demotes Facts back to Claims when evidence is withdrawn.

**Tech Stack:** Python 3.12, Memgraph (Cypher), AsyncMock for testing, pytest

**Spec Reference:** `context/specs/brain-transactions-pseudocode.md` lines 1378-1495

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/sage/transactions.py` | Add PromoteResult, DemoteResult dataclasses; tx18_promote, tx19_demote functions |
| `src/context_service/db/queries.py` | Add GET_CLAIM_FOR_PROMOTE, PROMOTE_CLAIM_TO_FACT_STATUS, GET_FACT_FOR_DEMOTE, DEMOTE_FACT_TO_CLAIM queries |
| `tests/sage/test_layer_movement.py` | New test file for TX18, TX19 tests |

---

## Task 1: Add Result Dataclasses

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add PromoteResult dataclass**

Add after existing lifecycle dataclasses:

```python
@dataclass
class PromoteResult:
    """Result of TX18 PROMOTE."""

    claim_id: uuid.UUID
    promoted_at: datetime
    new_confidence: float
    corroboration_count: int


@dataclass
class DemoteResult:
    """Result of TX19 DEMOTE."""

    fact_id: uuid.UUID
    demoted_at: datetime
    new_confidence: float
    corroboration_count: int
```

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from context_service.sage.transactions import PromoteResult, DemoteResult; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add layer movement result dataclasses for Phase 5"
```

---

## Task 2: Add Cypher Queries

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add GET_CLAIM_FOR_PROMOTE query**

```python
GET_CLAIM_FOR_PROMOTE = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
RETURN c.id AS id,
       c.properties.state AS state,
       c.properties.claim_status AS claim_status,
       c.properties.corroboration_count AS corroboration_count,
       c.properties.confidence AS confidence
"""
```

- [ ] **Step 2: Add UPDATE_CLAIM_TO_PROMOTED query**

```python
UPDATE_CLAIM_TO_PROMOTED = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
WHERE c.properties.state = 'ACTIVE'
  AND c.properties.claim_status = 'UNPROMOTED'
SET c.properties.claim_status = 'PROMOTED',
    c.properties.promoted_at = $promoted_at,
    c.properties.confidence = $new_confidence
SET c:Fact
RETURN c.id AS id, c.properties.claim_status AS claim_status
"""
```

- [ ] **Step 3: Add GET_FACT_FOR_DEMOTE query**

```python
GET_FACT_FOR_DEMOTE = """
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
RETURN f.id AS id,
       f.properties.state AS state,
       f.properties.claim_status AS claim_status,
       f.properties.corroboration_count AS corroboration_count,
       f.properties.confidence AS confidence
"""
```

- [ ] **Step 4: Add UPDATE_FACT_TO_DEMOTED query**

```python
UPDATE_FACT_TO_DEMOTED = """
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
WHERE f.properties.state = 'ACTIVE'
  AND f.properties.claim_status = 'PROMOTED'
SET f.properties.claim_status = 'UNPROMOTED',
    f.properties.demoted_at = $demoted_at,
    f.properties.confidence = $new_confidence
REMOVE f:Fact
RETURN f.id AS id, f.properties.claim_status AS claim_status
"""
```

- [ ] **Step 5: Add RECOUNT_CORROBORATION query**

```python
RECOUNT_CORROBORATION = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MATCH (corroborating:Claim {silo_id: $silo_id})
WHERE corroborating.properties.subject = c.properties.subject
  AND corroborating.properties.predicate = c.properties.predicate
  AND corroborating.properties.object = c.properties.object
  AND corroborating.properties.state = 'ACTIVE'
OPTIONAL MATCH (corroborating)-[:DERIVED_FROM]->(evidence)
RETURN count(DISTINCT evidence.id) AS corroboration_count
"""
```

- [ ] **Step 6: Verify queries are valid Python**

Run: `uv run python -c "from context_service.db import queries; print('OK')"`

- [ ] **Step 7: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Cypher queries for layer movement transactions"
```

---

## Task 3: Write Tests for TX18 PROMOTE and TX19 DEMOTE

**Files:**
- Create: `tests/sage/test_layer_movement.py`

- [ ] **Step 1: Create test file with imports and fixtures**

```python
"""Tests for Phase 5 layer movement transactions (TX18 PROMOTE, TX19 DEMOTE)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    DemoteResult,
    InvariantViolation,
    PROMOTION_THRESHOLD,
    PromoteResult,
    tx18_promote,
    tx19_demote,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_write = AsyncMock(return_value=[{"id": str(uuid.uuid4())}])
    store.execute_query = AsyncMock(return_value=[])
    return store


def make_uuid() -> str:
    """Generate a valid UUID string for tests."""
    return str(uuid.uuid4())
```

- [ ] **Step 2: Add TestTx18Promote class**

```python
class TestTx18Promote:
    """Tests for TX18 PROMOTE."""

    @pytest.mark.asyncio
    async def test_promotes_claim_with_sufficient_corroboration(self, mock_store: AsyncMock) -> None:
        """Test that TX18 promotes a claim meeting corroboration threshold."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[{
            "id": claim_id,
            "state": "ACTIVE",
            "claim_status": "UNPROMOTED",
            "corroboration_count": PROMOTION_THRESHOLD,
            "confidence": 0.8,
        }])
        mock_store.execute_write = AsyncMock(return_value=[{
            "id": claim_id,
            "claim_status": "PROMOTED",
        }])

        result, events = await tx18_promote(
            store=mock_store,
            claim_id=claim_id,
            silo_id="test-silo",
        )

        assert isinstance(result, PromoteResult)
        assert result.corroboration_count >= PROMOTION_THRESHOLD

    @pytest.mark.asyncio
    async def test_rejects_insufficient_corroboration(self, mock_store: AsyncMock) -> None:
        """Test that TX18 rejects claims below corroboration threshold."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[{
            "id": claim_id,
            "state": "ACTIVE",
            "claim_status": "UNPROMOTED",
            "corroboration_count": PROMOTION_THRESHOLD - 1,
            "confidence": 0.8,
        }])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx18_promote(
                store=mock_store,
                claim_id=claim_id,
                silo_id="test-silo",
            )

        assert exc_info.value.code == "INSUFFICIENT_CORROBORATION"

    @pytest.mark.asyncio
    async def test_idempotent_for_already_promoted(self, mock_store: AsyncMock) -> None:
        """Test that TX18 is idempotent for already promoted claims."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[{
            "id": claim_id,
            "state": "ACTIVE",
            "claim_status": "PROMOTED",
            "corroboration_count": PROMOTION_THRESHOLD,
            "confidence": 0.9,
        }])

        result, events = await tx18_promote(
            store=mock_store,
            claim_id=claim_id,
            silo_id="test-silo",
        )

        assert isinstance(result, PromoteResult)
        # Should not call execute_write for already promoted
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_missing_claim(self, mock_store: AsyncMock) -> None:
        """Test that TX18 rejects non-existent claims."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx18_promote(
                store=mock_store,
                claim_id=make_uuid(),
                silo_id="test-silo",
            )

        assert exc_info.value.code == "CLAIM_NOT_FOUND"
```

- [ ] **Step 3: Add TestTx19Demote class**

```python
class TestTx19Demote:
    """Tests for TX19 DEMOTE."""

    @pytest.mark.asyncio
    async def test_demotes_fact_with_insufficient_corroboration(self, mock_store: AsyncMock) -> None:
        """Test that TX19 demotes a fact below corroboration threshold."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_FACT_FOR_DEMOTE
            [{
                "id": fact_id,
                "state": "ACTIVE",
                "claim_status": "PROMOTED",
                "corroboration_count": PROMOTION_THRESHOLD - 1,
                "confidence": 0.9,
            }],
            # RECOUNT_CORROBORATION
            [{"corroboration_count": PROMOTION_THRESHOLD - 1}],
        ])
        mock_store.execute_write = AsyncMock(return_value=[{
            "id": fact_id,
            "claim_status": "UNPROMOTED",
        }])

        result, events = await tx19_demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        assert result.corroboration_count < PROMOTION_THRESHOLD

    @pytest.mark.asyncio
    async def test_skips_demote_if_still_corroborated(self, mock_store: AsyncMock) -> None:
        """Test that TX19 skips demotion if corroboration is still sufficient."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_FACT_FOR_DEMOTE
            [{
                "id": fact_id,
                "state": "ACTIVE",
                "claim_status": "PROMOTED",
                "corroboration_count": PROMOTION_THRESHOLD,
                "confidence": 0.9,
            }],
            # RECOUNT_CORROBORATION
            [{"corroboration_count": PROMOTION_THRESHOLD}],
        ])

        result, events = await tx19_demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        # Should not call execute_write if still corroborated
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_for_already_demoted(self, mock_store: AsyncMock) -> None:
        """Test that TX19 is idempotent for already demoted facts."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[{
            "id": fact_id,
            "state": "ACTIVE",
            "claim_status": "UNPROMOTED",
            "corroboration_count": 1,
            "confidence": 0.7,
        }])

        result, events = await tx19_demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_missing_fact(self, mock_store: AsyncMock) -> None:
        """Test that TX19 rejects non-existent facts."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx19_demote(
                store=mock_store,
                fact_id=make_uuid(),
                silo_id="test-silo",
            )

        assert exc_info.value.code == "FACT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_triggers_cascade_staleness(self, mock_store: AsyncMock) -> None:
        """Test that TX19 emits cascade_staleness event."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            [{
                "id": fact_id,
                "state": "ACTIVE",
                "claim_status": "PROMOTED",
                "corroboration_count": 1,
                "confidence": 0.9,
            }],
            [{"corroboration_count": 1}],
        ])
        mock_store.execute_write = AsyncMock(return_value=[{
            "id": fact_id,
            "claim_status": "UNPROMOTED",
        }])

        result, events = await tx19_demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        event_types = [e.event_type for e in events]
        assert "cascade_staleness" in event_types
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_layer_movement.py -v`
Expected: All tests FAIL with ImportError (tx18_promote, tx19_demote not defined yet)

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/sage/test_layer_movement.py
git commit -m "test(sage): add failing tests for TX18 PROMOTE, TX19 DEMOTE"
```

---

## Task 4: Implement TX18 PROMOTE and TX19 DEMOTE

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement tx18_promote function**

```python
async def tx18_promote(
    store: HyperGraphStore,
    claim_id: str,
    silo_id: str,
) -> tuple[PromoteResult, list[ReactionEvent]]:
    """TX18 PROMOTE: Promote Claim to Fact when corroboration threshold met.

    Per brain-transactions-pseudocode.md:
    - Preconditions: claim exists, state ACTIVE, claim_status UNPROMOTED
    - Preconditions: corroboration_count >= PROMOTION_THRESHOLD
    - Idempotent: already promoted returns success without modification
    """
    from context_service.db import queries as q

    # Fetch claim
    claim_result = await store.execute_query(q.GET_CLAIM_FOR_PROMOTE, {
        "claim_id": claim_id,
        "silo_id": silo_id,
    })

    if not claim_result:
        raise InvariantViolation("CLAIM_NOT_FOUND", "Claim not found")

    claim = claim_result[0]
    state = claim.get("state")
    claim_status = claim.get("claim_status")
    corroboration_count = claim.get("corroboration_count", 0)
    current_confidence = claim.get("confidence", 0.8)

    if state != NodeState.ACTIVE.value:
        raise InvariantViolation("CLAIM_NOT_ACTIVE", f"Claim is not active (state: {state})")

    # Idempotent: already promoted
    if claim_status == "PROMOTED":
        return PromoteResult(
            claim_id=uuid.UUID(claim_id),
            promoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    if corroboration_count < PROMOTION_THRESHOLD:
        raise InvariantViolation(
            "INSUFFICIENT_CORROBORATION",
            f"Corroboration count {corroboration_count} below threshold {PROMOTION_THRESHOLD}",
            count=corroboration_count,
            threshold=PROMOTION_THRESHOLD,
        )

    now = datetime.now(UTC)
    # Boost confidence based on corroboration
    new_confidence = min(1.0, current_confidence + 0.1 * (corroboration_count - PROMOTION_THRESHOLD + 1))

    await store.execute_write(q.UPDATE_CLAIM_TO_PROMOTED, {
        "claim_id": claim_id,
        "silo_id": silo_id,
        "promoted_at": now.isoformat(),
        "new_confidence": new_confidence,
    })

    result = PromoteResult(
        claim_id=uuid.UUID(claim_id),
        promoted_at=now,
        new_confidence=new_confidence,
        corroboration_count=corroboration_count,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="update_cluster_membership",
            node_id=claim_id,
            silo_id=silo_id,
        ),
    ]

    logger.debug("tx18_promote_complete", claim_id=claim_id, silo_id=silo_id, corroboration_count=corroboration_count)

    return result, events
```

- [ ] **Step 2: Implement tx19_demote function**

```python
async def tx19_demote(
    store: HyperGraphStore,
    fact_id: str,
    silo_id: str,
) -> tuple[DemoteResult, list[ReactionEvent]]:
    """TX19 DEMOTE: Demote Fact back to Claim when evidence withdrawn.

    Per brain-transactions-pseudocode.md:
    - Preconditions: fact exists, state ACTIVE, claim_status PROMOTED
    - Recounts corroboration; skips if still >= threshold
    - Idempotent: already demoted returns success without modification
    """
    from context_service.db import queries as q

    # Fetch fact
    fact_result = await store.execute_query(q.GET_FACT_FOR_DEMOTE, {
        "fact_id": fact_id,
        "silo_id": silo_id,
    })

    if not fact_result:
        raise InvariantViolation("FACT_NOT_FOUND", "Fact not found")

    fact = fact_result[0]
    state = fact.get("state")
    claim_status = fact.get("claim_status")
    current_confidence = fact.get("confidence", 0.8)

    if state != NodeState.ACTIVE.value:
        raise InvariantViolation("FACT_NOT_ACTIVE", f"Fact is not active (state: {state})")

    # Idempotent: already demoted
    if claim_status != "PROMOTED":
        corroboration_count = fact.get("corroboration_count", 0)
        return DemoteResult(
            fact_id=uuid.UUID(fact_id),
            demoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    # Recount corroboration
    recount_result = await store.execute_query(q.RECOUNT_CORROBORATION, {
        "claim_id": fact_id,
        "silo_id": silo_id,
    })
    corroboration_count = recount_result[0].get("corroboration_count", 0) if recount_result else 0

    # Still corroborated - no demotion needed
    if corroboration_count >= PROMOTION_THRESHOLD:
        return DemoteResult(
            fact_id=uuid.UUID(fact_id),
            demoted_at=datetime.now(UTC),
            new_confidence=current_confidence,
            corroboration_count=corroboration_count,
        ), []

    now = datetime.now(UTC)
    # Reduce confidence without corroboration boost
    new_confidence = max(0.1, current_confidence - 0.1)

    await store.execute_write(q.UPDATE_FACT_TO_DEMOTED, {
        "fact_id": fact_id,
        "silo_id": silo_id,
        "demoted_at": now.isoformat(),
        "new_confidence": new_confidence,
    })

    result = DemoteResult(
        fact_id=uuid.UUID(fact_id),
        demoted_at=now,
        new_confidence=new_confidence,
        corroboration_count=corroboration_count,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="cascade_staleness",
            node_id=fact_id,
            silo_id=silo_id,
            payload={"depth": 1},
        ),
        ReactionEvent(
            event_type="update_cluster_membership",
            node_id=fact_id,
            silo_id=silo_id,
        ),
    ]

    logger.debug("tx19_demote_complete", fact_id=fact_id, silo_id=silo_id, corroboration_count=corroboration_count)

    return result, events
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_layer_movement.py -v`
Expected: All 9 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX18 PROMOTE, TX19 DEMOTE transactions"
```

---

## Task 5: Run Full Test Suite and Lint

- [ ] **Step 1: Run all Phase 5 tests**

Run: `uv run pytest tests/sage/test_layer_movement.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing tests**

Run: `uv run pytest tests/sage/ -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 3: Run linter**

Run: `uv run ruff check src/context_service/sage/`
Expected: No errors

- [ ] **Step 4: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix(sage): address lint issues in Phase 5 transactions"
```

---

## Task 6: Update Module Exports

**Files:**
- Modify: `src/context_service/sage/__init__.py`

- [ ] **Step 1: Add new exports**

Add to imports and __all__:
- PromoteResult
- DemoteResult
- tx18_promote
- tx19_demote

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from context_service.sage import tx18_promote, tx19_demote, PromoteResult, DemoteResult; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/__init__.py
git commit -m "feat(sage): export Phase 5 transactions from module"
```

---

## Task 7: Update Brain Architecture Plan

**Files:**
- Modify: `context/plans/2026-06-01-brain-architecture.md`

- [ ] **Step 1: Mark Phase 5 tasks complete**

- [ ] **Step 2: Update status to "Phase 5 complete, Phase 6 next"**

- [ ] **Step 3: Commit**

```bash
git add context/plans/2026-06-01-brain-architecture.md
git commit -m "docs: mark Phase 5 tasks complete in brain architecture plan"
```

---

## Summary

This plan implements 2 transactions across 7 tasks:

| Transaction | Tests | Implementation |
|-------------|-------|----------------|
| TX18 PROMOTE | 4 tests | Task 4 |
| TX19 DEMOTE | 5 tests | Task 4 |

Total: 9 new tests, ~120 lines of transaction code, ~40 lines of queries.

**Batching opportunity:** Tasks 3 and 4 can be batched (all tests, then all implementations) as done in Phase 4.
