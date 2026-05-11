"""Import a silo's graph state from a JSONL dump produced by silo_export.py.

Usage:
    uv run python -m scripts.silo_import --in dump.jsonl --target-silo <uuid>
    uv run python -m scripts.silo_import --in dump.jsonl --target-silo <uuid> --rename-silo <new-uuid>
    uv run python -m scripts.silo_import --in dump.jsonl --target-silo <uuid> --dry-run
    uv run python -m scripts.silo_import --in dump.jsonl --target-silo <uuid> --force

Import is idempotent: MERGE semantics on both nodes and edges ensure that
re-running on a partially-imported target completes without duplication.

See context/specs/silo-portability.md for the wire format.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver
from context_service.stores.qdrant import QdrantClient

_SUPPORTED_SCHEMA_VERSIONS = frozenset([1])

# ---------------------------------------------------------------------------
# Cypher helpers
#
# MERGE on (id(), silo_id) would be cleanest, but id() from the source env is
# not valid in the target. Instead we key nodes on their application-layer
# `id` property (which every silo node carries) plus the target silo_id. If a
# node record has no `id` property we fall back to `_export_element_id`, a
# synthetic property written during import.
#
# Labels: Memgraph requires each label to be a literal in Cypher; we can't
# pass a list as a parameter and have them applied as labels. We build the
# label portion of the query dynamically from the record's `labels` list and
# then use apoc-style SET calls — but Memgraph doesn't have APOC. The
# supported approach is to pass labelling as part of the MERGE pattern by
# constructing the Cypher string with the labels embedded.
# ---------------------------------------------------------------------------

_COUNT_SILO_NODES = "MATCH (n {silo_id: $silo_id}) RETURN count(n) AS cnt"


def _build_node_merge(labels: list[str], properties: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (cypher, params) for a single node upsert.

    Memgraph does not support dynamic label application via parameters, so we
    embed the label tokens directly in the query string. Label names are
    restricted to identifier characters; we sanitise them before embedding.
    """
    safe_labels = [_sanitize_label(lb) for lb in labels if lb]
    label_str = "".join(f":{lb}" for lb in safe_labels) if safe_labels else ""

    # Key the MERGE on the app-layer id + silo_id so the import is idempotent
    # and stable across multiple runs. Nodes without an `id` property use the
    # export element ID as a fallback key.
    node_id = properties.get("id") or properties.get("_export_element_id", "")

    params: dict[str, Any] = {"node_id": node_id, "silo_id": properties.get("silo_id", "")}

    # Build SET clause for remaining properties
    set_pairs: list[str] = []
    prop_params: dict[str, Any] = {}
    for k, v in properties.items():
        # already in MERGE key or reserved
        if k in ("id", "silo_id"):
            continue
        param_name = f"p_{k}"
        set_pairs.append(f"n.{k} = ${param_name}")
        prop_params[param_name] = v

    params.update(prop_params)

    set_clause = ("SET " + ", ".join(set_pairs)) if set_pairs else ""

    cypher = f"""
MERGE (n{label_str} {{id: $node_id, silo_id: $silo_id}})
{set_clause}
RETURN id(n) AS eid
"""
    return cypher.strip(), params


def _build_edge_merge(
    src_node_id: str,
    dst_node_id: str,
    src_silo: str,
    dst_silo: str,
    rel_type: str,
    properties: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return (cypher, params) for a single edge upsert."""
    safe_type = _sanitize_label(rel_type)
    params: dict[str, Any] = {
        "src_id": src_node_id,
        "dst_id": dst_node_id,
        "src_silo": src_silo,
        "dst_silo": dst_silo,
    }

    set_pairs: list[str] = []
    for k, v in properties.items():
        param_name = f"ep_{k}"
        set_pairs.append(f"r.{k} = ${param_name}")
        params[param_name] = v

    set_clause = ("SET " + ", ".join(set_pairs)) if set_pairs else ""

    cypher = f"""
MATCH (a {{id: $src_id, silo_id: $src_silo}}), (b {{id: $dst_id, silo_id: $dst_silo}})
MERGE (a)-[r:{safe_type}]->(b)
{set_clause}
RETURN count(r) AS cnt
"""
    return cypher.strip(), params


def _sanitize_label(label: str) -> str:
    """Return label with non-identifier characters stripped.

    Allows ASCII letters, digits, and underscores only.
    """
    return "".join(c for c in label if c.isalnum() or c == "_")


class SiloImporter:
    """Stateful importer that tracks element-ID-to-app-ID mapping."""

    def __init__(
        self,
        client: MemgraphClient,
        target_silo_id: str,
        *,
        dry_run: bool = False,
    ) -> None:
        self._client = client
        self._target_silo_id = target_silo_id
        self._dry_run = dry_run
        # Maps export element ID -> app-layer id property value
        self._eid_to_app_id: dict[str, str] = {}
        self._log = get_logger(__name__)

    def _rewrite_silo(self, props: dict[str, Any]) -> dict[str, Any]:
        """Replace silo_id in property dict with the target silo."""
        out = dict(props)
        if "silo_id" in out:
            out["silo_id"] = self._target_silo_id
        return out

    async def import_node(self, record: dict[str, Any]) -> None:
        export_eid: str = record["id"]
        labels: list[str] = record.get("labels", [])
        props = self._rewrite_silo(record.get("properties", {}))

        # Stash the export element id as a synthetic property so edge resolution
        # can use it as a fallback when app-layer `id` is absent.
        if "id" not in props:
            props["_export_element_id"] = export_eid

        app_id: str = props.get("id") or props.get("_export_element_id", export_eid)
        self._eid_to_app_id[export_eid] = app_id

        if self._dry_run:
            self._log.debug("dry_run_node", export_eid=export_eid, labels=labels)
            return

        cypher, params = _build_node_merge(labels, props)
        await self._client.execute_write(cypher, params)

    async def import_edge(self, record: dict[str, Any]) -> None:
        src_eid: str = record["src"]
        dst_eid: str = record["dst"]
        rel_type: str = record["type"]
        props = record.get("properties", {})

        src_app_id = self._eid_to_app_id.get(src_eid)
        dst_app_id = self._eid_to_app_id.get(dst_eid)

        if src_app_id is None or dst_app_id is None:
            self._log.warning(
                "edge_endpoint_unresolved",
                src_eid=src_eid,
                dst_eid=dst_eid,
                rel_type=rel_type,
            )
            return

        if self._dry_run:
            self._log.debug(
                "dry_run_edge",
                src=src_app_id,
                dst=dst_app_id,
                rel_type=rel_type,
            )
            return

        cypher, params = _build_edge_merge(
            src_app_id,
            dst_app_id,
            self._target_silo_id,
            self._target_silo_id,
            rel_type,
            props,
        )
        await self._client.execute_write(cypher, params)

    async def import_vector(self, record: dict[str, Any], qdrant: QdrantClient) -> None:
        node_id: str = record["node_id"]
        dense: list[float] = record.get("dense", [])
        if not dense:
            self._log.warning("vector_empty", node_id=node_id)
            return
        if self._dry_run:
            self._log.debug("dry_run_vector", node_id=node_id)
            return
        await qdrant.upsert(
            node_id=node_id,
            vector=dense,
            payload={"node_id": node_id},
            silo_id=self._target_silo_id,
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a silo from a JSONL dump produced by silo_export."
    )
    parser.add_argument(
        "--in",
        dest="infile",
        required=True,
        metavar="PATH",
        help="Input JSONL dump file.",
    )
    parser.add_argument(
        "--target-silo",
        required=True,
        metavar="UUID",
        help="Target silo ID in the destination environment.",
    )
    parser.add_argument(
        "--rename-silo",
        metavar="NEW_UUID",
        help=(
            "Rewrite silo_id on all records to this value. "
            "Required when source and target environments share the same silo ID."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without mutating the graph.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the pre-existing-silo guard.",
    )
    parser.add_argument(
        "--allow-cross-env",
        action="store_true",
        help="Suppress the cross-environment warning.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_format=True)
    log = get_logger(__name__)

    inpath = Path(args.infile)
    if not inpath.exists():
        log.error("input_file_not_found", path=str(inpath))
        sys.exit(1)

    # --- Read and validate manifest ---
    with open(inpath, encoding="utf-8") as f:
        first_line = f.readline().strip()

    if not first_line:
        log.error("empty_dump_file", path=str(inpath))
        sys.exit(1)

    try:
        first_obj: dict[str, Any] = json.loads(first_line)
    except json.JSONDecodeError as exc:
        log.error("manifest_parse_error", error=str(exc))
        sys.exit(1)

    if "_manifest" not in first_obj:
        log.error("missing_manifest", first_line=first_line[:120])
        sys.exit(1)

    manifest: dict[str, Any] = first_obj["_manifest"]
    schema_version: int = manifest.get("schema_version", 0)
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        log.error(
            "unsupported_schema_version",
            schema_version=schema_version,
            supported=sorted(_SUPPORTED_SCHEMA_VERSIONS),
        )
        sys.exit(1)

    source_silo_id: str = manifest.get("silo_id", "")
    source_env: str = manifest.get("source_env", "unknown")
    exported_at: str = manifest.get("exported_at", "unknown")

    log.info(
        "manifest_loaded",
        source_silo_id=source_silo_id,
        source_env=source_env,
        exported_at=exported_at,
        schema_version=schema_version,
    )

    # Cross-environment warning
    if source_env != settings.environment and not args.allow_cross_env:
        log.warning(
            "cross_env_import",
            source_env=source_env,
            target_env=settings.environment,
            advice="Pass --allow-cross-env to suppress this warning.",
        )

    # Determine effective target silo
    target_silo_id: str = args.rename_silo if args.rename_silo else args.target_silo

    driver = await create_memgraph_driver(settings)
    client = MemgraphClient(driver)

    try:
        # Pre-existing silo guard
        if not args.force and not args.dry_run:
            rows = await client.execute_query(_COUNT_SILO_NODES, {"silo_id": target_silo_id})
            existing_count: int = rows[0]["cnt"] if rows else 0
            if existing_count > 0:
                log.error(
                    "target_silo_not_empty",
                    target_silo_id=target_silo_id,
                    existing_node_count=existing_count,
                    advice=(
                        "Target silo already has nodes. "
                        "Use --force to import anyway, or choose a different --target-silo."
                    ),
                )
                sys.exit(1)

        # --rename-silo safety: if same ID in target env without rename, warn.
        if not args.rename_silo and source_silo_id == args.target_silo:
            log.warning(
                "same_silo_id_no_rename",
                silo_id=source_silo_id,
                advice=(
                    "Source and target share the same silo ID. "
                    "Consider --rename-silo <new-uuid> to avoid accidental overwrites."
                ),
            )

        importer = SiloImporter(client, target_silo_id, dry_run=args.dry_run)

        # Qdrant client — lazy, only created if vectors are in the dump
        qdrant: QdrantClient | None = None

        nodes = 0
        edges = 0
        vectors = 0
        skipped = 0

        with open(inpath, encoding="utf-8") as f:
            # Skip manifest line
            f.readline()
            for lineno, raw in enumerate(f, start=2):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    log.warning("record_parse_error", lineno=lineno, error=str(exc))
                    skipped += 1
                    continue

                kind = record.get("kind")
                if kind == "node":
                    await importer.import_node(record)
                    nodes += 1
                elif kind == "edge":
                    await importer.import_edge(record)
                    edges += 1
                elif kind == "vector":
                    if qdrant is None:
                        qdrant = QdrantClient.from_settings(settings)
                        if not args.dry_run:
                            await qdrant.ensure_collection()
                    await importer.import_vector(record, qdrant)
                    vectors += 1
                else:
                    log.warning("unknown_record_kind", kind=kind, lineno=lineno)
                    skipped += 1

        if vectors == 0 and not args.dry_run:
            log.warning(
                "no_vectors_imported",
                advice=(
                    "No vector records in dump. "
                    "Run the embedding pipeline to regenerate vectors for this silo."
                ),
            )

        prefix = "dry_run_" if args.dry_run else ""
        log.info(
            f"{prefix}import_complete",
            target_silo_id=target_silo_id,
            nodes=nodes,
            edges=edges,
            vectors=vectors,
            skipped=skipped,
        )

    finally:
        await client.close()
        if qdrant is not None:
            await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
