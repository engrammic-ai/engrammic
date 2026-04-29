"""Shared Dagster partition definitions for context-service assets."""

from __future__ import annotations

import dagster as dg

silo_partitions = dg.DynamicPartitionsDefinition(name="silo_id")

__all__ = ["silo_partitions"]
