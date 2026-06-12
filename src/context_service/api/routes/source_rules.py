"""Admin API routes for source tier rule management.

Endpoints:
    GET  /admin/source-rules       - list rules (silo + global)
    POST /admin/source-rules       - add rule with pattern validation
    DELETE /admin/source-rules/{id} - remove rule
    POST /admin/source-rules/test  - preview resolution for given evidence refs

Auth: the existing admin bearer key acts as super-admin for all operations
(no per-silo scoping yet). T13 adds proper RBAC when partner self-service
arrives. Supply `silo_id` explicitly; "silo inferred from auth" was a
WorkOS-era design that does not apply to the static admin key.

The plan references `org_id` as the query param, but the DB FK is
`silo_source_rules.silo_id -> silo_config.silo_id` -- no org_id column
exists. We use `silo_id` directly and document the deviation here.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from fnmatch import translate as fnmatch_translate
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from context_service.api.routes.admin import _require_admin_key
from context_service.db.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/source-rules", tags=["admin"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

SourceTierLiteral = Literal["authoritative", "validated", "community"]


class SourceRuleResponse(BaseModel):
    """A single source tier rule as returned by the API."""

    id: str
    silo_id: str | None
    pattern: str
    tier: str
    reason: str | None
    priority: int
    created_at: datetime
    created_by: str | None
    source: Literal["silo", "global"]


class ListSourceRulesResponse(BaseModel):
    rules: list[SourceRuleResponse]


class AddSourceRuleRequest(BaseModel):
    """Request body for adding a new source tier rule."""

    pattern: str = Field(..., min_length=1, max_length=500, description="fnmatch glob pattern")
    tier: SourceTierLiteral = Field(
        ..., description="Quality tier: authoritative, validated, or community"
    )
    reason: str | None = Field(
        default=None, max_length=500, description="Human-readable reason for this rule"
    )
    priority: int = Field(default=0, ge=0, le=1000, description="Higher priority checked first")
    silo_id: str | None = Field(
        default=None,
        description=(
            "Target silo UUID. Null creates a global rule (requires admin key). "
            "When absent, a global rule is created."
        ),
    )

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate that the pattern is a usable fnmatch glob."""
        if not v.strip():
            raise ValueError("pattern must not be blank")
        try:
            compiled_re = re.compile(fnmatch_translate(v))
        except re.error as exc:
            raise ValueError(f"pattern is not a valid fnmatch glob: {exc}") from exc
        # Smoke-test: try matching a sample string -- shouldn't raise
        compiled_re.match("test://example.com/path")
        return v

    @field_validator("silo_id")
    @classmethod
    def validate_silo_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"silo_id must be a valid UUID: {exc}") from exc
        return v


class AddSourceRuleResponse(BaseModel):
    rule: SourceRuleResponse


class TestResolutionRequest(BaseModel):
    """Request body for the resolution test/debug endpoint."""

    evidence_refs: list[str] = Field(
        ...,
        min_length=1,
        description="List of evidence URI strings to resolve (e.g. 'https://...' or 'node:<id>')",
    )
    agent_hint: str | None = Field(
        default=None,
        description="Caller-supplied tier hint as fallback (authoritative, validated, community)",
    )
    silo_id: str | None = Field(
        default=None,
        description=(
            "Silo UUID to include silo-specific rules. If absent, only global rules are applied."
        ),
    )

    @field_validator("silo_id")
    @classmethod
    def validate_silo_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"silo_id must be a valid UUID: {exc}") from exc
        return v


class MatchedRule(BaseModel):
    id: str | None = None
    pattern: str
    tier: str
    silo_id: str | None = None


class TestResolutionResponse(BaseModel):
    resolved_tier: str
    resolution_layer: str
    matched_rule: MatchedRule | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: object) -> SourceRuleResponse:
    """Convert a SQLAlchemy Row to SourceRuleResponse."""
    return SourceRuleResponse(
        id=str(row[0]),
        silo_id=str(row[1]) if row[1] is not None else None,
        pattern=row[2],
        tier=row[3],
        reason=row[4],
        priority=row[5],
        created_at=row[6],
        created_by=row[7],
        source="global" if row[1] is None else "silo",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ListSourceRulesResponse,
    operation_id="admin_list_source_rules",
    summary="List source tier rules",
    dependencies=[Depends(_require_admin_key)],
)
async def list_source_rules(
    silo_id: str | None = Query(
        default=None,
        description="Filter to rules for this silo UUID. When absent, returns only global rules.",
    ),
    include_global: bool = Query(
        default=True,
        description="Include global rules (silo_id IS NULL) in the result.",
    ),
) -> ListSourceRulesResponse:
    """List source tier rules.

    When `silo_id` is provided, returns that silo's rules plus (optionally)
    global rules. Without `silo_id`, returns only global rules when
    `include_global=true`, or an empty list otherwise.
    """
    if silo_id is not None:
        try:
            uuid.UUID(silo_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="silo_id must be a valid UUID") from exc

    async with get_session() as session:
        if silo_id is not None and include_global:
            result = await session.execute(
                text(
                    """
                    SELECT id::text, silo_id, pattern, tier, reason, priority,
                           created_at, created_by
                    FROM silo_source_rules
                    WHERE silo_id = :silo_id OR silo_id IS NULL
                    ORDER BY (silo_id IS NOT NULL) DESC, priority DESC, created_at DESC
                    """
                ),
                {"silo_id": silo_id},
            )
        elif silo_id is not None:
            result = await session.execute(
                text(
                    """
                    SELECT id::text, silo_id, pattern, tier, reason, priority,
                           created_at, created_by
                    FROM silo_source_rules
                    WHERE silo_id = :silo_id
                    ORDER BY priority DESC, created_at DESC
                    """
                ),
                {"silo_id": silo_id},
            )
        elif include_global:
            result = await session.execute(
                text(
                    """
                    SELECT id::text, silo_id, pattern, tier, reason, priority,
                           created_at, created_by
                    FROM silo_source_rules
                    WHERE silo_id IS NULL
                    ORDER BY priority DESC, created_at DESC
                    """
                ),
            )
        else:
            return ListSourceRulesResponse(rules=[])

        rows = result.fetchall()

    rules = [_row_to_response(row) for row in rows]
    logger.info(
        "admin_source_rules.list",
        silo_id=silo_id,
        include_global=include_global,
        count=len(rules),
    )
    return ListSourceRulesResponse(rules=rules)


@router.post(
    "",
    response_model=AddSourceRuleResponse,
    operation_id="admin_add_source_rule",
    summary="Add a source tier rule",
    status_code=201,
    dependencies=[Depends(_require_admin_key)],
)
async def add_source_rule(body: AddSourceRuleRequest) -> AddSourceRuleResponse:
    """Add a new source tier rule.

    When `silo_id` is absent, creates a global rule (applies to all silos).
    Duplicate (silo_id, pattern) pairs are rejected with 409.
    """
    rule_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with get_session() as session:
        # Verify silo exists if silo_id is supplied
        if body.silo_id is not None:
            silo_check = await session.execute(
                text("SELECT 1 FROM silo_config WHERE silo_id = :silo_id"),
                {"silo_id": body.silo_id},
            )
            if silo_check.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Silo '{body.silo_id}' not found")

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO silo_source_rules
                        (id, silo_id, pattern, tier, reason, priority, created_at)
                    VALUES
                        (:id, :silo_id, :pattern, :tier, :reason, :priority, :created_at)
                    """
                ),
                {
                    "id": rule_id,
                    "silo_id": body.silo_id,
                    "pattern": body.pattern,
                    "tier": body.tier,
                    "reason": body.reason,
                    "priority": body.priority,
                    "created_at": now,
                },
            )
            await session.commit()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "unique" in exc_str or "duplicate" in exc_str or "uq_silo_source_rules" in exc_str:
                raise HTTPException(
                    status_code=409,
                    detail=f"Rule with pattern '{body.pattern}' already exists for this silo",
                ) from exc
            raise

    rule = SourceRuleResponse(
        id=rule_id,
        silo_id=body.silo_id,
        pattern=body.pattern,
        tier=body.tier,
        reason=body.reason,
        priority=body.priority,
        created_at=now,
        created_by=None,
        source="global" if body.silo_id is None else "silo",
    )

    logger.info(
        "admin_source_rules.added",
        rule_id=rule_id,
        silo_id=body.silo_id,
        pattern=body.pattern,
        tier=body.tier,
    )
    return AddSourceRuleResponse(rule=rule)


@router.delete(
    "/{rule_id}",
    status_code=204,
    operation_id="admin_delete_source_rule",
    summary="Delete a source tier rule",
    dependencies=[Depends(_require_admin_key)],
)
async def delete_source_rule(rule_id: str) -> None:
    """Delete a source tier rule by ID.

    Partner admins can only delete silo-specific rules (T13 adds enforcement).
    Global rules (silo_id IS NULL) can be deleted by the admin key holder
    (which acts as super-admin until T13 RBAC is implemented).
    """
    try:
        uuid.UUID(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="rule_id must be a valid UUID") from exc

    async with get_session() as session:
        result = await session.execute(
            text("DELETE FROM silo_source_rules WHERE id = :id RETURNING id::text"),
            {"id": rule_id},
        )
        deleted = result.fetchone()
        await session.commit()

    if deleted is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    logger.info("admin_source_rules.deleted", rule_id=rule_id)


@router.post(
    "/test",
    response_model=TestResolutionResponse,
    operation_id="admin_test_source_resolution",
    summary="Preview source tier resolution for given evidence refs",
    dependencies=[Depends(_require_admin_key)],
)
async def test_source_resolution(body: TestResolutionRequest) -> TestResolutionResponse:
    """Preview source tier resolution without storing anything.

    Runs the same resolver logic as the `learn` tool but returns the result
    directly. Useful for debugging rule configurations before adding them.

    When `silo_id` is absent, a nil UUID is used so only global rules apply.
    """
    from context_service.services.source_tier_resolver import resolve_source_tier

    # Use nil UUID to get global-only resolution when no silo is supplied
    effective_silo_id = body.silo_id or "00000000-0000-0000-0000-000000000000"

    resolved_tier, resolution_layer = await resolve_source_tier(
        silo_id=effective_silo_id,
        evidence_refs=body.evidence_refs,
        agent_hint=body.agent_hint,
    )

    # Attempt to find the matched rule for informational purposes
    matched_rule: MatchedRule | None = None
    if resolution_layer in ("silo_rule", "global_rule"):
        from fnmatch import fnmatch

        async with get_session() as session:
            if resolution_layer == "silo_rule" and body.silo_id:
                result = await session.execute(
                    text(
                        """
                        SELECT id::text, pattern, tier, silo_id
                        FROM silo_source_rules
                        WHERE silo_id = :silo_id
                        ORDER BY priority DESC
                        """
                    ),
                    {"silo_id": effective_silo_id},
                )
            else:
                result = await session.execute(
                    text(
                        """
                        SELECT id::text, pattern, tier, silo_id
                        FROM silo_source_rules
                        WHERE silo_id IS NULL
                        ORDER BY priority DESC
                        """
                    ),
                )
            rows = result.fetchall()

        for ref in body.evidence_refs:
            if ref.startswith("node:"):
                continue
            for row in rows:
                if fnmatch(ref, row[1]):
                    matched_rule = MatchedRule(
                        id=row[0],
                        pattern=row[1],
                        tier=row[2],
                        silo_id=str(row[3]) if row[3] is not None else None,
                    )
                    break
            if matched_rule:
                break

    logger.info(
        "admin_source_rules.test",
        evidence_count=len(body.evidence_refs),
        silo_id=body.silo_id,
        resolved_tier=resolved_tier.value,
        resolution_layer=resolution_layer,
    )

    return TestResolutionResponse(
        resolved_tier=resolved_tier.value,
        resolution_layer=resolution_layer,
        matched_rule=matched_rule,
    )
