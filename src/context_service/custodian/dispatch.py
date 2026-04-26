"""Custodian task type dispatch table."""

from __future__ import annotations

from typing import Any

from context_service.custodian.handlers.consensus import handle_consensus_task
from context_service.custodian.task_types import CONSENSUS_ON_CHAINS, CustodianTaskType

TASK_HANDLERS = {
    CONSENSUS_ON_CHAINS: handle_consensus_task,
}

STITCH_TOOLS = [
    "read_reasoning_chains",
    "read_commitments_in_cluster",
]


def validate_stitch_tools() -> None:
    """Validate STITCH_TOOLS entries exist in chain_reader module.

    Call at startup or in tests to catch tool name drift.
    """
    from context_service.custodian import chain_reader

    for tool_name in STITCH_TOOLS:
        if not hasattr(chain_reader, tool_name):
            raise ValueError(f"STITCH_TOOLS references missing function: {tool_name}")


async def dispatch_task(task_type: CustodianTaskType, **kwargs: Any) -> dict[str, Any]:
    handler = TASK_HANDLERS.get(task_type)
    if handler is None:
        raise NotImplementedError(f"No handler for task type: {task_type.name}")
    result = await handler(**kwargs)
    return dict(result)


__all__ = [
    "STITCH_TOOLS",
    "TASK_HANDLERS",
    "CustodianTaskType",
    "dispatch_task",
    "validate_stitch_tools",
]
