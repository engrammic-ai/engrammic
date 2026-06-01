# Phase 2: Conflict Detection + Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement conflict detection at write time, consolidation infrastructure, atomic corroboration checking, and static credibility scoring.

**Architecture:** Optimistic writes with async consolidation. TX2 detects conflicts and flags them; consolidation worker resolves asynchronously. Credibility computed statically at write time with full breakdown for transparency.

**Tech Stack:** Python 3.12+, Memgraph (Cypher), pytest, structlog

---

## File Structure

| File | Purpose |
|------|---------|
| `src/context_service/sage/__init__.py` | Package init (rename from brain/) |
| `src/context_service/sage/transactions.py` | Core transactions (rename from brain/), add FLAG_CONTRADICTION, fix CHECK_CORROBORATION |
| `src/context_service/sage/confidence.py` | Credibility formula, tier weights, breakdown helper |
| `src/context_service/sage/consolidation.py` | ConflictQueue, ConsolidationWorker, DeterministicResolver |
| `tests/sage/__init__.py` | Test package (rename from tests/brain/) |
| `tests/sage/test_transactions.py` | Transaction tests (rename, add conflict tests) |
| `tests/sage/test_confidence.py` | Credibility formula tests |
| `tests/sage/test_consolidation.py` | Consolidation worker tests |
| `src/context_service/mcp/tools/recall.py` | Update recall to surface conflict status + credibility |

---

## Task Dependencies

```
Task 1 (rename) -> Task 2 (confidence) -> Task 3 (corroboration) -> Task 4 (conflict detection)
                                                                          |
                                                                          v
Task 4 -> Task 5 (consolidation) -> Task 6 (credibility integration) -> Task 7 (recall updates)
                                                                          |
                                                                          v
                                                                    Task 8 (integration test)
```

**Important:** Task 5 imports `ConflictStatus` from transactions.py, which is added in Task 4. Do not start Task 5 until Task 4 is complete.

---

## Task 1: Rename brain/ to sage/

**Files:**
- Rename: `src/context_service/brain/` -> `src/context_service/sage/`
- Rename: `tests/brain/` -> `tests/sage/`
- Modify: All files importing from `context_service.brain`

- [ ] **Step 1: Rename source directory**

```bash
git mv src/context_service/brain src/context_service/sage
```

- [ ] **Step 2: Rename test directory**

```bash
git mv tests/brain tests/sage
```

- [ ] **Step 3: Update imports in sage/transactions.py**

Change the module docstring and any internal references:

```python
"""Sage transactions: Core write path with invariant enforcement.

Implements TX0, TX2, TX3, TX17 per brain-transactions-pseudocode.md.
"""
```

- [ ] **Step 4: Find and update all imports across codebase**

```bash
grep -r "context_service.brain" --include="*.py" src/ tests/
```

Update each occurrence from `context_service.brain` to `context_service.sage`.

- [ ] **Step 5: Run tests to verify rename works**

```bash
uv run pytest tests/sage/ -v
```

Expected: All existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename brain/ to sage/"
```

---

## Task 2: Add credibility formula (sage/confidence.py)

**Files:**
- Create: `src/context_service/sage/confidence.py`
- Create: `tests/sage/test_confidence.py`

- [ ] **Step 1: Write failing test for source tier weights**

```python
# tests/sage/test_confidence.py
"""Tests for credibility formula."""

import pytest

from context_service.sage.confidence import (
    SOURCE_TIER_WEIGHTS,
    METHOD_WEIGHTS,
    compute_credibility,
    CredibilityBreakdown,
)


class TestSourceTierWeights:
    """Tests for source tier weight constants."""

    def test_authoritative_is_highest(self) -> None:
        assert SOURCE_TIER_WEIGHTS["authoritative"] == 1.0

    def test_validated_weight(self) -> None:
        assert SOURCE_TIER_WEIGHTS["validated"] == 0.85

    def test_community_weight(self) -> None:
        assert SOURCE_TIER_WEIGHTS["community"] == 0.6

    def test_unknown_is_lowest(self) -> None:
        assert SOURCE_TIER_WEIGHTS["unknown"] == 0.4
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_confidence.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'context_service.sage.confidence'"

- [ ] **Step 3: Write minimal implementation for tier weights**

```python
# src/context_service/sage/confidence.py
"""Credibility formula and tier weights.

Computes static credibility score at write time with full breakdown for transparency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SOURCE_TIER_WEIGHTS: dict[str, float] = {
    "authoritative": 1.0,   # Primary source: official docs, verified API response
    "validated": 0.85,      # Cross-checked against independent source
    "community": 0.6,       # Unverified but from known-good agent/source
    "unknown": 0.4,         # No provenance info
}

METHOD_WEIGHTS: dict[str, float] = {
    "direct": 1.0,              # Agent directly observed/verified
    "validated_extractor": 0.85, # Extraction pipeline with validation
    "standard_extractor": 0.75,  # Standard extraction, no validation
    "experimental": 0.6,         # New/untested extraction method
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/sage/test_confidence.py::TestSourceTierWeights -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for method weights**

```python
# Add to tests/sage/test_confidence.py

class TestMethodWeights:
    """Tests for method weight constants."""

    def test_direct_is_highest(self) -> None:
        assert METHOD_WEIGHTS["direct"] == 1.0

    def test_validated_extractor_weight(self) -> None:
        assert METHOD_WEIGHTS["validated_extractor"] == 0.85

    def test_standard_extractor_weight(self) -> None:
        assert METHOD_WEIGHTS["standard_extractor"] == 0.75

    def test_experimental_is_lowest(self) -> None:
        assert METHOD_WEIGHTS["experimental"] == 0.6
```

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest tests/sage/test_confidence.py::TestMethodWeights -v
```

Expected: PASS (constants already defined)

- [ ] **Step 7: Write failing test for compute_credibility**

```python
# Add to tests/sage/test_confidence.py

class TestComputeCredibility:
    """Tests for compute_credibility function."""

    def test_basic_computation(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method="direct",
            raw_confidence=0.9,
        )
        # 0.85 * 1.0 * 0.9 = 0.765
        assert breakdown.credibility == pytest.approx(0.765)

    def test_returns_breakdown_with_all_factors(self) -> None:
        breakdown = compute_credibility(
            source_tier="authoritative",
            method="standard_extractor",
            raw_confidence=0.8,
        )
        assert breakdown.source_tier == "authoritative"
        assert breakdown.source_tier_weight == 1.0
        assert breakdown.method == "standard_extractor"
        assert breakdown.method_weight == 0.75
        assert breakdown.raw_confidence == 0.8
        # 1.0 * 0.75 * 0.8 = 0.6
        assert breakdown.credibility == pytest.approx(0.6)

    def test_defaults_to_unknown_tier(self) -> None:
        breakdown = compute_credibility(
            source_tier=None,
            method="direct",
            raw_confidence=0.9,
        )
        assert breakdown.source_tier == "unknown"
        assert breakdown.source_tier_weight == 0.4

    def test_defaults_to_direct_method(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method=None,
            raw_confidence=0.9,
        )
        assert breakdown.method == "direct"
        assert breakdown.method_weight == 1.0

    def test_clamps_raw_confidence_to_valid_range(self) -> None:
        breakdown = compute_credibility(
            source_tier="authoritative",
            method="direct",
            raw_confidence=1.5,  # Over 1.0
        )
        assert breakdown.raw_confidence == 1.0
        assert breakdown.credibility == pytest.approx(1.0)

    def test_to_dict_returns_serializable(self) -> None:
        breakdown = compute_credibility(
            source_tier="validated",
            method="direct",
            raw_confidence=0.9,
        )
        d = breakdown.to_dict()
        assert isinstance(d, dict)
        assert d["credibility"] == pytest.approx(0.765)
```

- [ ] **Step 8: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_confidence.py::TestComputeCredibility -v
```

Expected: FAIL with "cannot import name 'compute_credibility'"

- [ ] **Step 9: Implement CredibilityBreakdown and compute_credibility**

```python
# Add to src/context_service/sage/confidence.py

@dataclass
class CredibilityBreakdown:
    """Full breakdown of credibility computation for transparency."""

    source_tier: str
    source_tier_weight: float
    method: str
    method_weight: float
    raw_confidence: float
    credibility: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_tier": self.source_tier,
            "source_tier_weight": self.source_tier_weight,
            "method": self.method,
            "method_weight": self.method_weight,
            "raw_confidence": self.raw_confidence,
            "credibility": self.credibility,
        }


def compute_credibility(
    source_tier: str | None,
    method: str | None,
    raw_confidence: float,
) -> CredibilityBreakdown:
    """Compute static credibility score with full breakdown.

    Formula: credibility = source_tier_weight * method_weight * raw_confidence

    Args:
        source_tier: Source quality tier (authoritative, validated, community, unknown).
        method: Extraction method (direct, validated_extractor, standard_extractor, experimental).
        raw_confidence: Raw confidence score from source (0.0-1.0).

    Returns:
        CredibilityBreakdown with all factors and final score.
    """
    tier = source_tier if source_tier in SOURCE_TIER_WEIGHTS else "unknown"
    tier_weight = SOURCE_TIER_WEIGHTS[tier]

    meth = method if method in METHOD_WEIGHTS else "direct"
    meth_weight = METHOD_WEIGHTS[meth]

    clamped_confidence = max(0.0, min(1.0, raw_confidence))

    credibility = tier_weight * meth_weight * clamped_confidence

    return CredibilityBreakdown(
        source_tier=tier,
        source_tier_weight=tier_weight,
        method=meth,
        method_weight=meth_weight,
        raw_confidence=clamped_confidence,
        credibility=credibility,
    )
```

- [ ] **Step 10: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_confidence.py -v
```

Expected: All PASS

- [ ] **Step 11: Commit**

```bash
git add src/context_service/sage/confidence.py tests/sage/test_confidence.py
git commit -m "feat(sage): add credibility formula with transparency breakdown"
```

---

## Task 3: Fix CHECK_CORROBORATION (atomic query)

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Modify: `tests/sage/test_transactions.py`

- [ ] **Step 1: Write failing test for atomic corroboration check**

```python
# Add to tests/sage/test_transactions.py

class TestCheckCorroboration:
    """Tests for atomic CHECK_CORROBORATION helper."""

    @pytest.mark.asyncio
    async def test_returns_count_and_should_promote(self, mock_store: AsyncMock) -> None:
        """Test that corroboration check returns count and promotion flag."""
        # Mock query result: 2 distinct sources, threshold is 3
        mock_store.execute_query = AsyncMock(return_value=[{
            "count": 2,
            "should_promote": False,
        }])

        from context_service.sage.transactions import check_corroboration

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 2
        assert should_promote is False

    @pytest.mark.asyncio
    async def test_returns_true_when_threshold_met(self, mock_store: AsyncMock) -> None:
        """Test that should_promote is True when threshold met."""
        mock_store.execute_query = AsyncMock(return_value=[{
            "count": 3,
            "should_promote": True,
        }])

        from context_service.sage.transactions import check_corroboration

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 3
        assert should_promote is True

    @pytest.mark.asyncio
    async def test_uses_single_atomic_query(self, mock_store: AsyncMock) -> None:
        """Test that corroboration uses a single query (atomic)."""
        mock_store.execute_query = AsyncMock(return_value=[{
            "count": 1,
            "should_promote": False,
        }])

        from context_service.sage.transactions import check_corroboration

        await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        # Should be exactly one query call (atomic)
        assert mock_store.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_handles_no_corroborating_claims(self, mock_store: AsyncMock) -> None:
        """Test handling when no corroborating claims exist."""
        mock_store.execute_query = AsyncMock(return_value=[{
            "count": 1,
            "should_promote": False,
        }])

        from context_service.sage.transactions import check_corroboration

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 1  # Just the node itself
        assert should_promote is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_transactions.py::TestCheckCorroboration -v
```

Expected: FAIL with "cannot import name 'check_corroboration'"

- [ ] **Step 3: Implement atomic check_corroboration**

Replace the placeholder `_check_corroboration` in `src/context_service/sage/transactions.py`:

```python
PROMOTION_THRESHOLD = 3


async def check_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    threshold: int = PROMOTION_THRESHOLD,
) -> tuple[int, bool]:
    """Atomic corroboration check using single query.

    Finds all claims with same (subject, predicate, object), counts distinct
    evidence sources, updates corroboration_count on all, returns result.

    Args:
        store: Graph store instance.
        node_id: The claim node to check.
        silo_id: Tenant isolation ID.
        threshold: Promotion threshold (default: 3).

    Returns:
        Tuple of (distinct_source_count, should_promote).
    """
    cypher = """
    MATCH (new:Claim {id: $node_id, silo_id: $silo_id})
    MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.subject = new.properties.subject
      AND c.properties.predicate = new.properties.predicate
      AND c.properties.object = new.properties.object
      AND c.properties.state = 'ACTIVE'
    WITH collect(c) AS claims
    UNWIND claims AS claim
    OPTIONAL MATCH (claim)-[:DERIVED_FROM]->(evidence)
    WITH claims, collect(DISTINCT evidence.id) AS distinct_sources
    UNWIND claims AS claim
    SET claim.properties.corroboration_count = size(distinct_sources)
    RETURN size(distinct_sources) AS count, size(distinct_sources) >= $threshold AS should_promote
    """

    results = await store.execute_query(
        cypher,
        {"node_id": node_id, "silo_id": silo_id, "threshold": threshold},
    )

    if not results:
        return 1, False

    row = results[0]
    return row.get("count", 1), row.get("should_promote", False)
```

- [ ] **Step 4: Update _check_corroboration to call the new function and emit events**

```python
async def _check_corroboration(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
) -> tuple[int, bool, list[ReactionEvent]]:
    """Check corroboration and potentially emit PromoteRequested event.

    Returns (corroboration_count, should_promote, events).
    """
    count, should_promote = await check_corroboration(store, node_id, silo_id)
    
    events: list[ReactionEvent] = []
    if should_promote:
        events.append(
            ReactionEvent(
                event_type="promote_requested",
                node_id=node_id,
                silo_id=silo_id,
                payload={"corroboration_count": count},
            )
        )
    
    return count, should_promote, events
    return await check_corroboration(store, node_id, silo_id)
```

- [ ] **Step 5: Export check_corroboration in module**

Add to imports/exports at top of transactions.py and update `__all__` if present.

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_transactions.py::TestCheckCorroboration -v
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/sage/transactions.py tests/sage/test_transactions.py
git commit -m "feat(sage): implement atomic CHECK_CORROBORATION"
```

---

## Task 4: Add FLAG_CONTRADICTION to TX2 flow

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Modify: `tests/sage/test_transactions.py`

- [ ] **Step 1: Add ConflictStatus enum**

```python
# Add to src/context_service/sage/transactions.py

class ConflictStatus(StrEnum):
    """Conflict status for nodes."""

    NONE = "none"
    UNRESOLVED = "unresolved"
    RESOLVED_SUPERSEDE = "resolved_supersede"
    RESOLVED_MERGE = "resolved_merge"
    RESOLVED_COEXIST = "resolved_coexist"
```

- [ ] **Step 2: Write failing test for conflict detection**

```python
# Add to tests/sage/test_transactions.py

class TestFlagContradiction:
    """Tests for FLAG_CONTRADICTION in TX2 flow."""

    @pytest.mark.asyncio
    async def test_detects_structural_conflict(self, mock_store: AsyncMock) -> None:
        """Test that TX2 detects conflicting claims."""
        # First call: evidence validation
        # Second call: conflict detection returns existing claim
        mock_store.execute_query = AsyncMock(side_effect=[
            # Evidence validation
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            # Conflict detection: existing claim with different object
            [{
                "id": "existing-claim",
                "silo_id": "test-silo",
                "subject": "test-subject",
                "predicate": "has_value",
                "object": "different-value",
                "state": "ACTIVE",
            }],
            # Corroboration check
            [{"count": 1, "should_promote": False}],
        ])

        result, events = await tx2_store_claim(
            store=mock_store,
            content="test-subject has_value test-value",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="test-subject",
            predicate="has_value",
            object_value="test-value",
        )

        # Should emit ConflictDetected event
        conflict_events = [e for e in events if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 1
        assert conflict_events[0].payload["conflict_type"] == "structural"

    @pytest.mark.asyncio
    async def test_no_conflict_when_same_object(self, mock_store: AsyncMock) -> None:
        """Test no conflict when claims have same object."""
        mock_store.execute_query = AsyncMock(side_effect=[
            # Evidence validation
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            # Conflict detection: no conflicts (same object)
            [],
            # Corroboration check
            [{"count": 1, "should_promote": False}],
        ])

        result, events = await tx2_store_claim(
            store=mock_store,
            content="test-subject has_value test-value",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="test-subject",
            predicate="has_value",
            object_value="test-value",
        )

        conflict_events = [e for e in events if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 0

    @pytest.mark.asyncio
    async def test_creates_bidirectional_contradicts_edges(self, mock_store: AsyncMock) -> None:
        """Test that bidirectional CONTRADICTS edges are created."""
        mock_store.execute_query = AsyncMock(side_effect=[
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            [{"id": "existing-claim", "silo_id": "test-silo", "subject": "s", "predicate": "p", "object": "old", "state": "ACTIVE"}],
            [{"count": 1, "should_promote": False}],
        ])

        await tx2_store_claim(
            store=mock_store,
            content="s p new",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="s",
            predicate="p",
            object_value="new",
        )

        # Check that bidirectional edges were created (both directions in single query)
        write_calls = mock_store.execute_write.call_args_list
        contradicts_calls = [c for c in write_calls if "CONTRADICTS" in str(c)]
        assert len(contradicts_calls) == 1  # Single query creates both directions
        
        # Verify the query contains both MERGE statements for bidirectionality
        call_str = str(contradicts_calls[0])
        assert "(a)-[:CONTRADICTS" in call_str or "MERGE" in call_str
        assert "(b)-[:CONTRADICTS" in call_str or call_str.count("MERGE") >= 2
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_transactions.py::TestFlagContradiction -v
```

Expected: FAIL (tx2_store_claim doesn't accept subject/predicate/object params yet)

- [ ] **Step 4: Update tx2_store_claim signature to accept SPO**

```python
async def tx2_store_claim(
    store: HyperGraphStore,
    content: str,
    evidence_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    subject: str | None = None,
    predicate: str | None = None,
    object_value: str | None = None,  # Avoid shadowing builtin 'object'
    source_tier: str | None = None,
    confidence: float = 0.8,
    supersedes: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> tuple[StoreClaimResult, list[ReactionEvent]]:
```

- [ ] **Step 5: Implement flag_contradiction helper**

```python
async def _flag_contradiction(
    store: HyperGraphStore,
    new_node_id: str,
    subject: str | None,
    predicate: str | None,
    object_value: str | None,
    silo_id: str,
) -> list[ReactionEvent]:
    """Detect and flag structural conflicts with existing claims.

    Creates bidirectional CONTRADICTS edges and emits ConflictDetected events.
    """
    if not all([subject, predicate, object_value]):
        return []  # No SPO to check

    # Find conflicting claims
    cypher = """
    MATCH (c:Claim {silo_id: $silo_id})
    WHERE c.properties.subject = $subject
      AND c.properties.predicate = $predicate
      AND c.properties.object <> $object
      AND c.properties.state = 'ACTIVE'
      AND c.id <> $new_node_id
    RETURN c.id AS id
    """

    conflicts = await store.execute_query(
        cypher,
        {
            "silo_id": silo_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_value,
            "new_node_id": new_node_id,
        },
    )

    if not conflicts:
        return []

    events: list[ReactionEvent] = []
    detected_at = datetime.now(UTC).isoformat()

    for conflict in conflicts:
        existing_id = conflict["id"]

        # Create bidirectional CONTRADICTS edges (INV8)
        await _create_bidirectional_contradicts(
            store, new_node_id, existing_id, silo_id, detected_at
        )

        # Update conflict_status on both nodes
        await _set_conflict_status(
            store, new_node_id, existing_id, silo_id, ConflictStatus.UNRESOLVED
        )

        # Emit ConflictDetected event
        events.append(
            ReactionEvent(
                event_type="conflict_detected",
                node_id=new_node_id,
                silo_id=silo_id,
                payload={
                    "node_a": new_node_id,
                    "node_b": existing_id,
                    "conflict_type": "structural",
                    "detected_at": detected_at,
                },
            )
        )

    return events


async def _create_bidirectional_contradicts(
    store: HyperGraphStore,
    node_a: str,
    node_b: str,
    silo_id: str,
    detected_at: str,
) -> None:
    """Create bidirectional CONTRADICTS edges (A->B and B->A)."""
    cypher = """
    MATCH (a {id: $node_a, silo_id: $silo_id})
    MATCH (b {id: $node_b, silo_id: $silo_id})
    MERGE (a)-[:CONTRADICTS {weight: 1.0, detected_at: $detected_at, conflict_type: 'structural'}]->(b)
    MERGE (b)-[:CONTRADICTS {weight: 1.0, detected_at: $detected_at, conflict_type: 'structural'}]->(a)
    """
    await store.execute_write(
        cypher,
        {"node_a": node_a, "node_b": node_b, "silo_id": silo_id, "detected_at": detected_at},
    )


async def _set_conflict_status(
    store: HyperGraphStore,
    node_a: str,
    node_b: str,
    silo_id: str,
    status: ConflictStatus,
) -> None:
    """Set conflict_status on both nodes."""
    cypher = """
    MATCH (n {silo_id: $silo_id})
    WHERE n.id IN $node_ids
    SET n.properties.conflict_status = $status
    """
    await store.execute_write(
        cypher,
        {"node_ids": [node_a, node_b], "silo_id": silo_id, "status": status.value},
    )
```

- [ ] **Step 6: Integrate flag_contradiction into tx2_store_claim**

Add after corroboration check, before return:

```python
    # ... existing code ...

    corroboration_count, should_promote, corr_events = await _check_corroboration(
        store, str(node_id), silo_id
    )
    events.extend(corr_events)  # Includes PromoteRequested if threshold met

    # FLAG_CONTRADICTION: detect and flag conflicts
    conflict_events = await _flag_contradiction(
        store, str(node_id), subject, predicate, object_value, silo_id
    )
    events.extend(conflict_events)

    # Store SPO in node properties if provided
    if subject and predicate and object_value:
        props["subject"] = subject
        props["predicate"] = predicate
        props["object"] = object_value

    # ... rest of function ...
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_transactions.py::TestFlagContradiction -v
```

Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/context_service/sage/transactions.py tests/sage/test_transactions.py
git commit -m "feat(sage): add FLAG_CONTRADICTION to TX2 with bidirectional edges"
```

---

## Task 5: Create consolidation infrastructure

**Files:**
- Create: `src/context_service/sage/consolidation.py`
- Create: `tests/sage/test_consolidation.py`

- [ ] **Step 1: Write failing test for DeterministicResolver**

```python
# tests/sage/test_consolidation.py
"""Tests for consolidation infrastructure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from context_service.sage.consolidation import (
    ConflictSignals,
    DeterministicResolver,
    ResolutionAction,
    ResolutionResult,
)


class TestDeterministicResolver:
    """Tests for deterministic conflict resolution."""

    def test_higher_source_tier_wins(self) -> None:
        """Score uses source_tier_weight, not credibility."""
        resolver = DeterministicResolver()

        signals_a = ConflictSignals(
            node_id="node-a",
            credibility=0.9,
            corroboration_count=1,
            created_at=datetime.now(UTC),
            agent_id="agent-1",
            source_tier="authoritative",  # weight 1.0
        )
        signals_b = ConflictSignals(
            node_id="node-b",
            credibility=0.9,  # Same credibility
            corroboration_count=1,
            created_at=datetime.now(UTC),
            agent_id="agent-2",
            source_tier="community",  # weight 0.6
        )

        result = resolver.resolve(signals_a, signals_b)

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-a"  # Higher tier wins
        assert result.loser_id == "node-b"

    def test_higher_corroboration_wins(self) -> None:
        resolver = DeterministicResolver()

        signals_a = ConflictSignals(
            node_id="node-a",
            credibility=0.8,
            corroboration_count=5,
            created_at=datetime.now(UTC),
            agent_id="agent-1",
            source_tier="validated",
        )
        signals_b = ConflictSignals(
            node_id="node-b",
            credibility=0.8,
            corroboration_count=1,
            created_at=datetime.now(UTC),
            agent_id="agent-2",
            source_tier="validated",  # Same tier
        )

        result = resolver.resolve(signals_a, signals_b)

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-a"

    def test_more_recent_wins_when_same_agent(self) -> None:
        resolver = DeterministicResolver()
        now = datetime.now(UTC)

        signals_a = ConflictSignals(
            node_id="node-a",
            credibility=0.8,
            corroboration_count=1,
            created_at=now - timedelta(days=1),
            agent_id="same-agent",
        )
        signals_b = ConflictSignals(
            node_id="node-b",
            credibility=0.8,
            corroboration_count=1,
            created_at=now,
            agent_id="same-agent",
        )

        result = resolver.resolve(signals_a, signals_b)

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-b"  # Newer wins

    def test_older_wins_when_different_agents_tie(self) -> None:
        resolver = DeterministicResolver()
        now = datetime.now(UTC)

        signals_a = ConflictSignals(
            node_id="node-a",
            credibility=0.8,
            corroboration_count=1,
            created_at=now - timedelta(days=1),
            agent_id="agent-1",
        )
        signals_b = ConflictSignals(
            node_id="node-b",
            credibility=0.8,
            corroboration_count=1,
            created_at=now,
            agent_id="agent-2",
        )

        result = resolver.resolve(signals_a, signals_b)

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-a"  # Older wins for stability
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_consolidation.py::TestDeterministicResolver -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement consolidation types and resolver**

```python
# src/context_service/sage/consolidation.py
"""Consolidation infrastructure for conflict resolution.

Provides queue, worker, and resolver for async conflict consolidation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class ResolutionAction(StrEnum):
    """Actions a resolver can take."""

    SUPERSEDE = "supersede"  # Winner supersedes loser
    DEFER = "defer"          # Leave unresolved, retry later
    # Future: MERGE, COEXIST


@dataclass
class ConflictSignals:
    """Signals gathered for conflict resolution."""

    node_id: str
    credibility: float
    corroboration_count: int
    created_at: datetime
    agent_id: str
    source_tier: str = "unknown"


@dataclass
class ResolutionResult:
    """Result of conflict resolution."""

    action: ResolutionAction
    winner_id: str | None = None
    loser_id: str | None = None
    rationale: str = ""


class DeterministicResolver:
    """Deterministic conflict resolver using scoring formula.

    Score = tier_weight * log(1 + corroboration) * freshness

    Tiebreaker:
    - Same agent: newer wins (self-correction)
    - Different agents: older wins (stability)
    """

    def resolve(
        self,
        signals_a: ConflictSignals,
        signals_b: ConflictSignals,
    ) -> ResolutionResult:
        """Resolve conflict between two claims."""
        score_a = self._score(signals_a)
        score_b = self._score(signals_b)

        if abs(score_a - score_b) < 0.001:  # Tie
            return self._break_tie(signals_a, signals_b)

        if score_a > score_b:
            return ResolutionResult(
                action=ResolutionAction.SUPERSEDE,
                winner_id=signals_a.node_id,
                loser_id=signals_b.node_id,
                rationale=f"Higher score: {score_a:.3f} vs {score_b:.3f}",
            )
        else:
            return ResolutionResult(
                action=ResolutionAction.SUPERSEDE,
                winner_id=signals_b.node_id,
                loser_id=signals_a.node_id,
                rationale=f"Higher score: {score_b:.3f} vs {score_a:.3f}",
            )

    def _score(self, signals: ConflictSignals) -> float:
        """Compute resolution score.
        
        Formula per spec: tier_weight * log(1 + corroboration) * freshness
        Note: Uses source_tier_weight, NOT credibility (which would double-count).
        """
        from context_service.sage.confidence import SOURCE_TIER_WEIGHTS
        
        tier_weight = SOURCE_TIER_WEIGHTS.get(signals.source_tier, 0.4)
        corroboration = math.log(1 + signals.corroboration_count)
        days_old = (datetime.now(UTC) - signals.created_at).days
        freshness = 1.0 / (1 + days_old)

        return tier_weight * corroboration * freshness

    def _break_tie(
        self,
        signals_a: ConflictSignals,
        signals_b: ConflictSignals,
    ) -> ResolutionResult:
        """Break tie between equal-scored claims."""
        same_agent = signals_a.agent_id == signals_b.agent_id

        if same_agent:
            # Same agent: newer wins (self-correction)
            if signals_a.created_at > signals_b.created_at:
                winner, loser = signals_a, signals_b
            else:
                winner, loser = signals_b, signals_a
            rationale = "Same agent, newer wins"
        else:
            # Different agents: older wins (stability)
            if signals_a.created_at < signals_b.created_at:
                winner, loser = signals_a, signals_b
            else:
                winner, loser = signals_b, signals_a
            rationale = "Different agents, older wins for stability"

        return ResolutionResult(
            action=ResolutionAction.SUPERSEDE,
            winner_id=winner.node_id,
            loser_id=loser.node_id,
            rationale=rationale,
        )


class LLMResolverStub:
    """Stub LLM resolver that always defers. Ready for Phase 7 integration."""

    def resolve(
        self,
        signals_a: ConflictSignals,
        signals_b: ConflictSignals,
    ) -> ResolutionResult:
        """Always defer - stub for future LLM integration."""
        return ResolutionResult(
            action=ResolutionAction.DEFER,
            rationale="LLM resolver stub - always defers",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_consolidation.py::TestDeterministicResolver -v
```

Expected: All PASS

- [ ] **Step 5: Write failing test for ConsolidationWorker**

```python
# Add to tests/sage/test_consolidation.py

from context_service.sage.consolidation import ConsolidationWorker


class TestConsolidationWorker:
    """Tests for async consolidation worker."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        store = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_processes_conflict_event(self, mock_store: AsyncMock) -> None:
        """Test that worker processes conflict events."""
        # Mock node lookups
        mock_store.execute_query = AsyncMock(side_effect=[
            # Node A
            [{
                "id": "node-a",
                "credibility": 0.9,
                "corroboration_count": 2,
                "created_at": "2026-06-01T00:00:00Z",
                "created_by": "agent-1",
                "source_tier": "validated",
            }],
            # Node B
            [{
                "id": "node-b",
                "credibility": 0.5,
                "corroboration_count": 1,
                "created_at": "2026-06-01T00:00:00Z",
                "created_by": "agent-2",
                "source_tier": "community",
            }],
        ])

        worker = ConsolidationWorker(store=mock_store)

        result = await worker.process_conflict(
            node_a="node-a",
            node_b="node-b",
            silo_id="test-silo",
        )

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-a"

    @pytest.mark.asyncio
    async def test_applies_supersede_result(self, mock_store: AsyncMock) -> None:
        """Test that worker applies supersede result."""
        mock_store.execute_query = AsyncMock(side_effect=[
            [{"id": "node-a", "credibility": 0.9, "corroboration_count": 1, "created_at": "2026-06-01T00:00:00Z", "created_by": "agent-1", "source_tier": "validated"}],
            [{"id": "node-b", "credibility": 0.5, "corroboration_count": 1, "created_at": "2026-06-01T00:00:00Z", "created_by": "agent-2", "source_tier": "community"}],
        ])

        worker = ConsolidationWorker(store=mock_store)

        await worker.process_conflict(
            node_a="node-a",
            node_b="node-b",
            silo_id="test-silo",
        )

        # Verify supersede was called (via execute_write)
        assert mock_store.execute_write.called

    @pytest.mark.asyncio
    async def test_handles_defer_result(self, mock_store: AsyncMock) -> None:
        """Test that worker handles defer result without writes."""
        mock_store.execute_query = AsyncMock(side_effect=[
            [{"id": "node-a", "credibility": 0.8, "corroboration_count": 1, "created_at": "2026-06-01T00:00:00Z", "created_by": "agent-1", "source_tier": "validated"}],
            [{"id": "node-b", "credibility": 0.8, "corroboration_count": 1, "created_at": "2026-06-01T00:00:00Z", "created_by": "agent-2", "source_tier": "validated"}],
        ])

        # Use LLMResolverStub which always returns DEFER
        from context_service.sage.consolidation import LLMResolverStub
        worker = ConsolidationWorker(store=mock_store, resolver=LLMResolverStub())

        result = await worker.process_conflict(
            node_a="node-a",
            node_b="node-b",
            silo_id="test-silo",
        )

        assert result.action == ResolutionAction.DEFER
        # No writes should happen for defer
        assert not mock_store.execute_write.called
```

- [ ] **Step 6: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_consolidation.py::TestConsolidationWorker -v
```

Expected: FAIL with "cannot import name 'ConsolidationWorker'"

- [ ] **Step 7: Implement ConsolidationWorker**

```python
# Add to src/context_service/sage/consolidation.py

from context_service.sage.transactions import ConflictStatus, tx3_supersede, SupersedeReason


class ConsolidationWorker:
    """Async worker for processing conflict events."""

    def __init__(
        self,
        store: HyperGraphStore,
        resolver: DeterministicResolver | LLMResolverStub | None = None,
    ) -> None:
        self.store = store
        self.resolver = resolver or DeterministicResolver()

    async def process_conflict(
        self,
        node_a: str,
        node_b: str,
        silo_id: str,
    ) -> ResolutionResult:
        """Process a conflict between two nodes.

        Gathers signals, calls resolver, applies result.
        """
        signals_a = await self._gather_signals(node_a, silo_id)
        signals_b = await self._gather_signals(node_b, silo_id)

        result = self.resolver.resolve(signals_a, signals_b)

        if result.action == ResolutionAction.SUPERSEDE:
            await self._apply_supersede(result, silo_id)
        elif result.action == ResolutionAction.DEFER:
            logger.debug(
                "consolidation_deferred",
                node_a=node_a,
                node_b=node_b,
                rationale=result.rationale,
            )

        return result

    async def _gather_signals(self, node_id: str, silo_id: str) -> ConflictSignals:
        """Gather signals for a node."""
        cypher = """
        MATCH (n {id: $node_id, silo_id: $silo_id})
        RETURN n.id AS id,
               n.properties.credibility AS credibility,
               n.properties.corroboration_count AS corroboration_count,
               n.created_at AS created_at,
               n.properties.created_by AS created_by,
               n.properties.source_tier AS source_tier
        """
        results = await self.store.execute_query(
            cypher,
            {"node_id": node_id, "silo_id": silo_id},
        )

        if not results:
            raise ValueError(f"Node {node_id} not found")

        row = results[0]
        created_at = row.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        return ConflictSignals(
            node_id=row["id"],
            credibility=row.get("credibility", 0.5),
            corroboration_count=row.get("corroboration_count", 1),
            created_at=created_at or datetime.now(UTC),
            agent_id=row.get("created_by", "unknown"),
            source_tier=row.get("source_tier", "unknown"),
        )

    async def _apply_supersede(self, result: ResolutionResult, silo_id: str) -> None:
        """Apply supersede resolution."""
        if not result.winner_id or not result.loser_id:
            return

        # Call TX3 SUPERSEDE
        await tx3_supersede(
            store=self.store,
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            silo_id=silo_id,
            reason=SupersedeReason.CONTRADICTION,
        )

        # Update conflict_status on both
        cypher = """
        MATCH (n {silo_id: $silo_id})
        WHERE n.id IN [$winner_id, $loser_id]
        SET n.properties.conflict_status = $status
        """
        await self.store.execute_write(
            cypher,
            {
                "winner_id": result.winner_id,
                "loser_id": result.loser_id,
                "silo_id": silo_id,
                "status": ConflictStatus.RESOLVED_SUPERSEDE.value,
            },
        )

        logger.info(
            "consolidation_supersede_applied",
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            rationale=result.rationale,
        )
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_consolidation.py -v
```

Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/context_service/sage/consolidation.py tests/sage/test_consolidation.py
git commit -m "feat(sage): add consolidation infrastructure with deterministic resolver"
```

---

## Task 6: Integrate credibility into TX2

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Modify: `tests/sage/test_transactions.py`

- [ ] **Step 1: Write failing test for credibility in TX2**

```python
# Add to tests/sage/test_transactions.py

class TestTx2Credibility:
    """Tests for credibility computation in TX2."""

    @pytest.mark.asyncio
    async def test_computes_credibility_at_write(self, mock_store: AsyncMock) -> None:
        """Test that TX2 computes and stores credibility."""
        mock_store.execute_query = AsyncMock(side_effect=[
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            [],  # No conflicts
            [{"count": 1, "should_promote": False}],
        ])

        result, events = await tx2_store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            source_tier="validated",
            confidence=0.9,
        )

        # Check that credibility was stored in node properties
        write_call = mock_store.execute_write.call_args_list[0]
        props = write_call[0][1]["props"]  # Second arg, props key
        
        assert "credibility" in props
        # validated (0.85) * direct (1.0) * 0.9 = 0.765
        assert props["credibility"] == pytest.approx(0.765, rel=0.01)

    @pytest.mark.asyncio
    async def test_stores_credibility_breakdown(self, mock_store: AsyncMock) -> None:
        """Test that credibility breakdown is stored."""
        mock_store.execute_query = AsyncMock(side_effect=[
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            [],
            [{"count": 1, "should_promote": False}],
        ])

        result, events = await tx2_store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            source_tier="authoritative",
            confidence=0.8,
        )

        write_call = mock_store.execute_write.call_args_list[0]
        props = write_call[0][1]["props"]

        assert props["credibility_factors"]["source_tier"] == "authoritative"
        assert props["credibility_factors"]["source_tier_weight"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/sage/test_transactions.py::TestTx2Credibility -v
```

Expected: FAIL (credibility not computed yet)

- [ ] **Step 3: Integrate credibility computation into TX2**

```python
# Add import at top of src/context_service/sage/transactions.py
from context_service.sage.confidence import compute_credibility

# Update tx2_store_claim to compute and store credibility
async def tx2_store_claim(
    # ... existing params ...
) -> tuple[StoreClaimResult, list[ReactionEvent]]:
    # ... existing validation ...

    # Compute credibility
    credibility_breakdown = compute_credibility(
        source_tier=source_tier,
        method=None,  # Default to direct for MCP calls
        raw_confidence=confidence,
    )

    props: dict[str, Any] = {
        "layer": "knowledge",
        "state": NodeState.ACTIVE.value,
        "claim_status": "UNPROMOTED",
        "confidence": confidence,
        "credibility": credibility_breakdown.credibility,
        "credibility_factors": credibility_breakdown.to_dict(),
        "source_tier": source_tier or "unknown",
        "created_by": agent_id,
        "evidence": evidence_refs,
        **(metadata or {}),
    }
    # ... rest of function ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/sage/test_transactions.py::TestTx2Credibility -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/transactions.py tests/sage/test_transactions.py
git commit -m "feat(sage): integrate credibility computation into TX2"
```

---

## Task 7: Update recall to surface conflict status and credibility

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py` (or wherever recall is implemented)
- Create: `tests/sage/test_recall_conflict.py`

- [ ] **Step 1: Find the recall implementation**

```bash
grep -r "def recall" --include="*.py" src/context_service/
```

- [ ] **Step 2: Write failing test for conflict status in recall**

```python
# tests/sage/test_recall_conflict.py
"""Tests for conflict status and credibility in recall results."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestRecallConflictStatus:
    """Tests for conflict fields in recall results."""

    @pytest.mark.asyncio
    async def test_recall_includes_conflict_status(self, mock_store: AsyncMock) -> None:
        """Test that recall results include conflict_status field."""
        # Mock a node with conflict_status
        mock_store.execute_query = AsyncMock(return_value=[{
            "id": "node-1",
            "content": "Test claim",
            "conflict_status": "unresolved",
            "credibility": 0.85,
            "credibility_factors": {
                "source_tier": "validated",
                "source_tier_weight": 0.85,
                "method": "direct",
                "method_weight": 1.0,
                "raw_confidence": 1.0,
                "credibility": 0.85,
            },
        }])

        # Call recall (implementation varies by project structure)
        # result = await recall(store=mock_store, query="test", silo_id="test-silo")
        # assert result.items[0].conflict_status == "unresolved"
        # assert result.items[0].credibility == 0.85
        # assert result.items[0].credibility_factors is not None
        pass  # TODO: Implement based on actual recall structure

    @pytest.mark.asyncio
    async def test_recall_result_has_unresolved_conflicts_flag(self, mock_store: AsyncMock) -> None:
        """Test that RecallResult has has_unresolved_conflicts flag."""
        pass  # TODO: Implement based on actual recall structure
```

- [ ] **Step 3: Update RecallItem to include conflict fields**

Add to the RecallItem dataclass/model:

```python
@dataclass
class RecallItem:
    # ... existing fields ...
    
    # Conflict fields
    conflict_status: str = "none"  # 'none' | 'unresolved' | 'resolved_*'
    has_active_conflicts: bool = False
    conflicting_nodes: list[str] | None = None
    
    # Credibility breakdown
    credibility: float = 0.0
    credibility_factors: dict | None = None
```

- [ ] **Step 4: Update RecallResult to include has_unresolved_conflicts**

```python
@dataclass
class RecallResult:
    items: list[RecallItem]
    has_unresolved_conflicts: bool = False  # True if any item has conflict_status='unresolved'
    # ... existing fields ...
```

- [ ] **Step 5: Update recall query to fetch conflict fields**

Add to the Cypher query in recall:

```cypher
RETURN n.id AS id,
       n.content AS content,
       n.properties.conflict_status AS conflict_status,
       n.properties.credibility AS credibility,
       n.properties.credibility_factors AS credibility_factors,
       -- ... other fields ...
```

- [ ] **Step 6: Update recall result building to set has_unresolved_conflicts**

```python
def build_recall_result(items: list[RecallItem]) -> RecallResult:
    has_unresolved = any(item.conflict_status == "unresolved" for item in items)
    return RecallResult(
        items=items,
        has_unresolved_conflicts=has_unresolved,
    )
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/sage/test_recall_conflict.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/context_service/mcp/tools/recall.py tests/sage/test_recall_conflict.py
git commit -m "feat(sage): surface conflict status and credibility in recall"
```

---

## Task 8: Add integration test for full conflict flow

**Files:**
- Create: `tests/sage/test_conflict_flow.py`

- [ ] **Step 1: Write integration test**

```python
# tests/sage/test_conflict_flow.py
"""Integration tests for conflict detection and consolidation flow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from context_service.sage.consolidation import ConsolidationWorker, ResolutionAction
from context_service.sage.transactions import tx2_store_claim


class TestConflictFlow:
    """Integration tests for end-to-end conflict handling."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        store = AsyncMock()
        store.execute_write = AsyncMock(return_value=[{"id": str(uuid.uuid4())}])
        return store

    @pytest.mark.asyncio
    async def test_full_conflict_detection_and_resolution(self, mock_store: AsyncMock) -> None:
        """Test full flow: store claim, detect conflict, resolve."""
        # Setup: existing claim
        mock_store.execute_query = AsyncMock(side_effect=[
            # Evidence validation for first claim
            [{"id": "evidence-1", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            # No conflicts for first claim
            [],
            # Corroboration for first claim
            [{"count": 1, "should_promote": False}],
        ])

        # Store first claim
        result1, events1 = await tx2_store_claim(
            store=mock_store,
            content="Python version is 3.11",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="agent-1",
            subject="python",
            predicate="version",
            object_value="3.11",
            source_tier="community",
            confidence=0.7,
        )

        assert len([e for e in events1 if e.event_type == "conflict_detected"]) == 0

        # Setup: second claim with conflict
        first_claim_id = str(result1.node_id)
        mock_store.execute_query = AsyncMock(side_effect=[
            # Evidence validation
            [{"id": "evidence-2", "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}],
            # Conflict detected: first claim
            [{"id": first_claim_id, "silo_id": "test-silo", "subject": "python", "predicate": "version", "object": "3.11", "state": "ACTIVE"}],
            # Corroboration
            [{"count": 1, "should_promote": False}],
        ])

        # Store conflicting claim
        result2, events2 = await tx2_store_claim(
            store=mock_store,
            content="Python version is 3.12",
            evidence_refs=["node:evidence-2"],
            silo_id="test-silo",
            agent_id="agent-2",
            subject="python",
            predicate="version",
            object_value="3.12",
            source_tier="authoritative",  # Higher tier
            confidence=0.9,
        )

        # Verify conflict was detected
        conflict_events = [e for e in events2 if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 1
        assert conflict_events[0].payload["conflict_type"] == "structural"

        # Process conflict via worker
        mock_store.execute_query = AsyncMock(side_effect=[
            # Node A signals (second claim - higher credibility)
            [{"id": str(result2.node_id), "credibility": 0.9, "corroboration_count": 1, "created_at": datetime.now(UTC).isoformat(), "created_by": "agent-2", "source_tier": "authoritative"}],
            # Node B signals (first claim - lower credibility)
            [{"id": first_claim_id, "credibility": 0.42, "corroboration_count": 1, "created_at": datetime.now(UTC).isoformat(), "created_by": "agent-1", "source_tier": "community"}],
        ])

        worker = ConsolidationWorker(store=mock_store)
        resolution = await worker.process_conflict(
            node_a=str(result2.node_id),
            node_b=first_claim_id,
            silo_id="test-silo",
        )

        # Higher credibility claim should win
        assert resolution.action == ResolutionAction.SUPERSEDE
        assert resolution.winner_id == str(result2.node_id)
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/sage/test_conflict_flow.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/sage/test_conflict_flow.py
git commit -m "test(sage): add integration test for conflict detection and resolution flow"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
uv run pytest tests/ -v
```

- [ ] **Run type check and lint**

```bash
uv run just check
```

- [ ] **Verify success criteria**

1. TX2 detects structural conflicts and creates bidirectional CONTRADICTS edges
2. `conflict_status` set correctly on conflicting nodes
3. CHECK_CORROBORATION is atomic (single query)
4. Credibility computed at write with full breakdown available
5. Consolidation worker processes ConflictDetected events
6. Deterministic resolver picks winner based on score formula
7. All Phase 1 tests still pass after rename
