# EAG MCP Tool Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MCP tools from CRUD verbs to intent-based EAG verbs (remember, assert, commit, reflect, query, etc.)

**Architecture:** Replace existing tools with new intent-based surface. Add service layer for evidence validation, layer-aware storage, and meta-memory queries. Tools delegate to ContextService which handles layer routing.

**Tech Stack:** FastMCP, Memgraph (Cypher), Qdrant, Pydantic models, structlog

**Spec:** `context/specs/mcp-tool-surface.md`

---

## File Structure

### New Files
- `src/context_service/mcp/tools/context_remember.py` — Memory layer writes
- `src/context_service/mcp/tools/context_assert.py` — Knowledge layer with evidence
- `src/context_service/mcp/tools/context_commit.py` — Wisdom layer beliefs
- `src/context_service/mcp/tools/context_reflect.py` — Meta-observations
- `src/context_service/mcp/tools/context_link.py` — Relationship creation
- `src/context_service/mcp/tools/context_query.py` — Semantic search (replaces lookup)
- `src/context_service/mcp/tools/context_graph.py` — Graph traversal
- `src/context_service/mcp/tools/context_provenance.py` — Citation chain
- `src/context_service/mcp/tools/context_history.py` — Belief evolution
- `src/context_service/mcp/tools/context_reason.py` — Reasoning chains
- `src/context_service/services/evidence.py` — Evidence validation pipeline
- `src/context_service/models/mcp.py` — Pydantic models for tool I/O
- `tests/mcp/` — Tool tests

### Modified Files
- `src/context_service/mcp/tools/__init__.py` — Register new tools
- `src/context_service/mcp/server.py` — Import new tool modules
- `src/context_service/services/context.py` — Add layer-aware methods
- `src/context_service/db/queries.py` — Add provenance/history queries

### Deprecated (remove after migration)
- `src/context_service/mcp/tools/context_store.py`
- `src/context_service/mcp/tools/context_lookup.py`

---

## Task 1: Pydantic Models for MCP Tools

**Files:**
- Create: `src/context_service/models/mcp.py`
- Create: `tests/mcp/__init__.py`
- Create: `tests/mcp/test_models.py`

- [ ] **Step 1: Write model tests**

```python
# tests/mcp/test_models.py
"""Tests for MCP tool models."""
import pytest
from context_service.models.mcp import (
    SPOClaim,
    DecayClass,
    SourceType,
    ObservationType,
    EvidenceRef,
)


def test_spo_claim_valid():
    claim = SPOClaim(subject="OAuth", predicate="expires_in", object="30 days")
    assert claim.subject == "OAuth"
    assert claim.qualifiers is None


def test_spo_claim_with_qualifiers():
    claim = SPOClaim(
        subject="OAuth",
        predicate="expires_in",
        object="30 days",
        qualifiers={"as_of": "2026-04-01"},
    )
    assert claim.qualifiers["as_of"] == "2026-04-01"


def test_evidence_ref_node():
    ref = EvidenceRef(ref="node:abc-123")
    assert ref.is_node_ref
    assert ref.node_id == "abc-123"


def test_evidence_ref_uri():
    ref = EvidenceRef(ref="https://docs.example.com")
    assert ref.is_uri
    assert not ref.is_node_ref


def test_decay_class_values():
    assert DecayClass.EPHEMERAL == "ephemeral"
    assert DecayClass.STANDARD == "standard"
    assert DecayClass.DURABLE == "durable"
    assert DecayClass.PERMANENT == "permanent"


def test_source_type_values():
    assert SourceType.DOCUMENT == "document"
    assert SourceType.USER == "user"
    assert SourceType.EXTERNAL == "external"
    assert SourceType.AGENT == "agent"


def test_observation_type_values():
    assert ObservationType.BELIEF_CHANGE == "belief_change"
    assert ObservationType.CONTRADICTION == "contradiction"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.models.mcp'`

- [ ] **Step 3: Create __init__.py for tests/mcp**

```python
# tests/mcp/__init__.py
"""MCP tool tests."""
```

- [ ] **Step 4: Implement models**

```python
# src/context_service/models/mcp.py
"""Pydantic models for MCP tool inputs/outputs."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DecayClass(str, Enum):
    """Memory decay classes per EAG spec."""
    EPHEMERAL = "ephemeral"    # 7 days
    STANDARD = "standard"      # 90 days
    DURABLE = "durable"        # 540 days
    PERMANENT = "permanent"    # 5 years


class SourceType(str, Enum):
    """Evidence source types."""
    DOCUMENT = "document"   # From ingested doc/passage
    USER = "user"           # From user utterance
    EXTERNAL = "external"   # From URI
    AGENT = "agent"         # From agent reasoning chain


class ObservationType(str, Enum):
    """Meta-observation types."""
    BELIEF_CHANGE = "belief_change"
    CONFIDENCE_SHIFT = "confidence_shift"
    CONTRADICTION = "contradiction"
    UNCERTAINTY = "uncertainty"
    CORRECTION = "correction"
    INSIGHT = "insight"


class RelationshipType(str, Enum):
    """Allowed relationship types for context_link."""
    REFERENCES = "REFERENCES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    RELATED_TO = "RELATED_TO"


class Layer(str, Enum):
    """EAG cognitive layers."""
    MEMORY = "memory"
    KNOWLEDGE = "knowledge"
    WISDOM = "wisdom"
    INTELLIGENCE = "intelligence"


class SPOClaim(BaseModel):
    """Structured claim: subject-predicate-object."""
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any] | None = None


class EvidenceRef(BaseModel):
    """Reference to evidence source."""
    ref: str = Field(..., description="node:<uuid> or URI")

    @property
    def is_node_ref(self) -> bool:
        return self.ref.startswith("node:")

    @property
    def is_uri(self) -> bool:
        return self.ref.startswith("http://") or self.ref.startswith("https://") or self.ref.startswith("file://")

    @property
    def node_id(self) -> str | None:
        if self.is_node_ref:
            return self.ref[5:]  # Strip "node:"
        return None

    @field_validator("ref")
    @classmethod
    def validate_ref_format(cls, v: str) -> str:
        if not (v.startswith("node:") or v.startswith("http://") or v.startswith("https://") or v.startswith("file://")):
            raise ValueError("Evidence ref must be node:<uuid> or a URI (http://, https://, file://)")
        return v


class ReasoningStep(BaseModel):
    """A step in a reasoning chain."""
    step: int
    reasoning: str
    confidence: float | None = None


class Crystallization(BaseModel):
    """A claim to extract from reasoning."""
    claim: str | SPOClaim
    confidence: float = 0.8


class QueryFilters(BaseModel):
    """Filters for context_query."""
    tags: list[str] | None = None
    source_type: list[SourceType] | None = None
    min_confidence: float | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class ProvenanceStep(BaseModel):
    """A step in provenance chain."""
    node_id: str
    layer: Layer
    relationship: str
    confidence: float


class HistoryEntry(BaseModel):
    """An entry in belief history."""
    node_id: str
    content: str
    valid_from: datetime
    valid_to: datetime | None = None
    superseded_by: str | None = None
    supersession_reason: str | None = None
    confidence: float
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/mcp/test_models.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/models/mcp.py tests/mcp/
git commit -m "feat(mcp): add Pydantic models for EAG tool surface"
```

---

## Task 2: context_remember Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_remember.py`
- Create: `tests/mcp/test_context_remember.py`
- Modify: `src/context_service/mcp/tools/__init__.py`

- [ ] **Step 1: Write failing test**

```python
# tests/mcp/test_context_remember.py
"""Tests for context_remember tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


@pytest.fixture
def mock_auth():
    with patch("context_service.mcp.tools.context_remember.get_mcp_auth") as m:
        auth = MagicMock()
        auth.org_id = "test-org"
        m.return_value = auth
        yield m


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.tools.context_remember.get_context_service") as m:
        svc = AsyncMock()
        node = MagicMock()
        node.id = uuid.uuid4()
        svc.remember.return_value = node
        m.return_value = svc
        yield svc


@pytest.mark.asyncio
async def test_remember_basic(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_remember import _context_remember
    
    result = await _context_remember(
        silo_id=str(uuid.uuid4()),
        content="Test observation",
    )
    
    assert result["layer"] == "memory"
    assert "node_id" in result
    assert "created_at" in result
    mock_context_service.remember.assert_called_once()


@pytest.mark.asyncio
async def test_remember_with_decay_class(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_remember import _context_remember
    
    result = await _context_remember(
        silo_id=str(uuid.uuid4()),
        content="Ephemeral note",
        decay_class="ephemeral",
    )
    
    assert result["decay_class"] == "ephemeral"


@pytest.mark.asyncio
async def test_remember_invalid_silo(mock_auth):
    from context_service.mcp.tools.context_remember import _context_remember
    
    result = await _context_remember(
        silo_id="not-a-uuid",
        content="Test",
    )
    
    assert result["error"] == "invalid_silo_id"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/test_context_remember.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement context_remember**

```python
# src/context_service/mcp/tools/context_remember.py
"""MCP tool: context_remember - Store to Memory layer."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import DecayClass
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_remember(
    silo_id: str,
    content: str,
    content_type: str = "text",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
    observed_from: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.auth import get_mcp_auth
    from context_service.mcp.server import get_context_service

    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    # Validate silo_id
    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {
            "error": "silo_not_found",
            "silo_id": silo_id,
            "message": "Silo does not exist or org_id mismatch.",
        }

    # Validate decay_class
    try:
        decay = DecayClass(decay_class)
    except ValueError:
        return {
            "error": "invalid_decay_class",
            "message": f"decay_class must be one of: {[e.value for e in DecayClass]}",
        }

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.remember(
        scope=scope,
        content=content,
        content_type=content_type,
        metadata=metadata,
        tags=tags,
        decay_class=decay,
        observed_from=observed_from,
        agent_id=auth.agent_id if hasattr(auth, "agent_id") else None,
    )

    return {
        "node_id": str(node.id),
        "layer": "memory",
        "decay_class": decay_class,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_remember tool."""

    @mcp.tool(
        name="context_remember",
        description=(
            "Store an experience or observation to the Memory layer. "
            "Memories decay over time based on decay_class. "
            "Use for: events, utterances, observations, raw experiences."
        ),
    )
    async def context_remember(
        silo_id: str,
        content: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: str = "standard",
        observed_from: str | None = None,
    ) -> dict[str, Any]:
        """Store to Memory layer.

        Args:
            silo_id: UUID of the silo.
            content: The content to store.
            content_type: One of text, utterance, event.
            metadata: Optional metadata dict.
            tags: Optional tags for filtering.
            decay_class: ephemeral|standard|durable|permanent.
            observed_from: Attribution if reporting others (user:<id>, agent:<id>).

        Returns:
            {node_id, layer, decay_class, created_at}
        """
        return await _context_remember(
            silo_id=silo_id,
            content=content,
            content_type=content_type,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
            observed_from=observed_from,
        )
```

- [ ] **Step 4: Add remember method to ContextService**

Add to `src/context_service/services/context.py`:

```python
async def remember(
    self,
    scope: ScopeContext,
    content: str,
    content_type: str = "text",
    *,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: DecayClass = DecayClass.STANDARD,
    observed_from: str | None = None,
    agent_id: str | None = None,
) -> Node:
    """Store to Memory layer with decay semantics."""
    from context_service.models.mcp import DecayClass
    
    props = metadata or {}
    props["layer"] = "memory"
    props["decay_class"] = decay_class.value
    props["content_type"] = content_type
    if tags:
        props["tags"] = tags
    if observed_from:
        props["observed_from"] = observed_from
    if agent_id:
        props["agent_id"] = agent_id

    return await self.store(
        scope=scope,
        content=content,
        node_type=content_type,
        properties=props,
    )
```

- [ ] **Step 5: Update tools/__init__.py**

```python
# Add to src/context_service/mcp/tools/__init__.py
from context_service.mcp.tools import context_remember

def register_all(mcp: FastMCP) -> None:
    """Register all MCP tools."""
    context_remember.register(mcp)
    # ... existing registrations
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/mcp/test_context_remember.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/mcp/tools/context_remember.py src/context_service/services/context.py tests/mcp/test_context_remember.py src/context_service/mcp/tools/__init__.py
git commit -m "feat(mcp): add context_remember tool for Memory layer"
```

---

## Task 3: Evidence Validation Service

**Files:**
- Create: `src/context_service/services/evidence.py`
- Create: `tests/services/test_evidence.py`

- [ ] **Step 1: Write failing test**

```python
# tests/services/test_evidence.py
"""Tests for evidence validation service."""
import pytest
from unittest.mock import AsyncMock, patch
from context_service.services.evidence import EvidenceValidator, EvidenceResult


@pytest.fixture
def validator():
    memgraph = AsyncMock()
    return EvidenceValidator(memgraph=memgraph)


@pytest.mark.asyncio
async def test_validate_node_ref_exists(validator):
    validator._memgraph.execute_query.return_value = [{"id": "abc-123"}]
    
    result = await validator.validate("node:abc-123", silo_id="silo-1")
    
    assert result.status == "valid"
    assert result.node_id == "abc-123"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_validate_node_ref_not_found(validator):
    validator._memgraph.execute_query.return_value = []
    
    result = await validator.validate("node:missing", silo_id="silo-1")
    
    assert result.status == "invalid"
    assert "not found" in result.reason.lower()


@pytest.mark.asyncio
async def test_validate_uri_reachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 200
        
        validator = EvidenceValidator(memgraph=AsyncMock())
        result = await validator.validate("https://example.com/doc", silo_id="silo-1")
        
        assert result.status == "valid"
        assert result.confidence == 0.7


@pytest.mark.asyncio
async def test_validate_uri_unreachable():
    with patch("context_service.services.evidence.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        mock_client.head.return_value.status_code = 404
        
        validator = EvidenceValidator(memgraph=AsyncMock())
        result = await validator.validate("https://example.com/missing", silo_id="silo-1")
        
        assert result.status == "invalid"


@pytest.mark.asyncio
async def test_validate_invalid_format(validator):
    result = await validator.validate("invalid-ref", silo_id="silo-1")
    
    assert result.status == "invalid"
    assert "format" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/services/test_evidence.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement EvidenceValidator**

```python
# src/context_service/services/evidence.py
"""Evidence validation pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
import structlog

if TYPE_CHECKING:
    from context_service.stores import MemgraphClient

logger = structlog.get_logger(__name__)


@dataclass
class EvidenceResult:
    """Result of evidence validation."""
    status: Literal["valid", "invalid", "pending"]
    node_id: str | None = None
    confidence: float = 0.0
    reason: str | None = None


class EvidenceValidator:
    """Validates evidence references for context_assert."""

    def __init__(
        self,
        memgraph: MemgraphClient,
        http_timeout: float = 10.0,
    ) -> None:
        self._memgraph = memgraph
        self._http_timeout = http_timeout

    async def validate(
        self,
        ref: str,
        silo_id: str,
    ) -> EvidenceResult:
        """Validate an evidence reference.

        Args:
            ref: Evidence reference (node:<uuid> or URI)
            silo_id: Silo context for node lookups

        Returns:
            EvidenceResult with status and confidence
        """
        if ref.startswith("node:"):
            return await self._validate_node_ref(ref[5:], silo_id)
        elif ref.startswith("http://") or ref.startswith("https://"):
            return await self._validate_uri(ref)
        elif ref.startswith("file://"):
            return EvidenceResult(
                status="valid",
                confidence=0.9,
                reason="File URI accepted (local validation skipped)",
            )
        else:
            return EvidenceResult(
                status="invalid",
                reason="Invalid evidence format. Must be node:<uuid> or URI.",
            )

    async def _validate_node_ref(
        self,
        node_id: str,
        silo_id: str,
    ) -> EvidenceResult:
        """Check if node exists in silo."""
        query = """
        MATCH (n {id: $node_id, silo_id: $silo_id})
        RETURN n.id AS id
        LIMIT 1
        """
        results = await self._memgraph.execute_query(
            query,
            {"node_id": node_id, "silo_id": silo_id},
        )

        if results:
            return EvidenceResult(
                status="valid",
                node_id=node_id,
                confidence=1.0,
            )
        else:
            return EvidenceResult(
                status="invalid",
                reason=f"Node {node_id} not found in silo {silo_id}",
            )

    async def _validate_uri(self, uri: str) -> EvidenceResult:
        """Check if URI is reachable."""
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.head(uri, follow_redirects=True)

                if response.status_code < 400:
                    logger.debug("evidence_uri_valid", uri=uri, status=response.status_code)
                    return EvidenceResult(
                        status="valid",
                        confidence=0.7,
                        reason=f"URI reachable (status {response.status_code})",
                    )
                else:
                    return EvidenceResult(
                        status="invalid",
                        reason=f"URI returned status {response.status_code}",
                    )
        except httpx.RequestError as e:
            logger.warning("evidence_uri_unreachable", uri=uri, error=str(e))
            return EvidenceResult(
                status="invalid",
                reason=f"URI unreachable: {e}",
            )

    async def validate_all(
        self,
        refs: list[str],
        silo_id: str,
    ) -> list[EvidenceResult]:
        """Validate multiple evidence refs."""
        results = []
        for ref in refs:
            result = await self.validate(ref, silo_id)
            results.append(result)
        return results
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/services/test_evidence.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/evidence.py tests/services/test_evidence.py
git commit -m "feat(services): add evidence validation pipeline"
```

---

## Task 4: context_assert Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_assert.py`
- Create: `tests/mcp/test_context_assert.py`

- [ ] **Step 1: Write failing test**

```python
# tests/mcp/test_context_assert.py
"""Tests for context_assert tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


@pytest.fixture
def mock_deps():
    with patch("context_service.mcp.tools.context_assert.get_mcp_auth") as auth_mock, \
         patch("context_service.mcp.tools.context_assert.get_context_service") as svc_mock, \
         patch("context_service.mcp.tools.context_assert.get_evidence_validator") as ev_mock:
        
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth
        
        svc = AsyncMock()
        node = MagicMock()
        node.id = uuid.uuid4()
        svc.assert_claim.return_value = node
        svc_mock.return_value = svc
        
        ev = AsyncMock()
        ev.validate.return_value = MagicMock(status="valid", confidence=1.0, node_id="ev-123")
        ev_mock.return_value = ev
        
        yield {"auth": auth, "svc": svc, "ev": ev}


@pytest.mark.asyncio
async def test_assert_with_node_evidence(mock_deps):
    from context_service.mcp.tools.context_assert import _context_assert
    
    result = await _context_assert(
        silo_id=str(uuid.uuid4()),
        claim="OAuth tokens expire in 30 days",
        evidence="node:abc-123",
        source_type="document",
    )
    
    assert result["layer"] == "knowledge"
    assert result["evidence_status"] == "verified"
    mock_deps["svc"].assert_claim.assert_called_once()


@pytest.mark.asyncio
async def test_assert_with_invalid_evidence(mock_deps):
    mock_deps["ev"].validate.return_value = MagicMock(status="invalid", reason="Not found")
    
    from context_service.mcp.tools.context_assert import _context_assert
    
    result = await _context_assert(
        silo_id=str(uuid.uuid4()),
        claim="Some claim",
        evidence="node:missing",
        source_type="document",
    )
    
    assert result["error"] == "invalid_evidence"


@pytest.mark.asyncio
async def test_assert_structured_claim(mock_deps):
    from context_service.mcp.tools.context_assert import _context_assert
    
    result = await _context_assert(
        silo_id=str(uuid.uuid4()),
        claim={"subject": "OAuth", "predicate": "expires_in", "object": "30 days"},
        evidence="node:abc-123",
        source_type="user",
    )
    
    assert result["claim_type"] == "structured"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/test_context_assert.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement context_assert**

```python
# src/context_service/mcp/tools/context_assert.py
"""MCP tool: context_assert - Assert claim to Knowledge layer."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import SourceType, SPOClaim
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def get_evidence_validator():
    """Get evidence validator from server state."""
    from context_service.mcp.server import get_evidence_validator as _get
    return _get()


async def _context_assert(
    silo_id: str,
    claim: str | dict[str, Any],
    evidence: str | list[str],
    source_type: str,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    evidence_mode: str = "sync",
) -> dict[str, Any]:
    """Internal implementation."""
    from context_service.mcp.auth import get_mcp_auth
    from context_service.mcp.server import get_context_service

    auth = get_mcp_auth()
    ctx_svc = get_context_service()
    ev_validator = get_evidence_validator()

    # Validate silo_id
    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    # Validate source_type
    try:
        src_type = SourceType(source_type)
    except ValueError:
        return {"error": "invalid_source_type", "message": f"Must be one of: {[e.value for e in SourceType]}"}

    # Validate confidence
    if not 0.0 <= confidence <= 1.0:
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    # Parse claim
    claim_type = "freeform"
    parsed_claim: str | SPOClaim
    if isinstance(claim, dict):
        try:
            parsed_claim = SPOClaim(**claim)
            claim_type = "structured"
        except Exception as e:
            return {"error": "invalid_claim", "message": str(e)}
    else:
        parsed_claim = claim

    # Normalize evidence to list
    evidence_list = [evidence] if isinstance(evidence, str) else evidence

    # Validate evidence (sync mode)
    if evidence_mode == "sync":
        evidence_nodes = []
        for ev_ref in evidence_list:
            result = await ev_validator.validate(ev_ref, str(expected_silo_id))
            if result.status != "valid":
                return {
                    "error": "invalid_evidence",
                    "evidence": ev_ref,
                    "reason": result.reason,
                }
            if result.node_id:
                evidence_nodes.append(result.node_id)

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.assert_claim(
        scope=scope,
        claim=parsed_claim,
        evidence=evidence_list,
        source_type=src_type,
        confidence=confidence,
        metadata=metadata,
        tags=tags,
        agent_id=getattr(auth, "agent_id", None),
    )

    return {
        "node_id": str(node.id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes if evidence_mode == "sync" else [],
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_assert tool."""

    @mcp.tool(
        name="context_assert",
        description=(
            "Assert a claim to the Knowledge layer. Requires evidence. "
            "Evidence must be node:<uuid> refs or URIs. "
            "Claims persist until contradicted (no decay)."
        ),
    )
    async def context_assert(
        silo_id: str,
        claim: str | dict[str, Any],
        evidence: str | list[str],
        source_type: str,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        evidence_mode: str = "sync",
    ) -> dict[str, Any]:
        """Assert a claim with evidence.

        Args:
            silo_id: UUID of the silo.
            claim: Free text or {subject, predicate, object} SPO.
            evidence: node:<uuid> or URI, or list thereof. Required.
            source_type: document|user|external|agent.
            confidence: 0.0-1.0, agent's confidence.
            metadata: Optional metadata.
            tags: Optional tags.
            evidence_mode: sync (validate first) or async (validate later).

        Returns:
            {node_id, layer, claim_type, evidence_status, evidence_nodes, created_at}
        """
        return await _context_assert(
            silo_id=silo_id,
            claim=claim,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            metadata=metadata,
            tags=tags,
            evidence_mode=evidence_mode,
        )
```

- [ ] **Step 4: Add assert_claim to ContextService**

Add to `src/context_service/services/context.py`:

```python
async def assert_claim(
    self,
    scope: ScopeContext,
    claim: str | SPOClaim,
    evidence: list[str],
    source_type: SourceType,
    *,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    agent_id: str | None = None,
) -> Node:
    """Assert a claim to Knowledge layer with evidence."""
    from context_service.models.mcp import SPOClaim, SourceType
    
    props = metadata or {}
    props["layer"] = "knowledge"
    props["source_type"] = source_type.value
    props["confidence"] = confidence
    props["evidence"] = evidence
    if tags:
        props["tags"] = tags
    if agent_id:
        props["agent_id"] = agent_id

    content = claim if isinstance(claim, str) else f"{claim.subject} {claim.predicate} {claim.object}"
    
    if isinstance(claim, SPOClaim):
        props["claim_structured"] = True
        props["subject"] = claim.subject
        props["predicate"] = claim.predicate
        props["object"] = claim.object
        if claim.qualifiers:
            props["qualifiers"] = claim.qualifiers

    node = await self.store(
        scope=scope,
        content=content,
        node_type="Claim",
        properties=props,
    )

    # Create DERIVED_FROM edges to evidence nodes
    for ev_ref in evidence:
        if ev_ref.startswith("node:"):
            ev_node_id = ev_ref[5:]
            await self._memgraph.execute_write(
                """
                MATCH (claim {id: $claim_id}), (ev {id: $ev_id})
                MERGE (claim)-[:DERIVED_FROM]->(ev)
                """,
                {"claim_id": str(node.id), "ev_id": ev_node_id},
            )

    return node
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/mcp/test_context_assert.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_assert.py src/context_service/services/context.py tests/mcp/test_context_assert.py
git commit -m "feat(mcp): add context_assert tool with evidence validation"
```

---

## Task 5: context_commit Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_commit.py`
- Create: `tests/mcp/test_context_commit.py`

- [ ] **Step 1: Write failing test**

```python
# tests/mcp/test_context_commit.py
"""Tests for context_commit tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


@pytest.fixture
def mock_deps():
    with patch("context_service.mcp.tools.context_commit.get_mcp_auth") as auth_mock, \
         patch("context_service.mcp.tools.context_commit.get_context_service") as svc_mock:
        
        auth = MagicMock()
        auth.org_id = "test-org"
        auth.agent_id = "agent-123"
        auth_mock.return_value = auth
        
        svc = AsyncMock()
        node = MagicMock()
        node.id = uuid.uuid4()
        svc.commit_belief.return_value = node
        svc_mock.return_value = svc
        
        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_commit_basic(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit
    
    result = await _context_commit(
        silo_id=str(uuid.uuid4()),
        belief="This team ships on Fridays",
        about=["node:claim-1", "node:claim-2"],
    )
    
    assert result["layer"] == "wisdom"
    assert result["declared_by"] == "agent-123"
    mock_deps["svc"].commit_belief.assert_called_once()


@pytest.mark.asyncio
async def test_commit_with_reasoning(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit
    
    result = await _context_commit(
        silo_id=str(uuid.uuid4()),
        belief="Deploy on Friday is risky",
        about=["node:claim-1"],
        reasoning="Based on 3 outages in past month",
        confidence=0.9,
    )
    
    assert result["layer"] == "wisdom"
```

- [ ] **Step 2: Run test, implement, run again**

```python
# src/context_service/mcp/tools/context_commit.py
"""MCP tool: context_commit - Commit belief to Wisdom layer."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_commit(
    silo_id: str,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    from context_service.mcp.auth import get_mcp_auth
    from context_service.mcp.server import get_context_service

    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    agent_id = getattr(auth, "agent_id", None) or auth.org_id

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.commit_belief(
        scope=scope,
        belief=belief,
        about=about,
        confidence=confidence,
        reasoning=reasoning,
        metadata=metadata,
        tags=tags,
        agent_id=agent_id,
    )

    return {
        "node_id": str(node.id),
        "layer": "wisdom",
        "declared_by": agent_id,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_commit tool."""

    @mcp.tool(
        name="context_commit",
        description=(
            "Commit a belief or stance to the Wisdom layer. "
            "Commitments are agent-scoped via DECLARED_BY edge. "
            "Use for: synthesized judgments, declared positions, team patterns."
        ),
    )
    async def context_commit(
        silo_id: str,
        belief: str,
        about: list[str],
        confidence: float = 0.8,
        reasoning: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Commit a belief.

        Args:
            silo_id: UUID of the silo.
            belief: The belief statement.
            about: Node IDs this belief concerns.
            confidence: 0.0-1.0.
            reasoning: Why agent holds this belief.
            metadata: Optional metadata.
            tags: Optional tags.

        Returns:
            {node_id, layer, declared_by, about_nodes, created_at}
        """
        return await _context_commit(
            silo_id=silo_id,
            belief=belief,
            about=about,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
            tags=tags,
        )
```

- [ ] **Step 3: Add commit_belief to ContextService**

```python
async def commit_belief(
    self,
    scope: ScopeContext,
    belief: str,
    about: list[str],
    *,
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    agent_id: str,
) -> Node:
    """Commit belief to Wisdom layer."""
    props = metadata or {}
    props["layer"] = "wisdom"
    props["confidence"] = confidence
    props["about"] = about
    if reasoning:
        props["reasoning"] = reasoning
    if tags:
        props["tags"] = tags

    node = await self.store(
        scope=scope,
        content=belief,
        node_type="Commitment",
        properties=props,
    )

    # Create DECLARED_BY edge
    await self._memgraph.execute_write(
        """
        MATCH (c {id: $commitment_id})
        MERGE (a:Agent {id: $agent_id})
        MERGE (c)-[:DECLARED_BY]->(a)
        """,
        {"commitment_id": str(node.id), "agent_id": agent_id},
    )

    # Create ABOUT edges
    for about_ref in about:
        node_id = about_ref[5:] if about_ref.startswith("node:") else about_ref
        await self._memgraph.execute_write(
            """
            MATCH (c {id: $commitment_id}), (n {id: $node_id})
            MERGE (c)-[:ABOUT]->(n)
            """,
            {"commitment_id": str(node.id), "node_id": node_id},
        )

    return node
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests/mcp/test_context_commit.py -v
git add src/context_service/mcp/tools/context_commit.py tests/mcp/test_context_commit.py src/context_service/services/context.py
git commit -m "feat(mcp): add context_commit tool for Wisdom layer"
```

---

## Task 6: context_reflect Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_reflect.py`
- Create: `tests/mcp/test_context_reflect.py`

- [ ] **Step 1: Write test and implement**

```python
# src/context_service/mcp/tools/context_reflect.py
"""MCP tool: context_reflect - Store meta-observation."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import ObservationType
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_reflect(
    silo_id: str,
    observation: str,
    observation_type: str,
    about: list[str],
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    from context_service.mcp.auth import get_mcp_auth
    from context_service.mcp.server import get_context_service

    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    try:
        obs_type = ObservationType(observation_type)
    except ValueError:
        return {"error": "invalid_observation_type", "valid": [e.value for e in ObservationType]}

    agent_id = getattr(auth, "agent_id", None) or auth.org_id

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.reflect(
        scope=scope,
        observation=observation,
        observation_type=obs_type,
        about=about,
        confidence=confidence,
        metadata=metadata,
        agent_id=agent_id,
    )

    return {
        "node_id": str(node.id),
        "observation_type": observation_type,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_reflect tool."""

    @mcp.tool(
        name="context_reflect",
        description=(
            "Store a meta-observation about your own cognition. "
            "Types: belief_change, confidence_shift, contradiction, uncertainty, correction, insight."
        ),
    )
    async def context_reflect(
        silo_id: str,
        observation: str,
        observation_type: str,
        about: list[str],
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await _context_reflect(
            silo_id=silo_id,
            observation=observation,
            observation_type=observation_type,
            about=about,
            confidence=confidence,
            metadata=metadata,
        )
```

- [ ] **Step 2: Add reflect to ContextService, test, commit**

```bash
git add src/context_service/mcp/tools/context_reflect.py tests/mcp/test_context_reflect.py src/context_service/services/context.py
git commit -m "feat(mcp): add context_reflect tool for meta-observations"
```

---

## Task 7: context_query Tool (replaces context_lookup)

**Files:**
- Create: `src/context_service/mcp/tools/context_query.py`
- Create: `tests/mcp/test_context_query.py`
- Modify: `src/context_service/mcp/tools/__init__.py`

- [ ] **Step 1: Implement context_query**

```python
# src/context_service/mcp/tools/context_query.py
"""MCP tool: context_query - Semantic search with layer filtering."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import Layer, QueryFilters
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_query(
    silo_id: str,
    query: str,
    layers: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    top_k: int = 10,
    include_superseded: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    from context_service.mcp.auth import get_mcp_auth
    from context_service.mcp.server import get_context_service

    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found"}

    # Validate layers
    valid_layers = None
    if layers:
        try:
            valid_layers = [Layer(l) for l in layers]
        except ValueError:
            return {"error": "invalid_layer", "valid": [e.value for e in Layer]}

    # Parse as_of
    as_of_dt = None
    if as_of:
        try:
            as_of_dt = datetime.fromisoformat(as_of)
        except ValueError:
            return {"error": "invalid_as_of", "message": "Must be ISO format datetime"}

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    
    import time
    start = time.perf_counter()
    
    results = await ctx_svc.query(
        scope=scope,
        query=query,
        layers=valid_layers,
        filters=QueryFilters(**filters) if filters else None,
        top_k=top_k,
        include_superseded=include_superseded,
        as_of=as_of_dt,
    )
    
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "results": [
            {
                "node_id": str(r.node_id),
                "layer": r.layer,
                "content": r.content,
                "summary": r.summary,
                "confidence": r.confidence,
                "relevance_score": r.relevance_score,
                "tags": r.tags or [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
        "total_candidates": len(results),
        "search_time_ms": elapsed_ms,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_query tool."""

    @mcp.tool(
        name="context_query",
        description=(
            "Semantic search across Memory, Knowledge, and Wisdom layers. "
            "Supports layer filtering, time-travel (as_of), and metadata filters."
        ),
    )
    async def context_query(
        silo_id: str,
        query: str,
        layers: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        include_superseded: bool = False,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        return await _context_query(
            silo_id=silo_id,
            query=query,
            layers=layers,
            filters=filters,
            top_k=top_k,
            include_superseded=include_superseded,
            as_of=as_of,
        )
```

- [ ] **Step 2: Test and commit**

```bash
git add src/context_service/mcp/tools/context_query.py tests/mcp/test_context_query.py
git commit -m "feat(mcp): add context_query tool (replaces lookup)"
```

---

## Task 8: context_link Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_link.py`

- [ ] **Step 1: Implement**

```python
# src/context_service/mcp/tools/context_link.py
"""MCP tool: context_link - Create relationships."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import RelationshipType
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="context_link",
        description="Create a relationship between two nodes.",
    )
    async def context_link(
        silo_id: str,
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
    ) -> dict[str, Any]:
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id"}

        if requested != expected_silo_id:
            return {"error": "silo_not_found"}

        try:
            rel_type = RelationshipType(relationship)
        except ValueError:
            return {"error": "invalid_relationship", "valid": [e.value for e in RelationshipType]}

        edge_id = await ctx_svc.link(
            silo_id=str(expected_silo_id),
            from_node=from_node,
            to_node=to_node,
            relationship=rel_type.value,
            weight=weight,
            note=note,
        )

        return {
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "relationship": relationship,
            "created_at": datetime.now(UTC).isoformat(),
        }
```

- [ ] **Step 2: Add link method to ContextService**

```python
async def link(
    self,
    silo_id: str,
    from_node: str,
    to_node: str,
    relationship: str,
    weight: float = 1.0,
    note: str | None = None,
) -> str:
    """Create relationship between nodes."""
    edge_id = str(uuid.uuid4())
    
    props = {"id": edge_id, "weight": weight}
    if note:
        props["note"] = note

    await self._memgraph.execute_write(
        f"""
        MATCH (a {{id: $from_id, silo_id: $silo_id}})
        MATCH (b {{id: $to_id, silo_id: $silo_id}})
        CREATE (a)-[r:{relationship} $props]->(b)
        """,
        {"from_id": from_node, "to_id": to_node, "silo_id": silo_id, "props": props},
    )
    
    return edge_id
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/context_link.py src/context_service/services/context.py
git commit -m "feat(mcp): add context_link tool"
```

---

## Task 9: context_graph Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_graph.py`

- [ ] **Step 1: Implement graph traversal tool**

```python
# src/context_service/mcp/tools/context_graph.py
"""MCP tool: context_graph - Graph traversal from semantic seed."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="context_graph",
        description="Graph traversal from semantic seed or specific nodes.",
    )
    async def context_graph(
        silo_id: str,
        query: str | None = None,
        seed_nodes: list[str] | None = None,
        max_depth: int = 2,
        max_nodes: int = 50,
        relationship_types: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> dict[str, Any]:
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id"}

        if requested != expected_silo_id:
            return {"error": "silo_not_found"}

        if not query and not seed_nodes:
            return {"error": "missing_seed", "message": "Provide query or seed_nodes"}

        result = await ctx_svc.graph_traversal(
            silo_id=str(expected_silo_id),
            query=query,
            seed_nodes=seed_nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
            relationship_types=relationship_types,
            layers=layers,
        )

        return {
            "nodes": result.nodes,
            "edges": result.edges,
            "traversal_stats": {
                "depth_reached": result.depth_reached,
                "nodes_visited": result.nodes_visited,
                "edges_traversed": result.edges_traversed,
            },
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/context_graph.py
git commit -m "feat(mcp): add context_graph tool"
```

---

## Task 10: context_provenance Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_provenance.py`
- Add queries to: `src/context_service/db/queries.py`

- [ ] **Step 1: Add provenance query**

```python
# Add to src/context_service/db/queries.py

PROVENANCE_CHAIN = """
MATCH path = (start {id: $node_id, silo_id: $silo_id})-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM*1..10]->(source)
WHERE NOT (source)-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM]->()
UNWIND nodes(path) AS n
UNWIND relationships(path) AS r
RETURN DISTINCT
    n.id AS node_id,
    labels(n)[0] AS layer,
    type(r) AS relationship,
    n.confidence AS confidence
ORDER BY length(path)
"""
```

- [ ] **Step 2: Implement tool**

```python
# src/context_service/mcp/tools/context_provenance.py
"""MCP tool: context_provenance - Trace citation chain."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="context_provenance",
        description="Trace citation chain from a node to its Memory-layer sources.",
    )
    async def context_provenance(
        silo_id: str,
        node_id: str,
        max_depth: int = 10,
    ) -> dict[str, Any]:
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id"}

        if requested != expected_silo_id:
            return {"error": "silo_not_found"}

        result = await ctx_svc.provenance(
            silo_id=str(expected_silo_id),
            node_id=node_id,
            max_depth=max_depth,
        )

        return {
            "chain": result.chain,
            "root_sources": result.root_sources,
        }
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/context_provenance.py src/context_service/db/queries.py
git commit -m "feat(mcp): add context_provenance tool"
```

---

## Task 11: context_history Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_history.py`

- [ ] **Step 1: Implement**

```python
# src/context_service/mcp/tools/context_history.py
"""MCP tool: context_history - Belief evolution over time."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="context_history",
        description="Show how a belief or fact evolved over time via SUPERSEDES chain.",
    )
    async def context_history(
        silo_id: str,
        subject: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id"}

        if requested != expected_silo_id:
            return {"error": "silo_not_found"}

        if not subject and not node_id:
            return {"error": "missing_input", "message": "Provide subject or node_id"}

        result = await ctx_svc.history(
            silo_id=str(expected_silo_id),
            subject=subject,
            node_id=node_id,
        )

        return {
            "timeline": result.timeline,
            "current": result.current,
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/context_history.py
git commit -m "feat(mcp): add context_history tool"
```

---

## Task 12: context_reason Tool

**Files:**
- Create: `src/context_service/mcp/tools/context_reason.py`

- [ ] **Step 1: Implement**

```python
# src/context_service/mcp/tools/context_reason.py
"""MCP tool: context_reason - Store reasoning chains."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import ReasoningStep, Crystallization
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="context_reason",
        description="Store a reasoning chain to Intelligence layer. Optionally extract crystallizations.",
    )
    async def context_reason(
        silo_id: str,
        steps: list[dict[str, Any]],
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
        crystallizations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id"}

        if requested != expected_silo_id:
            return {"error": "silo_not_found"}

        # Parse steps
        parsed_steps = [ReasoningStep(**s) for s in steps]
        parsed_cryst = [Crystallization(**c) for c in (crystallizations or [])]

        session_id = getattr(auth, "session_id", None) or str(uuid.uuid4())

        result = await ctx_svc.reason(
            silo_id=str(expected_silo_id),
            steps=parsed_steps,
            conclusion=conclusion,
            evidence_used=evidence_used,
            crystallizations=parsed_cryst,
            session_id=session_id,
            agent_id=getattr(auth, "agent_id", None),
        )

        return {
            "chain_id": str(result.chain_id),
            "layer": "intelligence",
            "steps_count": len(steps),
            "crystallizations_queued": len(parsed_cryst),
            "session_id": session_id,
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/context_reason.py
git commit -m "feat(mcp): add context_reason tool for Intelligence layer"
```

---

## Task 13: Update Tool Registry and Deprecate Old Tools

**Files:**
- Modify: `src/context_service/mcp/tools/__init__.py`
- Modify: `src/context_service/mcp/server.py`

- [ ] **Step 1: Update __init__.py**

```python
# src/context_service/mcp/tools/__init__.py
"""MCP tool registry."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

from context_service.mcp.tools import (
    context_remember,
    context_assert,
    context_commit,
    context_reflect,
    context_query,
    context_get,
    context_link,
    context_graph,
    context_provenance,
    context_history,
    context_reason,
    silo,
)

# Deprecated - will be removed
# from context_service.mcp.tools import context_store, context_lookup


def register_all(mcp: FastMCP) -> None:
    """Register all EAG MCP tools."""
    # Write tools (intent verbs)
    context_remember.register(mcp)
    context_assert.register(mcp)
    context_commit.register(mcp)
    context_reflect.register(mcp)
    context_link.register(mcp)
    
    # Read tools
    context_query.register(mcp)
    context_get.register(mcp)
    context_graph.register(mcp)
    
    # Meta-memory tools
    context_provenance.register(mcp)
    context_history.register(mcp)
    
    # Intelligence tools
    context_reason.register(mcp)
    
    # Silo management
    silo.register(mcp)
```

- [ ] **Step 2: Update server.py to wire EvidenceValidator**

```python
# Add to src/context_service/mcp/server.py

_evidence_validator: EvidenceValidator | None = None

def configure_services(
    memgraph: MemgraphClient,
    qdrant: QdrantClient,
    redis: RedisClient | None = None,
    embedding: EmbeddingService | None = None,
) -> None:
    global _services, _evidence_validator
    # ... existing code ...
    _evidence_validator = EvidenceValidator(memgraph=memgraph)


def get_evidence_validator() -> EvidenceValidator:
    if _evidence_validator is None:
        raise RuntimeError("Evidence validator not configured")
    return _evidence_validator
```

- [ ] **Step 3: Run full test suite**

```bash
uv run just check
uv run just test
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/__init__.py src/context_service/mcp/server.py
git commit -m "feat(mcp): wire all EAG tools, deprecate CRUD tools"
```

---

## Task 14: Final Cleanup and Documentation

- [ ] **Step 1: Remove deprecated tool files**

```bash
rm src/context_service/mcp/tools/context_store.py
rm src/context_service/mcp/tools/context_lookup.py
```

- [ ] **Step 2: Update context/api-examples.md**

Update to reflect new tool signatures (remember, assert, commit, etc.)

- [ ] **Step 3: Run full verification**

```bash
uv run just check
uv run just test
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(mcp): remove deprecated CRUD tools, update docs"
```

---

## Verification Checklist

- [ ] All 13 MCP tools register without error
- [ ] `just check` passes (ruff + mypy)
- [ ] `just test` passes
- [ ] Evidence validation rejects invalid refs
- [ ] Layer routing works (remember→Memory, assert→Knowledge, commit→Wisdom)
- [ ] DERIVED_FROM edges created for context_assert
- [ ] DECLARED_BY edges created for context_commit
- [ ] context_provenance traces to Memory sources
- [ ] context_history shows SUPERSEDES chain
