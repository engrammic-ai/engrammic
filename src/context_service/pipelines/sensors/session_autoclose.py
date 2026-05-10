"""Dagster sensor: auto-close stale open ReasoningSession nodes.

A :ReasoningSession is considered stale when its ``updated_at`` timestamp is
older than ``settings.session_timeout_minutes`` minutes.  This sensor polls
the graph every 60 seconds, finds stale sessions across all silos, and closes
them by calling :func:`~context_service.engine.sessions.close_session`.

Closing a session:
- Creates cross-chain :REFERENCES edges between all chains in the session.
- Sets ``status = 'closed'`` and records ``closed_at`` on the session node.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg

from context_service.db.queries import GET_ALL_STALE_OPEN_SESSIONS
from context_service.pipelines.resources import MemgraphResource


@dg.sensor(
    name="session_autoclose_sensor",
    minimum_interval_seconds=60,
    description=(
        "Closes :ReasoningSession nodes that have been open longer than "
        "session_timeout_minutes (default 30) without activity."
    ),
)
def session_autoclose_sensor(
    context,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for stale open sessions and close them."""

    async def _run() -> list[dict[str, Any]]:
        from context_service.config.settings import get_settings
        from context_service.engine.memgraph_store import MemgraphStore
        from context_service.engine.sessions import close_session
        from context_service.stores import MemgraphClient

        settings = get_settings()
        timeout = timedelta(minutes=settings.session_timeout_minutes)
        stale_before = (datetime.now(UTC) - timeout).isoformat()

        driver = await memgraph.driver()
        raw_client = MemgraphClient(driver)
        store = MemgraphStore(raw_client)

        rows = await raw_client.execute_query(
            GET_ALL_STALE_OPEN_SESSIONS, {"stale_before": stale_before}
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            session_id = str(row["session_id"])
            silo_id = str(row["silo_id"])
            try:
                edges = await close_session(store, session_id, silo_id)
                results.append(
                    {"session_id": session_id, "silo_id": silo_id, "edges_created": edges}
                )
            except Exception as exc:
                context.log.warning(
                    f"session_autoclose_failed session={session_id} silo={silo_id} err={exc}"
                )

        return results

    closed = asyncio.run(_run())

    for item in closed:
        context.log.info(
            f"auto_closed session={item['session_id']} silo={item['silo_id']} "
            f"cross_chain_edges={item['edges_created']}"
        )

    return dg.SensorResult(run_requests=[], cursor=datetime.now(UTC).isoformat())
