"""Silo management service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from context_service.services.models import ScopeContext, Silo, derive_silo_id

if TYPE_CHECKING:
    from context_service.cache.silo_ownership_cache import SiloOwnershipCache
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class SiloService:
    """Manages organizational containers within a tenant."""

    def __init__(
        self,
        memgraph: HyperGraphStore,
        ownership_cache: SiloOwnershipCache | None = None,
    ) -> None:
        self._memgraph = memgraph
        self.ownership_cache = ownership_cache

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
                   s.description AS description, s.dissolvability AS dissolvability,
                   s.causal_coverage_from AS causal_coverage_from
            """,
            {"silo_id": str(scope.silo_id), "org_id": scope.org_id},
        )

        if not results:
            return None

        row = results[0]
        meta: dict[str, Any] = {}
        if row.get("causal_coverage_from") is not None:
            meta["causal_coverage_from"] = row["causal_coverage_from"]
        return Silo(
            id=uuid.UUID(row["id"]),
            name=row["name"],
            org_id=row["org_id"],
            description=row.get("description"),
            dissolvability=row.get("dissolvability", 0.5),
            metadata=meta,
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


async def validate_silo_ownership(
    silo_service: SiloService,
    silo_id: str,
    org_id: str,
) -> dict[str, Any] | None:
    """Validate that a silo exists and belongs to the given org.

    Returns None on success, or an error dict if validation fails.
    The silo_id must be a valid UUID and match the org's deterministic silo.
    Auto-creates the silo if it doesn't exist (MVP 1:1 model).
    """
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    expected = derive_silo_id(org_id)
    if requested != expected:
        return {
            "error": "silo_not_found",
            "silo_id": silo_id,
            "message": "Silo does not exist or org_id mismatch.",
        }

    cache = silo_service.ownership_cache
    if cache is not None:
        cached = await cache.get(org_id, silo_id)
        if cached is True:
            return None

    # Auto-create silo if it doesn't exist (MVP 1:1 model)
    await ensure_silo(silo_service, org_id)

    if cache is not None:
        await cache.set(org_id, silo_id)

    return None


async def ensure_silo(silo_service: SiloService, org_id: str) -> Silo:
    """Get or create the org's silo. Used for auto-create on first tool use.

    MVP model: 1:1 org-to-silo mapping. The silo is auto-created with a
    default name if it doesn't exist.
    """
    derived_id = derive_silo_id(org_id)
    scope = ScopeContext(org_id=org_id, silo_id=derived_id)

    existing = await silo_service.get_by_id(scope)
    if existing is not None:
        return existing

    return await silo_service.get_or_create(
        name="default",
        org_id=org_id,
        description="Auto-created org silo",
    )
