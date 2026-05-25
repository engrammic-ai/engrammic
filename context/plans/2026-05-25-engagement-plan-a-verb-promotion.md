# Engagement Plan A: Promote accept / reject to Agent Surface

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `context_accept_belief` and `context_reject_belief` from internal-only MCP tools to agent-facing `accept` and `reject` tools, available in the `reasoning` profile. This is the first ship-now slice of the layer 1 engagement design.

**Architecture:** Both verbs already exist as internal-only MCP tools with working graph queries and acceptance/rejection logic. Promotion is primarily a config + registration change. The underlying `_context_accept_belief` and `_context_reject_belief` private functions are unchanged and have no non-MCP consumers (verified). The tool surface (visible to agents) is governed by `src/context_service/config/mcp_tools.yaml` — adding entries and updating the `reasoning` profile is the source-of-truth change. The internal-only registration via `register_internal_tools` is removed for these two tools, since the agent-facing surface supersedes it.

**Tech Stack:** FastMCP 3.3.1, YAML config (`mcp_tools.yaml`), pytest, structlog

**Spec:** `context/brainstorm/2026-05-25-engagement-surface-layers.md` (decision 3, resolution: Option B — promote internal verbs)

**Out of scope for Plan A:**
- `dismiss(marker_id, reason)` — depends on marker types (Contradiction, StaleCommitment) which don't exist until SAGE Plan B. Moved to Plan C.
- `revise(marker_id, ...)` extension — same reason, moved to Plan C.
- Redis touch-counter primitive — only needed when engagement detection ships in Plan C. Identity primitive (`auth.session_id`) is already wired via `server.py:271` and consumed by `hypothesize` / `context_belief_state` today.
- Skill updates (`engrammic-engage`, `engrammic-recall`) — moved to Plan E.

**Verified safe to rename in this plan:**
- The `record_mcp_tool` metric tag rename (`"context_accept_belief"` → `"accept"`, same for reject) has been grep-confirmed not to appear in any dashboard, Pulumi infra config, alerting rule, or non-Python source. Telemetry pipeline takes the tag as a free string; the rename is a clean cut.

**Parameter naming preserved (deliberate):**
- The wrapper function exposes its first argument as `belief_id` while the description and the internal `_context_accept_belief` private function use `proposed_belief_id`. Plan A does not rename the wrapper's parameter, to keep the diff minimal and surface-only. Future plans may rename to `proposed_belief_id` for surface consistency; flagged here for awareness.

---

## File Structure

```
src/context_service/
  config/
    mcp_tools.yaml                          # MODIFY - add accept/reject entries + reasoning profile
  mcp/
    tools/
      context_accept_belief.py              # MODIFY - rename @mcp.tool name "context_accept_belief" -> "accept", update description
      context_reject_belief.py              # MODIFY - rename @mcp.tool name "context_reject_belief" -> "reject", update description
      registry.py                           # MODIFY - add accept/reject to tool_registers dict
      __init__.py                           # MODIFY - remove accept/reject from register_internal_tools

tests/
  integration/
    test_mcp_protocol.py                    # MODIFY - update tool-list assertions
  mcp/
    tools/
      test_accept_agent_surface.py          # CREATE - integration tests for agent-facing accept
      test_reject_agent_surface.py          # CREATE - integration tests for agent-facing reject
```

---

## Task 0: Verify Baseline

**Goal:** Confirm tests pass before touching anything. Establishes a clean baseline to detect regressions.

- [ ] **Step 1: Run the existing test suite**

```bash
just test
```

Expected: All tests pass (or at most the documented test debt — see `MEMORY.md` "Test debt" entry). Record the pass count and any failing tests so we can detect Plan A regressions later.

**Known stale assertion to expect:** `tests/integration/test_mcp_protocol.py::TestMCPProtocol::test_all_tools_registered` and `test_create_mcp_server_tool_count` both assert against an `EXPECTED_TOOLS` set that still lists the legacy `context_*` names (`context_store`, `context_recall`, `context_link`, `context_belief_state`, `context_update_belief`, `context_crystallize`, `context_accept_belief`, `context_reject_belief`). The v2.7 surface redesign replaced these with the intent verbs (`remember`, `learn`, etc.). If these two tests are already failing in this baseline, that confirms the stale set — Task 6 will rebuild it. If they happen to be passing, investigate before continuing, because something is masking the rename.

- [ ] **Step 2: Run lint + typecheck**

```bash
just check
```

Expected: clean. If not, do not start Plan A — fix or document first.

---

## Task 1: Add accept and reject entries to mcp_tools.yaml

**Files:**
- Modify: `src/context_service/config/mcp_tools.yaml`

**Goal:** Register the two new agent-facing tool names in the source-of-truth config, including the `reasoning` profile they belong to.

- [ ] **Step 1: Write the failing test (config loader contract)**

Add to `tests/mcp/tools/test_registry.py` (create the file if it does not exist):

```python
# tests/mcp/tools/test_registry.py
"""Tests for MCP tool registry / profile loading."""

from __future__ import annotations

from context_service.mcp.tools.registry import (
    get_profile_tools,
    get_tool_description,
)


def test_accept_in_reasoning_profile() -> None:
    """accept verb is part of the reasoning profile."""
    tools = get_profile_tools("reasoning")
    assert "accept" in tools, (
        f"accept not in reasoning profile. Got: {tools}"
    )


def test_reject_in_reasoning_profile() -> None:
    """reject verb is part of the reasoning profile."""
    tools = get_profile_tools("reasoning")
    assert "reject" in tools


def test_accept_description_present() -> None:
    """accept tool has a non-empty description."""
    desc = get_tool_description("accept")
    assert desc, "accept description is empty"
    assert "ProposedBelief" in desc or "synthesized" in desc.lower()


def test_reject_description_present() -> None:
    """reject tool has a non-empty description."""
    desc = get_tool_description("reject")
    assert desc, "reject description is empty"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/tools/test_registry.py -v
```

Expected: All 4 tests FAIL (`accept` / `reject` not in profile, descriptions empty).

- [ ] **Step 3: Add yaml entries**

Edit `src/context_service/config/mcp_tools.yaml`:

Under the `reasoning` profile list, add `accept` and `reject` (place them after `commit`):

```yaml
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
    - accept
    - reject
    - forget
```

Under the `tools:` block, add (place after `commit:` and before `forget:`):

```yaml
  accept:
    description: "Ratify a system-synthesized ProposedBelief, promoting it to an active Belief. Use when SAGE has surfaced a ProposedBelief you agree with. Optionally override the confidence on acceptance."
    maps_to: wisdom

  reject:
    description: "Reject a system-synthesized ProposedBelief with an optional reason. The proposal is tombstoned (status='rejected') but preserved for audit. Use when SAGE has surfaced a ProposedBelief you do not endorse."
    maps_to: wisdom
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/mcp/tools/test_registry.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml tests/mcp/tools/test_registry.py
git commit -m "feat(mcp): add accept/reject entries to tool config

Promotes internal accept/reject verbs to the agent-facing reasoning
profile per engagement layer 1 plan A. Underlying tool implementations
unchanged in this commit; registration wires up in the next."
```

---

## Task 2: Rename accept @mcp.tool to "accept"

**Files:**
- Modify: `src/context_service/mcp/tools/context_accept_belief.py`

**Goal:** Change the MCP-visible tool name from `context_accept_belief` to `accept`. Description updated for agent-facing semantics (the existing description leans internal).

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/tools/test_accept_agent_surface.py`:

```python
# tests/mcp/tools/test_accept_agent_surface.py
"""Agent-surface integration tests for the accept tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from context_service.mcp.tools import context_accept_belief


@pytest.mark.asyncio
async def test_accept_registers_with_agent_facing_name() -> None:
    """The accept tool registers with the name 'accept', not 'context_accept_belief'."""
    mcp = FastMCP("test")
    context_accept_belief.register(mcp)

    # FastMCP exposes the tool name via its internal registry.
    # The exact attribute depends on FastMCP version (3.3.1).
    # Tools are stored on the FastMCP server; pull the list:
    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "accept" in tool_names, f"Expected 'accept' in tools; got {tool_names}"
    assert "context_accept_belief" not in tool_names, (
        "Old name 'context_accept_belief' should no longer be registered"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/tools/test_accept_agent_surface.py -v
```

Expected: FAIL with `context_accept_belief` still being the registered name.

- [ ] **Step 3: Rename @mcp.tool and the inner function**

Edit `src/context_service/mcp/tools/context_accept_belief.py`:

Replace the `register()` function. Locate this block:

```python
    @mcp.tool(
        name="context_accept_belief",
        description=(
            "Accept a ProposedBelief and convert it to an active Belief. "
            "ProposedBeliefs are weak syntheses from the Custodian awaiting validation. "
            "Optionally override the confidence on acceptance."
        ),
    )
    async def context_accept_belief(
        belief_id: str,
        confidence: float | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
```

Replace with:

```python
    @mcp.tool(
        name="accept",
        description=(
            "Ratify a system-synthesized ProposedBelief, promoting it to an active Belief. "
            "Use when SAGE has surfaced a ProposedBelief you agree with. "
            "Optionally override the confidence on acceptance."
        ),
    )
    async def accept(
        belief_id: str,
        confidence: float | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
```

Also update the metric tag in the `finally:` block at the bottom of `register()`:

```python
            record_mcp_tool(
                "accept", (time.perf_counter() - start) * 1000, success=success
            )
```

(Was `"context_accept_belief"` — keep the metric name consistent with the agent-facing surface for cleaner telemetry on the new surface.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/mcp/tools/test_accept_agent_surface.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_accept_belief.py tests/mcp/tools/test_accept_agent_surface.py
git commit -m "feat(mcp): rename accept tool to agent-facing 'accept'

Changes the MCP-visible name from context_accept_belief to accept,
updates the description for agent consumption, and aligns the metric
tag with the new surface name."
```

---

## Task 3: Rename reject @mcp.tool to "reject"

**Files:**
- Modify: `src/context_service/mcp/tools/context_reject_belief.py`

**Goal:** Mirror of Task 2 for `reject`.

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/tools/test_reject_agent_surface.py`:

```python
# tests/mcp/tools/test_reject_agent_surface.py
"""Agent-surface integration tests for the reject tool."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from context_service.mcp.tools import context_reject_belief


@pytest.mark.asyncio
async def test_reject_registers_with_agent_facing_name() -> None:
    """The reject tool registers with the name 'reject', not 'context_reject_belief'."""
    mcp = FastMCP("test")
    context_reject_belief.register(mcp)

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "reject" in tool_names, f"Expected 'reject' in tools; got {tool_names}"
    assert "context_reject_belief" not in tool_names, (
        "Old name 'context_reject_belief' should no longer be registered"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/mcp/tools/test_reject_agent_surface.py -v
```

Expected: FAIL.

- [ ] **Step 3: Rename @mcp.tool and the inner function**

Edit `src/context_service/mcp/tools/context_reject_belief.py`:

Locate:

```python
    @mcp.tool(
        name="context_reject_belief",
        description=(
            "Reject a ProposedBelief with an optional reason. "
            "The proposal is tombstoned (status='rejected') but preserved for audit."
        ),
    )
    async def context_reject_belief(
        belief_id: str,
        reason: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
```

Replace with:

```python
    @mcp.tool(
        name="reject",
        description=(
            "Reject a system-synthesized ProposedBelief with an optional reason. "
            "The proposal is tombstoned (status='rejected') but preserved for audit. "
            "Use when SAGE has surfaced a ProposedBelief you do not endorse."
        ),
    )
    async def reject(
        belief_id: str,
        reason: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
```

Update the metric tag in `finally:`:

```python
            record_mcp_tool(
                "reject", (time.perf_counter() - start) * 1000, success=success
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/mcp/tools/test_reject_agent_surface.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_reject_belief.py tests/mcp/tools/test_reject_agent_surface.py
git commit -m "feat(mcp): rename reject tool to agent-facing 'reject'

Mirrors the accept rename: MCP-visible name becomes reject, description
updated for agent consumption, metric tag aligned with new surface."
```

---

## Task 4: Wire accept / reject into the profile registry

**Files:**
- Modify: `src/context_service/mcp/tools/registry.py`

**Goal:** Make `register_profile_tools` actually register `accept` and `reject` when they appear in a profile. Currently the `tool_registers` dict has no entry for them, so they would silently log `mcp_tool_not_found`.

- [ ] **Step 1: Write the failing test**

Add to `tests/mcp/tools/test_registry.py`:

```python
import pytest
from fastmcp import FastMCP

from context_service.mcp.tools.registry import register_profile_tools


@pytest.mark.asyncio
async def test_reasoning_profile_registers_accept_and_reject() -> None:
    """Loading the reasoning profile registers both accept and reject."""
    mcp = FastMCP("test")
    register_profile_tools(mcp, profile="reasoning")

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "accept" in tool_names
    assert "reject" in tool_names


@pytest.mark.asyncio
async def test_standard_profile_does_not_include_accept_reject() -> None:
    """The standard profile is leaner and does not include accept/reject."""
    mcp = FastMCP("test")
    register_profile_tools(mcp, profile="standard")

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "accept" not in tool_names
    assert "reject" not in tool_names
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/mcp/tools/test_registry.py::test_reasoning_profile_registers_accept_and_reject -v
```

Expected: FAIL (tool registered? No — registry has no entry for accept).

- [ ] **Step 3: Add accept / reject to the tool_registers dict**

Edit `src/context_service/mcp/tools/registry.py`. Locate `register_profile_tools`. Update the imports inside the function:

```python
    from context_service.mcp.tools import (
        believe,
        commit,
        context_accept_belief,
        context_reject_belief,
        forget,
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
```

Update the `tool_registers` dict:

```python
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
        "accept": context_accept_belief.register,
        "reject": context_reject_belief.register,
        "patterns": patterns.register,
        "forget": forget.register,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/mcp/tools/test_registry.py -v
```

Expected: All tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/registry.py tests/mcp/tools/test_registry.py
git commit -m "feat(mcp): register accept/reject via profile registry

Adds the two verbs to register_profile_tools so the reasoning profile
emits them at MCP-server startup. Standard profile remains lean."
```

---

## Task 5: Remove accept / reject from internal-only registration

**Files:**
- Modify: `src/context_service/mcp/tools/__init__.py`

**Goal:** Now that accept / reject are agent-facing, drop their imports and calls from `register_internal_tools`. Note: `register_internal_tools` has no callers in production code or tests today (grep `register_internal_tools` across the repo confirms this), so removal is dead-code cleanup, not behavior change.

- [ ] **Step 1: Confirm `register_internal_tools` has no callers**

```bash
grep -rn "register_internal_tools" src/ tests/ --include="*.py" | grep -v "def register_internal_tools"
```

Expected: zero hits. If hits surface, investigate before proceeding — the callers would need their own update.

- [ ] **Step 2: Read current state**

```bash
grep -n "context_accept_belief\|context_reject_belief\|register_internal_tools" src/context_service/mcp/tools/__init__.py
```

You should see:
- Near the top: `from context_service.mcp.tools.context_accept_belief import register as register_accept_belief`
- Same for reject_belief
- Both `register_accept_belief(mcp)` and `register_reject_belief(mcp)` calls inside `register_internal_tools`.

- [ ] **Step 3: Write the failing test**

Add to `tests/mcp/tools/test_registry.py`:

```python
def test_register_internal_tools_does_not_import_accept_reject_registers() -> None:
    """After Plan A, the internal-only registration path no longer references accept/reject.

    They are agent-facing via the reasoning profile; keeping them registered both ways
    is dead code (and would cause double-registration if any future caller invoked both
    paths against the same FastMCP instance).
    """
    import inspect

    from context_service.mcp.tools import __init__ as tools_init

    src = inspect.getsource(tools_init)
    assert "register_accept_belief" not in src, (
        "register_accept_belief is no longer needed in tools/__init__.py"
    )
    assert "register_reject_belief" not in src, (
        "register_reject_belief is no longer needed in tools/__init__.py"
    )
```

- [ ] **Step 4: Run test to verify failure**

```bash
uv run pytest tests/mcp/tools/test_registry.py::test_register_internal_tools_does_not_import_accept_reject_registers -v
```

Expected: FAIL (those imports / aliases still exist in `__init__.py`).

- [ ] **Step 5: Remove the dead imports and calls**

Edit `src/context_service/mcp/tools/__init__.py`. Remove these two import lines:

```python
# DELETE these two lines:
from context_service.mcp.tools.context_accept_belief import register as register_accept_belief
from context_service.mcp.tools.context_reject_belief import register as register_reject_belief
```

Inside `register_internal_tools`, remove the two calls:

```python
# DELETE:
    register_accept_belief(mcp)
    register_reject_belief(mcp)
```

Keep the other internal tools (`register_admin`, `register_belief_state`) intact.

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest tests/mcp/tools/test_registry.py::test_register_internal_tools_does_not_import_accept_reject_registers -v
```

Expected: PASS.

- [ ] **Step 7: Run the full registry test file**

```bash
uv run pytest tests/mcp/tools/test_registry.py -v
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/context_service/mcp/tools/__init__.py tests/mcp/tools/test_registry.py
git commit -m "refactor(mcp): drop dead accept/reject internal-only registration

accept and reject are agent-facing via the reasoning profile after Plan
A's verb promotion. Their internal-only register aliases in
tools/__init__.py had no callers, so this is dead-code cleanup."
```

---

## Task 6: Rebuild the protocol-level integration test against the current surface

**Files:**
- Modify: `tests/integration/test_mcp_protocol.py`

**Goal:** The existing `EXPECTED_TOOLS` set in this file is stale — it still references the legacy `context_*` names from before the v2.7 tool-surface redesign (`context_store`, `context_recall`, `context_link`, `context_belief_state`, `context_update_belief`, `context_crystallize`, `context_accept_belief`, `context_reject_belief`). The current `register_all` produces the intent verbs (`remember`, `learn`, `believe`, `recall`, `link`, etc.). Plan A's promotion adds `accept` and `reject` on top. Rebuild the set to match reality.

**Profile gotcha:** `register_all`'s Python signature defaults to `"standard"`, but `mcp_tools.yaml` sets `default_profile: reasoning`. The existing test calls `register_all(mcp)` with no profile, so it uses the Python default (`"standard"`). For deterministic assertions, pass profile explicitly.

- [ ] **Step 1: Read current state**

```bash
sed -n '14,60p' tests/integration/test_mcp_protocol.py
```

Confirm the `EXPECTED_TOOLS` set contains the legacy names and that `register_all(mcp)` is called without a profile argument.

- [ ] **Step 2: Run the file as-is**

```bash
uv run pytest tests/integration/test_mcp_protocol.py -v
```

If `test_all_tools_registered` and `test_create_mcp_server_tool_count` are FAILING (because `EXPECTED_TOOLS` is stale), good — that confirms the rebuild is needed. If they happen to be PASSING, investigate before continuing; something is masking the v2.7 rename.

- [ ] **Step 3: Rebuild `EXPECTED_TOOLS` and parameterize by profile**

Replace the `EXPECTED_TOOLS` constant and both test methods that consume it. Edit `tests/integration/test_mcp_protocol.py`:

Replace the top-of-file constant:

```python
EXPECTED_STANDARD_TOOLS = {
    "remember",
    "learn",
    "believe",
    "recall",
    "trace",
    "link",
    "patterns",
}

EXPECTED_REASONING_TOOLS = EXPECTED_STANDARD_TOOLS | {
    "reason",
    "reflect",
    "hypothesize",
    "revise",
    "commit",
    "accept",
    "reject",
    "forget",
}
```

Replace `test_all_tools_registered`:

```python
    @pytest.mark.asyncio
    async def test_standard_profile_tools_registered(self) -> None:
        mcp = FastMCP("test-registration")
        register_all(mcp, profile="standard")
        tools = await mcp.list_tools()
        registered = {t.name for t in tools}
        assert registered == EXPECTED_STANDARD_TOOLS

    @pytest.mark.asyncio
    async def test_reasoning_profile_tools_registered(self) -> None:
        mcp = FastMCP("test-registration")
        register_all(mcp, profile="reasoning")
        tools = await mcp.list_tools()
        registered = {t.name for t in tools}
        assert registered == EXPECTED_REASONING_TOOLS
```

Replace `test_create_mcp_server_tool_count`. The `create_mcp_server` function uses the configured default profile (likely `reasoning` from yaml — verify by reading `mcp/server.py`). If `create_mcp_server` defaults to `reasoning`:

```python
    @pytest.mark.asyncio
    async def test_create_mcp_server_tool_count(self) -> None:
        server = create_mcp_server()
        tools = await server.list_tools()
        registered = {t.name for t in tools}
        assert registered == EXPECTED_REASONING_TOOLS
```

If `create_mcp_server` accepts a profile argument, pass `"reasoning"` explicitly. If it defaults to `standard`, swap the expected set.

Remove the now-orphan `EXPECTED_TOOLS` constant.

- [ ] **Step 4: Run the file**

```bash
uv run pytest tests/integration/test_mcp_protocol.py -v
```

Expected: all tests PASS. If any test fails because the actual registered set differs from your `EXPECTED_*` constants, investigate — either the constants are wrong (fix them) or there is a genuine surface mismatch (which is more interesting and needs root-cause analysis).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_mcp_protocol.py
git commit -m "test: rebuild EXPECTED_TOOLS against current MCP surface

The legacy EXPECTED_TOOLS set referenced pre-v2.7-redesign context_*
names that no longer exist. Replaces it with EXPECTED_STANDARD_TOOLS
and EXPECTED_REASONING_TOOLS matching the current intent verbs plus
Plan A's promoted accept and reject."
```

---

## Task 7: Behavioral test — agent surface acceptance flow

**Files:**
- Modify: `tests/mcp/tools/test_accept_agent_surface.py`

**Goal:** Beyond name-registration tests, prove the tool actually accepts a ProposedBelief end-to-end. This catches regressions where the rename broke the wiring to the underlying graph query.

- [ ] **Step 1: Add an end-to-end test**

Append to `tests/mcp/tools/test_accept_agent_surface.py`:

```python
import uuid
from unittest.mock import AsyncMock, patch

from context_service.mcp.tools.context_accept_belief import _context_accept_belief


@pytest.mark.asyncio
async def test_accept_returns_created_belief_id_on_success() -> None:
    """Calling _context_accept_belief with a valid proposed_belief_id returns the new belief_id."""
    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())
    expected_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"belief_id": expected_belief_id}]

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_accept_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
        )

    assert result["status"] == "accepted"
    assert result["proposed_belief_id"] == proposed_belief_id
    assert result["created_belief_id"] == expected_belief_id


@pytest.mark.asyncio
async def test_accept_returns_not_found_when_no_rows() -> None:
    """If the underlying query returns no rows, the tool returns the not_found error envelope."""
    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_accept_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"
```

- [ ] **Step 2: Run the file**

```bash
uv run pytest tests/mcp/tools/test_accept_agent_surface.py -v
```

Expected: All tests PASS. The underlying logic was not touched, so behavior should be intact. If a test FAILS, that means the rename inadvertently broke the wiring — investigate before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/mcp/tools/test_accept_agent_surface.py
git commit -m "test: end-to-end behavior coverage for accept

Confirms the accept rename did not break the path to the underlying
graph query."
```

---

## Task 8: Behavioral test — agent surface rejection flow

**Files:**
- Modify: `tests/mcp/tools/test_reject_agent_surface.py`

**Goal:** Mirror of Task 7 for reject.

- [ ] **Step 1: Add the end-to-end test**

Append to `tests/mcp/tools/test_reject_agent_surface.py`:

```python
import uuid
from unittest.mock import AsyncMock, patch

from context_service.mcp.tools.context_reject_belief import _context_reject_belief


@pytest.mark.asyncio
async def test_reject_returns_rejected_status_on_success() -> None:
    """Calling _context_reject_belief with a valid proposed_belief_id returns rejected status."""
    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"id": proposed_belief_id}]

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_reject_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
            reason="superseded by direct evidence",
        )

    assert result["status"] == "rejected"
    assert result["proposed_belief_id"] == proposed_belief_id
    assert result["reason"] == "superseded by direct evidence"


@pytest.mark.asyncio
async def test_reject_returns_not_found_when_no_rows() -> None:
    """If the underlying query returns no rows, the tool returns the not_found error envelope."""
    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_reject_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"
```

- [ ] **Step 2: Run the file**

```bash
uv run pytest tests/mcp/tools/test_reject_agent_surface.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/mcp/tools/test_reject_agent_surface.py
git commit -m "test: end-to-end behavior coverage for reject

Mirrors Task 7's coverage for the reject verb."
```

---

## Task 9: Full sweep — lint, typecheck, full test suite

**Goal:** Confirm Plan A is green and ready to merge.

- [ ] **Step 1: Lint + typecheck**

```bash
just check
```

Expected: clean (no new lint or mypy failures introduced).

- [ ] **Step 2: Full test suite**

```bash
just test
```

Expected: All tests pass. Compare against the Task 0 baseline — any new failures should be investigated and resolved before declaring Plan A done.

- [ ] **Step 3: Verify the agent-facing surface end-to-end (manual smoke test)**

Start the server locally OR against the dev environment. Then in any MCP client (Claude Code, Cursor) call the `mcp__engrammic__patterns` tool with `action=list` and confirm the response mentions `accept` and `reject` in the reasoning profile guidance (if `patterns` references them — otherwise check tool discovery via the client's MCP UI).

Alternatively, write a quick FastMCP client snippet that lists tools and asserts both `accept` and `reject` are exposed. (Acceptable to skip if Tasks 1-8 are green; the integration test in Task 4 covers this at the protocol level.)

- [ ] **Step 4: Commit the brainstorm-doc update**

Edit `context/brainstorm/2026-05-25-engagement-surface-layers.md`. Under the verb-shape resolution section (decision 3, "Resolution"), add an inline note that Plan A has shipped:

```markdown
> Plan A (verb promotion) shipped 2026-MM-DD via `context/plans/2026-05-25-engagement-plan-a-verb-promotion.md`. accept and reject are live in the reasoning profile.
```

Replace `MM-DD` with the actual ship date.

```bash
git add context/brainstorm/2026-05-25-engagement-surface-layers.md
git commit -m "docs: mark Plan A (verb promotion) as shipped in brainstorm"
```

---

## Task 10: Update non-historical spec docs that reference the old names

**Files:**
- Modify: `context/specs/mcp-tool-surface.md`
- Modify: `context/specs/2026-05-15-mcp-tool-surface-redesign.md`
- Modify: `context/architecture/sage-system.md`
- Modify: `context/qa/scenarios/003-belief-accept-reject.md`

**Goal:** The above docs are reference material that will mislead readers if left with the legacy `context_accept_belief` / `context_reject_belief` names. Devlogs (`context/devlog/*`) are historical and left alone.

- [ ] **Step 1: Locate every occurrence**

```bash
grep -rn "context_accept_belief\|context_reject_belief" context/specs/ context/architecture/ context/qa/ 2>/dev/null
```

Confirm the file list matches the four above. If new occurrences have appeared since plan-write time, include them.

- [ ] **Step 2: Replace each occurrence**

For each file in the grep output, replace `context_accept_belief` with `accept` and `context_reject_belief` with `reject`, preserving surrounding wording. If a sentence reads "The internal-only `context_accept_belief` tool..." update it to "The agent-facing `accept` tool..." or similar — match the local sentence intent.

For `context/qa/scenarios/003-belief-accept-reject.md`, also update any sample MCP calls or response payloads to use the new tool names.

- [ ] **Step 3: Verify nothing slipped**

```bash
grep -rn "context_accept_belief\|context_reject_belief" context/specs/ context/architecture/ context/qa/ 2>/dev/null
```

Expected: zero hits.

- [ ] **Step 4: Commit**

```bash
git add context/specs/ context/architecture/ context/qa/
git commit -m "docs: update spec references to agent-facing accept/reject names

Tracks the Plan A verb promotion in spec, architecture, and QA scenario
docs. Devlogs are left as historical record."
```

(`context/plans/README.md` is already updated separately with the Plan A entry; no further action there.)

---

## Done criteria

Plan A is complete when:

- [ ] `mcp_tools.yaml` lists `accept` and `reject` in the `reasoning` profile with descriptions.
- [ ] `accept` and `reject` are MCP-visible names; old names (`context_accept_belief`, `context_reject_belief`) are gone from the agent surface.
- [ ] The two verbs are registered via the profile registry, not via `register_internal_tools`.
- [ ] All pre-existing tests still pass; new tests (`test_registry.py`, `test_accept_agent_surface.py`, `test_reject_agent_surface.py`) pass.
- [ ] `tests/integration/test_mcp_protocol.py` updated to the rebuilt `EXPECTED_STANDARD_TOOLS` / `EXPECTED_REASONING_TOOLS` sets and passes.
- [ ] `just check` and `just test` are green.
- [ ] Brainstorm doc reflects Plan A as shipped (Task 9 step 4).
- [ ] Spec docs (`context/specs/`, `context/architecture/`, `context/qa/`) carry the new names (Task 10).
- [ ] `context/plans/README.md` Active plans row is present (already added pre-execution; flip to Shipped section after merge).
- [ ] All commits follow the no-Co-Authored-By preference.

---

## What ships after Plan A

- **Plan B:** SAGE prerequisites — synthesizer aggression tuning, validator standup, Contradiction / StaleCommitment marker writes, precomputed marker index.
- **Plan C:** Engagement detection + soft surfacing on recall. Introduces `dismiss(marker_id, reason)`, extends `revise` to accept `marker_id`, adds Redis touch-counter primitive keyed by `auth.session_id`.
- **Plan D:** Hard checkpoint + soft-to-hard escalation. Recall-scoped block when threshold trips.
- **Plan E:** Skills + installer config — `engrammic-engage` skill, updates to `engrammic-recall` / `engrammic-onboarding`, ship `x-session-id` in installer-distributed MCP configs, AGENTS.md guidance block.

These are independent of Plan A and can be sequenced based on priority. Plan A is shippable today.
