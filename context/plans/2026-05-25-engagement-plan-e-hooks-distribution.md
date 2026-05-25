# Engagement Plan E: Hooks and Distribution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship Layer 2 hook surface and distribution assets so agents proactively check for engagement even when not calling recall.

**Depends on:** Plan D (hard checkpoint) — shipped 2026-05-25

**Spec:** `context/brainstorm/2026-05-25-engagement-surface-layers.md`

---

## Scope

### In scope for Plan E:
- `x-session-id` header injection via installer config
- Claude Code hook configs (`~/.claude/hooks/`) for tick triggers
- `engrammic-engage` skill teaching agents when/how to resolve markers
- AGENTS.md guidance block for engagement resolution patterns
- Installer updates to distribute hook configs and skills

### Out of scope:
- Harness-specific hooks beyond Claude Code (Cursor, Codex defer to their native patterns)
- Custom harness / Reflexion-style loop (Layer 3 per spec)
- Automated hook installation (user runs installer, we provide configs)

### Clarifications:
- **`tick` verb already exists** from Plan C. This plan distributes configs that invoke it.
- **Cross-harness strategy:** Claude Code gets reference hooks. Other harnesses get AGENTS.md guidance only (they lack hook support or have different patterns).

---

## Architecture

### Session ID Injection

The `x-session-id` header enables per-session touch tracking (Plan D). Currently optional with fallback to silo-scoped.

For Claude Code:
- Session ID can be injected via MCP server config in `~/.claude/mcp_settings.json`
- Or via environment variable in the server invocation

Installer update:
```bash
# In install.sh, after MCP config setup:
# Add x-session-id header with unique session identifier
```

### Hook Configurations

Claude Code hooks live in `~/.claude/hooks/`. Two trigger patterns:

1. **Session start hook** — calls `tick` on conversation start
2. **Post-tool hook** — calls `tick` after N tool calls without recall

Hook config format (YAML):
```yaml
# ~/.claude/hooks/engrammic-engage.yaml
triggers:
  - event: session_start
    action: mcp_call
    tool: tick
  - event: post_tool
    condition: "tools_since_recall >= 5"
    action: mcp_call
    tool: tick
```

### engrammic-engage Skill

Skill teaches agents the engagement resolution workflow:

```markdown
# engrammic-engage

When you see an `engagement` field in recall responses or tick results:

## Soft mode (mode: "soft")
Results are still available. Review markers when convenient:
- ProposedBelief: use `accept` to ratify or `reject` to decline
- Contradiction/StaleCommitment: resolve via `believe` with `supersedes`, then `dismiss`

## Hard mode (mode: "hard")
Results withheld until you resolve at least one marker.
This happens after 3+ touches without resolution.

## Resolution patterns
1. Read marker summary to understand the issue
2. For ProposedBelief: decide if synthesis is accurate
3. For Contradiction: determine which claim is correct
4. For StaleCommitment: form updated commitment
5. Call appropriate verb (accept/reject/dismiss)
```

### AGENTS.md Guidance

Add to distributed AGENTS.md:

```markdown
## Engagement Resolution

When recall returns `engagement.markers`, you have pending decisions:
- `accept`/`reject` for ProposedBelief (SAGE synthesized a belief)
- `dismiss` for Contradiction/StaleCommitment (after resolving via believe/learn)

Hard mode (`engagement.mode == "hard"`) means recall withholds results until resolution.
Call `tick` periodically if you go many turns without recall.
```

---

## File Structure

```
installer/
  src/
    install.sh                               # MODIFY - add session-id config
  configs/
    claude-code/
      hooks/
        engrammic-engage.yaml                # CREATE - hook trigger config
      mcp_settings_patch.json                # CREATE - session-id header

skills/
  engrammic-engage/
    skill.md                                 # CREATE - engagement resolution skill

docs/
  AGENTS.md                                  # MODIFY - add engagement guidance
```

---

## Task 0: Verify Baseline

- [ ] Run `just check` and `just test` to establish baseline
- [ ] Confirm `tick` verb works (from Plan C)
- [ ] Confirm hard checkpoint works (from Plan D)

---

## Task 1: Session ID Configuration

**Files:** `installer/`, MCP config documentation

**Goal:** Enable session ID injection for touch tracking.

- [ ] Document session ID injection pattern for Claude Code
- [ ] Add example MCP settings patch with x-session-id header
- [ ] Update installer to optionally configure session ID
- [ ] Test: verify session ID reaches server and enables per-session tracking

---

## Task 2: Claude Code Hook Configs

**Files:** `installer/configs/claude-code/hooks/`

**Goal:** Reference hook configurations for tick triggers.

- [ ] Create `engrammic-engage.yaml` with session_start trigger
- [ ] Add post_tool trigger with tools_since_recall condition
- [ ] Document hook installation in installer README
- [ ] Test: verify hooks invoke tick at correct triggers

---

## Task 3: engrammic-engage Skill

**Files:** `skills/engrammic-engage/`

**Goal:** Skill teaching engagement resolution patterns.

- [ ] Create skill.md with soft/hard mode guidance
- [ ] Include resolution patterns for each marker type
- [ ] Add to installer skill distribution
- [ ] Test: verify skill loads and provides useful guidance

---

## Task 4: AGENTS.md Guidance

**Files:** `docs/AGENTS.md` or distributed guidance

**Goal:** Cross-harness guidance for engagement resolution.

- [ ] Add engagement resolution section
- [ ] Document tick usage for proactive checking
- [ ] Include hard mode recovery pattern
- [ ] Distribute via installer

---

## Task 5: Documentation Site Update

**Files:** `../web/docs/`

**Goal:** Update docs.engrammic.ai with engagement surface documentation.

- [ ] Add engagement overview page (soft/hard modes, markers)
- [ ] Document dismiss and tick verbs in MCP tools reference
- [ ] Add troubleshooting section for hard mode recovery
- [ ] Update agent guide with engagement resolution patterns

---

## Task 6: Full Sweep

- [ ] `just check` — lint + typecheck clean
- [ ] `just test` — all tests pass
- [ ] Manual smoke test: install with new configs, verify hooks trigger
- [ ] Commit with summary of Plan E changes

---

## Done Criteria

Plan E is complete when:

- [ ] Session ID injection documented and configurable
- [ ] Claude Code hook configs distributed via installer
- [ ] engrammic-engage skill teaches resolution patterns
- [ ] AGENTS.md guidance covers engagement workflow
- [ ] Installer distributes all new configs/skills
- [ ] docs.engrammic.ai updated with engagement surface docs
- [ ] `just check` and `just test` green

---

## What Ships After Plan E

The engagement surface (Plans A-E) is complete. Next priorities:

- **Self-Hosted REST API Phase 1:** Auth + Memory/Knowledge endpoints
- **OSS Launch:** Engine repo, landing page, community setup
