"""Dogfood ingest — loads project knowledge into the context MCP for testing.

Connects to the running context-service MCP (SSE at http://localhost:8000/mcp/)
and ingests ~139 items from three data modules:

    _dogfood_data_api.py    — MCP tool contracts and integration patterns
    _dogfood_data_claude.py — project architecture, rules, and conventions
    _dogfood_data_plans.py  — design decisions, EAG gaps, phase status

Ingest is two-phase:
    Phase 1: memory + knowledge items  — stored first; node IDs collected by tag
    Phase 2: wisdom + intelligence     — wisdom `about` resolved from phase-1 IDs

Usage:
    uv run python -m scripts.dogfood_ingest
    uv run python -m scripts.dogfood_ingest --wipe          # reset silo before ingest
    uv run python -m scripts.dogfood_ingest --dry-run
    uv run python -m scripts.dogfood_ingest --concurrency 5
    uv run python -m scripts.dogfood_ingest --url http://localhost:8000/mcp/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

from scripts._dogfood_data_api import ITEMS as API_ITEMS
from scripts._dogfood_data_claude import ITEMS as CLAUDE_ITEMS
from scripts._dogfood_data_plans import ITEMS as PLANS_ITEMS

_DEFAULT_URL = "http://localhost:8000/mcp/"
_DEFAULT_CONCURRENCY = 4

# Map shorthand doc: refs to file:// URIs the evidence validator accepts.
_DOC_URI_MAP = {
    "doc:api-examples.md": "file:///app/context/api-examples.md",
    "doc:CLAUDE.md": "file:///app/CLAUDE.md",
    "doc:eag-integration-audit.md": "file:///app/context/plans/eag-integration-audit.md",
    "doc:oss-master.md": "file:///app/context/plans/oss-master.md",
    "doc:e2e-test-scenarios.md": "file:///app/context/plans/e2e-test-scenarios.md",
}


def _resolve_evidence(refs: list[str]) -> list[str]:
    return [_DOC_URI_MAP.get(r, r) for r in refs]


def _build_store_args(item: dict[str, Any], about_ids: list[str] | None = None) -> dict[str, Any]:
    """Build context_store arguments from an item dict."""
    args: dict[str, Any] = {
        "content": item["content"],
        "layer": item["layer"],
    }
    if item.get("tags"):
        args["tags"] = item["tags"]
    if item.get("evidence"):
        args["evidence"] = _resolve_evidence(item["evidence"])
    if item.get("source_type"):
        args["source_type"] = item["source_type"]
    elif item["layer"] == "knowledge":
        args["source_type"] = "document"
    if item.get("steps"):
        args["steps"] = item["steps"]
    if about_ids:
        args["about"] = about_ids
    return args


async def _store_item(
    session: ClientSession,
    item: dict[str, Any],
    about_ids: list[str] | None,
    *,
    dry_run: bool,
) -> str | None:
    """Call context_store for one item. Returns the node/chain ID or None on failure."""
    args = _build_store_args(item, about_ids)
    layer = item["layer"]

    if dry_run:
        print(f"  [dry-run] {layer:12s}  {item['content'][:72]}")
        return f"dry-{id(item)}"

    try:
        result = await session.call_tool("context_store", args)
        # result.content is a list of TextContent; first item is JSON
        raw = result.content[0].text if result.content else "{}"
        data = json.loads(raw)
        node_id = data.get("node_id") or data.get("chain_id")
        status = "ok" if node_id else "?"
        print(f"  [{status}] {layer:12s}  {item['content'][:72]}")
        return node_id
    except Exception as exc:  # noqa: BLE001
        print(f"  [err] {layer:12s}  {item['content'][:60]}  — {exc}", file=sys.stderr)
        return None


async def _store_batch(
    session: ClientSession,
    items: list[dict[str, Any]],
    about_map: dict[str, list[str]],
    *,
    dry_run: bool,
    concurrency: int,
) -> dict[str, list[str]]:
    """Store a batch of items with bounded concurrency. Returns tag→[node_id] map."""
    sem = asyncio.Semaphore(concurrency)
    collected: dict[str, list[str]] = defaultdict(list)

    # Collect a small set of fallback IDs (first node per tag) for wisdom items
    # whose about tags don't match any phase-1 tag directly.
    fallback_ids = [ids[0] for ids in about_map.values() if ids][:3]

    async def _bounded(item: dict[str, Any]) -> None:
        about_ids: list[str] | None = None
        if item["layer"] in ("wisdom", "meta"):
            resolved: list[str] = []
            for tag_or_id in item.get("about", []):
                resolved.extend(about_map.get(tag_or_id, []))
            # Fall back to a few general nodes so about is never empty
            about_ids = resolved or fallback_ids or None

        async with sem:
            node_id = await _store_item(session, item, about_ids, dry_run=dry_run)
        if node_id:
            for tag in item.get("tags", []):
                collected[tag].append(node_id)

    await asyncio.gather(*[_bounded(it) for it in items])
    return collected


async def wipe_silo(org_id: str = "dev-org") -> None:
    """Reset the dev silo via the engine layer (same approach as other scripts)."""
    from context_service.config.settings import get_settings
    from context_service.services.models import derive_silo_id
    from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver

    settings = get_settings()
    silo_id = derive_silo_id(org_id)
    driver = await create_memgraph_driver(settings)
    client = MemgraphClient(driver)
    try:
        from context_service.engine.memgraph_store import MemgraphStore
        store = MemgraphStore(client)
        deleted = await store.reset_silo(silo_id)
        print(f"Silo wiped — {deleted} nodes deleted (silo {silo_id}).")
    finally:
        await client.close()


async def wipe_all() -> None:
    """Delete every node and relationship in the graph — all silos."""
    from context_service.config.settings import get_settings
    from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver

    settings = get_settings()
    driver = await create_memgraph_driver(settings)
    client = MemgraphClient(driver)
    try:
        result = await client.execute_write("MATCH (n) DETACH DELETE n RETURN count(n) AS deleted")
        deleted = result[0]["deleted"] if result else 0
        print(f"All silos wiped — {deleted} nodes deleted.")
    finally:
        await client.close()


async def run(url: str, *, dry_run: bool, wipe: bool, wipe_all_silos: bool, concurrency: int) -> None:
    all_items = API_ITEMS + CLAUDE_ITEMS + PLANS_ITEMS
    phase1 = [it for it in all_items if it["layer"] in ("memory", "knowledge")]
    phase2 = [it for it in all_items if it["layer"] in ("wisdom", "intelligence", "meta")]

    if wipe_all_silos and not dry_run:
        print("Wiping all silos...")
        await wipe_all()
    elif wipe and not dry_run:
        print("Wiping silo...")
        await wipe_silo()

    print(f"Connecting to {url}")
    print(f"Total items: {len(all_items)}  (phase1={len(phase1)}, phase2={len(phase2)})")
    if dry_run:
        print("Mode: dry-run (no writes)\n")

    if dry_run:
        # Dry-run: no real connection needed
        print("--- Phase 1: memory + knowledge ---")
        tag_map: dict[str, list[str]] = defaultdict(list)
        for item in phase1:
            await _store_item(None, item, None, dry_run=True)  # type: ignore[arg-type]
        print("\n--- Phase 2: wisdom + intelligence ---")
        for item in phase2:
            await _store_item(None, item, None, dry_run=True)  # type: ignore[arg-type]
        print("\nDone (dry-run).")
        return

    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected.\n")

            print("--- Phase 1: memory + knowledge ---")
            tag_map = await _store_batch(
                session, phase1, {}, dry_run=False, concurrency=concurrency
            )
            print(f"\nPhase 1 done — {sum(len(v) for v in tag_map.values())} IDs collected across {len(tag_map)} tags.")

            print("\n--- Phase 2: wisdom + intelligence ---")
            await _store_batch(
                session, phase2, tag_map, dry_run=False, concurrency=concurrency
            )
            print("\nIngest complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dogfood ingest for context-service MCP.")
    parser.add_argument("--url", default=_DEFAULT_URL, help="MCP SSE endpoint URL.")
    parser.add_argument("--dry-run", action="store_true", help="Print items without writing.")
    parser.add_argument("--wipe", action="store_true", help="Reset the dev silo before ingesting.")
    parser.add_argument("--wipe-all", action="store_true", help="Delete ALL silos before ingesting.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help=f"Max parallel context_store calls (default: {_DEFAULT_CONCURRENCY}).",
    )
    args = parser.parse_args()
    asyncio.run(run(args.url, dry_run=args.dry_run, wipe=args.wipe, wipe_all_silos=args.wipe_all, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
