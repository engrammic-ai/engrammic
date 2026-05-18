# Context Checkpoint Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate whether Engrammic nodes can serve as durable context that survives Claude Code compaction/clears

**Architecture:** Three Claude Code hooks (PostToolUse, PreCompact, SessionStart) track node IDs, checkpoint before compaction, and offer restore on session start. Hooks call Engrammic via HTTP.

**Tech Stack:** Bash scripts, jq, curl, Claude Code hooks API

**Spec:** [docs/superpowers/specs/2026-05-18-context-checkpoint-hooks-design.md](../../docs/superpowers/specs/2026-05-18-context-checkpoint-hooks-design.md)

**Branch:** `spike/context-checkpoint-hooks`

---

## File Structure

```
~/.claude/hooks/
  engrammic-track.sh      # PostToolUse: track node IDs
  engrammic-checkpoint.sh # PreCompact: finalize checkpoint
  engrammic-restore.sh    # SessionStart: offer restore

~/.engrammic/
  config.json             # MCP URL and auth config
  checkpoints/            # Per-project checkpoint files
    {project_hash}.json
```

---

## Task 1: Create config structure

**Files:**
- Create: `~/.engrammic/config.json`
- Create: `~/.engrammic/checkpoints/.gitkeep`

- [ ] **Step 1: Create engrammic config directory**

```bash
mkdir -p ~/.engrammic/checkpoints
```

- [ ] **Step 2: Create config file**

```bash
cat > ~/.engrammic/config.json << 'EOF'
{
  "mcp_url": "http://strata-finance:8000/mcp/",
  "silo_id": null
}
EOF
```

- [ ] **Step 3: Verify structure**

```bash
ls -la ~/.engrammic/
```

Expected: `config.json` and `checkpoints/` directory

- [ ] **Step 4: Commit config template to dotfiles (optional)**

If you track dotfiles, commit the structure. Otherwise skip.

---

## Task 2: Implement engrammic-track hook

**Files:**
- Create: `~/.claude/hooks/engrammic-track.sh`

- [ ] **Step 1: Create the hook script**

```bash
cat > ~/.claude/hooks/engrammic-track.sh << 'HOOKEOF'
#!/usr/bin/env bash
set -euo pipefail

# PostToolUse hook: track Engrammic node IDs from remember/learn/recall calls
# Appends node IDs to checkpoint state file for later use by PreCompact

# Read stdin with timeout (Claude Code sends JSON)
INPUT=$(timeout 3 cat || echo '{}')

# Extract fields
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')
TOOL_RESPONSE=$(echo "$INPUT" | jq -r '.tool_response // ""')

# Exit silently if no cwd
[[ -z "$CWD" ]] && exit 0

# Generate project hash from cwd
PROJECT_HASH=$(echo -n "$CWD" | sha256sum | cut -c1-16)
CHECKPOINT_FILE="$HOME/.engrammic/checkpoints/${PROJECT_HASH}.json"

# Try to extract node_id from tool response
NODE_ID=$(echo "$TOOL_RESPONSE" | jq -r '.node_id // .id // empty' 2>/dev/null || echo "")

# Exit if no node ID found
[[ -z "$NODE_ID" ]] && exit 0

# Initialize checkpoint file if it doesn't exist
if [[ ! -f "$CHECKPOINT_FILE" ]]; then
    cat > "$CHECKPOINT_FILE" << INITEOF
{
  "project_dir": "$CWD",
  "node_ids": [],
  "created_at": "$(date -Iseconds)"
}
INITEOF
fi

# Append node_id if not already present
EXISTING=$(jq -r ".node_ids | index(\"$NODE_ID\")" "$CHECKPOINT_FILE")
if [[ "$EXISTING" == "null" ]]; then
    TMP=$(mktemp)
    jq --arg id "$NODE_ID" '.node_ids += [$id]' "$CHECKPOINT_FILE" > "$TMP"
    mv "$TMP" "$CHECKPOINT_FILE"
fi

exit 0
HOOKEOF
chmod +x ~/.claude/hooks/engrammic-track.sh
```

- [ ] **Step 2: Test the hook manually**

```bash
echo '{"cwd": "/tmp/test-project", "tool_response": "{\"node_id\": \"mem_test123\"}"}' | ~/.claude/hooks/engrammic-track.sh
cat ~/.engrammic/checkpoints/$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16).json
```

Expected: JSON with `node_ids: ["mem_test123"]`

- [ ] **Step 3: Clean up test file**

```bash
rm -f ~/.engrammic/checkpoints/$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16).json
```

---

## Task 3: Implement engrammic-checkpoint hook

**Files:**
- Create: `~/.claude/hooks/engrammic-checkpoint.sh`

- [ ] **Step 1: Create the hook script**

```bash
cat > ~/.claude/hooks/engrammic-checkpoint.sh << 'HOOKEOF'
#!/usr/bin/env bash
set -euo pipefail

# PreCompact hook: finalize checkpoint with timestamp
# Called before context compaction to ensure state is saved

INPUT=$(timeout 3 cat || echo '{}')

CWD=$(echo "$INPUT" | jq -r '.cwd // ""')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""')

[[ -z "$CWD" ]] && exit 0

PROJECT_HASH=$(echo -n "$CWD" | sha256sum | cut -c1-16)
CHECKPOINT_FILE="$HOME/.engrammic/checkpoints/${PROJECT_HASH}.json"

# Exit if no checkpoint file exists (nothing to finalize)
[[ ! -f "$CHECKPOINT_FILE" ]] && exit 0

# Update checkpoint with session info and timestamp
TMP=$(mktemp)
jq --arg ts "$(date -Iseconds)" --arg sid "$SESSION_ID" \
   '.checkpointed_at = $ts | .session_id = $sid' \
   "$CHECKPOINT_FILE" > "$TMP"
mv "$TMP" "$CHECKPOINT_FILE"

exit 0
HOOKEOF
chmod +x ~/.claude/hooks/engrammic-checkpoint.sh
```

- [ ] **Step 2: Test the hook manually**

```bash
# Create a test checkpoint first
PROJECT_HASH=$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16)
echo '{"project_dir": "/tmp/test-project", "node_ids": ["mem_abc"]}' > ~/.engrammic/checkpoints/${PROJECT_HASH}.json

# Run checkpoint hook
echo '{"cwd": "/tmp/test-project", "session_id": "test-session"}' | ~/.claude/hooks/engrammic-checkpoint.sh

# Verify
cat ~/.engrammic/checkpoints/${PROJECT_HASH}.json
```

Expected: JSON now has `checkpointed_at` and `session_id` fields

- [ ] **Step 3: Clean up test file**

```bash
rm -f ~/.engrammic/checkpoints/$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16).json
```

---

## Task 4: Implement engrammic-restore hook

**Files:**
- Create: `~/.claude/hooks/engrammic-restore.sh`

- [ ] **Step 1: Create the hook script**

```bash
cat > ~/.claude/hooks/engrammic-restore.sh << 'HOOKEOF'
#!/usr/bin/env bash
set -euo pipefail

# SessionStart hook: check for existing checkpoint and inform agent
# Outputs additionalContext if checkpoint exists for this project

INPUT=$(timeout 3 cat || echo '{}')

CWD=$(echo "$INPUT" | jq -r '.cwd // ""')

[[ -z "$CWD" ]] && exit 0

PROJECT_HASH=$(echo -n "$CWD" | sha256sum | cut -c1-16)
CHECKPOINT_FILE="$HOME/.engrammic/checkpoints/${PROJECT_HASH}.json"

# Exit silently if no checkpoint
[[ ! -f "$CHECKPOINT_FILE" ]] && exit 0

# Read checkpoint data
NODE_IDS=$(jq -r '.node_ids | join(", ")' "$CHECKPOINT_FILE")
CHECKPOINTED_AT=$(jq -r '.checkpointed_at // "unknown"' "$CHECKPOINT_FILE")

# Exit if no node IDs
[[ -z "$NODE_IDS" || "$NODE_IDS" == "null" ]] && exit 0

# Output additionalContext for Claude
CONTEXT="Previous session checkpoint found for this project.
Checkpointed at: $CHECKPOINTED_AT
Node IDs: [$NODE_IDS]

If the user wants to continue from the previous session, call recall with these node IDs to restore context."

# Output JSON for Claude Code
jq -n --arg ctx "$CONTEXT" '{
  "hookSpecificOutput": {
    "additionalContext": $ctx
  }
}'

exit 0
HOOKEOF
chmod +x ~/.claude/hooks/engrammic-restore.sh
```

- [ ] **Step 2: Test the hook manually**

```bash
# Create a test checkpoint
PROJECT_HASH=$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16)
cat > ~/.engrammic/checkpoints/${PROJECT_HASH}.json << 'EOF'
{
  "project_dir": "/tmp/test-project",
  "node_ids": ["mem_abc123", "mem_def456"],
  "checkpointed_at": "2026-05-18T20:30:00+00:00"
}
EOF

# Run restore hook
echo '{"cwd": "/tmp/test-project"}' | ~/.claude/hooks/engrammic-restore.sh
```

Expected: JSON output with `hookSpecificOutput.additionalContext` containing node IDs

- [ ] **Step 3: Clean up test file**

```bash
rm -f ~/.engrammic/checkpoints/$(echo -n "/tmp/test-project" | sha256sum | cut -c1-16).json
```

---

## Task 5: Configure hooks in Claude Code

**Files:**
- Modify: `~/.claude/settings.json` or `~/.claude/settings.local.json`

- [ ] **Step 1: Add hook configuration**

Add to your settings JSON (merge with existing hooks):

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

- [ ] **Step 2: Verify configuration**

```bash
jq '.hooks' ~/.claude/settings.json
```

Expected: All three hook events configured

---

## Task 6: End-to-end validation

- [ ] **Step 1: Start a Claude Code session in a test project**

```bash
cd /tmp/test-engrammic-hooks
claude
```

- [ ] **Step 2: Use Engrammic to store some context**

In the session, use `remember` or `learn` to store a few nodes.

- [ ] **Step 3: Trigger compaction**

Run `/compact` in Claude Code.

- [ ] **Step 4: Verify checkpoint was created**

```bash
ls -la ~/.engrammic/checkpoints/
cat ~/.engrammic/checkpoints/*.json
```

Expected: Checkpoint file with node IDs and `checkpointed_at` timestamp

- [ ] **Step 5: Start a new session or /clear**

Run `/clear` or start a fresh Claude Code session in the same directory.

- [ ] **Step 6: Verify restore offer**

The agent should mention that a previous checkpoint was found and offer to restore.

- [ ] **Step 7: Accept restore and verify coherence**

Confirm restore. Agent should call `recall` and continue coherently.

---

## Done Criteria

- [ ] All three hooks installed and executable
- [ ] Hooks configured in Claude Code settings
- [ ] E2E test: store nodes -> compact -> restore -> agent continues coherently
- [ ] Document findings (did it work? what broke? what's next?)

## Out of Scope

- Production auth (OAuth/WorkOS)
- Checkpoint expiry/pruning
- Multi-project management UI
- LLM-agnostic protocol design
