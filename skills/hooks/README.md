# Engrammic Claude Code Hooks

Optional hooks to nudge agents toward better Engrammic usage.

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
