"""Tests for context_link tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.sage.transactions import (
    BrainError,
    CrossSiloViolation,
    CycleError,
    LinkResult,
    LinkType,
)
from tests.fakes.fake_graph_store import FakeGraphStore


def _make_link_result(
    from_node: str,
    to_node: str,
    edge_type: LinkType = LinkType.REFERENCES,
) -> LinkResult:
    return LinkResult(
        edge_id=uuid.uuid4(),
        source_id=uuid.UUID(from_node) if len(from_node) == 36 else uuid.uuid4(),
        target_id=uuid.UUID(to_node) if len(to_node) == 36 else uuid.uuid4(),
        edge_type=edge_type,
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = "test-agent"
    return auth


@pytest.fixture
def mock_ctx_svc():
    svc = MagicMock()
    svc.graph_store = AsyncMock()
    return svc


@pytest.fixture
def mock_deps(mock_auth, mock_ctx_svc):
    with (
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_link.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch("context_service.mcp.tools.context_link.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_link.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_link.emit_reaction",
            new=AsyncMock(),
        ),
    ):
        yield {"auth": mock_auth, "svc": mock_ctx_svc}


@pytest.mark.asyncio
async def test_link_creates_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    link_result = _make_link_result(from_id, to_id, LinkType.REFERENCES)

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(return_value=(link_result, [])),
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="REFERENCES",
        )

    assert "edge_id" in result
    assert result["from_node"] == from_id
    assert result["to_node"] == to_id
    assert result["relationship"] == "REFERENCES"
    assert "created_at" in result


@pytest.mark.asyncio
async def test_link_all_relationship_types(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    silo = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
    all_rels = [
        "REFERENCES", "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO",
        "CAUSES", "CORROBORATES", "PREVENTS", "SUPERSEDES",
    ]
    for rel in all_rels:
        from_id = str(uuid.uuid4())
        to_id = str(uuid.uuid4())
        link_result = _make_link_result(from_id, to_id)

        with patch(
            "context_service.mcp.tools.context_link.brain_link",
            new=AsyncMock(return_value=(link_result, [])),
        ):
            result = await _context_link(
                silo_id=silo,
                from_node=from_id,
                to_node=to_id,
                relationship=rel,
            )
        assert "error" not in result, f"Failed for {rel}: {result}"


@pytest.mark.asyncio
async def test_link_invalid_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="INVALID_REL",
    )

    assert result["error"] == "invalid_relationship"
    assert "valid" in result


@pytest.mark.asyncio
async def test_link_invalid_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_link(
            silo_id="not-a-uuid",
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_link_wrong_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "silo_not_found", "silo_id": str(uuid.uuid4())},
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid4()),
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["error"] == "silo_not_found"


@pytest.mark.asyncio
async def test_link_with_weight_and_note(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    link_result = _make_link_result(from_id, to_id, LinkType.SUPPORTS)

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(return_value=(link_result, [])),
    ) as mock_brain_link:
        result = await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="SUPPORTS",
            weight=0.7,
            note="Strong structural support",
        )

    assert "error" not in result
    call_kwargs = mock_brain_link.call_args.kwargs
    assert call_kwargs["weight"] == 0.7
    assert call_kwargs["metadata"] == {"note": "Strong structural support"}


@pytest.mark.asyncio
async def test_link_invalid_weight(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="REFERENCES",
        weight=99.9,
    )

    assert result["error"] == "invalid_weight"


@pytest.mark.asyncio
async def test_link_passes_correct_relationship_to_brain(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    link_result = _make_link_result(from_id, to_id, LinkType.CONTRADICTS)

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(return_value=(link_result, [])),
    ) as mock_brain_link:
        await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="CONTRADICTS",
        )

    call_kwargs = mock_brain_link.call_args.kwargs
    assert call_kwargs["edge_type"] == LinkType.CONTRADICTS
    assert call_kwargs["source_id"] == from_id
    assert call_kwargs["target_id"] == to_id


@pytest.mark.asyncio
async def test_link_corroborates_maps_to_supports(mock_deps):
    """CORROBORATES has no distinct LinkType and maps to SUPPORTS."""
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    link_result = _make_link_result(from_id, to_id, LinkType.SUPPORTS)

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(return_value=(link_result, [])),
    ) as mock_brain_link:
        result = await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="CORROBORATES",
        )

    assert "error" not in result
    call_kwargs = mock_brain_link.call_args.kwargs
    assert call_kwargs["edge_type"] == LinkType.SUPPORTS
    # Public response preserves the original relationship name
    assert result["relationship"] == "CORROBORATES"


@pytest.mark.asyncio
async def test_link_cross_silo_violation(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(side_effect=CrossSiloViolation("silo-a", "silo-b")),
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="SUPPORTS",
        )

    assert result["error"] == "cross_silo_violation"


@pytest.mark.asyncio
async def test_link_duplicate_edge(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    with patch(
        "context_service.mcp.tools.context_link.brain_link",
        new=AsyncMock(
            side_effect=BrainError("DUPLICATE_EDGE", "Edge already exists")
        ),
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
            from_node=from_id,
            to_node=to_id,
            relationship="SUPPORTS",
        )

    assert result["error"] == "duplicate_edge"


# ---------------------------------------------------------------------------
# Outcome-verification tests using FakeGraphStore
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_graph_store() -> FakeGraphStore:
    return FakeGraphStore()


@pytest.fixture
def mock_deps_real_store(fake_graph_store, mock_auth):
    """Patches that inject FakeGraphStore directly into brain_link's store arg."""
    ctx_svc = MagicMock()
    ctx_svc.graph_store = fake_graph_store

    with (
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_link.get_context_service",
            return_value=ctx_svc,
        ),
        patch("context_service.mcp.tools.context_link.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_link.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_link.emit_reaction",
            new=AsyncMock(),
        ),
    ):
        yield fake_graph_store


def _seed_valid_link(store: FakeGraphStore, silo_id: str, from_id: str, to_id: str) -> None:
    """Seed FakeGraphStore for a valid brain_link call (no conflicts)."""
    # _validate_link: first query checks nodes exist + same silo
    store.seed_query_result([{"source_silo": silo_id, "target_silo": silo_id,
                               "source_state": "ACTIVE", "target_state": "ACTIVE"}])
    # _validate_link: second query checks for duplicate edge
    store.seed_query_result([])  # no duplicates


@pytest.mark.asyncio
async def test_link_writes_edge_to_graph_store(mock_deps_real_store):
    """brain_link must write an edge to the graph store."""
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())
    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    _seed_valid_link(mock_deps_real_store, silo_id, from_id, to_id)

    result = await _context_link(
        silo_id=silo_id,
        from_node=from_id,
        to_node=to_id,
        relationship="REFERENCES",
    )

    assert "error" not in result
    assert len(mock_deps_real_store.write_log) == 1
    cypher, params = mock_deps_real_store.write_log[0]
    assert "CREATE" in cypher
    assert "REFERENCES" in cypher
    assert params["source_id"] == from_id
    assert params["target_id"] == to_id
    assert params["edge_id"] == result["edge_id"]


@pytest.mark.asyncio
async def test_link_write_log_contains_weight(mock_deps_real_store):
    """Weight parameter must be forwarded to the brain_link write."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
    _seed_valid_link(mock_deps_real_store, silo_id, str(uuid.uuid4()), str(uuid.uuid4()))

    await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="SUPPORTS",
        weight=0.42,
    )

    assert len(mock_deps_real_store.write_log) == 1
    _, params = mock_deps_real_store.write_log[0]
    assert params["weight"] == 0.42


@pytest.mark.asyncio
async def test_link_no_write_on_invalid_relationship(mock_deps_real_store):
    """Invalid relationship must be rejected before any write hits the store."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    result = await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="NOT_A_REAL_REL",
    )

    assert result["error"] == "invalid_relationship"
    assert mock_deps_real_store.write_log == []


@pytest.mark.asyncio
async def test_link_no_write_on_invalid_weight(mock_deps_real_store):
    """Out-of-range weight must be rejected before any write hits the store."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    result = await _context_link(
        silo_id=silo_id,
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="REFERENCES",
        weight=99.9,
    )

    assert result["error"] == "invalid_weight"
    assert mock_deps_real_store.write_log == []


@pytest.mark.asyncio
async def test_link_relationship_type_in_cypher(mock_deps_real_store):
    """Each relationship type must appear verbatim in the generated Cypher."""
    from context_service.mcp.tools.context_link import _context_link

    silo_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

    for rel in ["REFERENCES", "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO"]:
        mock_deps_real_store._write_log.clear()
        mock_deps_real_store._query_log.clear()
        _seed_valid_link(mock_deps_real_store, silo_id, str(uuid.uuid4()), str(uuid.uuid4()))

        await _context_link(
            silo_id=silo_id,
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship=rel,
        )
        cypher, _ = mock_deps_real_store.write_log[0]
        assert rel in cypher, f"Expected {rel!r} in Cypher but got: {cypher}"
