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

**Behavior:**
- Parse tool result from stdin
- Extract node ID from response
- Append to checkpoint state file

### 2. engrammic-checkpoint (PreCompact)

Fires before context compaction. Finalizes the checkpoint with a summary.

**Behavior:**
- Read accumulated node IDs from state file
- Call Engrammic to generate a summary of the working context
- Write final checkpoint with summary + timestamp

### 3. engrammic-restore (SessionStart)

Fires at session start. Checks for existing checkpoint and informs the agent.

**Behavior:**
- Check if checkpoint exists for current project
- If found, output `additionalContext` JSON with:
  - Node IDs
  - Checkpoint summary
  - Instruction for agent to offer restore to user
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
