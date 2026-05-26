"""In-process metrics buffer for aggregation before DB flush."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MetricBucket:
    """Aggregated metrics for a single (time, silo, metric) key."""

    count: int = 0
    error_count: int = 0
    latencies: list[float] = field(default_factory=list)


class MetricsBuffer:
    """Thread-safe buffer for metric aggregation.

    Records are keyed by (bucket_time, silo_id, metric_name).
    Call flush() periodically to get aggregated rows and clear the buffer.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str, str], MetricBucket] = defaultdict(MetricBucket)
        self._lock = threading.Lock()

    def record(
        self,
        metric_name: str,
        silo_id: str,
        latency_ms: float | None = None,
        error: bool = False,
    ) -> None:
        """Record a metric observation."""
        bucket_time = self._truncate_to_minute(time.time())
        key = (bucket_time, silo_id, metric_name)

        with self._lock:
            bucket = self._buckets[key]
            bucket.count += 1
            if error:
                bucket.error_count += 1
            if latency_ms is not None:
                bucket.latencies.append(latency_ms)

    def flush(self) -> list[dict[str, Any]]:
        """Return aggregated metrics and clear buffer."""
        with self._lock:
            results: list[dict[str, Any]] = []
            for (bucket_time, silo_id, metric_name), bucket in self._buckets.items():
                latencies = sorted(bucket.latencies) if bucket.latencies else []
                results.append(
                    {
                        "bucket": datetime.fromisoformat(bucket_time),
                        "silo_id": silo_id,
                        "metric_name": metric_name,
                        "count": bucket.count,
                        "error_count": bucket.error_count,
                        "latency_sum_ms": sum(latencies),
                        "latency_p50_ms": self._percentile(latencies, 50),
                        "latency_p95_ms": self._percentile(latencies, 95),
                        "latency_max_ms": max(latencies) if latencies else None,
                    }
                )
            self._buckets.clear()
            return results

    def _truncate_to_minute(self, ts: float) -> str:
        """Truncate timestamp to minute boundary, return ISO string."""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        truncated = dt.replace(second=0, microsecond=0)
        return truncated.isoformat()

    def _percentile(self, sorted_values: list[float], p: int) -> float | None:
        """Compute percentile from sorted list."""
        if not sorted_values:
            return None
        k = (len(sorted_values) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_values) else f
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
