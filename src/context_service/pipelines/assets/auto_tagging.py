"""Dagster asset: auto_tagging — LLM-based tag refinement per silo.

Fetches nodes with auto_tagged_at IS NULL (up to 50 per run), sends content
snippets to the LLM for tag suggestions, and writes the results back to
Memgraph along with an auto_tagged_at timestamp.

Design notes:
- Uses LLMResource.get_client() (sync) to retrieve the LLMProvider instance.
- LLMProvider.complete() is async; the asset drives it via _run_async from
  pipelines.utils to handle Dagster's potentially-running event loop.
- Uses memgraph.driver() through the async inner function; never imports
  MemgraphClient directly (rule 8 via the resource).
- Limit is 50 nodes per run (matches plan spec).
"""

import json
import time
from typing import TYPE_CHECKING, Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.logging import set_dagster_context
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.pipelines.utils import run_async

if TYPE_CHECKING:
    pass

_BATCH_SIZE = 50

_FETCH_UNTAGGED_CYPHER = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND n.content IS NOT NULL
  AND n.auto_tagged_at IS NULL
RETURN
    id(n) AS node_id,
    labels(n) AS labels,
    n.content AS content
LIMIT $limit
"""

_TAG_PROMPT_TEMPLATE = """\
You are a precise tagging assistant. Given the following content snippets from a \
knowledge graph, produce a JSON object mapping each node_id to a list of concise, \
lowercase tags (3-8 tags per node). Tags must be single words or hyphenated phrases, \
no punctuation, no stop words.

Respond with valid JSON only — no prose, no markdown fences.

Format:
{{"<node_id>": ["tag1", "tag2", ...], ...}}

Content snippets:
{snippets}
"""


def _build_prompt(nodes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for node in nodes:
        node_id = node["node_id"]
        content = (node.get("content") or "")[:400]
        labels = ", ".join(node.get("labels") or [])
        lines.append(f"[{node_id}] ({labels}): {content}")
    snippets = "\n".join(lines)
    return _TAG_PROMPT_TEMPLATE.format(snippets=snippets)


def _parse_tag_response(raw: str) -> dict[str, list[str]]:
    """Parse LLM JSON response into {node_id: [tag, ...]}."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Strip markdown fences if the LLM ignores instructions.
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for node_id, tags in data.items():
        if isinstance(tags, list):
            result[str(node_id)] = [str(t) for t in tags if isinstance(t, str)]
    return result


@dg.asset(
    name="auto_tagging",
    partitions_def=silo_partitions,
    description=(
        "LLM-based tag refinement for nodes that have not yet been auto-tagged. "
        "Processes up to 50 untagged nodes per run per silo partition."
    ),
    retry_policy=dg.RetryPolicy(max_retries=1, delay=30.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "auto_tagging"},
    op_tags={"dagster/max_runtime_seconds": 300},
)
def auto_tagging(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Run LLM-based tag refinement for the silo partition."""
    set_dagster_context(context)
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        import datetime

        driver = await memgraph.driver()
        async with driver.session() as session:
            # Fetch untagged nodes.
            fetch_result = await session.run(
                _FETCH_UNTAGGED_CYPHER,
                silo_id=silo_id,
                limit=_BATCH_SIZE,
            )
            records = await fetch_result.data()

        if not records:
            context.log.info(f"silo={silo_id} no untagged nodes found")
            return {"silo_id": silo_id, "processed": 0, "skipped": 0, "errors": 0}

        context.log.info(f"silo={silo_id} fetched {len(records)} untagged nodes")

        # Build and send prompt.
        prompt = _build_prompt(records)
        llm_client = llm.get_client()
        raw_response, _usage = await llm_client.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout=60.0,
        )

        tag_map = _parse_tag_response(raw_response)
        if not tag_map:
            context.log.warning(f"silo={silo_id} LLM returned unparseable tag response")
            return {"silo_id": silo_id, "processed": 0, "skipped": len(records), "errors": 1}

        # Write tags back (batched to avoid N+1).
        from context_service.db.queries import BATCH_UPDATE_NODE_TAGS

        now = datetime.datetime.now(datetime.UTC).isoformat()
        updates = []
        for record in records:
            node_id_int = int(record["node_id"])
            node_id_str = str(node_id_int)
            tags = tag_map.get(node_id_str)
            if tags:
                updates.append({"node_id": node_id_int, "tags": tags, "now": now})

        processed = 0
        errors = 0
        if updates:
            try:
                async with driver.session() as session:
                    result = await session.run(BATCH_UPDATE_NODE_TAGS, updates=updates)
                    await result.consume()  # Ensure transaction commits
                processed = len(updates)
            except Exception as exc:  # noqa: BLE001
                context.log.warning(f"silo={silo_id} batch tag write failed: {exc}")
                errors = len(updates)

        skipped = len(records) - processed - errors
        return {
            "silo_id": silo_id,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
        }

    result: dict[str, Any] = run_async(_run())
    duration_s = time.monotonic() - t0
    result["duration_s"] = duration_s
    skipped_no_work = result["processed"] == 0 and result["errors"] == 0

    if skipped_no_work:
        context.log.info(f"silo={silo_id} skipped_no_work duration={duration_s:.2f}s")
    else:
        context.log.info(
            f"silo={silo_id} "
            f"processed={result['processed']} "
            f"skipped={result['skipped']} "
            f"errors={result['errors']} "
            f"duration={duration_s:.2f}s"
        )

    result["skipped_no_work"] = skipped_no_work
    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "processed": dg.MetadataValue.int(result["processed"]),
            "skipped": dg.MetadataValue.int(result["skipped"]),
            "errors": dg.MetadataValue.int(result["errors"]),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped_no_work),
        },
    )
