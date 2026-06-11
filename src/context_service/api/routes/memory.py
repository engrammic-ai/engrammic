"""REST wrapper endpoints for memory operations.

Exposes remember and recall over HTTP for benchmark harnesses and headless
integrations that cannot use the MCP transport.

Headers:
- X-Silo-ID: required for both endpoints; treated as org_id, silo UUID is derived
- X-Session-ID: required for remember, optional for recall
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from context_service.config.models import load_models_config
from context_service.config.settings import get_settings
from context_service.mcp.server import get_context_service
from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.query_expander import QueryExpander
from context_service.sage.transactions import store_memory
from context_service.services.models import ScopeContext, derive_silo_id

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["memory"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RememberRequest(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)


class RememberResponse(BaseModel):
    node_id: str
    created_at: str


class RecallRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=100)


class RecallResultItem(BaseModel):
    node_id: str
    content: str | None = None
    layer: str | None = None
    confidence: float | None = None
    relevance_score: float | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    summary: str | None = None


class RecallResponse(BaseModel):
    results: list[RecallResultItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/remember",
    response_model=RememberResponse,
    operation_id="memory_remember",
    summary="Store an observation to memory",
)
async def remember(
    request_body: RememberRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> RememberResponse:
    """Store an observation to the memory layer.

    The ``X-Silo-ID`` header is treated as the org ID; the actual silo UUID is
    derived deterministically from it, matching how the MCP surface works.
    ``X-Session-ID`` is used as the ``agent_id`` on the written node.
    """
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)

    try:
        result_tx, _events = await store_memory(
            store=store,
            content=request_body.content,
            silo_id=str(silo_uuid),
            agent_id=x_session_id,
            layer="memory",
            tags=request_body.tags or None,
            content_type="text",
            decay_class="standard",
            metadata={},
        )
    except Exception as exc:
        logger.error(
            "rest_remember_failed",
            silo_id=str(silo_uuid),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to store memory") from exc

    logger.info(
        "rest_remember_ok",
        node_id=str(result_tx.node_id),
        silo_id=str(silo_uuid),
    )

    return RememberResponse(
        node_id=str(result_tx.node_id),
        created_at=result_tx.created_at.isoformat(),
    )


@router.post(
    "/recall",
    response_model=RecallResponse,
    operation_id="memory_recall",
    summary="Search for relevant knowledge",
)
async def recall(
    request_body: RecallRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> RecallResponse:
    """Search for relevant observations and knowledge.

    ``X-Session-ID`` is optional for recall; it is accepted but not used in the
    query path.
    """
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    silo_uuid = derive_silo_id(x_silo_id)
    scope = ScopeContext(org_id=x_silo_id, silo_id=silo_uuid)

    # Query expansion for hard queries (same logic as MCP recall)
    effective_query = request_body.query
    settings = get_settings()
    if settings.reranking.expand_hard_queries and is_hard_query(request_body.query):
        models_config = load_models_config()
        expander_model = models_config.litellm_expander_model
        redis = getattr(request.app.state, "redis", None)
        if expander_model and redis:
            try:
                expander = QueryExpander(
                    llm_model=expander_model,
                    redis=redis,
                    cache_ttl_seconds=settings.reranking.expansion_cache_ttl_days * 86400,
                    timeout_seconds=settings.reranking.expander_timeout_seconds,
                    vertex_project=models_config.vertex_project or None,
                )
                effective_query = await expander.expand(request_body.query, str(silo_uuid))
                if effective_query != request_body.query:
                    logger.info(
                        "rest_query_expanded",
                        original_len=len(request_body.query),
                        expanded_len=len(effective_query),
                    )
            except Exception as exc:
                logger.warning("rest_query_expansion_failed", error=str(exc))

    try:
        results = await ctx_svc.query(
            scope=scope,
            query=effective_query,
            layers=None,
            top_k=request_body.top_k,
        )
    except Exception as exc:
        logger.error(
            "rest_recall_failed",
            silo_id=str(silo_uuid),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to execute recall query") from exc

    items = [
        RecallResultItem(
            node_id=str(r.node_id),
            content=r.content,
            layer=r.layer,
            confidence=r.confidence,
            relevance_score=r.relevance_score,
            tags=r.tags or [],
            created_at=r.created_at.isoformat() if r.created_at else None,
            summary=r.summary,
        )
        for r in results
    ]

    logger.info(
        "rest_recall_ok",
        silo_id=str(silo_uuid),
        result_count=len(items),
    )

    return RecallResponse(results=items)
