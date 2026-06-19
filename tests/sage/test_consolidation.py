"""Tests for sage consolidation: DeterministicResolver and ConsolidationWorker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.sage.consolidation import (
    ConflictSignals,
    ConsolidationWorker,
    DeterministicResolver,
    LLMResolver,
    ResolutionAction,
    ResolutionResult,
    _score,
)
from context_service.sage.transactions import SupersedeReason

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_signals(
    *,
    node_id: str | None = None,
    credibility: float = 0.8,
    corroboration_count: int = 1,
    created_at: datetime | None = None,
    agent_id: str = "agent-a",
    source_tier: str = "validated",
) -> ConflictSignals:
    return ConflictSignals(
        node_id=node_id or str(uuid.uuid4()),
        credibility=credibility,
        corroboration_count=corroboration_count,
        created_at=created_at or datetime.now(UTC),
        agent_id=agent_id,
        source_tier=source_tier,
    )


def make_store() -> AsyncMock:
    store = AsyncMock()
    store.execute_write = AsyncMock(return_value=[])
    store.execute_query = AsyncMock(return_value=[])
    return store


class _DeferResolver:
    """Test-only resolver that always defers."""

    def resolve(self, _a: ConflictSignals, _b: ConflictSignals) -> ResolutionResult:
        return ResolutionResult(
            action=ResolutionAction.DEFER,
            winner_id=None,
            loser_id=None,
            rationale="test defer",
        )


# ---------------------------------------------------------------------------
# ResolutionAction enum
# ---------------------------------------------------------------------------


class TestResolutionAction:
    def test_supersede_value(self) -> None:
        assert ResolutionAction.SUPERSEDE == "supersede"

    def test_defer_value(self) -> None:
        assert ResolutionAction.DEFER == "defer"


# ---------------------------------------------------------------------------
# ConflictSignals dataclass
# ---------------------------------------------------------------------------


class TestConflictSignals:
    def test_fields(self) -> None:
        ts = datetime.now(UTC)
        sig = ConflictSignals(
            node_id="n1",
            credibility=0.9,
            corroboration_count=3,
            created_at=ts,
            agent_id="agent-x",
            source_tier="authoritative",
        )
        assert sig.node_id == "n1"
        assert sig.credibility == 0.9
        assert sig.corroboration_count == 3
        assert sig.created_at == ts
        assert sig.agent_id == "agent-x"
        assert sig.source_tier == "authoritative"


# ---------------------------------------------------------------------------
# ResolutionResult dataclass
# ---------------------------------------------------------------------------


class TestResolutionResult:
    def test_supersede_result(self) -> None:
        r = ResolutionResult(
            action=ResolutionAction.SUPERSEDE,
            winner_id="w",
            loser_id="l",
            rationale="score",
        )
        assert r.action == ResolutionAction.SUPERSEDE
        assert r.winner_id == "w"
        assert r.loser_id == "l"

    def test_defer_result_has_none_ids(self) -> None:
        r = ResolutionResult(
            action=ResolutionAction.DEFER,
            winner_id=None,
            loser_id=None,
            rationale="deferred",
        )
        assert r.winner_id is None
        assert r.loser_id is None


# ---------------------------------------------------------------------------
# _score helper
# ---------------------------------------------------------------------------


class TestScore:
    def test_authoritative_higher_than_unknown(self) -> None:
        auth = make_signals(source_tier="authoritative", corroboration_count=1)
        unknown = make_signals(source_tier="unknown", corroboration_count=1)
        assert _score(auth) > _score(unknown)

    def test_higher_corroboration_raises_score(self) -> None:
        low = make_signals(corroboration_count=1)
        high = make_signals(corroboration_count=10)
        assert _score(high) > _score(low)

    def test_older_claim_has_lower_freshness(self) -> None:
        new = make_signals(created_at=datetime.now(UTC))
        old = make_signals(created_at=datetime.now(UTC) - timedelta(days=30))
        assert _score(new) > _score(old)

    def test_score_is_positive(self) -> None:
        sig = make_signals()
        assert _score(sig) > 0


# ---------------------------------------------------------------------------
# DeterministicResolver
# ---------------------------------------------------------------------------


class TestDeterministicResolver:
    def setup_method(self) -> None:
        self.resolver = DeterministicResolver()

    def test_higher_tier_wins(self) -> None:
        auth = make_signals(source_tier="authoritative", corroboration_count=1)
        unknown = make_signals(source_tier="unknown", corroboration_count=1)
        result = self.resolver.resolve(auth, unknown)
        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == auth.node_id
        assert result.loser_id == unknown.node_id

    def test_higher_tier_wins_reversed_args(self) -> None:
        auth = make_signals(source_tier="authoritative", corroboration_count=1)
        unknown = make_signals(source_tier="unknown", corroboration_count=1)
        result = self.resolver.resolve(unknown, auth)
        assert result.winner_id == auth.node_id
        assert result.loser_id == unknown.node_id

    def test_higher_corroboration_wins_same_tier(self) -> None:
        low = make_signals(source_tier="validated", corroboration_count=1)
        high = make_signals(source_tier="validated", corroboration_count=20)
        result = self.resolver.resolve(low, high)
        assert result.winner_id == high.node_id

    def test_returns_supersede_always(self) -> None:
        a = make_signals()
        b = make_signals(source_tier="unknown")
        result = self.resolver.resolve(a, b)
        assert result.action == ResolutionAction.SUPERSEDE

    def test_rationale_is_non_empty(self) -> None:
        a = make_signals(source_tier="authoritative")
        b = make_signals(source_tier="unknown")
        result = self.resolver.resolve(a, b)
        assert result.rationale

    # -----------------------------------------------------------------------
    # Tiebreaker: same agent, newer wins
    # -----------------------------------------------------------------------

    def test_tie_same_agent_newer_wins(self) -> None:
        now = datetime.now(UTC)
        older = make_signals(
            node_id="node-older",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=now - timedelta(hours=1),
        )
        newer = make_signals(
            node_id="node-newer",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=now,
        )
        # Same tier, same corroboration, same-day (0 days) -> tied scores
        result = self.resolver.resolve(older, newer)
        assert result.winner_id == newer.node_id
        assert result.loser_id == older.node_id

    def test_tie_same_agent_newer_wins_reversed_args(self) -> None:
        now = datetime.now(UTC)
        older = make_signals(
            node_id="node-older",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=now - timedelta(hours=1),
        )
        newer = make_signals(
            node_id="node-newer",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=now,
        )
        result = self.resolver.resolve(newer, older)
        assert result.winner_id == newer.node_id

    # -----------------------------------------------------------------------
    # Tiebreaker: different agents, older wins
    # -----------------------------------------------------------------------

    def test_tie_different_agents_older_wins(self) -> None:
        now = datetime.now(UTC)
        older = make_signals(
            node_id="node-older",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-alpha",
            created_at=now - timedelta(hours=2),
        )
        newer = make_signals(
            node_id="node-newer",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-beta",
            created_at=now,
        )
        result = self.resolver.resolve(older, newer)
        assert result.winner_id == older.node_id
        assert result.loser_id == newer.node_id

    def test_tie_different_agents_older_wins_reversed_args(self) -> None:
        now = datetime.now(UTC)
        older = make_signals(
            node_id="node-older",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-alpha",
            created_at=now - timedelta(hours=2),
        )
        newer = make_signals(
            node_id="node-newer",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-beta",
            created_at=now,
        )
        result = self.resolver.resolve(newer, older)
        assert result.winner_id == older.node_id

    # -----------------------------------------------------------------------
    # Stable final tiebreaker (identical timestamps)
    # -----------------------------------------------------------------------

    def test_fully_identical_stable_lex_tiebreak(self) -> None:
        ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        node_a = make_signals(
            node_id="aaa",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=ts,
        )
        node_b = make_signals(
            node_id="bbb",
            source_tier="validated",
            corroboration_count=1,
            agent_id="agent-x",
            created_at=ts,
        )
        result1 = self.resolver.resolve(node_a, node_b)
        result2 = self.resolver.resolve(node_b, node_a)
        # Both calls must agree on the same winner
        assert result1.winner_id == result2.winner_id
        # Lex smaller wins
        assert result1.winner_id == "aaa"


# ---------------------------------------------------------------------------
# LLMResolver prompt parsing
# ---------------------------------------------------------------------------


class TestLLMResolverParsing:
    """Tests for LLMResolver structured output parsing."""

    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def signals_a(self) -> ConflictSignals:
        return make_signals(node_id="node-a", source_tier="authoritative")

    @pytest.fixture
    def signals_b(self) -> ConflictSignals:
        return make_signals(node_id="node-b", source_tier="community")

    @pytest.mark.asyncio
    async def test_parses_supersede_a_wins(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "supersede", "winner": "a", "rationale": "A has better evidence"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-a"
        assert result.loser_id == "node-b"
        assert "better evidence" in result.rationale

    @pytest.mark.asyncio
    async def test_parses_supersede_b_wins(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "supersede", "winner": "b", "rationale": "B is more recent"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.SUPERSEDE
        assert result.winner_id == "node-b"
        assert result.loser_id == "node-a"

    @pytest.mark.asyncio
    async def test_parses_merge_with_content(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        merged = "Combined claim incorporating both perspectives"
        mock_llm.extract_structured.return_value = (
            {
                "action": "merge",
                "winner": None,
                "rationale": "Both have valid points",
                "merged_content": merged,
            },
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.MERGE
        assert result.winner_id is None
        assert result.loser_id is None
        assert result.merged_content == merged

    @pytest.mark.asyncio
    async def test_parses_coexist(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "coexist", "winner": None, "rationale": "Different valid perspectives"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.COEXIST
        assert result.winner_id is None
        assert result.loser_id is None

    @pytest.mark.asyncio
    async def test_parses_defer(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "defer", "rationale": "Need more information"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.DEFER
        assert result.winner_id is None

    @pytest.mark.asyncio
    async def test_llm_error_returns_defer(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.side_effect = RuntimeError("LLM unavailable")

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.DEFER
        assert "LLM call failed" in result.rationale

    @pytest.mark.asyncio
    async def test_unknown_action_defaults_to_defer(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "unknown_action", "rationale": "Something"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.DEFER

    @pytest.mark.asyncio
    async def test_supersede_missing_winner_returns_defer(
        self, mock_llm: AsyncMock, signals_a: ConflictSignals, signals_b: ConflictSignals
    ) -> None:
        mock_llm.extract_structured.return_value = (
            {"action": "supersede", "winner": None, "rationale": "Missing winner"},
            {},
        )

        resolver = LLMResolver(mock_llm)
        result = await resolver.resolve(signals_a, signals_b, "Claim A", "Claim B")

        assert result.action == ResolutionAction.DEFER


# ---------------------------------------------------------------------------
# ConsolidationWorker
# ---------------------------------------------------------------------------


NODE_A = str(uuid.uuid4())
NODE_B = str(uuid.uuid4())
SILO = "test-silo"


def _make_store_with_nodes(node_a_id: str, node_b_id: str, silo: str) -> AsyncMock:
    """Return a store mock whose execute_query returns signal rows for both nodes."""
    now_iso = datetime.now(UTC).isoformat()
    earlier_iso = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    store = make_store()
    store.execute_query.return_value = [
        {
            "id": node_a_id,
            "credibility": 0.85,
            "corroboration_count": 2,
            "created_at": now_iso,
            "agent_id": "agent-a",
            "source_tier": "authoritative",
        },
        {
            "id": node_b_id,
            "credibility": 0.4,
            "corroboration_count": 1,
            "created_at": earlier_iso,
            "agent_id": "agent-b",
            "source_tier": "unknown",
        },
    ]
    return store


class TestConsolidationWorker:
    @pytest.mark.asyncio
    async def test_uses_deterministic_resolver_by_default(self) -> None:
        worker = ConsolidationWorker()
        assert isinstance(worker._resolver, DeterministicResolver)

    @pytest.mark.asyncio
    async def test_accepts_custom_resolver(self) -> None:
        stub = _DeferResolver()
        worker = ConsolidationWorker(resolver=stub)
        assert worker._resolver is stub

    @pytest.mark.asyncio
    async def test_supersede_calls_tx3(self) -> None:
        store = _make_store_with_nodes(NODE_A, NODE_B, SILO)

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            mock_tx3.return_value = (MagicMock(), [])
            worker = ConsolidationWorker()
            result = await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        assert result.action == ResolutionAction.SUPERSEDE
        mock_tx3.assert_awaited_once_with(
            store,
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            silo_id=SILO,
            reason=SupersedeReason.CONTRADICTION,
        )

    @pytest.mark.asyncio
    async def test_supersede_updates_conflict_status(self) -> None:
        store = _make_store_with_nodes(NODE_A, NODE_B, SILO)

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            mock_tx3.return_value = (MagicMock(), [])
            worker = ConsolidationWorker()
            await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        # execute_write called for conflict_status update
        assert store.execute_write.await_count >= 1

    @pytest.mark.asyncio
    async def test_defer_skips_tx3(self) -> None:
        store = _make_store_with_nodes(NODE_A, NODE_B, SILO)

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            worker = ConsolidationWorker(resolver=_DeferResolver())
            result = await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        assert result.action == ResolutionAction.DEFER
        mock_tx3.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_defer_does_not_update_conflict_status(self) -> None:
        store = _make_store_with_nodes(NODE_A, NODE_B, SILO)

        with patch("context_service.sage.consolidation.supersede", new_callable=AsyncMock):
            worker = ConsolidationWorker(resolver=_DeferResolver())
            await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        # execute_write should NOT be called (no status update on defer)
        store.execute_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_signals_queried_with_correct_params(self) -> None:
        store = _make_store_with_nodes(NODE_A, NODE_B, SILO)

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            mock_tx3.return_value = (MagicMock(), [])
            worker = ConsolidationWorker()
            await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        store.execute_query.assert_awaited_once()
        call_kwargs = store.execute_query.call_args[0][1]
        assert call_kwargs["silo_id"] == SILO
        assert NODE_A in call_kwargs["node_ids"]
        assert NODE_B in call_kwargs["node_ids"]

    @pytest.mark.asyncio
    async def test_missing_node_data_uses_defaults(self) -> None:
        """Worker should not crash if a node row is missing from query results."""
        store = make_store()
        # Only return data for node_a; node_b is missing
        store.execute_query.return_value = [
            {
                "id": NODE_A,
                "credibility": 0.8,
                "corroboration_count": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "agent_id": "agent-a",
                "source_tier": "authoritative",
            }
        ]

        with patch(
            "context_service.sage.consolidation.supersede", new_callable=AsyncMock
        ) as mock_tx3:
            mock_tx3.return_value = (MagicMock(), [])
            worker = ConsolidationWorker()
            result = await worker.process_conflict(store, NODE_A, NODE_B, SILO)

        assert result.action in (ResolutionAction.SUPERSEDE, ResolutionAction.DEFER)
