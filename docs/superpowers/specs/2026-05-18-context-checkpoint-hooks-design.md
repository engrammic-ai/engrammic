# Context Checkpoint Hooks Design

Research spike for dynamic node tracking and context reload via Claude Code hooks.

## Problem

When an LLM agent's context window compacts or clears, accumulated working knowledge is lost or compressed into lossy summaries. If the agent has been storing structured context to Engrammic, those node IDs could serve as durable pointers that survive context resets and enable coherent rehydration.

## Hypothesis

An agent can meaningfully continue work after a context reset if it can rehydrate from structured Engrammic nodes instead of raw conversation history.

## Approach

Use Claude Code hooks to:
1. Track which Engrammic nodes are created/accessed during a session
2. Checkpoint node IDs before compaction
3. Offer to restore context on session start

This is a research spike to validate whether the core mechanic works before designing a full protocol.

## Architecture

Three hooks working together:

### 1. engrammic-track (PostToolUse)

Fires after `remember`, `learn`, or `recall` MCP calls. Extracts node IDs from responses and accumulates them in a session state file.

**Trigger:** `mcp__engrammic__remember|mcp__engrammic__learn|mcp__engrammic__recall`

**Input (stdin):**
```json
{
  "session_id": "abc123",
  "cwd": "/path/to/project",
  "tool_name": "mcp__engrammic__remember",
  "tool_input": { "content": "...", "tags": [...] },
  "tool_response": "{ \"node_id\": \"mem_abc123\", ... }"
}
```

**Behavior:**
- Parse `tool_response` JSON to extract node ID
- Append to checkpoint state file at `~/.engrammic/checkpoints/{project_hash}.json`
- Exit 0 (silent success)

### 2. engrammic-checkpoint (PreCompact)

Fires before context compaction. Finalizes the checkpoint with a summary.

**Matcher:** `manual|auto` (fires on both `/compact` and automatic compaction)

**Input (stdin):**
```json
{
  "session_id": "abc123",
  "cwd": "/path/to/project",
  "hook_event_name": "PreCompact"
}
```

**Behavior:**
- Read accumulated node IDs from state file
- Call Engrammic to generate a summary of the working context
- Write final checkpoint with summary + timestamp
- Exit 0 (silent success)

### 3. engrammic-restore (SessionStart)

Fires at session start. Checks for existing checkpoint and informs the agent.

**Matcher:** `startup|resume|clear|compact` (fires on session start and after compaction/clear)

**Input (stdin):**
```json
{
  "session_id": "abc123",
  "cwd": "/path/to/project",
  "hook_event_name": "SessionStart",
  "session_resume_reason": "startup"
}
```

**Output (stdout on exit 0):**
```json
{
  "hookSpecificOutput": {
    "additionalContext": "Previous session checkpoint found for this project.\nSummary: \"Working on OAuth implementation\"\nNode IDs: [mem_abc123, mem_def456]\nIf user wants to continue, call recall with these IDs."
  }
}
```

**Behavior:**
- Check if checkpoint exists for current project (hash of `cwd`)
- If found, output `additionalContext` JSON with node IDs and summary
- If not found, exit 0 with no output
- Agent asks user if they want to restore; user confirms or declines

## State File

Location: `~/.engrammic/checkpoints/{project_hash}.json`

```json
{
  "session_id": "abc123",
  "project_dir": "/path/to/project",
  "checkpointed_at": "2026-05-18T20:30:00Z",
  "node_ids": [
    "mem_abc123",
    "mem_def456"
  ],
  "checkpoint_summary": "Working on OAuth implementation, identified 3 files to modify"
}
```

Keyed by project hash to avoid collisions between projects.

## Hook Configuration

In `~/.claude/settings.json` or `~/.claude/settings.local.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__engrammic__remember|mcp__engrammic__learn|mcp__engrammic__recall",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/engrammic-track.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "manual|auto",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/engrammic-checkpoint.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/engrammic-restore.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Hooks live in `~/.claude/hooks/` to work across projects.

## Engrammic Communication

Hooks call the MCP endpoint directly via HTTP:

```bash
curl -X POST "${ENGRAMMIC_MCP_URL:-http://localhost:8000/mcp/}" \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "recall", "arguments": {...}}}'
```

Endpoint URL is configurable via `ENGRAMMIC_MCP_URL` environment variable. Defaults to localhost for local development.

## Authentication

Hooks need credentials to call Engrammic. Configuration via `~/.engrammic/config.json`:

```json
{
  "mcp_url": "http://strata-finance:8000/mcp/",
  "silo_id": "user-silo-id",
  "api_key": "optional-api-key-if-required"
}
```

Hooks read this file on each invocation. For the research spike, we assume:
- Local development with no auth required, OR
- Pre-configured credentials in the config file

Production auth (OAuth, WorkOS) is out of scope for this spike.

## Restore Flow

1. SessionStart hook detects checkpoint exists
2. Hook outputs additionalContext:
   ```
   Previous session checkpoint found for this project.
   Summary: "Working on OAuth implementation, identified 3 files to modify"
   Node IDs: [mem_abc123, mem_def456]
   If user wants to continue from there, call recall with these IDs.
   ```
3. Agent sees context, asks user: "I found context from a previous session. Want me to restore it?"
4. User confirms or declines
5. If confirmed, agent calls `recall` with the node IDs

This keeps restore opt-in and conversational.

## Validation

After implementation:
1. Use hooks in a real Claude Code session
2. Work on a task, accumulate context via Engrammic
3. Trigger `/compact` to force compaction
4. Verify checkpoint was created
5. Start new session or `/clear`
6. Verify restore offer appears
7. Accept restore, verify agent continues coherently

## Success Criteria

- Agent can continue a task after context reset without repeating work
- Restored context feels coherent, not disjointed
- No manual intervention required beyond confirming restore

## Out of Scope

- Automatic restore (always opt-in for now)
- Multi-project checkpoint management
- Checkpoint pruning/expiry
- LLM-agnostic protocol design (research spike is Claude Code specific)

## Future Considerations

If this works:
- Design a formal protocol that other harnesses could implement
- Consider "Concepts" as a higher-level unit for checkpoint/restore
- Explore automatic relevance tracking vs explicit marking
