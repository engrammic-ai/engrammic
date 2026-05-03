"""Architecture boundary: MemgraphClient direct-import guard.

Prevents regression where modules that should depend on the HyperGraphStore
protocol (engine/protocols.py) instead import MemgraphClient directly.

Allowed locations for direct MemgraphClient imports:
  - src/context_service/engine/       adapter implementations live here
  - src/context_service/stores/       client definitions
  - src/context_service/db/           query utilities (temporary: union types)
  - src/context_service/pipelines/    wraps client in store (temporary bridge)
  - tests/                            test code may import anything

All other src/ paths must go through engine/protocols.HyperGraphStore.

Known pre-existing violations are listed in _KNOWN_VIOLATIONS below.
They are tracked for migration; adding a new one will fail CI immediately.
Remove an entry from _KNOWN_VIOLATIONS once the module is migrated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"

_ALLOWED_PREFIXES = (
    "src/context_service/engine/",
    "src/context_service/stores/",
    "src/context_service/db/",
    "src/context_service/pipelines/",
)

# mcp/server.py imports MemgraphClient only under TYPE_CHECKING as a cast
# bridge (noted in the file). That import never runs at runtime, but grep
# still finds it, so we explicitly allowlist it until the HyperGraphStore
# implementation is complete and the cast is removed.
#
# The remaining entries are pre-existing violations that predate this boundary
# check. They are being migrated to HyperGraphStore; tracked here so that no
# new violations can be introduced silently. Do not add new entries — fix the
# code instead.
_KNOWN_VIOLATIONS = {
    # TYPE_CHECKING cast bridge — runtime-safe, removable once HyperGraphStore
    # implementation is complete.
    "src/context_service/mcp/server.py",
    # api/app.py is the composition root — it constructs the concrete
    # MemgraphClient for lifecycle management (close(), bootstrap schema).
    # This is intentional and not a violation of the boundary rule.
    "src/context_service/api/app.py",
}


def test_no_direct_memgraph_client_imports_outside_boundary() -> None:
    """Fail if MemgraphClient is imported outside the allowed module set."""
    result = subprocess.run(
        ["grep", "-r", "--include=*.py", "-l", "MemgraphClient", "src/"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    # grep returns exit code 1 when no matches found, which is fine.
    matching_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]

    violations: list[str] = []
    for rel_path in matching_files:
        if any(rel_path.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            continue
        if rel_path in _KNOWN_VIOLATIONS:
            continue
        violations.append(rel_path)

    if violations:
        joined = "\n  ".join(violations)
        raise AssertionError(
            "Direct MemgraphClient imports found outside the allowed boundary.\n"
            "These modules must depend on engine/protocols.HyperGraphStore instead:\n"
            f"  {joined}\n\n"
            "Allowed locations: engine/, stores/, db/, pipelines/, tests/.\n"
            "See the task description in context/plans/ for migration guidance."
        )
