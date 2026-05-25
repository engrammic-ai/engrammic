#!/bin/bash
# Engrammic engagement check hook (opt-in)
# Fires on session start and optionally after tool calls.
# Add to settings.json hooks to enable (see README.md).
#
# On session start: prompts the agent to call tick and resolve any
# pending markers before beginning work.
#
# On PostToolUse: tracks how many tool calls have occurred in this
# session (via a temp counter file) and nudges after every N calls
# if no recall/tick has been observed.

COUNTER_FILE="${TMPDIR:-/tmp}/engrammic_tool_count_$$"
TICK_INTERVAL="${ENGRAMMIC_TICK_INTERVAL:-10}"

# Read the hook event payload from stdin
input=$(cat)

# Detect hook type from the event payload
event_type=$(echo "$input" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4 2>/dev/null || true)

if [ "$event_type" = "SessionStart" ]; then
  cat << 'EOF'
[engrammic-engage] Session started. Call tick() to check for pending markers before proceeding.
If markers are returned, resolve them:
  - ProposedBelief: accept(node_id) or reject(node_id, reason)
  - Contradiction/StaleCommitment: believe(..., supersedes=...) then dismiss(marker_id)
EOF
  exit 0
fi

# PostToolUse path: increment counter, nudge at intervals
if [ -f "$COUNTER_FILE" ]; then
  count=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
else
  count=0
fi

# Check if this tool call was a recall or tick (reset counter)
if echo "$input" | grep -qE '"tool_name":"(recall|tick)"'; then
  echo 0 > "$COUNTER_FILE"
  exit 0
fi

count=$((count + 1))
echo "$count" > "$COUNTER_FILE"

if [ "$count" -ge "$TICK_INTERVAL" ]; then
  echo 0 > "$COUNTER_FILE"
  cat << 'EOF'
[engrammic-engage] Many tool calls since last recall. Consider calling tick() to check for pending markers.
  tick()
  -- or with a scoped hint --
  tick(about_hint: ["{node_id_1}", "{node_id_2}"])
EOF
fi

exit 0
