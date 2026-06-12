"""REST endpoints for graph visualization.

Exposes graph nodes, edges, and neighborhood expansion for the frontend
knowledge graph UI.

Headers:
- X-Silo-ID: required; treated as org_id, silo UUID is derived
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from context_service.mcp.server import get_context_service
from context_service.services.models import ScopeContext, derive_silo_id

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["graph"])

TYPE_TO_LAYER = {
    "Observation": "memory",
    "Utterance": "memory",
    "Event": "memory",
    "Document": "memory",
    "Passage": "memory",
    "Claim": "knowledge",
    "Fact": "knowledge",
    "Belief": "knowledge",
    "Entity": "knowledge",
    "Reflection": "wisdom",
    "Pattern": "wisdom",
    "Commitment": "wisdom",
}


def _node_type_to_layer(node_type: str) -> str:
    return TYPE_TO_LAYER.get(node_type, "memory")


class GraphNodeResponse(BaseModel):
    id: str
    layer: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    metadata: dict | None = None


class GraphEdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    type: str
    metadata: dict | None = None


class NeighborhoodResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class MetricsResponse(BaseModel):
    total_nodes: int
    nodes_by_layer: dict[str, int]
    nodes_last_24h: int
    nodes_last_7d: int


class SearchResultItem(BaseModel):
    node: GraphNodeResponse
    score: float
    highlights: list[str] = Field(default_factory=list)


class SearchFilters(BaseModel):
    tags: list[str] | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=100)
    layers: list[str] | None = Field(
        default=None, description="Filter by layers: memory, knowledge, wisdom"
    )
    tags: list[str] | None = Field(default=None, description="Filter by tags")


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


def _node_to_response(node) -> GraphNodeResponse:
    tags = node.properties.get("tags", []) if hasattr(node, "properties") else []
    if isinstance(tags, str):
        tags = [tags]
    return GraphNodeResponse(
        id=str(node.id),
        layer=_node_type_to_layer(node.type),
        content=node.content or "",
        tags=tags,
        created_at=node.created_at.isoformat() if node.created_at else "",
        updated_at=node.updated_at.isoformat()
        if hasattr(node, "updated_at") and node.updated_at
        else node.created_at.isoformat()
        if node.created_at
        else "",
        metadata=node.properties if hasattr(node, "properties") else None,
    )


def _edge_to_response(edge) -> GraphEdgeResponse:
    return GraphEdgeResponse(
        id=str(edge.id),
        source=str(edge.source_id),
        target=str(edge.target_id),
        type=edge.type,
        metadata=edge.properties if hasattr(edge, "properties") else None,
    )


@router.get(
    "/nodes",
    response_model=list[GraphNodeResponse],
    operation_id="graph_list_nodes",
    summary="List graph nodes",
)
async def list_nodes(
    request: Request,
    layers: str | None = Query(default=None, description="Comma-separated layer filter"),
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    limit: int = Query(default=50, ge=1, le=500),
    sort: str | None = Query(default=None, description="Sort field:direction, e.g. created_at:desc"),
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> list[GraphNodeResponse]:
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)

    try:
        nodes, _ = await store.find_nodes(str(silo_uuid), limit=limit)
    except Exception as exc:
        logger.error("graph_list_nodes_failed", silo_id=str(silo_uuid), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list nodes") from exc

    results = [_node_to_response(n) for n in nodes]

    if layers:
        layer_set = set(layers.split(","))
        results = [r for r in results if r.layer in layer_set]

    if tags:
        tag_set = set(tags.split(","))
        results = [r for r in results if any(t in tag_set for t in r.tags)]

    if sort:
        field, _, direction = sort.partition(":")
        reverse = direction.lower() == "desc"
        results = sorted(results, key=lambda r: getattr(r, field, None) or "", reverse=reverse)

    logger.info("graph_list_nodes_ok", silo_id=str(silo_uuid), count=len(results))
    return results


@router.get(
    "/edges",
    response_model=list[GraphEdgeResponse],
    operation_id="graph_list_edges",
    summary="List edges for given node IDs",
)
async def list_edges(
    request: Request,
    node_ids: str = Query(..., description="Comma-separated node IDs"),
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> list[GraphEdgeResponse]:
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)
    ids = [id.strip() for id in node_ids.split(",") if id.strip()]

    if not ids:
        return []

    try:
        all_edges = []
        for node_id in ids:
            try:
                node_uuid = uuid.UUID(node_id)
            except ValueError:
                continue
            edges, _ = await store.get_binary_edges(node_uuid, str(silo_uuid), limit=100)
            all_edges.extend(edges)

        seen = set()
        unique_edges = []
        for e in all_edges:
            if str(e.id) not in seen:
                seen.add(str(e.id))
                unique_edges.append(e)

        id_set = set(ids)
        filtered = [
            e for e in unique_edges if str(e.source_id) in id_set and str(e.target_id) in id_set
        ]

    except Exception as exc:
        logger.error("graph_list_edges_failed", silo_id=str(silo_uuid), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list edges") from exc

    results = [_edge_to_response(e) for e in filtered]
    logger.info("graph_list_edges_ok", silo_id=str(silo_uuid), count=len(results))
    return results


@router.get(
    "/nodes/{node_id}/neighbors",
    response_model=NeighborhoodResponse,
    operation_id="graph_neighborhood",
    summary="Get neighborhood around a node",
)
async def get_neighborhood(
    request: Request,
    node_id: str,
    max_depth: int = Query(default=2, ge=1, le=5),
    max_nodes: int = Query(default=50, ge=1, le=200),
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> NeighborhoodResponse:
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)

    try:
        node_uuid = uuid.UUID(node_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid node ID format") from None

    try:
        subgraph = await store.neighborhood(
            node_uuid,
            str(silo_uuid),
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
    except Exception as exc:
        logger.error(
            "graph_neighborhood_failed", silo_id=str(silo_uuid), node_id=node_id, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="Failed to get neighborhood") from exc

    nodes = [_node_to_response(n) for n in subgraph.nodes.values()]
    edges = [_edge_to_response(e) for e in subgraph.binary_edges]

    logger.info(
        "graph_neighborhood_ok",
        silo_id=str(silo_uuid),
        node_id=node_id,
        nodes=len(nodes),
        edges=len(edges),
    )
    return NeighborhoodResponse(nodes=nodes, edges=edges)


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    operation_id="graph_metrics",
    summary="Get dashboard metrics",
)
async def get_metrics(
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> MetricsResponse:
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)

    try:
        total = await store.count_nodes(str(silo_uuid))
        nodes, _ = await store.find_nodes(str(silo_uuid), limit=500)

        nodes_by_layer = {"memory": 0, "knowledge": 0, "wisdom": 0}
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        nodes_24h = 0
        nodes_7d = 0

        for node in nodes:
            layer = _node_type_to_layer(node.type)
            if layer in nodes_by_layer:
                nodes_by_layer[layer] += 1

            if node.created_at:
                if node.created_at >= day_ago:
                    nodes_24h += 1
                if node.created_at >= week_ago:
                    nodes_7d += 1

    except Exception as exc:
        logger.error("graph_metrics_failed", silo_id=str(silo_uuid), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to get metrics") from exc

    logger.info("graph_metrics_ok", silo_id=str(silo_uuid), total=total)
    return MetricsResponse(
        total_nodes=total,
        nodes_by_layer=nodes_by_layer,
        nodes_last_24h=nodes_24h,
        nodes_last_7d=nodes_7d,
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    operation_id="graph_search",
    summary="Search nodes",
)
async def search_nodes(
    request_body: SearchRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> SearchResponse:
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

    filters = SearchFilters(tags=request_body.tags) if request_body.tags else None

    try:
        results = await ctx_svc.query(
            scope=scope,
            query=request_body.query,
            layers=request_body.layers,
            filters=filters,
            top_k=request_body.top_k,
        )
    except Exception as exc:
        logger.error("graph_search_failed", silo_id=str(silo_uuid), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to search") from exc

    items = []
    for r in results:
        node = GraphNodeResponse(
            id=str(r.node_id),
            layer=r.layer or "memory",
            content=r.content or "",
            tags=r.tags or [],
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.created_at.isoformat() if r.created_at else "",
            metadata=None,
        )
        items.append(
            SearchResultItem(
                node=node,
                score=r.relevance_score or 0.0,
                highlights=[r.summary] if r.summary else [],
            )
        )

    logger.info("graph_search_ok", silo_id=str(silo_uuid), count=len(items))
    return SearchResponse(results=items)
