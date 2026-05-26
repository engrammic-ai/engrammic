# Engrammic Integration Snippet for CLAUDE.md

Add this to your project's `CLAUDE.md` or `AGENTS.md` to enable proactive memory usage.

## Minimal Version (~20 lines)

```markdown
## Memory (Engrammic MCP)

**At session start:** `recall` what's relevant to today's work.

**Store proactively (don't wait to be asked):**
- User preferences or corrections → `remember`
- Codebase discoveries with file evidence → `learn`
- Bug fixes (what was wrong, why, how fixed) → `learn`
- Decisions or conclusions from multiple facts → `believe`
- Changed understanding or mistakes → `reflect`

**Always `recall` before storing** — supersede existing nodes, don't duplicate.

**Skip:** debug output, terminal logs, obvious-from-code things, speculation.
```

## Standard Version (~40 lines)

```markdown
## Memory (Engrammic MCP)

You have persistent memory across sessions. Use it proactively.

### Session Start
`recall(query: "{today's task or domain}")` — check existing context before working.

### Store Triggers (Act Without Being Asked)

| Event | Action |
|-------|--------|
| User shares preference | `remember` |
| User corrects you | `remember` the correction |
| Discover something non-obvious about codebase | `learn` with file:// evidence |
| Fix a bug | `learn` what/why/how |
| Form conclusion from multiple facts | `believe` with about=[node_ids] |
| Your understanding changes | `reflect` |

### Recall Triggers

| Event | Action |
|-------|--------|
| User mentions concept/project you may know about | `recall` first |
| User says "before", "last time", "we discussed" | `recall` that context |
| Starting work in a domain you've touched | `recall` background |
| Before storing anything | `recall` to check for supersession |

### Anti-Spam

**Store when:** future sessions benefit, not obvious from code, you'd mention it to a colleague.

**Skip:** debug output, error messages, in-flight task state, "might be useful" speculation.

### Supersession

Before storing, `recall` the topic. If node exists:
- Updating it? Pass `supersedes=<node_id>`
- Contradicts? `link(type="CONTRADICTS")` then `reflect`
```

## Full Version (with layer guidance)

```markdown
## Memory (Engrammic MCP)

You have persistent, epistemically-grounded memory. Use it proactively, not just when asked.

### Session Start

1. `recall(query: "{today's task or domain}")` — check what's known
2. Proceed with work (no ceremony if context is fresh)

### Store Triggers (Act Without Being Asked)

| When this happens | Do this |
|-------------------|---------|
| User shares a preference | `remember` it |
| User corrects you | `remember` the correction |
| You learn something non-obvious about the codebase | `learn` with file:// evidence |
| You fix a bug | `learn` what was wrong, why, and how |
| You form a conclusion from multiple facts | `believe` with `about` node IDs |
| Your understanding changes | `reflect` |
| You make a decision worth remembering rationale for | `believe` or `learn` |

### Recall Triggers (Act Without Being Asked)

| When this happens | Do this |
|-------------------|---------|
| User mentions a concept/project/term | `recall` to check what you know |
| User says "before", "last time", "we discussed" | `recall` that context |
| Starting work in a domain you've touched before | `recall` relevant background |
| Before storing anything | `recall` to check for supersession |
| User asks same question twice | `recall` — you may have missed it |

### Anti-Spam Rules

**Store only when:**
- Future sessions would benefit
- It's not obvious from reading the code
- You'd tell a colleague about it tomorrow

**Recall only when:**
- The result would change your response
- Not on every noun — only when it matters

**Never store:**
- Debug output, terminal logs, error messages
- In-flight task progress (use task tools instead)
- Things obvious from the code
- "Might be useful later" speculation

### Layer Selection

| Layer | When to use | Evidence required? |
|-------|-------------|-------------------|
| Memory (`remember`) | Raw observation, preference, note | No |
| Knowledge (`learn`) | Verifiable claim, discovery, bug fix | Yes (file://, https://) |
| Wisdom (`believe`) | Conclusion synthesized from facts | Links to supporting nodes |
| Meta (`reflect`) | Your understanding changed | Links to affected nodes |

### Supersession Protocol

Before storing, always `recall` first. If a node exists on the same topic:
- **Updating it:** pass `supersedes=<node_id>` to chain the update
- **Contradicts:** `link(type="CONTRADICTS")` + `reflect` on the change
- **Related:** store new node, then `link` them

This creates version chains. Old nodes stay for history; new node becomes current.

### Quick Reference

```
recall → before any store, before starting work in known domain
remember → raw observation (no evidence needed)
learn → claim with evidence (evidence required)
believe → conclusion from facts (about node IDs required)
reflect → when understanding shifts
link → explicit relationship between nodes
```
```

## Notes

- The **minimal version** is best for most projects — enough to trigger proactive behavior without overwhelming.
- The **standard version** adds recall triggers and anti-spam guidance.
- The **full version** is for teams deeply using Engrammic's epistemic layers.

Pick based on your team's familiarity with Engrammic.
