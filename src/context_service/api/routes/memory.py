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

from context_service.api.routes._auth import get_silo_context
from context_service.config.models import load_models_config
from context_service.config.settings import get_settings
from context_service.mcp.server import get_context_service
from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.query_expander import QueryExpander
from context_service.retrieval.fusion import FusionRetriever
from context_service.sage.transactions import LinkType, store_claim, store_memory
from context_service.sage.transactions import link as brain_link
from context_service.services.models import ScopeContext

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


class LearnRequest(BaseModel):
    claim: str
    evidence: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class LearnResponse(BaseModel):
    node_id: str
    created_at: str


class LinkRequest(BaseModel):
    from_node: str
    to_node: str
    relation: str


class LinkResponse(BaseModel):
    success: bool
    edge_id: str | None = None


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
    silo_id, session_id = await get_silo_context(x_silo_id, x_session_id, require_session=True)

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    try:
        result_tx, _events = await store_memory(
            store=store,
            content=request_body.content,
            silo_id=silo_id,
            agent_id=session_id,
            layer="memory",
            tags=request_body.tags or None,
            content_type="text",
            decay_class="standard",
            metadata={},
        )
    except Exception as exc:
        logger.error(
            "rest_remember_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to store memory") from exc

    logger.info(
        "rest_remember_ok",
        node_id=str(result_tx.node_id),
        silo_id=silo_id,
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
    silo_id, _ = await get_silo_context(x_silo_id, require_session=False)

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    scope = ScopeContext(org_id=x_silo_id or silo_id, silo_id=silo_id)

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
                    vertex_location=models_config.vertex_location or None,
                    provider=models_config.expander_provider,
                )
                effective_query = await expander.expand(request_body.query, silo_id)
                if effective_query != request_body.query:
                    logger.info(
                        "rest_query_expanded",
                        original_len=len(request_body.query),
                        expanded_len=len(effective_query),
                    )
            except Exception as exc:
                logger.warning("rest_query_expansion_failed", error=str(exc))

    try:
        # Use 4-channel FusionRetriever for multi-modal retrieval
        retriever = FusionRetriever(ctx_svc)
        fused_results = await retriever.retrieve(
            query=effective_query,
            scope=scope,
            top_k=request_body.top_k,
        )

        # Batch fetch full node data for ranked IDs
        import uuid as uuid_mod

        node_ids = [uuid_mod.UUID(r.node_id) for r in fused_results]
        if node_ids:
            nodes_map = await ctx_svc.graph_store.batch_get_nodes(node_ids, silo_id)
        else:
            nodes_map = {}

        # Map to response format, preserving fusion rank order
        items = []
        for fused in fused_results:
            node = nodes_map.get(uuid_mod.UUID(fused.node_id))
            if node is None:
                continue
            props = node.properties or {}
            layer_val = props.get("layer", node.type)
            items.append(
                RecallResultItem(
                    node_id=fused.node_id,
                    content=node.content,
                    layer=layer_val.value if hasattr(layer_val, "value") else str(layer_val),
                    confidence=props.get("confidence", 0.0),
                    relevance_score=fused.rrf_score,
                    tags=list(props.get("tags", [])),
                    created_at=node.created_at.isoformat() if node.created_at else None,
                    summary=props.get("summary"),
                )
            )
    except Exception as exc:
        logger.error(
            "rest_recall_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to execute recall query") from exc

    logger.info(
        "rest_recall_ok",
        silo_id=silo_id,
        result_count=len(items),
    )

    return RecallResponse(results=items)


@router.post(
    "/learn",
    response_model=LearnResponse,
    operation_id="memory_learn",
    summary="Store a claim with evidence to knowledge layer",
)
async def learn(
    request_body: LearnRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> LearnResponse:
    """Store a verifiable claim with evidence.

    Creates a Knowledge layer node (Claim) that can be verified by SAGE.
    """
    silo_id, session_id = await get_silo_context(x_silo_id, x_session_id, require_session=True)

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    try:
        result_tx, _events = await store_claim(
            store=store,
            content=request_body.claim,
            evidence_refs=request_body.evidence,
            silo_id=silo_id,
            agent_id=session_id,
            confidence=0.8,
            tags=request_body.tags or None,
        )
    except Exception as exc:
        logger.error(
            "rest_learn_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Failed to store claim: {exc}") from exc

    logger.info(
        "rest_learn_ok",
        node_id=str(result_tx.node_id),
        silo_id=silo_id,
    )

    return LearnResponse(
        node_id=str(result_tx.node_id),
        created_at=result_tx.created_at.isoformat(),
    )


@router.post(
    "/link",
    response_model=LinkResponse,
    operation_id="memory_link",
    summary="Create a relationship between nodes",
)
async def link(
    request_body: LinkRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> LinkResponse:
    """Create a typed relationship between two nodes."""
    silo_id, session_id = await get_silo_context(x_silo_id, x_session_id, require_session=False)

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    agent_id = session_id or silo_id

    # Map relation string to LinkType
    relation_map = {
        "FOLLOWED_BY": LinkType.RELATED_TO,
        "CONTAINS": LinkType.RELATED_TO,
        "RELATED_TO": LinkType.RELATED_TO,
        "SUPPORTS": LinkType.SUPPORTS,
        "CONTRADICTS": LinkType.CONTRADICTS,
        "DERIVED_FROM": LinkType.DERIVED_FROM,
        "REFERENCES": LinkType.REFERENCES,
        "CAUSES": LinkType.CAUSES,
        "PREVENTS": LinkType.PREVENTS,
        "SUPERSEDES": LinkType.SUPERSEDES,
    }
    link_type = relation_map.get(request_body.relation.upper(), LinkType.RELATED_TO)

    try:
        result_tx, _events = await brain_link(
            store=store,
            source_id=request_body.from_node,
            target_id=request_body.to_node,
            edge_type=link_type,
            silo_id=silo_id,
            agent_id=agent_id,
            weight=1.0,
        )
    except Exception as exc:
        logger.error(
            "rest_link_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Failed to create link: {exc}") from exc

    logger.info(
        "rest_link_ok",
        edge_id=str(result_tx.edge_id),
        silo_id=silo_id,
    )

    return LinkResponse(
        success=True,
        edge_id=str(result_tx.edge_id),
    )
