"""Tests for MetricsBuffer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_service.telemetry.buffer import MetricsBuffer


class TestMetricsBuffer:
    def test_record_increments_count(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        assert len(rows) == 1
        assert rows[0]["count"] == 2
        assert rows[0]["error_count"] == 0

    def test_record_tracks_errors(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1", error=True)
        buffer.record("tool.remember", "silo-1", error=False)

        rows = buffer.flush()
        assert rows[0]["count"] == 2
        assert rows[0]["error_count"] == 1

    def test_record_aggregates_latency(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.recall", "silo-1", latency_ms=100.0)
        buffer.record("tool.recall", "silo-1", latency_ms=200.0)
        buffer.record("tool.recall", "silo-1", latency_ms=300.0)

        rows = buffer.flush()
        assert rows[0]["latency_sum_ms"] == 600.0
        assert rows[0]["latency_p50_ms"] == 200.0
        assert rows[0]["latency_max_ms"] == 300.0

    def test_separate_buckets_per_silo(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.remember", "silo-2")

        rows = buffer.flush()
        assert len(rows) == 2
        silo_ids = {r["silo_id"] for r in rows}
        assert silo_ids == {"silo-1", "silo-2"}

    def test_separate_buckets_per_metric(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.recall", "silo-1")

        rows = buffer.flush()
        assert len(rows) == 2
        metrics = {r["metric_name"] for r in rows}
        assert metrics == {"tool.remember", "tool.recall"}

    def test_flush_clears_buffer(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows1 = buffer.flush()
        rows2 = buffer.flush()

        assert len(rows1) == 1
        assert len(rows2) == 0

    def test_percentile_empty_list(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        assert rows[0]["latency_p50_ms"] is None
        assert rows[0]["latency_p95_ms"] is None
        assert rows[0]["latency_max_ms"] is None

    def test_bucket_is_truncated_to_minute(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        bucket: datetime = rows[0]["bucket"]
        assert bucket.second == 0
        assert bucket.microsecond == 0
