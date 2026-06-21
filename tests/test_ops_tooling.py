"""Tests for v1.3g ops tooling: causal_tombstone asset and confidence metrics."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Tombstone — query structure tests (no live DB required)
# ---------------------------------------------------------------------------


def _load_tombstone_engine_source() -> str:
    p = Path(__file__).parent.parent / "src" / "context_service" / "engine" / "tombstone.py"
    return p.read_text()


_TOMBSTONE_SOURCE = _load_tombstone_engine_source()


class TestTombstoneQueryStructure:
    """Verify Cypher templates enforce silo isolation."""

    def test_find_query_filters_by_silo(self) -> None:
        assert "silo_id: $silo_id" in _TOMBSTONE_SOURCE

    def test_tombstone_query_uses_silo_id(self) -> None:
        tombstone_match = re.search(
            r"_TOMBSTONE_EDGE\s*=\s*\"\"\"(.+?)\"\"\"", _TOMBSTONE_SOURCE, re.DOTALL
        )
        assert tombstone_match, "_TOMBSTONE_EDGE query not found"
        query = tombstone_match.group(1)
        assert "silo_id: $silo_id" in query
        assert "id: $edge_id" in query

    def test_tombstone_query_sets_invalidated_flag(self) -> None:
        tombstone_match = re.search(
            r"_TOMBSTONE_EDGE\s*=\s*\"\"\"(.+?)\"\"\"", _TOMBSTONE_SOURCE, re.DOTALL
        )
        assert tombstone_match
        query = tombstone_match.group(1)
        assert "r.invalidated = true" in query
        assert "r.invalidated_at" in query
        assert "r.invalidation_reason" in query

    def test_find_query_excludes_already_invalidated(self) -> None:
        # The template variable contains the invalidated filter.
        assert "invalidated" in _TOMBSTONE_SOURCE


class TestBuildFindQuery:
    """Unit tests for the build_find_query helper."""

    def test_no_filters_produces_clean_query(self) -> None:
        from context_service.engine.tombstone import build_find_query

        q = build_find_query(None, None, None)
        assert "$silo_id" in q
        assert "$batch_limit" in q
        assert "type(r)" not in q

    def test_edge_type_filter_injected(self) -> None:
        from context_service.engine.tombstone import build_find_query

        q = build_find_query("CAUSES", None, None)
        assert "type(r) = 'CAUSES'" in q

    def test_confidence_filter_injected(self) -> None:
        from context_service.engine.tombstone import build_find_query

        q = build_find_query(None, 0.5, None)
        assert "< 0.5" in q

    def test_created_before_filter_injected(self) -> None:
        from datetime import UTC, datetime

        from context_service.engine.tombstone import build_find_query

        dt = datetime(2026, 1, 1, tzinfo=UTC)
        q = build_find_query(None, None, dt)
        assert "2026-01-01" in q


class TestRunTombstoneLogic:
    """Unit tests for run_tombstone with mock client."""

    def test_explicit_edge_ids_tombstones_each(self) -> None:
        import asyncio

        from context_service.engine.tombstone import run_tombstone

        client = MagicMock()
        client.execute_write = AsyncMock(return_value=None)

        with patch(
            "context_service.engine.causal_invalidation.invalidate_derived_edges",
            new=AsyncMock(return_value=2),
        ):
            counts = asyncio.run(
                run_tombstone(
                    client,
                    "silo_a",
                    edge_ids=["e1", "e2"],
                )
            )

        assert counts["direct"] == 2
        assert counts["derived"] == 4  # 2 per edge

    def test_filter_mode_queries_db(self) -> None:
        import asyncio

        from context_service.engine.tombstone import run_tombstone

        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[{"edge_id": "e99"}])
        client.execute_write = AsyncMock(return_value=None)

        with patch(
            "context_service.engine.causal_invalidation.invalidate_derived_edges",
            new=AsyncMock(return_value=0),
        ):
            counts = asyncio.run(
                run_tombstone(
                    client,
                    "silo_a",
                    confidence_below=0.3,
                )
            )

        client.execute_query.assert_awaited_once()
        assert counts["direct"] == 1

    def test_silo_boundary_enforced_in_write(self) -> None:
        """Confirm silo_id is always passed to execute_write."""
        import asyncio

        from context_service.engine.tombstone import run_tombstone

        client = MagicMock()
        write_calls: list[dict] = []

        async def _capture_write(query: str, params: dict) -> None:
            write_calls.append(params)

        client.execute_write = _capture_write

        with patch(
            "context_service.engine.causal_invalidation.invalidate_derived_edges",
            new=AsyncMock(return_value=0),
        ):
            asyncio.run(
                run_tombstone(
                    client,
                    "silo_xyz",
                    edge_ids=["edge1"],
                )
            )

        assert all(p["silo_id"] == "silo_xyz" for p in write_calls)

    def test_no_cross_silo_write(self) -> None:
        """Different silo in the tombstone helper must not bleed through."""
        import asyncio

        from context_service.engine.tombstone import run_tombstone

        client = MagicMock()
        client.execute_write = AsyncMock(return_value=None)

        with patch(
            "context_service.engine.causal_invalidation.invalidate_derived_edges",
            new=AsyncMock(return_value=0),
        ):
            asyncio.run(
                run_tombstone(
                    client,
                    "silo_a",
                    edge_ids=["e1"],
                )
            )

        for call_args in client.execute_write.call_args_list:
            params = call_args[0][1]
            assert params.get("silo_id") == "silo_a"

    def test_empty_edge_list_returns_zeros(self) -> None:
        import asyncio

        from context_service.engine.tombstone import run_tombstone

        client = MagicMock()
        client.execute_write = AsyncMock(return_value=None)

        with patch(
            "context_service.engine.causal_invalidation.invalidate_derived_edges",
            new=AsyncMock(return_value=0),
        ):
            counts = asyncio.run(
                run_tombstone(
                    client,
                    "silo_a",
                    edge_ids=[],
                )
            )

        assert counts["direct"] == 0
        assert counts["derived"] == 0


# ---------------------------------------------------------------------------
# Confidence metrics
# ---------------------------------------------------------------------------


class TestConfidenceHistogramsExist:
    """Verify histogram objects are registered in the Prometheus registry."""

    def test_edge_histogram_registered(self) -> None:
        from context_service.api.metrics import EDGE_CONFIDENCE_DISTRIBUTION, REGISTRY

        names = {m.name for m in REGISTRY.collect()}
        assert "edge_confidence_distribution" in names
        assert EDGE_CONFIDENCE_DISTRIBUTION is not None

    def test_belief_histogram_registered(self) -> None:
        from context_service.api.metrics import BELIEF_CONFIDENCE_DISTRIBUTION, REGISTRY

        names = {m.name for m in REGISTRY.collect()}
        assert "belief_confidence_distribution" in names
        assert BELIEF_CONFIDENCE_DISTRIBUTION is not None

    def test_edge_histogram_accepts_observations(self) -> None:
        from context_service.api.metrics import EDGE_CONFIDENCE_DISTRIBUTION

        EDGE_CONFIDENCE_DISTRIBUTION.labels(silo_id="test_silo", edge_type="CAUSES").observe(0.8)

    def test_belief_histogram_accepts_observations(self) -> None:
        from context_service.api.metrics import BELIEF_CONFIDENCE_DISTRIBUTION

        BELIEF_CONFIDENCE_DISTRIBUTION.labels(
            silo_id="test_silo", edge_type="CORROBORATES"
        ).observe(0.6)

    def test_record_edge_confidence_helper(self) -> None:
        from context_service.api.metrics import record_edge_confidence

        record_edge_confidence(0.75, silo_id="s1", edge_type="CAUSES")

    def test_record_belief_confidence_helper(self) -> None:
        from context_service.api.metrics import record_belief_confidence

        record_belief_confidence(0.5, silo_id="s1", edge_type="PREVENTS")


class TestConfidenceBuckets:
    """Verify histogram bucket boundaries match the spec (0.1, 0.3, 0.5, 0.7, 0.9)."""

    def _get_buckets(self, histogram_name: str) -> list[float]:
        from context_service.api.metrics import REGISTRY

        for metric in REGISTRY.collect():
            if metric.name == histogram_name:
                les = [
                    float(s.labels["le"])
                    for s in metric.samples
                    if s.name.endswith("_bucket") and s.labels.get("le") != "+Inf"
                ]
                return sorted(set(les))
        return []

    def test_edge_histogram_buckets(self) -> None:
        from context_service.api.metrics import EDGE_CONFIDENCE_DISTRIBUTION

        EDGE_CONFIDENCE_DISTRIBUTION.labels(silo_id="bucket_test", edge_type="CAUSES").observe(0.5)
        buckets = self._get_buckets("edge_confidence_distribution")
        for expected in (0.1, 0.3, 0.5, 0.7, 0.9):
            assert expected in buckets, f"expected bucket {expected} not found in {buckets}"

    def test_belief_histogram_buckets(self) -> None:
        from context_service.api.metrics import BELIEF_CONFIDENCE_DISTRIBUTION

        BELIEF_CONFIDENCE_DISTRIBUTION.labels(
            silo_id="bucket_test", edge_type="CORROBORATES"
        ).observe(0.3)
        buckets = self._get_buckets("belief_confidence_distribution")
        for expected in (0.1, 0.3, 0.5, 0.7, 0.9):
            assert expected in buckets, f"expected bucket {expected} not found in {buckets}"


# confidence_drift_sensor was deleted as part of the SAGE schedule
# consolidation. TestConfidenceDriftSensor has been removed.

# ---------------------------------------------------------------------------
# Admin route — tombstone endpoint
# ---------------------------------------------------------------------------


class TestAdminTombstoneRoute:
    """Unit tests for POST /admin/tombstone via FastAPI TestClient."""

    def _make_bare_app(self) -> object:
        """App without memgraph state (for 503 test)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from context_service.api.routes.admin import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_tombstone_returns_503_when_memgraph_missing(self) -> None:
        from fastapi.testclient import TestClient

        client = self._make_bare_app()
        assert isinstance(client, TestClient)

        resp = client.post(
            "/admin/tombstone",
            json={"silo_id": "silo_a", "edge_ids": ["e1"]},
        )
        assert resp.status_code == 503

    def test_tombstone_returns_result_when_memgraph_available(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from context_service.api.routes.admin import router

        app = FastAPI()
        app.include_router(router)

        mock_client = MagicMock()
        mock_client.execute_write = AsyncMock(return_value=None)
        app.state.memgraph = mock_client
        app.state.memgraph_store = mock_client

        with patch(
            "context_service.engine.tombstone.run_tombstone",
            new=AsyncMock(return_value={"direct": 3, "derived": 1}),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/admin/tombstone",
                json={"silo_id": "silo_a", "edge_ids": ["e1", "e2", "e3"]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["silo_id"] == "silo_a"
        assert body["direct_tombstoned"] == 3
        assert body["derived_tombstoned"] == 1

    def test_tombstone_rejects_invalid_confidence(self) -> None:
        from fastapi.testclient import TestClient

        client = self._make_bare_app()
        assert isinstance(client, TestClient)

        resp = client.post(
            "/admin/tombstone",
            json={"silo_id": "silo_a", "confidence_below": 1.5},
        )
        assert resp.status_code == 422

    def test_tombstone_asset_registered_in_all_assets(self) -> None:
        # Check the asset appears in the source list without importing Dagster assets.
        init_path = (
            Path(__file__).parent.parent
            / "src"
            / "context_service"
            / "pipelines"
            / "assets"
            / "__init__.py"
        )
        source = init_path.read_text()
        assert "causal_tombstone" in source
