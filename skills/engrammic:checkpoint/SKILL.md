---
name: engrammic:checkpoint
description: Save context for later or handoff. Summarize what matters, tag for findability.
---

# Checkpoint

You have Engrammic memory available. Here's how to save context for later recall or handoff:

## What to checkpoint

- **Current state** - where things stand, what's done, what's not
- **Key findings** - facts learned, decisions made, hypotheses in play
- **Blockers or open questions** - what's preventing progress
- **Next steps** - what the resuming agent (you or someone else) should do

## How to store it

- Use `remember` with `decay: durable` for checkpoint summaries
- Tag generously - include project, area, date, and any relevant identifiers
- If findings are facts with evidence, `learn` them separately so they persist beyond the checkpoint

## Tagging for recall

Good tags make checkpoints findable:
- `checkpoint`, `handoff`, or `session-end`
- Project/feature name
- Date (YYYY-MM-DD)
- Area (e.g., `auth`, `payments`, `infra`)

Example: `["checkpoint", "auth-migration", "2026-05-19", "blocked"]`

## No ceremony

The goal is resumability. Store enough that someone can pick up where you left off.
