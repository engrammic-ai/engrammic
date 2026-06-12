# REST API for MCP Tool Surface

## Context

The MCP server is the primary agent surface, but REST endpoints are needed for:
- Non-MCP clients (admin tools, dashboards, integrations)
- Benchmark harnesses (LongMemEval, etc.)
- Future API-key auth for headless agents

Four endpoints already exist in `memory.py`: remember, recall, learn, link.
This plan adds the remaining 13 MCP tools as REST endpoints.

## Current State

`api/routes/memory.py` has:
- POST /remember (memory layer write)
- POST /recall (search across layers)
- POST /learn (knowledge layer write) - uses `store_claim` brain TX
- POST /link (create edges) - uses `brain_link` TX with LinkType enum

Uses brain transactions directly (`store_memory`, `store_claim`, `brain_link`).

## Auth Pattern

Respect `AUTH_ENABLED` env var while maintaining silo scoping:

```python
from context_service.config.settings import get_settings

async def get_silo_context(
    x_silo_id: str | None,
    x_session_id: str | None = None,
    require_session: bool = False,
) -> tuple[str, str | None]:
    """Get silo_id and session_id, respecting AUTH_ENABLED."""
    settings = get_settings()
    
    if not settings.auth_enabled:
        # Dev mode: use header or fallback to dev defaults
        silo_id = x_silo_id or settings.dev_org_id
        session_id = x_session_id or "dev-session"
    else:
        # Prod mode: require headers
        if not x_silo_id:
            raise HTTPException(400, "X-Silo-ID header is required")
        if require_session and not x_session_id:
            raise HTTPException(400, "X-Session-ID header is required")
        silo_id = x_silo_id
        session_id = x_session_id
    
    return str(derive_silo_id(silo_id)), session_id
```

Put this helper in a shared location (e.g., `api/routes/_auth.py`) and use across all route files.

## Route Structure

Align with CITE cognitive layers:

```
api/routes/
  memory.py        # EXISTING: remember, recall, learn, link
  wisdom.py        # NEW: decide, accept, hypothesize, commit, dismiss, revise
  intelligence.py  # NEW: reason, reflect
  meta.py          # NEW: trace, history, patterns, forget, tick
```

## Endpoints by File

### wisdom.py (6 endpoints)

| Endpoint | Auth | Brain Transaction | Purpose |
|----------|------|-------------------|---------|
| POST /decide | silo + session | `commit()` | Create commitment from facts |
| POST /accept | silo + session | `accept_proposal()` | Promote ProposedBelief to Belief |
| POST /hypothesize | silo + session | `_context_store_belief()` | Session-scoped tentative belief |
| POST /crystallize | silo + session | `crystallize()` | Finalize hypotheses to commitments |
| POST /dismiss | silo + session | `_dismiss_marker()` | Dismiss engagement marker or reject ProposedBelief |
| POST /revise | silo + session | `_context_update_belief()` | Update working hypothesis |

### intelligence.py (2 endpoints)

| Endpoint | Auth | Brain Transaction | Purpose |
|----------|------|-------------------|---------|
| POST /reason | silo + session | `_context_reason()` | Store reasoning chain |
| POST /reflect | silo + session | `_context_reflect()` | Meta-observation about understanding |

### meta.py (5 endpoints)

| Endpoint | Auth | Brain Transaction | Purpose |
|----------|------|-------------------|---------|
| POST /trace | silo only | `ctx_svc.provenance()` | Provenance chain for a node |
| POST /history | silo only | `ctx_svc.history()` | Supersession chain for a node |
| POST /patterns | silo only | `SkillService` | Skill/workflow templates |
| POST /forget | silo + session | `forget()` | Request node deletion |
| POST /tick | silo + session | `_tick()` | Acknowledge engagement without action |

## Implementation Pattern

Follow existing memory.py pattern:

```python
@router.post("/decide", response_model=DecideResponse)
async def decide(
    request_body: DecideRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> DecideResponse:
    if not x_silo_id:
        raise HTTPException(status_code=400, detail="X-Silo-ID header is required")
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required")
    
    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")
    
    store = request.app.state.memgraph
    silo_uuid = derive_silo_id(x_silo_id)
    
    result_tx, _events = await commit(
        store=store,
        content=request_body.decision,
        about_ids=request_body.about,
        silo_id=str(silo_uuid),
        agent_id=x_session_id,
        confidence=request_body.confidence or 0.8,
    )
    
    return DecideResponse(
        node_id=str(result_tx.node_id),
        created_at=result_tx.created_at.isoformat(),
    )
```

## Implementation Mapping

MCP tools use a mix of brain transactions and context helpers. For REST, call the same functions:

| Endpoint | Call | Location |
|----------|------|----------|
| decide | `commit()` | `sage/transactions.py` |
| accept | `accept_proposal()` | `sage/transactions.py` |
| hypothesize | `_context_store_belief()` | `mcp/tools/context_store.py` |
| crystallize | `crystallize()` | `sage/transactions.py` |
| revise | `_context_update_belief()` | `mcp/tools/context_update_belief.py` |
| dismiss | `_dismiss_marker()` | `mcp/tools/dismiss.py` |
| reason | `_context_reason()` | `mcp/tools/context_store.py` |
| reflect | `_context_reflect()` | `mcp/tools/context_store.py` |
| trace | `ctx_svc.provenance()` | `services/context.py` |
| history | `ctx_svc.history()` | `services/context.py` |
| patterns | `SkillService` | `services/skills.py` |
| forget | `forget()` | `sage/transactions.py` |
| tick | `_tick()` | `mcp/tools/tick.py` |

Note: Rename `/commit` to `/crystallize` to avoid collision with `commit()` brain TX.
Document this in wisdom.py with a comment explaining the rename.

## Files to Create/Modify

1. **Create** `api/routes/_auth.py` - shared `get_silo_context()` helper
2. **Create** `api/routes/wisdom.py` - 6 endpoints
3. **Create** `api/routes/intelligence.py` - 2 endpoints
4. **Create** `api/routes/meta.py` - 5 endpoints
5. **Edit** `api/routes/memory.py` - refactor to use `get_silo_context()`
6. **Edit** `api/app.py` - register new routers

## Verification

1. `just check` passes
2. Add tests in `tests/api/` for each new endpoint
3. Manual curl tests against local dev stack
