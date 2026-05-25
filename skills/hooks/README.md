# Engrammic Claude Code Hooks

Optional hooks to nudge agents toward better Engrammic usage.

## engrammic-engage-hook.sh

Fires on session start and periodically during tool use to prompt the agent to
check for pending engagement markers (contradictions, stale commitments,
proposed beliefs).

### Installation

1. Copy to your hooks directory:
   ```bash
   cp engrammic-engage-hook.sh ~/.claude/hooks/
   chmod +x ~/.claude/hooks/engrammic-engage-hook.sh
   ```

2. Add two entries to `~/.claude/settings.json`:

   **Session start trigger** (recommended minimum):
   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "bash \"$HOME/.claude/hooks/engrammic-engage-hook.sh\"",
               "timeout": 5
             }
           ]
         }
       ]
     }
   }
   ```

   **Periodic PostToolUse trigger** (optional, noisier):
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Bash|Edit|Write|Read",
           "hooks": [
             {
               "type": "command",
               "command": "bash \"$HOME/.claude/hooks/engrammic-engage-hook.sh\"",
               "timeout": 5
             }
           ]
         }
       ]
     }
   }
   ```

   You can tune how often the PostToolUse nudge fires by setting
   `ENGRAMMIC_TICK_INTERVAL` in your environment (default: 10 tool calls).

### Output

On session start, the agent sees:
```
[engrammic-engage] Session started. Call tick() to check for pending markers before proceeding.
If markers are returned, resolve them:
  - ProposedBelief: accept(node_id) or reject(node_id, reason)
  - Contradiction/StaleCommitment: believe(..., supersedes=...) then dismiss(marker_id)
```

After N tool calls without a recall or tick:
```
[engrammic-engage] Many tool calls since last recall. Consider calling tick() to check for pending markers.
  tick()
```

### Session ID configuration

See [session-id-config.md](session-id-config.md) for how to configure the
`x-session-id` header so engagement escalation is scoped per session rather
than accumulating across all sessions.

---

## engrammic-post-commit-nudge.sh

Fires after `git commit` commands and reminds the agent to log non-obvious fixes to Engrammic.

### Installation

1. Copy to your hooks directory:
   ```bash
   cp engrammic-post-commit-nudge.sh ~/.claude/hooks/
   chmod +x ~/.claude/hooks/engrammic-post-commit-nudge.sh
   ```

2. Add to `~/.claude/settings.json` under `hooks.PostToolUse`:
   ```json
   {
     "matcher": "Bash",
     "hooks": [
       {
         "type": "command",
         "command": "bash \"$HOME/.claude/hooks/engrammic-post-commit-nudge.sh\"",
         "timeout": 5
       }
     ]
   }
   ```

### Output

After a commit, the agent sees:
```
[engrammic-nudge] Commit detected. If this fix/change is non-obvious, consider logging it:
  learn(claim="<what changed and why>", evidence=["file://<path>"], source="agent", tags=["<domain>"])
```
