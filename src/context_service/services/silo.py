"""Silo management service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.models.silo import SiloConfig
from context_service.services.models import ScopeContext, Silo, derive_silo_id

if TYPE_CHECKING:
    from context_service.cache.silo_ownership_cache import SiloOwnershipCache
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a datetime from Memgraph -- handles str, native datetime, neo4j DateTime, and epoch-us int."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Memgraph timestamp() returns epoch-microseconds (not ms)
        return datetime.fromtimestamp(value / 1_000_000.0, tz=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    # neo4j driver returns neo4j.time.DateTime -- convert via iso_format()
    if hasattr(value, "iso_format"):
        return datetime.fromisoformat(value.iso_format())
    if hasattr(value, "to_native"):
        native = value.to_native()
        if not isinstance(native, datetime):
            raise TypeError(f"to_native() returned {type(native).__name__!r}, expected datetime")
        return native
    return datetime.fromisoformat(str(value))


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
                dissolvability: $dissolvability,
                created_at: datetime()
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
                   s.causal_coverage_from AS causal_coverage_from,
                   s.created_at AS created_at
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
            created_at=_parse_datetime(row.get("created_at")),
        )

    async def list(self, org_id: str) -> list[Silo]:
        """List all silos for an org."""
        results = await self._memgraph.execute_query(
            """
            MATCH (s:Silo {org_id: $org_id})
            RETURN s.id AS id, s.name AS name, s.org_id AS org_id,
                   s.description AS description, s.dissolvability AS dissolvability,
                   s.created_at AS created_at
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
                created_at=_parse_datetime(row.get("created_at")),
            )
            for row in results
        ]

    async def get_silo_config(self, scope: ScopeContext) -> SiloConfig:
        """Return the per-silo config for *scope*.

        If the silo has no stored config, an empty SiloConfig (all overrides
        None, meaning global settings apply) is returned.
        """
        results = await self._memgraph.execute_query(
            """
            MATCH (s:Silo {id: $silo_id, org_id: $org_id})
            RETURN s.silo_config AS silo_config
            """,
            {"silo_id": str(scope.silo_id), "org_id": scope.org_id},
        )

        if not results:
            logger.warning(
                "get_silo_config.silo_not_found",
                silo_id=str(scope.silo_id),
                org_id=scope.org_id,
            )
            return SiloConfig()

        raw = results[0].get("silo_config")
        if not raw:
            return SiloConfig()

        data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
        return SiloConfig.from_metadata_dict(data)

    async def update_silo_config(
        self,
        scope: ScopeContext,
        config: SiloConfig,
    ) -> SiloConfig:
        """Persist *config* for the silo identified by *scope*.

        The config is serialised to JSON and stored on the Silo node's
        ``silo_config`` property. Returns the stored config.
        """
        serialised = json.dumps(config.to_metadata_dict())

        await self._memgraph.execute_write(
            """
            MATCH (s:Silo {id: $silo_id, org_id: $org_id})
            SET s.silo_config = $silo_config
            """,
            {
                "silo_id": str(scope.silo_id),
                "org_id": scope.org_id,
                "silo_config": serialised,
            },
        )

        logger.info(
            "silo_config_updated",
            silo_id=str(scope.silo_id),
            org_id=scope.org_id,
        )
        return config


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
