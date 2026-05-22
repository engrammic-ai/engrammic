#!/bin/bash
# Engrammic post-commit nudge (opt-in)
# Add to settings.json hooks to enable

# Read the tool input from stdin
input=$(cat)

# Check if this was a git commit command
if echo "$input" | grep -q '"command".*git commit'; then
  # Output reminder to Claude
  cat << 'EOF'
[engrammic-nudge] Commit detected. If this fix/change is non-obvious, consider logging it:
  learn(claim="<what changed and why>", evidence=["file://<path>"], source="agent", tags=["<domain>"])
EOF
fi

exit 0
