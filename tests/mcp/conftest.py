"""Pre-import MCP tool modules so mock.patch targets are resolvable."""
from __future__ import annotations

import context_service.mcp.tools.context_graph  # noqa: F401
import context_service.mcp.tools.context_link  # noqa: F401
import context_service.mcp.tools.context_query  # noqa: F401
