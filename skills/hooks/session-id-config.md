# Session ID Configuration

The `x-session-id` header scopes touch tracking and engagement escalation to a
single conversation or agent session. Without it, touch counts accumulate at the
silo level across all sessions.

## What it does

Each time an agent calls `recall`, the server records a touch on the accessed
nodes for the given session. After 3 touches without resolution, engagement
escalates from soft to hard mode. Supplying a stable, unique session ID means
hard mode triggers per-session rather than accumulating across unrelated runs.

## How session ID is resolved

The server resolves session ID in priority order:

1. `x-session-id` HTTP header (explicit, highest priority)
2. SHA-256 hash of the Authorization token (stable fallback for OAuth/API key sessions)
3. `None` (dev mode without auth; touch tracking is silo-scoped only)

## Configuration patterns

### SSE transport (Claude Code native, `type: "sse"`)

Claude Code's SSE MCP config does not currently support per-request header
injection. The connection is established once when Claude Code starts, so any
session ID configured here is stable for the lifetime of that Claude Code
process -- which aligns with treating one Claude Code launch as one session.

```json
{
  "mcpServers": {
    "engrammic": {
      "type": "sse",
      "url": "https://beta.engrammic.ai/mcp/",
      "headers": {
        "x-session-id": "claude-code-<your-machine-id>"
      }
    }
  }
}
```

Note: `headers` support in SSE MCP configs depends on your harness version.
If unsupported, the server falls back to the token hash, which is stable
per-credential and acceptable for most use cases.

### stdio transport (engrammic-mcp serve)

When running the proxy server via `uvx engrammic-mcp serve`, set the
environment variable before launching. Claude Code's stdio MCP config supports
`env` blocks:

```json
{
  "mcpServers": {
    "engrammic": {
      "command": "uvx",
      "args": ["engrammic-mcp", "serve"],
      "env": {
        "ENGRAMMIC_SESSION_ID": "claude-code-20260526"
      }
    }
  }
}
```

The proxy server reads `ENGRAMMIC_SESSION_ID` and forwards it as the
`x-session-id` header on every request. This is the recommended approach
for stdio deployments.

### Generating a unique session ID

A good session ID is stable within a session but distinct across sessions.
Options:

```bash
# Static per-machine (one session per Claude Code instance)
"claude-code-$(hostname)"

# Date-scoped (one session per day per machine)
"claude-code-$(hostname)-$(date +%Y%m%d)"

# Truly unique per launch (use in a wrapper script)
"claude-code-$(uuidgen)"
```

For most users, a machine-scoped or date-scoped ID is sufficient. Truly unique
IDs per launch reset touch counts each time, which prevents hard mode from
persisting across restarts.

## Verification

After configuring, call `tick()` from the agent surface. If session tracking is
active, the engagement response will reflect per-session state rather than
silo-wide accumulation. You can confirm via `context_admin(action="usage")`.
