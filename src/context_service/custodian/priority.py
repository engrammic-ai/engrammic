"""Back-compat shim: priority formulas now live in signals.priority.

Legacy import path retained so existing callers keep working until they
migrate to ``context_service.signals.priority`` directly.
"""

from __future__ import annotations

from context_service.signals.priority import compute_consensus_priority

__all__ = ["compute_consensus_priority"]
