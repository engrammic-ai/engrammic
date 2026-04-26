"""Silo management service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from context_service.services.models import ScopeContext, Silo, derive_silo_id

if TYPE_CHECKING:
    from context_service.stores import MemgraphClient

logger = structlog.get_logger(__name__)


class SiloService:
    """Manages organizational containers within a tenant."""

    def __init__(self, memgraph: MemgraphClient) -> None:
        self._memgraph = memgraph

    async def get_or_create(
        self,
        name: str,
        org_id: str,
        *,
        description: str | None = None,
        dissolvability: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> Silo:
        """Get existing silo or create if not exists (idempotent).

        MVP 1:1 per org: silo_id is deterministic from org_id.
        """
        derived_id = derive_silo_id(org_id)

        existing = await self.get_by_id(ScopeContext(org_id=org_id, silo_id=derived_id))
        if existing is not None:
            return existing

        silo = Silo(
            id=derived_id,
            name=name,
            org_id=org_id,
            description=description,
            dissolvability=dissolvability,
            metadata=metadata or {},
        )

        await self._memgraph.execute_write(
            """
            CREATE (s:Silo {
                id: $id,
                name: $name,
                org_id: $org_id,
                description: $description,
                dissolvability: $dissolvability
            })
            RETURN s
            """,
            {
                "id": str(silo.id),
                "name": silo.name,
                "org_id": silo.org_id,
                "description": silo.description or "",
                "dissolvability": silo.dissolvability,
            },
        )

        logger.info("silo_created", silo_name=name, org_id=org_id, silo_id=str(derived_id))
        return silo

    async def get_by_id(self, scope: ScopeContext) -> Silo | None:
        """Get silo by ID, scoped to org."""
        results = await self._memgraph.execute_query(
            """
            MATCH (s:Silo {id: $silo_id, org_id: $org_id})
            RETURN s.id AS id, s.name AS name, s.org_id AS org_id,
                   s.description AS description, s.dissolvability AS dissolvability
            """,
            {"silo_id": str(scope.silo_id), "org_id": scope.org_id},
        )

        if not results:
            return None

        row = results[0]
        return Silo(
            id=uuid.UUID(row["id"]),
            name=row["name"],
            org_id=row["org_id"],
            description=row.get("description"),
            dissolvability=row.get("dissolvability", 0.5),
        )

    async def list(self, org_id: str) -> list[Silo]:
        """List all silos for an org."""
        results = await self._memgraph.execute_query(
            """
            MATCH (s:Silo {org_id: $org_id})
            RETURN s.id AS id, s.name AS name, s.org_id AS org_id,
                   s.description AS description, s.dissolvability AS dissolvability
            ORDER BY s.name
            """,
            {"org_id": org_id},
        )

        return [
            Silo(
                id=uuid.UUID(row["id"]),
                name=row["name"],
                org_id=row["org_id"],
                description=row.get("description"),
                dissolvability=row.get("dissolvability", 0.5),
            )
            for row in results
        ]
