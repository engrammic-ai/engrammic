"""Apply scalar quantization to existing Qdrant collections.

Usage:
    uv run python scripts/migrate_qdrant_quantization.py [--dry-run] [--prefix PREFIX]

Targets all collections matching ctx_* and ctx_clusters_* prefixes.
Calls update_collection with ScalarQuantization(INT8, always_ram=True).
Non-destructive: Qdrant rebuilds the quantized index incrementally.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import ScalarQuantization, ScalarQuantizationConfig, ScalarType

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings

_COLLECTION_PREFIXES = ("ctx_", "ctx_clusters_")


def _has_int8_quantization(collection_info: object) -> bool:
    """Return True if the collection already has INT8 scalar quantization configured."""
    try:
        quant = collection_info.config.quantization_config  # type: ignore[union-attr]
        if quant is None:
            return False
        scalar = getattr(quant, "scalar", None)
        if scalar is None:
            return False
        return getattr(scalar, "type", None) == ScalarType.INT8
    except AttributeError:
        return False


async def run_migration(
    *,
    dry_run: bool = False,
    prefix: str | None = None,
    always_ram: bool = True,
) -> int:
    """Apply INT8 scalar quantization to matching Qdrant collections.

    Returns the number of collections that were updated (or would be updated
    in dry-run mode). Returns -1 if any update fails.
    """
    settings = get_settings()
    log = get_logger(__name__)

    api_key: str | None = None
    if settings.qdrant_api_key is not None:
        api_key = settings.qdrant_api_key.get_secret_value()

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key)

    try:
        collections_response = await client.get_collections()
        all_names = [c.name for c in collections_response.collections]
    except Exception as exc:
        log.error("migration_list_collections_failed", error=str(exc))
        await client.close()
        return -1

    # Determine target prefixes.
    if prefix is not None:
        target_prefixes = (prefix,)
    else:
        target_prefixes = _COLLECTION_PREFIXES

    targeted = [n for n in all_names if any(n.startswith(p) for p in target_prefixes)]

    if not targeted:
        log.info("migration_no_collections_matched", prefixes=list(target_prefixes))
        await client.close()
        return 0

    log.info(
        "migration_collections_targeted",
        count=len(targeted),
        collections=targeted,
        dry_run=dry_run,
    )

    updated = 0
    failed = 0

    for name in targeted:
        try:
            info = await client.get_collection(name)
        except Exception as exc:
            log.error("migration_get_collection_failed", collection=name, error=str(exc))
            failed += 1
            continue

        if _has_int8_quantization(info):
            log.info("migration_skip_already_quantized", collection=name)
            continue

        current_quant = None
        try:
            current_quant = info.config.quantization_config  # type: ignore[union-attr]
        except AttributeError:
            pass

        log.info(
            "migration_will_apply_quantization",
            collection=name,
            current_quantization=str(current_quant),
            dry_run=dry_run,
        )

        if dry_run:
            updated += 1
            continue

        try:
            await client.update_collection(
                collection_name=name,
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        always_ram=always_ram,
                    )
                ),
            )
            log.info("migration_applied_quantization", collection=name, always_ram=always_ram)
            updated += 1
        except Exception as exc:
            log.error("migration_update_failed", collection=name, error=str(exc))
            failed += 1

    await client.close()

    if dry_run:
        log.info("migration_dry_run_complete", would_update=updated, skipped=len(targeted) - updated)
    else:
        log.info(
            "migration_complete",
            updated=updated,
            failed=failed,
            total_targeted=len(targeted),
        )

    return -1 if failed > 0 else updated


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply INT8 scalar quantization to existing Qdrant collections."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List targeted collections and current quantization status without applying changes.",
    )
    parser.add_argument(
        "--prefix",
        metavar="PREFIX",
        default=None,
        help="Scope to collections matching a specific prefix (default: ctx_ and ctx_clusters_).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)

    result = await run_migration(dry_run=args.dry_run, prefix=args.prefix)
    if result < 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
