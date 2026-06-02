"""Integration test for conflict detection and resolution flow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.sage.consolidation import (
    ConsolidationWorker,
    ResolutionAction,
)
from context_service.sage.transactions import (
    ConflictStatus,
    store_claim,
)

SILO = "test-silo"
SUBJECT = "python-version"
PREDICATE = "is"


def make_evidence_id() -> str:
    return str(uuid.uuid4())


def make_node_id() -> str:
    return str(uuid.uuid4())


def _evidence_row(evidence_id: str, silo: str = SILO) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "silo_id": silo,
        "layer": "memory",
        "state": "ACTIVE",
    }


class TestConflictFlow:
    """Integration test: conflict detection via TX2 and resolution via ConsolidationWorker."""

    @pytest.mark.asyncio
    async def test_full_conflict_detection_and_resolution(self) -> None:
        """End-to-end: store two conflicting claims, detect conflict, resolve via credibility.

        Steps:
        1. Store first claim with subject/predicate/object (no conflict yet).
        2. Store second claim with same subject/predicate but different object -
           should emit conflict_detected event.
        3. Verify conflict_detected event was emitted with correct payload.
        4. Process conflict via ConsolidationWorker.
        5. Verify the higher credibility claim wins (authoritative > unknown).
        """
        evidence_id_1 = make_evidence_id()
        evidence_id_2 = make_evidence_id()

        # --- Step 1: Store first claim (no conflict) ---
        store_first = AsyncMock()

        # execute_query calls during store_claim for first claim:
        #   [0] evidence validation -> returns the memory node
        #   [1] conflict detection  -> returns [] (no conflicts yet)
        store_first.execute_query = AsyncMock(
            side_effect=[
                [_evidence_row(evidence_id_1)],
                [],  # No conflicting claims
            ]
        )
        # execute_write calls: CREATE claim, DERIVED_FROM edges, corroboration check
        store_first.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        result_first, events_first = await store_claim(
            store=store_first,
            content="python-version is 3.11",
            evidence_refs=[f"node:{evidence_id_1}"],
            silo_id=SILO,
            agent_id="agent-alpha",
            subject=SUBJECT,
            predicate=PREDICATE,
            object_value="3.11",
            source_tier="authoritative",
            confidence=0.9,
        )

        first_claim_id = str(result_first.node_id)

        # First claim: no conflict events expected
        conflict_events_first = [e for e in events_first if e.event_type == "conflict_detected"]
        assert len(conflict_events_first) == 0, (
            "First claim should not emit conflict_detected (no prior conflicting claim)"
        )

        # --- Step 2: Store second claim with same s/p, different object ---
        store_second = AsyncMock()

        # execute_query calls during store_claim for second claim:
        #   [0] evidence validation -> returns the memory node
        #   [1] conflict detection  -> returns first_claim_id (conflict!)
        store_second.execute_query = AsyncMock(
            side_effect=[
                [_evidence_row(evidence_id_2)],
                [{"id": first_claim_id}],  # Existing claim with different object
            ]
        )
        store_second.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        result_second, events_second = await store_claim(
            store=store_second,
            content="python-version is 3.12",
            evidence_refs=[f"node:{evidence_id_2}"],
            silo_id=SILO,
            agent_id="agent-beta",
            subject=SUBJECT,
            predicate=PREDICATE,
            object_value="3.12",
            source_tier="unknown",
            confidence=0.5,
        )

        second_claim_id = str(result_second.node_id)

        # --- Step 3: Verify conflict_detected event was emitted ---
        conflict_events_second = [e for e in events_second if e.event_type == "conflict_detected"]
        assert len(conflict_events_second) == 1, (
            "Second claim with same subject+predicate but different object should emit "
            "exactly one conflict_detected event"
        )

        conflict_event = conflict_events_second[0]
        assert conflict_event.silo_id == SILO
        assert conflict_event.payload["conflict_type"] == "structural"
        assert conflict_event.payload["node_b"] == first_claim_id
        assert conflict_event.payload["node_a"] == second_claim_id

        # Bidirectional CONTRADICTS edges should have been written
        write_calls = store_second.execute_write.call_args_list
        contradicts_calls = [c for c in write_calls if "CONTRADICTS" in str(c)]
        assert len(contradicts_calls) >= 1, "CONTRADICTS edges should be created"

        # conflict_status = 'unresolved' should be set on both nodes
        status_calls = [c for c in write_calls if ConflictStatus.UNRESOLVED.value in str(c)]
        assert len(status_calls) >= 1, "conflict_status should be set to 'unresolved'"

        # --- Step 4: Process conflict via ConsolidationWorker ---
        now_iso = datetime.now(UTC).isoformat()
        earlier_iso = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

        # The first claim is authoritative (higher credibility); second is unknown (lower).
        # DeterministicResolver uses: tier_weight * log(1+corroboration) * freshness.
        # authoritative weight (1.0) > unknown weight (0.4), so first claim wins.
        store_worker = AsyncMock()
        store_worker.execute_query = AsyncMock(
            return_value=[
                {
                    "id": first_claim_id,
                    "credibility": 0.9,
                    "corroboration_count": 1,
                    "created_at": earlier_iso,
                    "agent_id": "agent-alpha",
                    "source_tier": "authoritative",
                },
                {
                    "id": second_claim_id,
                    "credibility": 0.2,
                    "corroboration_count": 1,
                    "created_at": now_iso,
                    "agent_id": "agent-beta",
                    "source_tier": "unknown",
                },
            ]
        )
        store_worker.execute_write = AsyncMock(return_value=[])

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            mock_tx3.return_value = (MagicMock(), [])

            worker = ConsolidationWorker()
            resolution = await worker.process_conflict(
                store=store_worker,
                node_a_id=first_claim_id,
                node_b_id=second_claim_id,
                silo_id=SILO,
            )

        # --- Step 5: Verify higher credibility claim wins ---
        assert resolution.action == ResolutionAction.SUPERSEDE, (
            "DeterministicResolver should resolve via SUPERSEDE (not defer)"
        )
        assert resolution.winner_id == first_claim_id, (
            "The authoritative claim (first) should win over the unknown-tier claim (second)"
        )
        assert resolution.loser_id == second_claim_id, (
            "The unknown-tier claim (second) should be the loser"
        )

        # TX3 supersede should have been called with correct args
        mock_tx3.assert_awaited_once()
        call_kwargs = mock_tx3.call_args.kwargs
        assert call_kwargs["winner_id"] == first_claim_id
        assert call_kwargs["loser_id"] == second_claim_id
        assert call_kwargs["silo_id"] == SILO
