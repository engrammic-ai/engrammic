"""Backfill doc2query expansions and re-encode SPLADE sparse vectors for existing nodes.

New nodes receive an ``expansion`` payload field and a re-encoded sparse vector that
includes the expansion at store time. This script retrofits the same treatment onto
points that were stored before expansion was introduced.

Usage:
    uv run python scripts/backfill_expansions.py --silo-id <id>
    uv run python scripts/backfill_expansions.py --all-silos
    uv run python scripts/backfill_expansions.py --dry-run --silo-id <id>
    uv run python scripts/backfill_expansions.py --all-silos --batch-size 50

A resume file is written to the working directory (``backfill_expansions_resume.json``)
so the script can pick up from where it left off after interruption.  Pass
``--no-resume`` to ignore it and start over.

Requires:
    - A running Qdrant instance (configured via QDRANT_URL / .env).
    - A running Memgraph instance (for --all-silos silo discovery).
    - The ``splade`` extra: uv sync --extra splade
    - An LLM provider configured (expansion_llm_provider / expansion_llm_model settings).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
from typing import Any

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
from context_service.expansion.generator import ExpansionGenerator
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import DENSE_VECTOR_NAME, QdrantClient, get_collection_name

_DEFAULT_BATCH_SIZE = 100
_LOG_EVERY = 100
_RESUME_FILE = pathlib.Path("backfill_expansions_resume.json")

_LIST_SILOS = """
MATCH (n:Node)
WHERE n.silo_id IS NOT NULL
RETURN DISTINCT n.silo_id AS silo_id
"""


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------


def _load_resume() -> dict[str, Any]:
    if _RESUME_FILE.exists():
        try:
            return json.loads(_RESUME_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_resume(state: dict[str, Any]) -> None:
    _RESUME_FILE.write_text(json.dumps(state, indent=2))


def _clear_resume_silo(state: dict[str, Any], silo_id: str) -> None:
    state.pop(silo_id, None)
    _save_resume(state)


# ---------------------------------------------------------------------------
# Silo discovery
# ---------------------------------------------------------------------------


async def _list_silos(client: MemgraphClient) -> list[str]:
    rows: list[dict[str, Any]] = await client.execute_query(_LIST_SILOS)
    return [str(row["silo_id"]) for row in rows]


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


async def _backfill_silo(
    qdrant_client: QdrantClient,
    encoder: SpladeEncoder,
    generator: ExpansionGenerator,
    silo_id: str,
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    resume_state: dict[str, Any],
) -> int:
    """Backfill expansions and sparse vectors for one silo.

    Scrolls through Qdrant points for the silo, skipping any that already carry
    a non-empty ``expansion`` payload field. For the remainder it generates an
    expansion via the LLM, re-encodes the combined text through SPLADE, and
    upserts the updated point.

    Returns the number of points updated (or that would be updated in dry-run
    mode).
    """
    log = get_logger(__name__)
    client = await qdrant_client._get_client()

    # Check collection exists.
    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}
    if get_collection_name(silo_id) not in existing:
        log.warning("backfill_collection_missing", collection=get_collection_name(silo_id), silo_id=silo_id)
        return 0

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    query_filter = Filter(
        must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
    )

    # Resume: restore last offset for this silo if available.
    resume_offset: str | int | None = resume_state.get(silo_id)
    if resume_offset is not None:
        log.info("backfill_resuming", silo_id=silo_id, offset=resume_offset)

    total_updated = 0
    total_seen = 0
    offset: str | int | None = resume_offset

    while True:
        scroll_result = await client.scroll(
            collection_name=get_collection_name(silo_id),
            scroll_filter=query_filter,
            limit=batch_size,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )
        points, next_offset = scroll_result

        if not points:
            break

        total_seen += len(points)

        # Filter to points that need expansion: missing or empty field.
        needs_expansion = [
            p
            for p in points
            if p.payload is not None
            and not str(p.payload.get("expansion") or "").strip()
        ]

        if needs_expansion and not dry_run:
            contents = [
                str(
                    p.payload.get("content")
                    or p.payload.get("text")
                    or p.payload.get("node_id")
                    or str(p.id)
                )
                for p in needs_expansion
                if p.payload is not None
            ]

            # Generate expansions one-by-one (LLM calls are not batch-able in
            # the current ExpansionGenerator contract).
            expansions: list[str] = []
            for content in contents:
                expansion = await generator.generate(content)
                expansions.append(expansion)

            # Build combined texts for SPLADE: content + expansion.
            combined_texts = [
                f"{content} {expansion}".strip() if expansion else content
                for content, expansion in zip(contents, expansions, strict=True)
            ]

            try:
                sparse_vecs = await encoder.encode_batch(combined_texts)
            except SpladeEncoderError as exc:
                log.error("backfill_encode_error", silo_id=silo_id, error=str(exc))
                # Advance past this batch to avoid getting stuck.
                if next_offset is None:
                    break
                offset = next_offset
                resume_state[silo_id] = next_offset
                _save_resume(resume_state)
                continue

            from qdrant_client.models import PointStruct, SparseVector

            updated_points: list[PointStruct] = []
            for p, expansion, sparse in zip(
                needs_expansion, expansions, sparse_vecs, strict=False
            ):
                indices, values = encoder.to_qdrant(sparse)
                if not indices:
                    # SPLADE produced an empty vector — skip rather than corrupt.
                    log.warning("backfill_empty_sparse", point_id=str(p.id))
                    continue

                existing_payload = dict(p.payload or {})
                existing_payload["expansion"] = expansion

                existing_vectors = p.vector
                if isinstance(existing_vectors, dict):
                    dense_vec: list[float] = existing_vectors.get(DENSE_VECTOR_NAME, [])  # type: ignore[assignment]
                else:
                    dense_vec = list(existing_vectors or [])

                updated_points.append(
                    PointStruct(
                        id=p.id,
                        vector={
                            DENSE_VECTOR_NAME: dense_vec,
                            "sparse": SparseVector(indices=indices, values=values),
                        },
                        payload=existing_payload,
                    )
                )

            if updated_points:
                await client.upsert(
                    collection_name=get_collection_name(silo_id), points=updated_points
                )
                log.info(
                    "backfill_batch_upserted",
                    silo_id=silo_id,
                    count=len(updated_points),
                )

            total_updated += len(needs_expansion)
        elif dry_run:
            total_updated += len(needs_expansion)

        if total_seen % _LOG_EVERY == 0 or next_offset is None:
            log.info(
                "backfill_progress",
                silo_id=silo_id,
                seen=total_seen,
                updated=total_updated,
                dry_run=dry_run,
            )

        # Persist resume cursor after each batch.
        if next_offset is not None:
            resume_state[silo_id] = next_offset
            _save_resume(resume_state)

        if next_offset is None:
            break
        offset = next_offset

    # Silo complete — remove from resume file.
    _clear_resume_silo(resume_state, silo_id)

    if dry_run:
        log.info("backfill_dry_run", silo_id=silo_id, would_update=total_updated, seen=total_seen)
    else:
        log.info("backfill_complete", silo_id=silo_id, updated=total_updated, seen=total_seen)

    return total_updated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill doc2query expansions and re-encoded SPLADE sparse vectors "
            "for Qdrant points that pre-date the expansion feature."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--silo-id", metavar="ID", help="Backfill a single silo.")
    group.add_argument(
        "--all-silos",
        action="store_true",
        help="Discover and backfill all silos via Memgraph.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count points that need backfilling without writing anything.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Points per Qdrant scroll page (default: {_DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore the resume file and start from the beginning.",
    )
    parser.add_argument(
        "--splade-model",
        default="prithivida/Splade_PP_en_v1",
        help="SPLADE model name (default: prithivida/Splade_PP_en_v1).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)
    log = get_logger(__name__)

    resume_state: dict[str, Any] = {} if args.no_resume else _load_resume()
    if resume_state:
        log.info("backfill_resume_loaded", silos_in_progress=list(resume_state.keys()))

    encoder = SpladeEncoder(model_name=args.splade_model)
    generator = ExpansionGenerator()
    qdrant = QdrantClient.from_settings(settings)

    if args.all_silos:
        driver = await create_memgraph_driver(settings)
        memgraph = MemgraphClient(driver)
        try:
            silo_ids = await _list_silos(memgraph)
        finally:
            await memgraph.close()
        log.info("backfill_discovered_silos", count=len(silo_ids))
    else:
        silo_ids = [args.silo_id]

    total = 0
    for silo_id in silo_ids:
        total += await _backfill_silo(
            qdrant,
            encoder,
            generator,
            silo_id,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            resume_state=resume_state,
        )

    if args.dry_run:
        log.info("backfill_dry_run_total", would_update=total, silos=len(silo_ids))
    else:
        log.info("backfill_total", updated=total, silos=len(silo_ids))

    await generator.close()
    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
