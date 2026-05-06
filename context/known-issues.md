# Known Issues

## Claude Code Subagents Cannot Use MCP

**Status:** Open (upstream)
**Date:** 2026-05-06
**Affects:** Any workflow spawning subagents that need context_recall/context_store

Claude Code subagents do not inherit MCP server connections from the parent agent. This is a platform limitation, not a Delta Prime bug.

**GitHub Issues:**
- [#5465](https://github.com/anthropics/claude-code/issues/5465) - Subagents fail to inherit permissions in MCP server mode
- [#13605](https://github.com/anthropics/claude-code/issues/13605) - Custom plugin subagents cannot access MCP tools
- [#6825](https://github.com/anthropics/claude-code/issues/6825) - System prompt and memory inheritance not configurable
- [#40104](https://github.com/anthropics/claude-code/issues/40104) - context:fork subagents inherit all tool definitions causing prompt bloat

**Workaround:**
1. Main agent calls `context_recall` before spawning subagent
2. Pass recalled context explicitly in the subagent prompt
3. Subagent returns results; main agent calls `context_store` if needed

**Mitigation added:** `UserPromptSubmit` hook in settings.json auto-recalls on every user message, ensuring context is in the main agent's window before dispatch.

**Better solution:** Use Agent Teams (teammates) instead of subagents. Teammates inherit MCP server configuration from project settings, so Delta Prime tools are available to all team members. Requires `teammateMode: "auto"` in settings (already configured).

## HTTP Transport for MCP (Already Available)

MCP is mounted at `/mcp/*` with SSE transport via FastMCP:
```python
mcp_app = mcp_server.http_app(path="/", transport="sse")
```

Endpoint: `http://localhost:8000/mcp` (or production URL)

This means any agent process can connect independently without relying on stdio inheritance. To use from Claude Code, configure the MCP server with `url` instead of `command` in `.claude/mcp-servers.json`.
