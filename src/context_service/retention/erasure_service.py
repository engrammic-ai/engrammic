"""GDPR erasure service with cascade and audit logging."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.postgres.audit import ErasureAuditLog
from context_service.retention.service import RetentionService

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore

logger = structlog.get_logger(__name__)


# Query to find nodes that reference this node (for cascade)
FIND_REFERENCING_NODES = """
MATCH (n {silo_id: $silo_id})-[r]->(target {id: $id, silo_id: $silo_id})
WHERE n.id <> $id
RETURN DISTINCT n.id AS node_id
"""


class ErasureService:
    """Handle GDPR right-to-erasure requests."""

    def __init__(
        self,
        store: HyperGraphStore,
        qdrant_store: EngineQdrantStore | None,
        db_session: AsyncSession,
    ) -> None:
        self._store = store
        self._qdrant_store = qdrant_store
        self._db_session = db_session
        self._retention = RetentionService(store=store, qdrant_store=qdrant_store)

    async def erase(
        self,
        node_ids: list[str],
        silo_id: str,
        requester_type: str,  # 'user', 'admin', 'system'
        requester_id: str | None = None,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Permanently erase nodes with full audit trail."""
        request_id = str(uuid.uuid4())
        requested_at = datetime.now(UTC)

        erased_ids: list[str] = []
        failed_ids: list[str] = []
        cascade_count = 0
        error_details: dict[str, str] = {}

        # Build full list of nodes to delete (originals + cascade targets)
        all_node_ids = list(node_ids)
        if cascade:
            for node_id in node_ids:
                refs = await self._store.execute_query(
                    FIND_REFERENCING_NODES,
                    {"id": node_id, "silo_id": silo_id},
                )
                for ref in refs:
                    ref_id = ref["node_id"]
                    if ref_id not in all_node_ids:
                        all_node_ids.append(ref_id)
                        cascade_count += 1

        # Hard delete each node
        for node_id in all_node_ids:
            try:
                deleted = await self._retention.hard_delete_node(
                    node_id=node_id,
                    silo_id=silo_id,
                )
                if deleted:
                    erased_ids.append(node_id)
                else:
                    # Node not found counts as a failure to erase
                    failed_ids.append(node_id)
                    error_details[node_id] = "node not found"
            except Exception as e:
                logger.error("erasure_failed", node_id=node_id, error=str(e))
                failed_ids.append(node_id)
                error_details[node_id] = str(e)

        # Determine status
        if not failed_ids:
            status = "completed"
        elif not erased_ids:
            status = "failed"
        else:
            status = "partial"

        # Write audit log
        completed_at = datetime.now(UTC)
        audit_log = ErasureAuditLog(
            silo_id=silo_id,
            request_id=request_id,
            requester_type=requester_type,
            requester_id=requester_id,
            node_ids=erased_ids + failed_ids,
            cascade_count=cascade_count,
            status=status,
            error_details=error_details if error_details else None,
            requested_at=requested_at,
            completed_at=completed_at,
        )
        self._db_session.add(audit_log)
        await self._db_session.commit()

        logger.info(
            "erasure_complete",
            request_id=request_id,
            erased=len(erased_ids),
            failed=len(failed_ids),
            cascade_count=cascade_count,
        )

        return {
            "request_id": request_id,
            "status": status,
            "erased_count": len(erased_ids),
            "failed_count": len(failed_ids),
            "cascade_count": cascade_count,
            "erased_ids": erased_ids,
            "failed_ids": failed_ids,
        }
