"""Telemetry subsystem for self-hosted deployments."""

from context_service.telemetry.flush import flush_metrics_to_db

__all__ = ["flush_metrics_to_db"]
