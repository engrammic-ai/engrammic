# MCP Tool Surface Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace layer-based MCP tools with intent-based tools (remember, learn, believe, etc.) loaded from YAML config with profile support.

**Architecture:** New tools are thin wrappers calling existing `_context_*` implementations. YAML config defines tool metadata and profiles. Registry loads config and registers tools dynamically based on selected profile.

**Tech Stack:** Python 3.12, FastMCP, PyYAML, pytest

**Spec:** [`context/specs/2026-05-15-mcp-tool-surface-redesign.md`](../specs/2026-05-15-mcp-tool-surface-redesign.md)

**Reference:** Review spec for design decisions, tool mappings, and success criteria.

---

## File Structure

**Create:**
- `src/context_service/config/mcp_tools.yaml` - Tool definitions and profiles
- `src/context_service/mcp/tools/registry.py` - YAML loader and dynamic registration
- `src/context_service/mcp/tools/remember.py` - remember tool
- `src/context_service/mcp/tools/learn.py` - learn tool
- `src/context_service/mcp/tools/believe.py` - believe tool
- `src/context_service/mcp/tools/trace.py` - trace tool (extracted from admin)
- `src/context_service/mcp/tools/reason.py` - reason tool
- `src/context_service/mcp/tools/reflect.py` - reflect tool
- `src/context_service/mcp/tools/hypothesize.py` - hypothesize tool
- `src/context_service/mcp/tools/revise.py` - revise tool
- `src/context_service/mcp/tools/commit.py` - commit tool
- `src/context_service/mcp/tools/patterns.py` - patterns tool (renamed from skills)

**Modify:**
- `src/context_service/mcp/tools/context_recall.py` - add `include_hypotheses` param
- `src/context_service/mcp/tools/context_link.py` - rename to `link.py` or wrap
- `src/context_service/mcp/tools/__init__.py` - use registry
- `src/context_service/mcp/server.py` - use registry with profile selection
- `src/context_service/config/settings.py` - add `mcp_tool_profile` setting

**Keep (internal only):**
- `src/context_service/mcp/tools/context_admin.py`
- `src/context_service/mcp/tools/context_accept_belief.py`
- `src/context_service/mcp/tools/context_reject_belief.py`
- `src/context_service/mcp/tools/context_belief_state.py`

---

## Task 1: Create YAML Config File

**Files:**
- Create: `src/context_service/config/mcp_tools.yaml`

- [ ] **Step 1: Create the YAML config file**

```yaml
# src/context_service/config/mcp_tools.yaml
# MCP Tool Surface Configuration
# Edit this file to change tool names, descriptions, and profiles without code changes.

mcp_instructions: |
  Engrammic: Epistemic memory for AI agents.
  
  Quick start:
  - remember: store observations
  - learn: record claims WITH evidence
  - believe: declare conclusions
  - recall: search your knowledge
  - trace: understand why you believe something
  - link: connect related knowledge
  
  Guidelines:
  - Always provide evidence when using learn
  - Reference existing nodes when forming beliefs
  - Use recall before storing to avoid duplicates

profiles:
  standard:
    - remember
    - learn
    - believe
    - recall
    - trace
    - link

  reasoning:
    - remember
    - learn
    - believe
    - reason
    - reflect
    - recall
    - trace
    - link
    - hypothesize
    - revise
    - commit

tools:
  remember:
    description: "Store an observation. Use for raw information you may need later."
    maps_to: memory

  learn:
    description: "Record something you learned with evidence. Evidence is required."
    maps_to: knowledge

  believe:
    description: "Declare a belief as a commitment. Requires 'about' nodes that led to this belief."
    maps_to: wisdom

  recall:
    description: "Retrieve knowledge. Search by query or fetch by node_id."
    maps_to: recall

  trace:
    description: "Trace the provenance of a belief back to its sources."
    maps_to: provenance

  link:
    description: "Create a typed relationship between nodes."
    maps_to: link

  reason:
    description: "Record explicit reasoning steps for complex problems."
    maps_to: intelligence

  reflect:
    description: "Record a meta-observation about your knowledge."
    maps_to: meta

  hypothesize:
    description: "Form a tentative belief during reasoning. Use commit to finalize."
    maps_to: belief

  revise:
    description: "Update a tentative hypothesis when new information arrives."
    maps_to: update_belief

  commit:
    description: "Promote tentative hypotheses to permanent commitments."
    maps_to: crystallize

  patterns:
    description: "Discover workflow templates for common tasks."
    maps_to: skills
    always_available: true
```

- [ ] **Step 2: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('src/context_service/config/mcp_tools.yaml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml
git commit -m "feat(mcp): add YAML config for intent-based tool surface"
```

---

## Task 2: Create Registry Module

**Files:**
- Create: `src/context_service/mcp/tools/registry.py`
- Create: `tests/mcp/tools/conftest.py`
- Test: `tests/mcp/tools/test_registry.py`

- [ ] **Step 1: Create test fixtures**

```python
# tests/mcp/tools/conftest.py
"""Shared fixtures for MCP tool tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_mcp_auth_context():
    """Mock MCP auth context."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session-123"
    return auth


@pytest.fixture
def mock_mcp_context(mock_mcp_auth_context):
    """Patch get_mcp_auth_context to return mock."""
    with patch(
        "context_service.mcp.server.get_mcp_auth_context",
        new=AsyncMock(return_value=mock_mcp_auth_context),
    ):
        yield mock_mcp_auth_context


@pytest.fixture
def mock_context_service():
    """Mock context service with common methods."""
    svc = MagicMock()
    svc.store = AsyncMock(return_value={"node_id": "test-node-id", "created_at": "2026-01-01T00:00:00Z"})
    svc.provenance = AsyncMock(return_value=MagicMock(chain=[], root_sources=[]))
    svc.graph_store = MagicMock()
    svc.graph_store.execute_query = AsyncMock(return_value=[])
    
    with patch("context_service.mcp.server.get_context_service", return_value=svc):
        yield svc


@pytest.fixture
def mock_evidence_validator():
    """Mock evidence validator."""
    validator = MagicMock()
    validator.validate = AsyncMock(return_value={"valid": True, "resolved": []})
    
    with patch("context_service.mcp.server.get_evidence_validator", return_value=validator):
        yield validator
```

- [ ] **Step 2: Write the failing test**

```python
# tests/mcp/tools/test_registry.py
"""Tests for MCP tool registry."""

import pytest

from context_service.mcp.tools.registry import load_tool_config, get_profile_tools


def test_load_tool_config_returns_dict():
    config = load_tool_config()
    assert isinstance(config, dict)
    assert "profiles" in config
    assert "tools" in config
    assert "mcp_instructions" in config


def test_standard_profile_has_six_tools():
    config = load_tool_config()
    assert len(config["profiles"]["standard"]) == 6
    assert "remember" in config["profiles"]["standard"]
    assert "learn" in config["profiles"]["standard"]
    assert "believe" in config["profiles"]["standard"]
    assert "recall" in config["profiles"]["standard"]
    assert "trace" in config["profiles"]["standard"]
    assert "link" in config["profiles"]["standard"]


def test_reasoning_profile_has_eleven_tools():
    config = load_tool_config()
    assert len(config["profiles"]["reasoning"]) == 11


def test_get_profile_tools_standard():
    tools = get_profile_tools("standard")
    assert len(tools) == 7  # 6 + patterns (always available)
    assert "patterns" in tools


def test_get_profile_tools_invalid_profile_returns_standard():
    tools = get_profile_tools("invalid")
    assert len(tools) == 7  # falls back to standard
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_registry.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.registry'"

- [ ] **Step 4: Write the registry implementation**

```python
# src/context_service/mcp/tools/registry.py
"""MCP tool registry - loads tool config from YAML and registers dynamically."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "mcp_tools.yaml"
_cached_config: dict[str, Any] | None = None


def load_tool_config() -> dict[str, Any]:
    """Load tool configuration from YAML file.
    
    Returns cached config on subsequent calls.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    
    with open(_CONFIG_PATH) as f:
        _cached_config = yaml.safe_load(f)
    
    logger.info("mcp_tool_config_loaded", path=str(_CONFIG_PATH))
    return _cached_config


def get_profile_tools(profile: str) -> list[str]:
    """Get list of tool names for a profile, including always-available tools.
    
    Args:
        profile: Profile name (standard, reasoning). Falls back to standard if invalid.
    
    Returns:
        List of tool names to register.
    """
    config = load_tool_config()
    
    if profile not in config["profiles"]:
        logger.warning("invalid_mcp_profile", profile=profile, fallback="standard")
        profile = "standard"
    
    tools = list(config["profiles"][profile])
    
    # Add always-available tools
    for name, tool_def in config["tools"].items():
        if tool_def.get("always_available") and name not in tools:
            tools.append(name)
    
    return tools


def get_tool_description(tool_name: str) -> str:
    """Get description for a tool from config."""
    config = load_tool_config()
    return config["tools"].get(tool_name, {}).get("description", "")


def get_mcp_instructions() -> str:
    """Get MCP server instructions from config."""
    config = load_tool_config()
    return config.get("mcp_instructions", "")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_registry.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/registry.py tests/mcp/tools/conftest.py tests/mcp/tools/test_registry.py
git commit -m "feat(mcp): add tool registry for YAML-based configuration"
```

---

## Task 3: Create remember Tool

**Files:**
- Create: `src/context_service/mcp/tools/remember.py`
- Test: `tests/mcp/tools/test_remember.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_remember.py
"""Tests for remember tool."""

import pytest

from context_service.mcp.tools.remember import _remember_impl


@pytest.mark.asyncio
async def test_remember_returns_node_id(mock_mcp_context, mock_context_service):
    """remember should return node_id and created_at."""
    result = await _remember_impl(
        content="Test observation",
        tags=["test"],
        decay="standard",
    )
    
    assert "node_id" in result
    assert "created_at" in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_remember_invalid_decay_returns_error(mock_mcp_context):
    """remember should return error for invalid decay class."""
    result = await _remember_impl(
        content="Test",
        decay="invalid_decay",
    )
    
    assert "error" in result
    assert result["error"] == "invalid_decay_class"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_remember.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.remember'"

- [ ] **Step 3: Write the remember tool**

```python
# src/context_service/mcp/tools/remember.py
"""MCP tool: remember - Store an observation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_remember
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _remember_impl(
    content: str,
    tags: list[str] | None = None,
    decay: str = "standard",
) -> dict[str, Any]:
    """Implementation for remember tool."""
    return await _context_remember(
        silo_id=None,  # auto-derived from auth
        content=content,
        tags=tags,
        decay_class=decay,
    )


def register(mcp: FastMCP) -> None:
    """Register the remember tool."""
    
    @mcp.tool(
        name="remember",
        description=get_tool_description("remember"),
    )
    async def remember(
        content: str,
        tags: list[str] | None = None,
        decay: str = "standard",
    ) -> dict[str, Any]:
        """Store an observation.

        Args:
            content: What to remember.
            tags: Optional categorization tags.
            decay: How long to keep: ephemeral|standard|durable|permanent.

        Returns:
            {node_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _remember_impl(content, tags, decay)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("remember", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_remember.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/remember.py tests/mcp/tools/test_remember.py
git commit -m "feat(mcp): add remember tool for memory layer"
```

---

## Task 4: Create learn Tool

**Files:**
- Create: `src/context_service/mcp/tools/learn.py`
- Test: `tests/mcp/tools/test_learn.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_learn.py
"""Tests for learn tool."""

import pytest

from context_service.mcp.tools.learn import _learn_impl


@pytest.mark.asyncio
async def test_learn_requires_evidence(mock_mcp_context):
    """learn should require evidence parameter."""
    result = await _learn_impl(
        claim="Test claim",
        evidence=[],  # empty evidence
        source="document",
    )
    
    # Empty evidence should be rejected or handled
    assert "node_id" in result or "error" in result


@pytest.mark.asyncio
async def test_learn_returns_node_id(mock_mcp_context, mock_context_service, mock_evidence_validator):
    """learn should return node_id with valid evidence."""
    result = await _learn_impl(
        claim="Test claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
        source="document",
        confidence=0.9,
    )
    
    assert "node_id" in result
    assert "created_at" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_learn.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.learn'"

- [ ] **Step 3: Write the learn tool**

```python
# src/context_service/mcp/tools/learn.py
"""MCP tool: learn - Assert a claim with evidence."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_assert
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _learn_impl(
    claim: str,
    evidence: list[str],
    source: str,
    confidence: float = 0.8,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for learn tool."""
    return await _context_assert(
        silo_id=None,  # auto-derived from auth
        claim=claim,
        evidence=evidence,
        source_type=source,
        confidence=confidence,
        tags=tags,
    )


def register(mcp: FastMCP) -> None:
    """Register the learn tool."""
    
    @mcp.tool(
        name="learn",
        description=get_tool_description("learn"),
    )
    async def learn(
        claim: str,
        evidence: list[str],
        source: str,
        confidence: float = 0.8,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record something you learned with evidence.

        Args:
            claim: What you learned.
            evidence: REQUIRED. References: node:<uuid> or URI.
            source: Source type: document|user|external|agent.
            confidence: 0.0-1.0 (default 0.8).
            tags: Optional categorization.

        Returns:
            {node_id, evidence_status, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _learn_impl(claim, evidence, source, confidence, tags)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("learn", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_learn.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/learn.py tests/mcp/tools/test_learn.py
git commit -m "feat(mcp): add learn tool for knowledge layer"
```

---

## Task 5: Create believe Tool

**Files:**
- Create: `src/context_service/mcp/tools/believe.py`
- Test: `tests/mcp/tools/test_believe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_believe.py
"""Tests for believe tool."""

import pytest

from context_service.mcp.tools.believe import _believe_impl


@pytest.mark.asyncio
async def test_believe_requires_about(mock_mcp_context):
    """believe should require about parameter."""
    result = await _believe_impl(
        belief="Test belief",
        about=[],  # empty about
    )
    
    assert "error" in result
    assert result["error"] == "missing_about"


@pytest.mark.asyncio
async def test_believe_returns_node_id(mock_mcp_context, mock_context_service):
    """believe should return node_id with valid about."""
    result = await _believe_impl(
        belief="Test belief",
        about=["node-123"],
        confidence=0.9,
        reasoning="Based on evidence",
    )
    
    assert "node_id" in result
    assert "created_at" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_believe.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.believe'"

- [ ] **Step 3: Write the believe tool**

```python
# src/context_service/mcp/tools/believe.py
"""MCP tool: believe - Declare a commitment."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_commit
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _believe_impl(
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Implementation for believe tool."""
    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}
    
    return await _context_commit(
        silo_id=None,  # auto-derived from auth
        belief=belief,
        about=about,
        confidence=confidence,
        reasoning=reasoning,
    )


def register(mcp: FastMCP) -> None:
    """Register the believe tool."""
    
    @mcp.tool(
        name="believe",
        description=get_tool_description("believe"),
    )
    async def believe(
        belief: str,
        about: list[str],
        confidence: float = 0.8,
        reasoning: str | None = None,
    ) -> dict[str, Any]:
        """Declare a belief as a commitment.

        Args:
            belief: What you believe.
            about: REQUIRED. Node IDs this belief concerns.
            confidence: 0.0-1.0 (default 0.8).
            reasoning: Why you believe this.

        Returns:
            {node_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _believe_impl(belief, about, confidence, reasoning)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("believe", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_believe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/believe.py tests/mcp/tools/test_believe.py
git commit -m "feat(mcp): add believe tool for wisdom layer"
```

---

## Task 6: Create trace Tool

**Files:**
- Create: `src/context_service/mcp/tools/trace.py`
- Test: `tests/mcp/tools/test_trace.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_trace.py
"""Tests for trace tool."""

import pytest

from context_service.mcp.tools.trace import _trace_impl


@pytest.mark.asyncio
async def test_trace_requires_node_id(mock_mcp_context):
    """trace should require node_id parameter."""
    result = await _trace_impl(node_id="")
    
    assert "error" in result


@pytest.mark.asyncio
async def test_trace_returns_chain(mock_mcp_context, mock_context_service):
    """trace should return provenance chain."""
    result = await _trace_impl(node_id="test-node-id")
    
    assert "chain" in result
    assert "root_sources" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_trace.py -v`
Expected: FAIL with "No module named 'context_service.mcp.tools.trace'"

- [ ] **Step 3: Write the trace tool**

```python
# src/context_service/mcp/tools/trace.py
"""MCP tool: trace - Explain why you believe something."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_context_service, get_mcp_auth_context
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _trace_impl(node_id: str) -> dict[str, Any]:
    """Implementation for trace tool."""
    if not node_id:
        return {"error": "missing_node_id", "message": "node_id is required"}
    
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()
    
    result = await ctx_svc.provenance(silo_id, node_id)
    
    return {
        "chain": [
            {
                "node_id": step.node_id,
                "layer": step.layer,
                "relationship": step.relationship,
                "confidence": step.confidence,
            }
            for step in result.chain
        ],
        "root_sources": result.root_sources,
    }


def register(mcp: FastMCP) -> None:
    """Register the trace tool."""
    
    @mcp.tool(
        name="trace",
        description=get_tool_description("trace"),
    )
    async def trace(node_id: str) -> dict[str, Any]:
        """Trace provenance of a belief back to its sources.

        Args:
            node_id: Node to trace.

        Returns:
            {chain: [...], root_sources: [...]}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _trace_impl(node_id)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("trace", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_trace.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/trace.py tests/mcp/tools/test_trace.py
git commit -m "feat(mcp): add trace tool for provenance"
```

---

## Task 7: Create link Tool Wrapper

**Files:**
- Create: `src/context_service/mcp/tools/link.py`

- [ ] **Step 1: Create the link tool wrapper**

```python
# src/context_service/mcp/tools/link.py
"""MCP tool: link - Create a relationship between nodes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_link import _context_link
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _link_impl(
    from_node: str,
    to_node: str,
    relationship: str,
    weight: float = 1.0,
    note: str | None = None,
) -> dict[str, Any]:
    """Implementation for link tool."""
    return await _context_link(
        silo_id=None,
        from_node=from_node,
        to_node=to_node,
        relationship=relationship,
        weight=weight,
        note=note,
    )


def register(mcp: FastMCP) -> None:
    """Register the link tool."""
    
    @mcp.tool(
        name="link",
        description=get_tool_description("link"),
    )
    async def link(
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a typed relationship between nodes.

        Args:
            from_node: Source node ID.
            to_node: Target node ID.
            relationship: Type: supports|contradicts|derives|references|causes|supersedes.
            weight: Strength 0.0-10.0 (default 1.0).
            note: Optional annotation.

        Returns:
            {edge_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _link_impl(from_node, to_node, relationship, weight, note)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("link", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/link.py
git commit -m "feat(mcp): add link tool wrapper"
```

---

## Task 8: Create recall Tool with include_hypotheses

**Files:**
- Create: `src/context_service/mcp/tools/recall.py`

- [ ] **Step 1: Create the recall tool wrapper with include_hypotheses**

```python
# src/context_service/mcp/tools/recall.py
"""MCP tool: recall - Search or fetch knowledge."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_mcp_auth_context
from context_service.mcp.tools.context_recall import _context_recall
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    include_hypotheses: bool = False,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    
    result = await _context_recall(
        silo_id=silo_id,
        query=query,
        node_ids=node_ids,
        depth=depth,
        layers=layers,
        top_k=top_k,
    )
    
    if include_hypotheses:
        # Fetch active hypotheses for current session
        from context_service.db.queries import GET_WORKING_HYPOTHESES_FOR_SESSION
        from context_service.mcp.server import get_context_service
        
        ctx_svc = get_context_service()
        session_id = auth.session_id
        
        if session_id:
            rows = await ctx_svc.graph_store.execute_query(
                GET_WORKING_HYPOTHESES_FOR_SESSION,
                {"session_id": session_id, "silo_id": silo_id},
            )
            result["hypotheses"] = [
                {
                    "belief_id": r["belief_id"],
                    "content": r["content"],
                    "confidence": r["confidence"],
                    "about": r.get("about_ids", []),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        else:
            result["hypotheses"] = []
    
    return result


def register(mcp: FastMCP) -> None:
    """Register the recall tool."""
    
    @mcp.tool(
        name="recall",
        description=get_tool_description("recall"),
    )
    async def recall(
        query: str | None = None,
        node_ids: list[str] | None = None,
        depth: int = 0,
        layers: list[str] | None = None,
        top_k: int = 10,
        include_hypotheses: bool = False,
    ) -> dict[str, Any]:
        """Retrieve knowledge.

        Args:
            query: Natural language search.
            node_ids: Specific nodes to fetch.
            depth: 0=flat, 1-3=graph traversal.
            layers: Filter: memory|knowledge|wisdom|intelligence.
            top_k: Max results for search (default 10).
            include_hypotheses: Include tentative beliefs from current session.

        Returns:
            {results|nodes, hypotheses?, ...}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _recall_impl(query, node_ids, depth, layers, top_k, include_hypotheses)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("recall", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/recall.py
git commit -m "feat(mcp): add recall tool with include_hypotheses"
```

---

## Task 9: Create Reasoning Profile Tools

**Files:**
- Create: `src/context_service/mcp/tools/reason.py`
- Create: `src/context_service/mcp/tools/reflect.py`
- Create: `src/context_service/mcp/tools/hypothesize.py`
- Create: `src/context_service/mcp/tools/revise.py`
- Create: `src/context_service/mcp/tools/commit.py`

- [ ] **Step 1: Create reason tool**

```python
# src/context_service/mcp/tools/reason.py
"""MCP tool: reason - Record a reasoning chain."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_reason
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _reason_impl(
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for reason tool."""
    return await _context_reason(
        silo_id=None,
        steps=steps,
        conclusion=conclusion,
        evidence_used=evidence_used,
    )


def register(mcp: FastMCP) -> None:
    """Register the reason tool."""
    
    @mcp.tool(
        name="reason",
        description=get_tool_description("reason"),
    )
    async def reason(
        steps: list[dict[str, Any]],
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record explicit reasoning steps.

        Args:
            steps: List of {step, reasoning, confidence?}.
            conclusion: Final conclusion.
            evidence_used: Node IDs referenced.

        Returns:
            {chain_id, session_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _reason_impl(steps, conclusion, evidence_used)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("reason", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 2: Create reflect tool**

```python
# src/context_service/mcp/tools/reflect.py
"""MCP tool: reflect - Record a meta-observation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_reflect
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _reflect_impl(
    observation: str,
    type: str,
    about: list[str],
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Implementation for reflect tool."""
    return await _context_reflect(
        silo_id=None,
        observation=observation,
        observation_type=type,
        about=about,
        confidence=confidence,
    )


def register(mcp: FastMCP) -> None:
    """Register the reflect tool."""
    
    @mcp.tool(
        name="reflect",
        description=get_tool_description("reflect"),
    )
    async def reflect(
        observation: str,
        type: str,
        about: list[str],
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        """Record a meta-observation about your knowledge.

        Args:
            observation: What you noticed.
            type: Type: pattern|contradiction|uncertainty|drift.
            about: REQUIRED. Node IDs this concerns.
            confidence: 0.0-1.0 (default 0.8).

        Returns:
            {node_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _reflect_impl(observation, type, about, confidence)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("reflect", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 3: Create hypothesize tool**

```python
# src/context_service/mcp/tools/hypothesize.py
"""MCP tool: hypothesize - Form a tentative belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_mcp_auth_context
from context_service.mcp.tools.context_store import _context_store_belief
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _hypothesize_impl(
    hypothesis: str,
    about: list[str],
    confidence: float = 0.8,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Implementation for hypothesize tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    
    # Use provided session_id or fall back to auth context
    resolved_session_id = session_id or auth.session_id
    if not resolved_session_id:
        return {"error": "no_session", "message": "No session available. Connect with a session-enabled auth."}
    
    result = await _context_store_belief(
        silo_id=silo_id,
        content=hypothesis,
        session_id=resolved_session_id,
        about=about,
        confidence=confidence,
    )
    
    # Add session_id to response
    if "error" not in result:
        result["session_id"] = resolved_session_id
    
    return result


def register(mcp: FastMCP) -> None:
    """Register the hypothesize tool."""
    
    @mcp.tool(
        name="hypothesize",
        description=get_tool_description("hypothesize"),
    )
    async def hypothesize(
        hypothesis: str,
        about: list[str],
        confidence: float = 0.8,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Form a tentative belief during reasoning.

        Args:
            hypothesis: Tentative belief.
            about: REQUIRED. Node IDs this concerns.
            confidence: 0.0-1.0 (default 0.8).
            session_id: Optional override. Defaults to MCP session.

        Returns:
            {belief_id, session_id, potential_conflicts, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _hypothesize_impl(hypothesis, about, confidence, session_id)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("hypothesize", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 4: Create revise tool**

```python
# src/context_service/mcp/tools/revise.py
"""MCP tool: revise - Update a tentative belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_update_belief import _context_update_belief
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _revise_impl(
    belief_id: str,
    confidence: float,
    content: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Implementation for revise tool."""
    return await _context_update_belief(
        silo_id=None,
        belief_id=belief_id,
        confidence=confidence,
        content=content,
        reason=reason,
    )


def register(mcp: FastMCP) -> None:
    """Register the revise tool."""
    
    @mcp.tool(
        name="revise",
        description=get_tool_description("revise"),
    )
    async def revise(
        belief_id: str,
        confidence: float,
        reason: str,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Update a tentative hypothesis.

        Args:
            belief_id: Hypothesis to update.
            confidence: New confidence 0.0-1.0.
            reason: REQUIRED. Why revising.
            content: New content (optional).

        Returns:
            {updated_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _revise_impl(belief_id, confidence, content, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("revise", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 5: Create commit tool**

```python
# src/context_service/mcp/tools/commit.py
"""MCP tool: commit - Crystallize hypotheses to commitments."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_crystallize import _context_crystallize
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _commit_impl(
    belief_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for commit tool."""
    return await _context_crystallize(
        silo_id=None,
        belief_ids=belief_ids,
        reason=reason,
    )


def register(mcp: FastMCP) -> None:
    """Register the commit tool."""
    
    @mcp.tool(
        name="commit",
        description=get_tool_description("commit"),
    )
    async def commit(
        belief_ids: list[str],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Promote tentative hypotheses to permanent commitments.

        Args:
            belief_ids: Hypotheses to commit.
            reason: Why committing now.

        Returns:
            {committed: [...], superseded: [...]}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _commit_impl(belief_ids, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("commit", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 6: Commit all reasoning tools**

```bash
git add src/context_service/mcp/tools/reason.py \
        src/context_service/mcp/tools/reflect.py \
        src/context_service/mcp/tools/hypothesize.py \
        src/context_service/mcp/tools/revise.py \
        src/context_service/mcp/tools/commit.py
git commit -m "feat(mcp): add reasoning profile tools (reason, reflect, hypothesize, revise, commit)"
```

---

## Task 10: Create patterns Tool

**Files:**
- Create: `src/context_service/mcp/tools/patterns.py`

- [ ] **Step 1: Create the patterns tool**

```python
# src/context_service/mcp/tools/patterns.py
"""MCP tool: patterns - Discover workflow templates."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.server import get_mcp_auth_context, get_skill_service
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _patterns_impl(
    action: Literal["list", "get", "search"],
    name: str | None = None,
    query: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Implementation for patterns tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    
    try:
        skill_svc = get_skill_service()
    except RuntimeError:
        return {"error": "patterns_unavailable", "message": "Patterns service not configured"}
    
    if action == "list":
        skills = await skill_svc.list(silo_id, namespace=profile, limit=50, offset=0)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }
    
    elif action == "get":
        if not name:
            return {"error": "missing_name", "message": "name required for get action"}
        skill = await skill_svc.get(silo_id, name)
        if not skill:
            return {"error": "not_found", "message": f"Pattern not found: {name}"}
        return {"pattern": skill.model_dump(exclude_none=True)}
    
    elif action == "search":
        if not query:
            return {"error": "missing_query", "message": "query required for search action"}
        skills = await skill_svc.search(silo_id, query, namespace=profile, limit=20)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in skills],
            "count": len(skills),
        }
    
    return {"error": "invalid_action", "valid": ["list", "get", "search"]}


def register(mcp: FastMCP) -> None:
    """Register the patterns tool."""
    
    @mcp.tool(
        name="patterns",
        description=get_tool_description("patterns"),
    )
    async def patterns(
        action: Literal["list", "get", "search"],
        name: str | None = None,
        query: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Discover workflow templates for common tasks.

        Args:
            action: list|get|search.
            name: Pattern name (for get).
            query: Search query (for search).
            profile: Filter by profile: standard|reasoning.

        Returns:
            {patterns: [...]} or {pattern: {...}}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _patterns_impl(action, name, query, profile)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("patterns", (time.perf_counter() - start) * 1000, success=success)
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/patterns.py
git commit -m "feat(mcp): add patterns tool (renamed from context_skills)"
```

---

## Task 11: Create Example Workflow Patterns

**Files:**
- Create: `skills/patterns:observe-and-learn/SKILL.md`
- Create: `skills/patterns:research/SKILL.md`
- Create: `skills/patterns:build-knowledge/SKILL.md`
- Create: `skills/patterns:deliberate/SKILL.md`
- Create: `skills/patterns:reflect-on-knowledge/SKILL.md`

- [ ] **Step 1: Create observe-and-learn pattern**

```markdown
<!-- skills/patterns:observe-and-learn/SKILL.md -->
---
name: patterns:observe-and-learn
description: Store observations and convert them to learned knowledge
namespace: standard
tags: [workflow, beginner]
---

# Observe and Learn

A basic workflow for converting raw observations into learned claims.

## Steps

1. **remember** - Store the raw observation
   ```
   remember(content="Noticed X happening when Y")
   ```

2. **learn** - Convert to a claim with evidence
   ```
   learn(
     claim="X occurs because of Y",
     evidence=["node:<id-from-step-1>"],
     source="agent"
   )
   ```

3. **believe** - Form a conclusion if confident
   ```
   believe(
     belief="Y reliably causes X",
     about=["<id-from-step-2>"],
     reasoning="Observed consistent pattern"
   )
   ```

## When to Use

- You've observed something and want to record it properly
- You have evidence to support a claim
- You're ready to commit to a belief
```

- [ ] **Step 2: Create research pattern**

```markdown
<!-- skills/patterns:research/SKILL.md -->
---
name: patterns:research
description: Research existing knowledge before adding new claims
namespace: standard
tags: [workflow, search]
---

# Research

Search existing knowledge before adding new information.

## Steps

1. **recall** - Search for related knowledge
   ```
   recall(query="topic I'm researching", top_k=10)
   ```

2. **trace** - Understand provenance of relevant nodes
   ```
   trace(node_id="<interesting-node>")
   ```

3. **learn** - Add new claim citing what you found
   ```
   learn(
     claim="New insight building on existing knowledge",
     evidence=["node:<existing-node>", "https://source.url"],
     source="document"
   )
   ```

## When to Use

- Before storing new claims, check what already exists
- You want to build on existing knowledge
- You need to cite sources properly
```

- [ ] **Step 3: Create build-knowledge pattern**

```markdown
<!-- skills/patterns:build-knowledge/SKILL.md -->
---
name: patterns:build-knowledge
description: Build structured knowledge from observations
namespace: standard
tags: [workflow, comprehensive]
---

# Build Knowledge

Full workflow from observations to beliefs with relationships.

## Steps

1. **remember** - Capture multiple observations
   ```
   remember(content="Observation 1")  # -> obs_1
   remember(content="Observation 2")  # -> obs_2
   ```

2. **learn** - Form claims with evidence
   ```
   learn(
     claim="Pattern from observations",
     evidence=["node:<obs_1>", "node:<obs_2>"],
     source="agent"
   )  # -> claim_1
   ```

3. **link** - Connect related knowledge
   ```
   link(
     from_node="<claim_1>",
     to_node="<related_claim>",
     relationship="supports"
   )
   ```

4. **believe** - Synthesize conclusions
   ```
   believe(
     belief="Conclusion from linked claims",
     about=["<claim_1>", "<related_claim>"],
     reasoning="Claims mutually reinforce"
   )
   ```

## When to Use

- Building comprehensive understanding of a topic
- Multiple related observations need to be connected
- Ready to form lasting beliefs
```

- [ ] **Step 4: Create deliberate pattern (reasoning profile)**

```markdown
<!-- skills/patterns:deliberate/SKILL.md -->
---
name: patterns:deliberate
description: Extended reasoning with tentative beliefs
namespace: reasoning
tags: [workflow, reasoning, advanced]
---

# Deliberate

For extended reasoning sessions where beliefs may change.

## Steps

1. **hypothesize** - Form tentative belief
   ```
   hypothesize(
     hypothesis="Initial theory about X",
     about=["<evidence-nodes>"],
     confidence=0.6
   )  # -> hyp_1
   ```

2. **reason** - Record reasoning steps
   ```
   reason(
     steps=[
       {"step": "Considered alternative A", "reasoning": "Unlikely because..."},
       {"step": "Evaluated evidence B", "reasoning": "Supports hypothesis"}
     ],
     evidence_used=["<evidence-nodes>"]
   )
   ```

3. **revise** - Update as you learn more
   ```
   revise(
     belief_id="<hyp_1>",
     confidence=0.8,
     reason="New evidence strengthens theory"
   )
   ```

4. **commit** - Finalize when confident
   ```
   commit(
     belief_ids=["<hyp_1>"],
     reason="Sufficient evidence gathered"
   )
   ```

## When to Use

- Complex problems requiring extended reasoning
- Initial beliefs may need revision
- You want to track your reasoning process
```

- [ ] **Step 5: Create reflect-on-knowledge pattern (reasoning profile)**

```markdown
<!-- skills/patterns:reflect-on-knowledge/SKILL.md -->
---
name: patterns:reflect-on-knowledge
description: Meta-analysis of existing knowledge
namespace: reasoning
tags: [workflow, meta, reflection]
---

# Reflect on Knowledge

Analyze patterns in your existing knowledge.

## Steps

1. **recall** - Retrieve existing knowledge
   ```
   recall(
     layers=["knowledge", "wisdom"],
     top_k=20
   )
   ```

2. **reflect** - Note meta-observations
   ```
   reflect(
     observation="These claims seem contradictory",
     type="contradiction",
     about=["<claim_a>", "<claim_b>"]
   )
   ```

   ```
   reflect(
     observation="Pattern: X always follows Y",
     type="pattern",
     about=["<relevant-nodes>"]
   )
   ```

3. **believe** - Synthesize meta-insight
   ```
   believe(
     belief="Higher-order conclusion from reflection",
     about=["<reflection-nodes>"],
     reasoning="Pattern analysis reveals..."
   )
   ```

## When to Use

- Periodic review of accumulated knowledge
- Detecting contradictions or gaps
- Synthesizing higher-order insights
```

- [ ] **Step 6: Commit patterns**

```bash
git add skills/patterns:observe-and-learn/SKILL.md \
        skills/patterns:research/SKILL.md \
        skills/patterns:build-knowledge/SKILL.md \
        skills/patterns:deliberate/SKILL.md \
        skills/patterns:reflect-on-knowledge/SKILL.md
git commit -m "feat(patterns): add example workflow patterns for standard and reasoning profiles"
```

---

## Task 12: Update Registry with Tool Registration

**Files:**
- Modify: `src/context_service/mcp/tools/registry.py`

- [ ] **Step 1: Add tool registration to registry**

Add to the end of `registry.py`:

```python
def register_profile_tools(mcp: FastMCP, profile: str = "standard") -> None:
    """Register all tools for a profile.
    
    Args:
        mcp: FastMCP server instance.
        profile: Tool profile (standard or reasoning).
    
    Note: Imports are inside function to avoid circular imports,
    since tool modules import from registry.
    """
    # Lazy imports to avoid circular dependency
    from context_service.mcp.tools import (
        believe,
        commit,
        hypothesize,
        learn,
        link,
        patterns,
        reason,
        recall,
        reflect,
        remember,
        revise,
        trace,
    )
    
    tool_registers = {
        "remember": remember.register,
        "learn": learn.register,
        "believe": believe.register,
        "recall": recall.register,
        "trace": trace.register,
        "link": link.register,
        "reason": reason.register,
        "reflect": reflect.register,
        "hypothesize": hypothesize.register,
        "revise": revise.register,
        "commit": commit.register,
        "patterns": patterns.register,
    }
    
    tool_names = get_profile_tools(profile)
    
    for name in tool_names:
        if name in tool_registers:
            tool_registers[name](mcp)
            logger.debug("mcp_tool_registered", tool=name, profile=profile)
        else:
            logger.warning("mcp_tool_not_found", tool=name)
    
    logger.info(
        "mcp_profile_tools_registered",
        profile=profile,
        tool_count=len(tool_names),
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/registry.py
git commit -m "feat(mcp): add tool registration to registry"
```

---

## Task 13: Update server.py to Use Registry

**Files:**
- Modify: `src/context_service/mcp/server.py`
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Add mcp_tool_profile setting**

In `src/context_service/config/settings.py`, add to the Settings class:

```python
    # MCP settings
    mcp_tool_profile: str = "standard"
```

- [ ] **Step 2: Update create_mcp_server in server.py**

Replace the `create_mcp_server` function:

```python
def create_mcp_server(profile: str | None = None) -> FastMCP:
    """Create and configure the FastMCP server with intent-based tools.
    
    Args:
        profile: Tool profile override. If None, uses settings or env var.
    """
    from context_service.config.settings import get_settings
    from context_service.mcp.tools.registry import (
        get_mcp_instructions,
        register_profile_tools,
    )
    
    settings = get_settings()
    
    # Determine profile: param > env > settings > default
    resolved_profile = (
        profile
        or os.environ.get("MCP_TOOL_PROFILE")
        or settings.mcp_tool_profile
        or "standard"
    )
    
    mcp = FastMCP(
        name="engrammic",
        instructions=get_mcp_instructions(),
    )
    
    # Register tools based on profile
    register_profile_tools(mcp, resolved_profile)
    
    logger.info("mcp_server_created", profile=resolved_profile)
    return mcp
```

- [ ] **Step 3: Add os import if not present**

At top of server.py, ensure:

```python
import os
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/server.py src/context_service/config/settings.py
git commit -m "feat(mcp): use registry for profile-based tool registration"
```

---

## Task 14: Update __init__.py

**Files:**
- Modify: `src/context_service/mcp/tools/__init__.py`

- [ ] **Step 1: Update __init__.py to export new tools**

```python
# src/context_service/mcp/tools/__init__.py
"""MCP tool implementations -- intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Intent-based tools (external-facing)
from context_service.mcp.tools import (
    believe,
    commit,
    hypothesize,
    learn,
    link,
    patterns,
    reason,
    recall,
    reflect,
    remember,
    revise,
    trace,
)

# Registry for profile-based registration
from context_service.mcp.tools.registry import register_profile_tools

# Internal-only tools (not registered via registry)
from context_service.mcp.tools.context_accept_belief import register as register_accept_belief
from context_service.mcp.tools.context_admin import register as register_admin
from context_service.mcp.tools.context_belief_state import register as register_belief_state
from context_service.mcp.tools.context_reject_belief import register as register_reject_belief


def register_all(mcp: FastMCP, profile: str = "standard") -> None:
    """Register all MCP tools for the given profile.
    
    This is the main entry point. Use this instead of individual registers.
    """
    register_profile_tools(mcp, profile)


def register_internal_tools(mcp: FastMCP) -> None:
    """Register internal-only tools (for SAGE and admin use).
    
    These are NOT included in the standard/reasoning profiles.
    Call separately if needed.
    """
    register_admin(mcp)
    register_accept_belief(mcp)
    register_reject_belief(mcp)
    register_belief_state(mcp)


__all__ = [
    "register_all",
    "register_internal_tools",
    "register_profile_tools",
    # Individual tool modules
    "remember",
    "learn",
    "believe",
    "recall",
    "trace",
    "link",
    "reason",
    "reflect",
    "hypothesize",
    "revise",
    "commit",
    "patterns",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/mcp/tools/__init__.py
git commit -m "feat(mcp): update tools __init__ for intent-based surface"
```

---

## Task 15: Run Tests and Fix Issues

**Files:**
- Various test files

- [ ] **Step 1: Run type checker**

Run: `uv run mypy src/context_service/mcp/tools/`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/context_service/mcp/tools/`
Expected: No errors

- [ ] **Step 3: Run existing MCP tests**

Run: `uv run pytest tests/mcp/ -v --tb=short`
Expected: Tests pass (some may need updates for new tool names)

- [ ] **Step 4: Fix any failing tests**

Update test imports and tool names as needed.

- [ ] **Step 5: Commit fixes**

```bash
git add -A
git commit -m "fix(mcp): update tests for intent-based tool surface"
```

---

## Task 16: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short -x`
Expected: All tests pass

- [ ] **Step 2: Run type check on full codebase**

Run: `just check`
Expected: All checks pass

- [ ] **Step 3: Manual verification**

Start the dev server and verify tools are registered:
```bash
just dev
# In another terminal, check MCP tool list
```

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(mcp): cleanup after tool surface redesign"
```

---

## Done Criteria

- [ ] YAML config file loads correctly
- [ ] Registry registers correct tools per profile
- [ ] Standard profile exposes 7 tools (6 + patterns)
- [ ] Reasoning profile exposes 12 tools (11 + patterns)
- [ ] All intent-based tools call existing implementations
- [ ] Internal tools (context_admin, accept/reject belief) are NOT registered
- [ ] MCP instructions come from YAML
- [ ] Example workflow patterns created (5 patterns: 3 standard, 2 reasoning)
- [ ] All tests pass
- [ ] Type checker passes

## Out of Scope

- Hot reload of YAML config (future enhancement)
- Silo-level and connection-level profile selection (env-level only for now)
- Updating primitives spec (tracked in open questions)
- Error response standardization (separate task)
- Metrics rename (telemetry already uses new names)
