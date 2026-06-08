# Wisdom Layer Split: Commitments vs Beliefs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate agent-declared Commitments from SAGE-synthesized Beliefs for cleaner epistemics

**Architecture:** Two Wisdom subtypes with different trust models. Commitments are agent decisions (created via `decide` or `commit`). Beliefs are system-synthesized (created by SAGE via ProposedBelief -> agent `accept`). ProposedBelief is an intermediate state requiring agent review before becoming a full Belief.

**Tech Stack:** Python 3.12 / FastAPI / FastMCP / Memgraph / Taskiq reactions

---

## File Structure

**New files:**
- `src/context_service/mcp/tools/decide.py` - Direct commitment tool
- `src/context_service/mcp/tools/accept.py` - Accept ProposedBelief tool
- `tests/mcp/tools/test_decide.py` - Unit tests for decide
- `tests/mcp/tools/test_accept.py` - Unit tests for accept
- `tests/sage/test_accept_proposal.py` - Transaction tests

**Modified files:**
- `src/context_service/sage/transactions.py` - Add AcceptProposalResult, accept_proposal()
- `src/context_service/reactions/events.py` - Add PROPOSAL_READY event type
- `src/context_service/db/queries.py` - Add GET_PROPOSED_BELIEF query (singular)
- `src/context_service/mcp/tools/dismiss.py` - Handle ProposedBelief rejection
- `src/context_service/mcp/tools/recall.py` - Include ProposedBeliefs in results
- `src/context_service/mcp/tools/registry.py` - Add decide, accept; remove believe from imports and dict
- `src/context_service/mcp/tools/__init__.py` - Add decide, accept; remove believe
- `src/context_service/config/mcp_tools.yaml` - Update tool surface
- `CLAUDE.md` - Update docs

**Deleted files:**
- `src/context_service/mcp/tools/believe.py`

---

## Existing Queries Reference

The following queries already exist in `db/queries.py` (lines 1467-1529):

```python
# CREATE_PROPOSED_BELIEF - params: id, silo_id, content, confidence, created_at, expires_at, synthesized_from_ids
# GET_PROPOSED_BELIEFS_FOR_SILO - params: silo_id, limit (returns multiple pending)
# ACCEPT_PROPOSED_BELIEF - params: proposed_belief_id, silo_id, accepted_at, belief_id, override_confidence
#   NOTE: Creates NEW Belief node linked via PROMOTED_FROM, not relabel
# REJECT_PROPOSED_BELIEF - params: proposed_belief_id, silo_id, rejected_at, reason
```

We only need to add `GET_PROPOSED_BELIEF` (singular) for fetching a single proposal by ID.

---

## Task 1: Add GET_PROPOSED_BELIEF Query

**Files:**
- Modify: `src/context_service/db/queries.py`
- Test: `tests/db/test_queries.py`

- [ ] **Step 1: Write test for GET_PROPOSED_BELIEF query**

```python
# tests/db/test_queries.py - add to existing file
@pytest.mark.asyncio
async def test_get_proposed_belief(graph_store: HyperGraphStore, silo_id: str) -> None:
    """GET_PROPOSED_BELIEF returns single proposal by ID."""
    from context_service.db import queries as q

    proposal_id = str(uuid.uuid4())

    # Create pending proposal
    await graph_store.execute_write(
        """
        CREATE (pb:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'test synthesis',
            confidence: 0.85, status: 'pending', created_at: datetime()
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )

    result = await graph_store.execute_query(
        q.GET_PROPOSED_BELIEF,
        {"proposed_belief_id": proposal_id, "silo_id": silo_id},
    )

    assert len(result) == 1
    assert result[0]["proposed_belief_id"] == proposal_id
    assert result[0]["content"] == "test synthesis"
    assert result[0]["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test -k test_get_proposed_belief -v`
Expected: FAIL with "GET_PROPOSED_BELIEF not defined"

- [ ] **Step 3: Add GET_PROPOSED_BELIEF query**

```python
# src/context_service/db/queries.py - add after GET_PROPOSED_BELIEFS_FOR_SILO (line ~1496)

GET_PROPOSED_BELIEF = """
MATCH (pb:ProposedBelief {id: $proposed_belief_id, silo_id: $silo_id})
OPTIONAL MATCH (pb)-[:SYNTHESIZED_FROM]->(f:Fact)
WITH pb, collect(f.id) AS source_fact_ids
RETURN pb.id AS proposed_belief_id,
       pb.content AS content,
       pb.confidence AS confidence,
       pb.status AS status,
       pb.created_at AS created_at,
       pb.accepted_at AS accepted_at,
       pb.rejected_at AS rejected_at,
       pb.rejection_reason AS rejection_reason,
       source_fact_ids
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test -k test_get_proposed_belief -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/db/queries.py tests/db/test_queries.py
git commit -m "feat(db): add GET_PROPOSED_BELIEF query for single proposal fetch"
```

---

## Task 2: Add PROPOSAL_READY Reaction Event

**Files:**
- Modify: `src/context_service/reactions/events.py`

- [ ] **Step 1: Add PROPOSAL_READY to ReactionEventType**

```python
# src/context_service/reactions/events.py - add to ReactionEventType enum (around line 43)

class ReactionEventType(StrEnum):
    # ... existing events ...
    CONSOLIDATE = "consolidate"
    PROPOSAL_READY = "proposal_ready"  # notification-only: ProposedBelief ready for agent review
```

- [ ] **Step 2: Update docstring to document notification-only events**

The docstring at lines 19-29 already documents notification-only events. Add PROPOSAL_READY:

```python
    """Typed event identifiers for async reaction processing.

    Most event types have corresponding task handlers in tasks.py. Four are
    notification-only signals with no handler - they are emitted for logging
    and observability but do not trigger task execution:

    - CASCADE_STALENESS_COMPLETE: Signals cascade finished (no action needed)
    - CONFLICT_DETECTED: Signals conflict found (handled inline, not async)
    - CHECK_EXTRACTION_TRIGGER: Reserved for future extraction pipeline
    - PROPOSAL_READY: ProposedBelief created, awaiting agent accept/dismiss
    """
```

- [ ] **Step 3: Run typecheck to verify**

Run: `just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/reactions/events.py
git commit -m "feat(reactions): add PROPOSAL_READY event type"
```

---

## Task 3: Add AcceptProposalResult and accept_proposal Transaction

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Test: `tests/sage/test_accept_proposal.py`

- [ ] **Step 1: Write test for accept_proposal transaction**

```python
# tests/sage/test_accept_proposal.py
"""Tests for accept_proposal transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from context_service.sage.transactions import (
    AcceptProposalResult,
    InvariantViolation,
    accept_proposal,
)


@pytest.fixture
async def pending_proposal(graph_store, silo_id: str) -> str:
    """Create a pending ProposedBelief for testing."""
    proposal_id = str(uuid.uuid4())
    await graph_store.execute_write(
        """
        CREATE (pb:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'Test synthesis',
            confidence: 0.85, status: 'pending', created_at: datetime()
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )
    return proposal_id


@pytest.mark.asyncio
async def test_accept_proposal_success(
    graph_store, silo_id: str, pending_proposal: str
) -> None:
    """Accept creates Belief from ProposedBelief."""
    result, events = await accept_proposal(
        store=graph_store,
        proposal_id=pending_proposal,
        silo_id=silo_id,
        agent_id="test-agent",
        reason="Verified against sources",
        emit=False,
    )

    assert isinstance(result, AcceptProposalResult)
    assert result.accepted is True
    # belief_id is a NEW node, not same as proposal_id
    assert result.belief_id is not None

    # Verify Belief was created and linked
    check = await graph_store.execute_query(
        """
        MATCH (b:Belief {id: $belief_id})-[:PROMOTED_FROM]->(pb:ProposedBelief {id: $proposal_id})
        RETURN b.id AS belief_id, pb.status AS proposal_status
        """,
        {"belief_id": str(result.belief_id), "proposal_id": pending_proposal},
    )
    assert len(check) == 1
    assert check[0]["proposal_status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_proposal_not_found(graph_store, silo_id: str) -> None:
    """Accept fails for non-existent proposal."""
    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=graph_store,
            proposal_id=str(uuid.uuid4()),
            silo_id=silo_id,
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "PROPOSAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_accept_proposal_already_rejected(graph_store, silo_id: str) -> None:
    """Accept fails for already rejected proposal."""
    proposal_id = str(uuid.uuid4())
    await graph_store.execute_write(
        """
        CREATE (pb:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'test',
            confidence: 0.8, status: 'rejected', created_at: datetime()
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=graph_store,
            proposal_id=proposal_id,
            silo_id=silo_id,
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "PROPOSAL_REJECTED"


@pytest.mark.asyncio
async def test_accept_proposal_already_accepted(
    graph_store, silo_id: str, pending_proposal: str
) -> None:
    """Accept is idempotent for already accepted proposals."""
    # First accept
    result1, _ = await accept_proposal(
        store=graph_store,
        proposal_id=pending_proposal,
        silo_id=silo_id,
        agent_id="test-agent",
        emit=False,
    )

    # Second accept - idempotent, returns same belief_id
    result2, _ = await accept_proposal(
        store=graph_store,
        proposal_id=pending_proposal,
        silo_id=silo_id,
        agent_id="test-agent",
        emit=False,
    )

    assert result2.accepted is True
    assert result2.belief_id == result1.belief_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/sage/test_accept_proposal.py -v`
Expected: FAIL with "cannot import name 'AcceptProposalResult'"

- [ ] **Step 3: Add AcceptProposalResult dataclass**

```python
# src/context_service/sage/transactions.py - add after CrystallizeResult (around line 218)

@dataclass
class AcceptProposalResult:
    """Result of accept_proposal transaction."""

    belief_id: uuid.UUID
    proposal_id: uuid.UUID
    accepted: bool
    accepted_at: datetime
    confidence: float
```

- [ ] **Step 4: Add accept_proposal transaction**

```python
# src/context_service/sage/transactions.py - add after crystallize function (around line 1418)

async def accept_proposal(
    store: HyperGraphStore,
    proposal_id: str,
    silo_id: str,
    agent_id: str,
    *,
    reason: str | None = None,
    override_confidence: float | None = None,
    emit: bool = True,
) -> tuple[AcceptProposalResult, list[ReactionEvent]]:
    """Accept a ProposedBelief, creating a full Belief.

    Uses existing ACCEPT_PROPOSED_BELIEF query which creates a NEW Belief node
    linked to ProposedBelief via PROMOTED_FROM edge.

    Args:
        store: Graph store instance.
        proposal_id: ProposedBelief node ID.
        silo_id: Tenant isolation ID.
        agent_id: Agent accepting the proposal.
        reason: Optional rationale for acceptance.
        override_confidence: Override the synthesized confidence.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        InvariantViolation: If proposal not found, already rejected, or invalid.
    """
    from context_service.db import queries as q

    # Check proposal exists and get status
    proposal_result = await store.execute_query(
        q.GET_PROPOSED_BELIEF,
        {"proposed_belief_id": proposal_id, "silo_id": silo_id},
    )

    if not proposal_result:
        raise InvariantViolation("PROPOSAL_NOT_FOUND", "ProposedBelief not found")

    row = proposal_result[0]
    status = row.get("status")

    # Already accepted - idempotent, find existing belief
    if status == "accepted":
        existing_belief = await store.execute_query(
            """
            MATCH (b:Belief)-[:PROMOTED_FROM]->(pb:ProposedBelief {id: $proposal_id, silo_id: $silo_id})
            RETURN b.id AS belief_id, b.confidence AS confidence
            """,
            {"proposal_id": proposal_id, "silo_id": silo_id},
        )
        if existing_belief:
            return AcceptProposalResult(
                belief_id=uuid.UUID(existing_belief[0]["belief_id"]),
                proposal_id=uuid.UUID(proposal_id),
                accepted=True,
                accepted_at=datetime.now(UTC),
                confidence=float(existing_belief[0].get("confidence", 0.8)),
            ), []
        raise InvariantViolation("INCONSISTENT_STATE", "Accepted proposal has no Belief")

    if status == "rejected":
        raise InvariantViolation(
            "PROPOSAL_REJECTED",
            "ProposedBelief was already rejected",
        )

    if status != "pending":
        raise InvariantViolation(
            "INVALID_STATUS",
            f"ProposedBelief has status {status!r}, expected 'pending'",
        )

    now = datetime.now(UTC)
    belief_id = uuid.uuid4()

    # Use existing ACCEPT_PROPOSED_BELIEF query
    accept_result = await store.execute_write(
        q.ACCEPT_PROPOSED_BELIEF,
        {
            "proposed_belief_id": proposal_id,
            "silo_id": silo_id,
            "accepted_at": now.isoformat(),
            "belief_id": str(belief_id),
            "override_confidence": override_confidence,
        },
    )

    if not accept_result:
        raise InvariantViolation("ACCEPT_FAILED", "Failed to accept proposal")

    final_confidence = float(accept_result[0].get("confidence", row.get("confidence", 0.8)))

    # Store acceptance metadata
    if reason:
        await store.execute_write(
            """
            MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
            SET b.acceptance_reason = $reason, b.accepted_by = $agent_id
            """,
            {"belief_id": str(belief_id), "silo_id": silo_id, "reason": reason, "agent_id": agent_id},
        )

    result = AcceptProposalResult(
        belief_id=belief_id,
        proposal_id=uuid.UUID(proposal_id),
        accepted=True,
        accepted_at=now,
        confidence=final_confidence,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(belief_id),
            silo_id=silo_id,
            payload={"access_type": "ACCEPT"},
        ),
        ReactionEvent(
            event_type=ReactionEventType.PROPAGATE_CONFIDENCE,
            node_id=str(belief_id),
            silo_id=silo_id,
        ),
    ]

    if emit:
        for event in events:
            await emit_reaction(event)

    logger.debug(
        "accept_proposal_complete",
        belief_id=str(belief_id),
        proposal_id=proposal_id,
        silo_id=silo_id,
        agent_id=agent_id,
    )

    return result, events
```

- [ ] **Step 5: Run test to verify it passes**

Run: `just test tests/sage/test_accept_proposal.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/sage/transactions.py tests/sage/test_accept_proposal.py
git commit -m "feat(sage): add accept_proposal transaction for wisdom layer split"
```

---

## Task 4: Add decide MCP Tool

**Files:**
- Create: `src/context_service/mcp/tools/decide.py`
- Test: `tests/mcp/tools/test_decide.py`

- [ ] **Step 1: Write test for decide tool**

```python
# tests/mcp/tools/test_decide.py
"""Tests for decide MCP tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    """Mock MCP auth context."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = "test-agent"
    auth.session_id = "test-session"
    return auth


@pytest.mark.asyncio
async def test_decide_creates_commitment(mock_auth) -> None:
    """decide creates a Commitment with ABOUT edges."""
    from context_service.mcp.tools.decide import _decide_impl
    from context_service.sage.transactions import CommitResult

    about_node = str(uuid.uuid4())

    mock_result = CommitResult(
        commitment_id=uuid.uuid4(),
        silo_id="test-silo",
        created_at=datetime.now(UTC),
        confidence=0.9,
    )

    with (
        patch("context_service.mcp.tools.decide.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.decide.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.decide.get_context_service") as mock_ctx,
        patch("context_service.mcp.tools.decide.tx_commit", new_callable=AsyncMock, return_value=(mock_result, [])),
    ):
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _decide_impl(
            decision="We will use PostgreSQL for persistence",
            about=[about_node],
            confidence=0.9,
        )

        assert "commitment_id" in result
        assert "error" not in result


@pytest.mark.asyncio
async def test_decide_requires_about(mock_auth) -> None:
    """decide fails without about nodes."""
    from context_service.mcp.tools.decide import _decide_impl

    with (
        patch("context_service.mcp.tools.decide.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.decide.track_tool_usage", new_callable=AsyncMock),
    ):
        result = await _decide_impl(
            decision="Some decision",
            about=[],
        )

        assert result["error"] == "missing_about"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/mcp/tools/test_decide.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.decide'"

- [ ] **Step 3: Create decide.py tool**

```python
# src/context_service/mcp/tools/decide.py
"""MCP tool: decide - Declare a decision/commitment directly."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation, commit as tx_commit
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("decide")
async def _decide_impl(
    decision: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Implementation for decide tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "decide")

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()
    agent_id = auth.agent_id or auth.org_id

    try:
        result, events = await tx_commit(
            store=ctx_svc.graph_store,
            content=decision,
            about_refs=about,
            silo_id=silo_id,
            agent_id=agent_id,
            confidence=confidence,
            metadata={"reasoning": reasoning} if reasoning else None,
            emit=False,
        )

        for event in events:
            await emit_reaction(event)

        record_belief_confidence(confidence, silo_id=silo_id)

        return {
            "commitment_id": str(result.commitment_id),
            "created_at": result.created_at.isoformat(),
            "confidence": result.confidence,
        }

    except InvariantViolation as e:
        return {
            "error": e.code,
            "message": e.message,
        }


def register(mcp: FastMCP) -> None:
    """Register the decide tool."""

    @mcp.tool(
        name="decide",
        description=get_tool_description("decide"),
    )
    @mcp_error_boundary
    async def decide(
        decision: str,
        about: list[str] | str,
        confidence: float = 0.8,
        reasoning: str | None = None,
    ) -> dict[str, Any]:
        """Declare a decision or commitment directly.

        Use this when you have made a decision that should be recorded.
        For tentative beliefs during reasoning, use hypothesize + commit instead.

        Args:
            decision: The decision or commitment being made.
            about: REQUIRED. Node IDs this decision references/concerns.
            confidence: 0.0-1.0 (default 0.8).
            reasoning: Optional rationale for the decision.

        Returns:
            {commitment_id, created_at, confidence}
        """
        start = time.perf_counter()
        success = True
        about_list = coerce_list(about)
        try:
            return await _decide_impl(decision, about_list, confidence, reasoning)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("decide", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test tests/mcp/tools/test_decide.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/decide.py tests/mcp/tools/test_decide.py
git commit -m "feat(mcp): add decide tool for direct commitments"
```

---

## Task 5: Add accept MCP Tool

**Files:**
- Create: `src/context_service/mcp/tools/accept.py`
- Test: `tests/mcp/tools/test_accept.py`

- [ ] **Step 1: Write test for accept tool**

```python
# tests/mcp/tools/test_accept.py
"""Tests for accept MCP tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    """Mock MCP auth context."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = "test-agent"
    return auth


@pytest.mark.asyncio
async def test_accept_promotes_proposal(mock_auth) -> None:
    """accept promotes ProposedBelief to Belief."""
    from context_service.mcp.tools.accept import _accept_impl
    from context_service.sage.transactions import AcceptProposalResult

    proposal_id = str(uuid.uuid4())
    belief_id = uuid.uuid4()

    mock_result = AcceptProposalResult(
        belief_id=belief_id,
        proposal_id=uuid.UUID(proposal_id),
        accepted=True,
        accepted_at=datetime.now(UTC),
        confidence=0.85,
    )

    with (
        patch("context_service.mcp.tools.accept.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.accept.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.accept.get_context_service") as mock_ctx,
        patch("context_service.mcp.tools.accept.accept_proposal", new_callable=AsyncMock, return_value=(mock_result, [])),
    ):
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _accept_impl(
            proposal_id=proposal_id,
            reason="Verified",
        )

        assert result["belief_id"] == str(belief_id)
        assert result["accepted"] is True
        assert "error" not in result


@pytest.mark.asyncio
async def test_accept_returns_error_for_not_found(mock_auth) -> None:
    """accept returns error for non-existent proposal."""
    from context_service.mcp.tools.accept import _accept_impl
    from context_service.sage.transactions import InvariantViolation

    with (
        patch("context_service.mcp.tools.accept.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.accept.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.accept.get_context_service") as mock_ctx,
        patch("context_service.mcp.tools.accept.accept_proposal", new_callable=AsyncMock) as mock_accept,
    ):
        mock_accept.side_effect = InvariantViolation("PROPOSAL_NOT_FOUND", "Not found")
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _accept_impl(
            proposal_id=str(uuid.uuid4()),
        )

        assert result["error"] == "PROPOSAL_NOT_FOUND"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/mcp/tools/test_accept.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.accept'"

- [ ] **Step 3: Create accept.py tool**

```python
# src/context_service/mcp/tools/accept.py
"""MCP tool: accept - Accept a ProposedBelief, promoting it to Belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation, accept_proposal
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("accept")
async def _accept_impl(
    proposal_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for accept tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "accept")

    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()
    agent_id = auth.agent_id or auth.org_id

    try:
        result, events = await accept_proposal(
            store=ctx_svc.graph_store,
            proposal_id=proposal_id,
            silo_id=silo_id,
            agent_id=agent_id,
            reason=reason,
            emit=False,
        )

        for event in events:
            await emit_reaction(event)

        return {
            "belief_id": str(result.belief_id),
            "proposal_id": str(result.proposal_id),
            "accepted": result.accepted,
            "accepted_at": result.accepted_at.isoformat(),
            "confidence": result.confidence,
        }

    except InvariantViolation as e:
        return {
            "error": e.code,
            "message": e.message,
        }


def register(mcp: FastMCP) -> None:
    """Register the accept tool."""

    @mcp.tool(
        name="accept",
        description=get_tool_description("accept"),
    )
    @mcp_error_boundary
    async def accept(
        proposal_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Accept a ProposedBelief, promoting it to a full Belief.

        ProposedBeliefs are created by SAGE synthesis. Use accept to confirm
        you agree with the synthesized belief. Use dismiss to reject it.

        Args:
            proposal_id: The ProposedBelief node ID.
            reason: Optional rationale for acceptance.

        Returns:
            {belief_id, proposal_id, accepted, accepted_at, confidence}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _accept_impl(proposal_id, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("accept", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test tests/mcp/tools/test_accept.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/accept.py tests/mcp/tools/test_accept.py
git commit -m "feat(mcp): add accept tool for ProposedBelief promotion"
```

---

## Task 6: Update dismiss Tool to Handle ProposedBelief Rejection

**Files:**
- Modify: `src/context_service/mcp/tools/dismiss.py`
- Test: `tests/mcp/tools/test_dismiss.py`

- [ ] **Step 1: Write test for dismiss rejecting ProposedBelief**

```python
# tests/mcp/tools/test_dismiss.py - add to existing tests

@pytest.mark.asyncio
async def test_dismiss_rejects_proposed_belief(graph_store, silo_id: str, redis_client) -> None:
    """dismiss rejects a ProposedBelief."""
    from context_service.mcp.tools.dismiss import _dismiss_marker

    # Create pending ProposedBelief
    proposal_id = str(uuid.uuid4())
    await graph_store.execute_write(
        """
        CREATE (pb:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'test',
            confidence: 0.8, status: 'pending', created_at: datetime()
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )

    result = await _dismiss_marker(
        marker_id=proposal_id,
        reason="Factually incorrect",
        silo_id=silo_id,
    )

    assert result.get("status") == "rejected"
    assert result.get("proposal_id") == proposal_id

    # Verify status changed in graph
    check = await graph_store.execute_query(
        "MATCH (pb:ProposedBelief {id: $id}) RETURN pb.status AS status",
        {"id": proposal_id},
    )
    assert check[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_dismiss_rejects_only_pending_proposals(graph_store, silo_id: str, redis_client) -> None:
    """dismiss fails for already-rejected ProposedBelief."""
    from context_service.mcp.tools.dismiss import _dismiss_marker

    proposal_id = str(uuid.uuid4())
    await graph_store.execute_write(
        """
        CREATE (pb:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'test',
            confidence: 0.8, status: 'rejected', created_at: datetime()
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )

    result = await _dismiss_marker(
        marker_id=proposal_id,
        reason="Try again",
        silo_id=silo_id,
    )

    assert result.get("error") == "invalid_status"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/mcp/tools/test_dismiss.py::test_dismiss_rejects_proposed_belief -v`
Expected: FAIL (current code returns error telling user to use 'reject' verb)

- [ ] **Step 3: Update _dismiss_marker to handle ProposedBelief rejection**

```python
# src/context_service/mcp/tools/dismiss.py - replace lines 18-85

async def _dismiss_marker(
    marker_id: str,
    reason: str,
    silo_id: str,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from datetime import UTC, datetime

    from context_service.db import queries as q
    from context_service.engine.markers import dismiss_marker, get_marker_details
    from context_service.mcp.server import get_context_service, get_redis

    ctx = get_context_service()
    store = ctx.graph_store

    # Check if this is a ProposedBelief first
    proposal_check = await store.execute_query(
        "MATCH (pb:ProposedBelief {id: $id, silo_id: $silo_id}) RETURN pb.status AS status",
        {"id": marker_id, "silo_id": silo_id},
    )

    if proposal_check:
        status = proposal_check[0].get("status")
        if status != "pending":
            return {
                "error": "invalid_status",
                "message": f"ProposedBelief has status {status!r}, expected 'pending'",
            }

        # Reject the ProposedBelief using existing query
        now = datetime.now(UTC)
        reject_result = await store.execute_write(
            q.REJECT_PROPOSED_BELIEF,
            {
                "proposed_belief_id": marker_id,
                "silo_id": silo_id,
                "rejected_at": now.isoformat(),
                "reason": reason,
            },
        )

        if not reject_result:
            return {
                "error": "reject_failed",
                "message": "Failed to reject ProposedBelief",
            }

        return {
            "proposal_id": marker_id,
            "status": "rejected",
            "reason": reason,
            "rejected_at": now.isoformat(),
        }

    # Not a ProposedBelief - handle as regular marker
    redis_client = get_redis()
    if redis_client is None:
        return {
            "error": "service_unavailable",
            "message": "Redis is not configured",
        }
    redis = redis_client._redis

    # Fetch marker to validate it exists and check type/status
    details = await get_marker_details(store, silo_id, [marker_id])
    if not details:
        return {
            "error": "not_found",
            "message": f"Marker {marker_id!r} not found",
        }

    marker = details[0]
    status = marker.get("status")

    # Only pending markers can be dismissed
    if status != "pending":
        return {
            "error": "invalid_status",
            "message": f"Marker {marker_id!r} has status {status!r}, expected 'pending'",
        }

    result = await dismiss_marker(
        store=store,
        redis=redis,
        silo_id=silo_id,
        marker_id=marker_id,
        reason=reason,
    )

    # Clear touch counter so the agent can recall normally again.
    import contextlib

    from context_service.engine.touch_counter import clear_touches

    with contextlib.suppress(Exception):
        await clear_touches(redis, silo_id, marker_id)

    return {
        "marker_id": result["marker_id"],
        "status": "dismissed",
        "reason": result.get("resolution"),
        "resolved_at": result.get("resolved_at"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test tests/mcp/tools/test_dismiss.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/dismiss.py tests/mcp/tools/test_dismiss.py
git commit -m "feat(mcp): extend dismiss to handle ProposedBelief rejection"
```

---

## Task 7: Remove believe Tool and Update Registry

**Files:**
- Delete: `src/context_service/mcp/tools/believe.py`
- Modify: `src/context_service/mcp/tools/__init__.py`
- Modify: `src/context_service/mcp/tools/registry.py`

- [ ] **Step 1: Update registry.py - add decide, accept imports and remove believe**

```python
# src/context_service/mcp/tools/registry.py - replace register_tools function (lines 51-102)

def register_tools(mcp: FastMCP) -> None:
    """Register all MCP tools.

    Args:
        mcp: FastMCP server instance.

    Note: Imports are inside function to avoid circular imports,
    since tool modules import from registry.
    """
    from context_service.mcp.tools import (
        accept,
        commit,
        decide,
        dismiss,
        forget,
        history,
        hypothesize,
        learn,
        link,
        patterns,
        reason,
        recall,
        reflect,
        remember,
        revise,
        tick,
        trace,
    )

    tool_registers = {
        "remember": remember.register,
        "learn": learn.register,
        "recall": recall.register,
        "trace": trace.register,
        "history": history.register,
        "link": link.register,
        "reason": reason.register,
        "reflect": reflect.register,
        "hypothesize": hypothesize.register,
        "revise": revise.register,
        "commit": commit.register,
        "decide": decide.register,
        "accept": accept.register,
        "dismiss": dismiss.register,
        "tick": tick.register,
        "patterns": patterns.register,
        "forget": forget.register,
    }

    for name, register_fn in tool_registers.items():
        register_fn(mcp)
        logger.debug("mcp_tool_registered", tool=name)

    logger.info("mcp_tools_registered", tool_count=len(tool_registers))
```

- [ ] **Step 2: Update __init__.py**

```python
# src/context_service/mcp/tools/__init__.py
"""MCP tool implementations -- intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Intent-based tools (external-facing)
from context_service.mcp.tools import (
    accept,
    commit,
    decide,
    dismiss,
    forget,
    history,
    hypothesize,
    learn,
    link,
    patterns,
    reason,
    recall,
    reflect,
    remember,
    revise,
    tick,
    trace,
)

# Registry
from context_service.mcp.tools.registry import register_tools


def register_all(mcp: FastMCP) -> None:
    """Register all MCP tools.

    This is the main entry point. Use this instead of individual registers.
    """
    register_tools(mcp)


__all__ = [
    "register_all",
    "register_tools",
    # Individual tool modules
    "remember",
    "learn",
    "recall",
    "trace",
    "history",
    "link",
    "reason",
    "reflect",
    "hypothesize",
    "revise",
    "commit",
    "decide",
    "accept",
    "dismiss",
    "forget",
    "tick",
    "patterns",
]
```

- [ ] **Step 3: Delete believe.py**

```bash
git rm src/context_service/mcp/tools/believe.py
```

- [ ] **Step 4: Run check to verify no import errors**

Run: `just check`
Expected: PASS

- [ ] **Step 5: Delete believe test file if exists**

```bash
git rm tests/mcp/tools/test_believe.py 2>/dev/null || true
```

- [ ] **Step 6: Run tests to verify nothing broke**

Run: `just test -k "mcp" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/mcp/tools/__init__.py src/context_service/mcp/tools/registry.py
git commit -m "refactor(mcp): remove believe tool, add decide and accept to registry"
```

---

## Task 8: Update mcp_tools.yaml

**Files:**
- Modify: `src/context_service/config/mcp_tools.yaml`

- [ ] **Step 1: Update mcp_tools.yaml - remove believe, add decide and accept**

```yaml
# src/context_service/config/mcp_tools.yaml
# MCP Tool Surface Configuration

mcp_instructions: |
  Engrammic: Epistemic memory for AI agents.

  Quick start:
  - remember: store observations
  - learn: record claims WITH evidence
  - decide: declare decisions/commitments
  - recall: search your knowledge
  - trace: understand why you believe something (provenance)
  - history: see how a belief evolved over time (versioning)
  - link: connect related knowledge

  Always recall before you store, and at the start of a task.

  Supersession pattern (important):
  Before storing, recall to check if you're updating existing knowledge.
  If found, pass supersedes:<node_id> to chain the update.

  Example:
    1. recall("API authentication method")
    2. Found node abc123: "The API uses OAuth2"
    3. learn("The API uses OAuth2 with PKCE", evidence=[...], supersedes="abc123")

  This creates a version chain - old node stays for history, new node becomes current.
  Use history(node_id) to view the full chain. If you skip recall, duplicates may exist
  (Custodian catches these later, but explicit is better).

  Guidelines:
  - Always provide evidence when using learn
  - Hint source_tier on learn when you know the source quality (authoritative for .gov/.edu, validated for curated data)
  - Reference existing nodes when forming decisions
  - Recall before storing to check for supersession opportunities

  Reasoning flow (hypothesize/commit):
  - hypothesize creates session-scoped tentative beliefs
  - commit promotes them to permanent commitments WITHIN THE SAME SESSION
  - If session ends without commit, hypotheses are garbage collected
  - For direct decisions, use decide instead

  Belief acceptance flow:
  - SAGE synthesizes beliefs from corroborated facts
  - ProposedBeliefs appear in recall results with status="pending"
  - Use accept to promote to full Belief, or dismiss to reject

  Onboarding:
  - At session start, call patterns(action='get', name='onboarding') for your workflow guide

tools:
  remember:
    description: |
      Store an observation to memory. Returns immediately; node becomes
      searchable within ~500ms (async embedding). For immediate recall,
      use the returned node_id with recall(node_ids=[...]). No evidence
      required. Consider recall first - if updating existing knowledge,
      pass supersedes:<node_id>.
    maps_to: memory

  learn:
    description: |
      Record a claim with evidence. Returns immediately; node becomes
      searchable within ~500ms (async embedding). For immediate recall,
      use the returned node_id with recall(node_ids=[...]). Recall first
      to check for existing claims - pass supersedes:<node_id> to update.
      Optionally hint source_tier.
    maps_to: knowledge

  decide:
    description: |
      Declare a decision or commitment. Use when you have decided something.
      Requires 'about' nodes to reference. For tentative beliefs during
      reasoning, use hypothesize + commit instead. Recall first - pass
      supersedes:<node_id> if updating a prior decision.
    maps_to: commitment

  accept:
    description: |
      Accept a ProposedBelief, promoting it to a full Belief. ProposedBeliefs
      are created by SAGE synthesis from corroborated facts. They appear in
      recall results with status="pending". Use dismiss to reject instead.
    maps_to: belief

  recall:
    description: |
      Search or fetch knowledge. Call this at the START of any task and
      before storing anything (to supersede, not duplicate). Use query for
      semantic search, node_ids for direct fetch, query="*" to list all.
      Low-confidence and unresolved-contradiction memories are withheld by
      default and reported as a withheld count; pass include_withheld=true
      to see them. min_threshold overrides the relevance cutoff (0.0-1.0).
      ProposedBeliefs appear with status="pending" for your review.
    maps_to: retrieve

  trace:
    description: "Trace the provenance of a belief back to its sources."
    maps_to: provenance

  history:
    description: |
      Show how a belief evolved over time. Returns the supersession chain
      from oldest to newest. Use when you need to understand how knowledge
      changed, not just what it is now.
    maps_to: history

  link:
    description: "Create a typed relationship between nodes."
    maps_to: link

  reason:
    description: "Record explicit reasoning steps for complex problems."
    maps_to: intelligence

  reflect:
    description: "Record a meta-observation about your knowledge."
    maps_to: meta

  hypothesize:
    description: "Form a tentative belief during reasoning. SESSION-SCOPED: must call commit within the same session to persist. For direct decisions, use decide instead."
    maps_to: belief

  revise:
    description: "Update a tentative hypothesis when new information arrives. Only works within the session that created the hypothesis."
    maps_to: update_belief

  commit:
    description: "Promote tentative hypotheses to permanent commitments. MUST be called in the same session as hypothesize - hypotheses do not survive session boundaries."
    maps_to: crystallize

  forget:
    description: "Request deletion of a node. The node enters a cancel window before permanent deletion."
    maps_to: forget

  dismiss:
    description: "Dismiss a marker or reject a ProposedBelief. Use for false positives, acknowledged issues, or beliefs you disagree with."
    maps_to: marker

  patterns:
    description: "Discover workflow templates for common tasks."
    maps_to: skills

  tick:
    description: "Lightweight engagement check. Returns pending markers without a full recall. Safe to call frequently; zero side effects. Optionally scope to specific node IDs via about_hint."
    maps_to: engagement
```

- [ ] **Step 2: Run check**

Run: `just check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml
git commit -m "docs(mcp): update tool surface for wisdom layer split - decide/accept verbs"
```

---

## Task 9: Update recall to Include ProposedBeliefs

**Files:**
- Modify: `src/context_service/mcp/tools/context_recall.py`

- [ ] **Step 1: Check current recall behavior**

The recall tool should already include ProposedBeliefs since they're in the graph. We need to ensure they're surfaced with clear status indicator.

- [ ] **Step 2: Update _context_recall to include proposal status in results**

In `context_recall.py`, ensure the result mapping includes `status` field for ProposedBeliefs:

```python
# src/context_service/mcp/tools/context_recall.py - in the result mapping section

# When mapping results, include status for ProposedBeliefs
def _format_result(node: dict[str, Any]) -> dict[str, Any]:
    """Format a node for recall response."""
    result = {
        "id": node.get("id"),
        "content": node.get("content"),
        "layer": node.get("layer"),
        "type": node.get("type"),
        "confidence": node.get("confidence"),
        "created_at": node.get("created_at"),
    }
    # Include status for ProposedBeliefs
    if node.get("type") == "ProposedBelief" or node.get("status"):
        result["status"] = node.get("status", "active")
    return result
```

- [ ] **Step 3: Add test for ProposedBelief in recall results**

```python
# tests/mcp/tools/test_recall.py - add test

@pytest.mark.asyncio
async def test_recall_includes_proposed_beliefs_with_status(graph_store, silo_id: str) -> None:
    """recall returns ProposedBeliefs with status field."""
    proposal_id = str(uuid.uuid4())
    await graph_store.execute_write(
        """
        CREATE (pb:Node:ProposedBelief {
            id: $id, silo_id: $silo_id, content: 'pending synthesis',
            type: 'ProposedBelief', properties: {layer: 'wisdom', status: 'pending'}
        })
        """,
        {"id": proposal_id, "silo_id": silo_id},
    )
    # Ensure embedding exists for search
    # ... test implementation
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_recall.py tests/mcp/tools/test_recall.py
git commit -m "feat(mcp): ensure recall includes ProposedBelief status"
```

---

## Task 10: Modify synthesize Transaction to Create ProposedBelief

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Update synthesize to use CREATE_PROPOSED_BELIEF query**

In `transactions.py`, modify the `synthesize` function (around lines 486-520) to create ProposedBelief instead of Belief:

```python
# src/context_service/sage/transactions.py - in synthesize function, replace belief creation block

        # Create ProposedBelief (not Belief directly - requires agent accept)
        belief_id = uuid.uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(days=7)  # 7-day expiry for unreviewed proposals

        await store.execute_write(
            q.CREATE_PROPOSED_BELIEF,
            {
                "id": str(belief_id),
                "silo_id": silo_id,
                "content": synthesis_result.content,
                "confidence": aggregate_confidence,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "synthesized_from_ids": fact_ids,
            },
        )

        # Update cluster
        await store.execute_write(
            q.UPDATE_CLUSTER_AFTER_SYNTHESIS,
            {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.SYNTHESIZED.value,
                "belief_id": str(belief_id),
                "synthesized_at": created_at.isoformat(),
            },
        )

        events: list[ReactionEvent] = [
            ReactionEvent(
                event_type=ReactionEventType.COMPUTE_EMBEDDING,
                node_id=str(belief_id),
                silo_id=silo_id,
            ),
            ReactionEvent(
                event_type=ReactionEventType.UPDATE_HEAT,
                node_id=str(belief_id),
                silo_id=silo_id,
                payload={"access_type": "SYNTHESIS"},
            ),
            # Notify agents that a proposal is ready for review
            ReactionEvent(
                event_type=ReactionEventType.PROPOSAL_READY,
                node_id=str(belief_id),
                silo_id=silo_id,
            ),
        ]
```

- [ ] **Step 2: Update SynthesizeResult docstring**

```python
@dataclass
class SynthesizeResult:
    """Result of TX4 SYNTHESIZE.
    
    Note: belief_id is a ProposedBelief ID. Agent must call accept_proposal
    to promote it to a full Belief.
    """

    belief_id: uuid.UUID | None  # ProposedBelief ID until accepted
    cluster_id: str
    cluster_state: ClusterState
    fact_count: int
    confidence: float | None
    timed_out: bool = False
```

- [ ] **Step 3: Run synthesize tests**

Run: `just test -k synthesize -v`
Expected: PASS (may need test updates)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): synthesize creates ProposedBelief instead of Belief"
```

---

## Task 11: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update MCP tool surface table**

```markdown
## MCP tool surface

Source of truth: `src/context_service/config/mcp_tools.yaml`. Names and descriptions are config, not code. The surface is intent/verb-based.

| Tool | Maps to |
|------|---------|
| `remember` | memory (observation, no evidence) |
| `learn` | knowledge (claim, evidence required) |
| `decide` | commitment (agent decision, requires about nodes) |
| `accept` | promote ProposedBelief to Belief |
| `recall` | retrieval (query or node_id) |
| `trace` | provenance (where did this come from?) |
| `history` | versioning (how did this evolve?) |
| `link` | typed relationship |
| `reason` | intelligence (reasoning steps) |
| `reflect` | meta-observation |
| `hypothesize` | tentative belief (finalize with `commit`) |
| `revise` | update tentative belief |
| `commit` | crystallize hypotheses |
| `forget` | request node deletion |
| `patterns` | skills / workflow templates |
| `dismiss` | dismiss marker or reject ProposedBelief |
| `tick` | acknowledge engagement without action |
```

- [ ] **Step 2: Update Belief architecture section**

```markdown
## Belief architecture

Two Wisdom subtypes with different trust models:

**Commitments (agent decisions):**
- Created via `decide` (direct) or `commit` (from hypotheses)
- Agent-scoped trust: "this agent decided"
- No synthesis chain required

**Beliefs (system-synthesized):**
- Created by SAGE synthesizer as ProposedBelief
- Require agent `accept` to promote to full Belief
- System-scoped trust: "corroborated from facts"
- Full provenance chain (SYNTHESIZED_FROM edges to Facts)
- Use `dismiss` to reject

**Formation flows:**
```
Agent observes    -> remember()     -> Memory (decays)
Agent claims      -> learn()        -> Claim (Knowledge)
System verifies   -> [custodian]    -> Fact (Knowledge, promoted)
System clusters   -> [custodian]    -> Cluster reaches threshold
System synthesizes-> [synthesizer]  -> ProposedBelief (pending)
Agent reviews     -> accept/dismiss -> Belief (Wisdom) or rejected
Agent decides     -> decide()       -> Commitment (Wisdom)
Agent reasons     -> hypothesize()  -> WorkingHypothesis (Intelligence)
Agent crystallizes-> commit()       -> Commitment (from hypothesis)
```

Agent-facing verbs: `decide` for direct decisions, `hypothesize` then `commit` for reasoning, `accept` to approve SAGE synthesis.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for wisdom layer split"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
just ci
```
Expected: PASS

- [ ] **Step 2: Verify tool registration**

```bash
uv run python -c "
from context_service.mcp.tools.registry import get_tool_description
print('decide:', get_tool_description('decide')[:50])
print('accept:', get_tool_description('accept')[:50])
try:
    get_tool_description('believe')
    print('ERROR: believe still has description')
except:
    pass
print('Verification complete')
"
```

- [ ] **Step 3: Create PR**

```bash
git push -u origin feat/wisdom-layer-split
gh pr create --title "feat: wisdom layer split - decide/accept verbs" --body "$(cat <<'EOF'
## Summary
- Separate Commitments (agent decisions) from Beliefs (SAGE-synthesized)
- Add `decide` tool for direct commitment creation
- Add `accept` tool for ProposedBelief promotion
- Remove `believe` tool (replaced by decide/accept)
- Update `dismiss` to handle ProposedBelief rejection
- Modify `synthesize` to create ProposedBelief instead of Belief

## Breaking Changes
- `believe` tool removed - use `decide` for decisions, `accept` for beliefs

## Test plan
- [ ] Run `just ci` - all tests pass
- [ ] Test `decide` creates Commitment with ABOUT edges
- [ ] Test `accept` promotes ProposedBelief to Belief
- [ ] Test `dismiss` rejects ProposedBelief
- [ ] Verify `believe` is no longer available

Generated with Claude Code
EOF
)"
```

---

## Success Criteria

1. All Wisdom nodes have clear `type` discriminator (commitment | belief | proposed_belief)
2. `believe` tool removed from MCP surface entirely
3. `decide` and `accept` tools working and documented
4. SAGE synthesizer creates ProposedBeliefs, not Beliefs directly
5. ProposedBeliefs surface in recall with `status: pending`
6. `accept` promotes ProposedBelief -> Belief with PROMOTED_FROM edge
7. `dismiss` on ProposedBelief sets status to rejected
8. Audit trail clearly distinguishes "agent decided" from "system learned"
9. All docs updated, no stale references to `believe`
