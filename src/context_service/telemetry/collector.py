from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

_START_TIME: float | None = None


def mark_start_time() -> None:
    """Mark the application start time. Call once at app startup."""
    global _START_TIME
    _START_TIME = time.time()


@dataclass
class SiloMetrics:
    store_count: int = 0
    recall_count: int = 0
    store_p50_ms: float = 0.0
    store_p95_ms: float = 0.0
    recall_p50_ms: float = 0.0
    recall_p95_ms: float = 0.0
    error_count: int = 0


@dataclass
class TelemetryPayload:
    install_id: str
    version: str
    tier: int
    uptime_seconds: float
    total_silos: int = 0
    total_nodes: int = 0
    total_store_ops: int = 0
    total_recall_ops: int = 0
    error_rate: float = 0.0
    latency_mean_ms: float = 0.0
    silo_metrics: dict[str, SiloMetrics] = field(default_factory=dict)


class TelemetryCollector:
    def __init__(
        self,
        install_id: str,
        version: str,
        registry: CollectorRegistry,
        silos: list[str] | None = None,
        all_silos: bool = False,
    ) -> None:
        self._install_id = install_id
        self._version = version
        self._registry = registry
        self._silos = silos or []
        self._all_silos = all_silos

    def collect(self) -> TelemetryPayload:
        tier = 2 if (self._silos or self._all_silos) else 1
        start = _START_TIME if _START_TIME is not None else time.time()
        uptime = time.time() - start

        payload = TelemetryPayload(
            install_id=self._install_id,
            version=self._version,
            tier=tier,
            uptime_seconds=uptime,
        )

        self._collect_aggregates(payload)

        if tier == 2:
            self._collect_silo_metrics(payload)

        return payload

    def _collect_aggregates(self, payload: TelemetryPayload) -> None:
        """Collect aggregate metrics from prometheus registry."""
        store_sum = 0
        recall_sum = 0
        latency_sum = 0.0
        latency_count = 0
        silos_seen: set[str] = set()

        for metric in self._registry.collect():
            for sample in metric.samples:
                name = sample.name
                labels = sample.labels
                value = sample.value

                if "silo_id" in labels:
                    silos_seen.add(labels["silo_id"])

                if name == "context_store_latency_seconds_count":
                    store_sum += int(value)
                elif name == "context_query_latency_seconds_count":
                    recall_sum += int(value)
                elif name == "context_store_latency_seconds_sum":
                    latency_sum += value
                    latency_count += int(
                        self._get_sample_value(
                            metric, "context_store_latency_seconds_count", labels
                        )
                    )

        payload.total_store_ops = store_sum
        payload.total_recall_ops = recall_sum
        payload.total_silos = len(silos_seen)

        if latency_count > 0:
            payload.latency_mean_ms = (latency_sum / latency_count) * 1000

    def _get_sample_value(self, metric: object, name: str, labels: dict[str, str]) -> float:
        """Get a specific sample value from a metric family."""
        for sample in getattr(metric, "samples", []):
            if sample.name == name and sample.labels == labels:
                return float(sample.value)
        return 0.0

    def _collect_silo_metrics(self, payload: TelemetryPayload) -> None:
        """Collect per-silo metrics from prometheus registry."""
        silo_data: dict[str, SiloMetrics] = {}

        # Pre-populate requested silos with empty metrics
        if not self._all_silos:
            for silo_id in self._silos:
                silo_data[silo_id] = SiloMetrics()

        for metric in self._registry.collect():
            for sample in metric.samples:
                labels = sample.labels
                if "silo_id" not in labels:
                    continue

                silo_id = labels["silo_id"]

                if not self._all_silos and silo_id not in self._silos:
                    continue

                if silo_id not in silo_data:
                    silo_data[silo_id] = SiloMetrics()

                name = sample.name
                value = sample.value

                if name == "context_store_latency_seconds_count":
                    silo_data[silo_id].store_count += int(value)
                elif name == "context_query_latency_seconds_count":
                    silo_data[silo_id].recall_count += int(value)

        payload.silo_metrics = silo_data
