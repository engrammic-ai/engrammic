# Enforcement architecture design spec (workstream A)

Date: 2026-06-04
Status: Design spec, decisions taken per user delegation ("the enforcement stuff i'll take your rec").
Companion: context/brainstorm/2026-06-04-enforcement-harness-docs.md (research + the 4-tier forcing hierarchy).
Feeds: the docs seam slots (workstream B) and the installer/plugin work (workstream C).

## The decision, stated plainly

Make Engrammic "out of the box effective" by being the active context layer through mechanisms the ecosystem
already exposes (inject / gate / instruct). Do not build a harness. The spine is server-side so it travels to every
MCP client; hooks are a per-harness amplifier, deepest on Claude Code.

Aha (turn-one differentiator): the agent only walks in knowing what it can stand behind. A fresh session starts
with relevant context already surfaced WITH provenance, and the stale / superseded / low-confidence memory that a
flat layer (mem0/Zep) would inject as equal-trust fact is withheld or flagged, not surfaced blind.

Posture: ambient-helpful injection with a trust gate on what gets surfaced (refuse to surface unwarranted memory),
plus soft nudges on writes. Hard write-gating (evidence-required reject, contradiction hard-block) is a one-flag
opt-in. Self-hosted ships soft-by-default.

Wedge (calibrated, do not overclaim): trust-typing (Memory/Knowledge/Wisdom) + confidence-gated injection. NOT
"we detect contradictions/staleness", which Zep/Graphiti/Cognee already do. Our claim is that we refuse to inject
what we cannot stand behind.

## The 4-tier forcing hierarchy (by how little harness cooperation each needs)

1. Tool descriptions: universal, zero-install. Every MCP client sends them to the model.
2. MCP server `instructions` + tool-response payloads: ship with the server; render where the client supports it
   (Claude Code yes, Codex yes/512-char, others partial/unverified). Tool responses reach every client.
3. Rules files (CLAUDE.md / AGENTS.md / ...): universal INSTRUCT, install-time, context not enforcement.
4. Hooks: deterministic INJECT/GATE; available in all six surveyed harnesses; install-time.

## Components

### A1. Portable server-side spine (every harness, zero install) - THE MVP

This is the part that delivers the aha with no hook and no rules file, because it lives in the MCP server.

1. Tool-description hardening. Encode the behavior INTO recall/remember/learn/believe descriptions: "call recall
   at the start of any task"; "after a fact with file evidence, call learn"; "recall before storing and pass
   supersedes." Anthropic's guidance: tool descriptions are a primary forcing function.

2. Trust-gated recall/injection. The recall response already exposes the signals we need: confidence,
   conflict_status, supersession (head/tail chain), credibility, relevance_score. Add a gate that, by default:
   - surfaces only the current node in a supersession chain (not superseded versions);
   - excludes or flags nodes under an unresolved Contradiction (conflict_status);
   - applies a confidence floor for AMBIENT surfacing (explicit recall can still return below-floor with a flag);
   - returns withheld items as a COUNT + reason, never a silent omit, so the behavior is demonstrable
     ("3 lower-confidence memories withheld; ask to see them"). This count is the demo and the trust signal.
   Layer policy: Knowledge/Wisdom are ambient-surfaceable when warranted; raw Memory observations return on
   explicit recall but are not pushed into the ambient primer by default.

3. Portable INJECT vector. The server `instructions` field carries the recall-first/supersession guidance (first
   512 chars self-contained for Codex). The FIRST recall (or a dedicated primer) of a session returns a warranted
   context primer in the tool-response payload, which reaches every MCP client without a hook.

4. Write gate (posture: soft default, hard opt-in). learn without evidence -> soft warning in the response by
   default; hard-reject under the opt-in flag. Duplicate on store -> supersede-or-flag. This generalizes the
   existing engagement soft/hard escalation (which already withholds recall results after 3 untouched markers).

### A2. Hooks amplifier (per-harness, depth-first on Claude Code)

- SessionStart recall via an HTTP/command hook (NOT mcp_tool: servers are not connected at session start) that
  injects the warranted context primer as additionalContext.
- UserPromptSubmit recall primer (servers connected by then) injecting per-turn warranted context.
- Stop hook persistence nudge ("you discovered X and did not persist it"), the closest thing to compelling writes.
- PreToolUse validator on learn to enforce evidence/supersession BEFORE a bad write lands.
- Package the whole thing as a Claude Code plugin (MCP config + hooks + EAG skill in one marketplace install).
  The installer (C) covers the other harnesses; Codex reuses CC's JSON contract, Gemini is CC-style with its own
  event names.

### A3. Single canonical instruction source (shared with B and C)

One Markdown partial is the source of truth, rendered into: the server `instructions` field, the docs snippet, and
the installer's per-harness output (CLAUDE.md / AGENTS.md / rules). Kills the >=3-copy drift.

## Non-goals

- Building our own harness or runtime.
- Auto-extraction from every turn (the commodity capture path). The agent calls verbs; hooks amplify. We compete
  on trust of what is surfaced, not on capture volume.
- Multi-agent coordination (deferred per prior decision).

## Phasing

- A1 first: tool-description hardening + trust-gated recall + tool-response primer + soft write gate. This is the
  portable, zero-install MVP and IS the differentiator. Demoable on any harness.
- A2: the Claude Code hook suite + plugin (overlaps C).
- A3 lands with B's canonical-source work.

## Acceptance / the Antler demo

Side-by-side, same harness: a memory that has been superseded or dropped below the confidence floor. A flat layer
injects it as fact; Engrammic withholds it, surfaces the current/warranted version with provenance, and shows the
"N withheld" count. One screen, the whole wedge.

## Open design questions (for the implementation plan)

1. Confidence floor value, and whether it is per-layer and/or per-silo configurable.
2. Is the ambient primer hook-only (CC) or also delivered via the first tool-response (every client)? (Spec leans:
   both - tool-response for universality, hook for the richer CC experience.)
3. Withheld-memory surfacing: count+reason vs include-with-flag. (Spec leans: count+reason, never silent.)
4. Exact interaction with the existing engagement hard-mode (do not double-gate).
5. Performance: the trust gate must keep recall within the < 250ms search budget.
