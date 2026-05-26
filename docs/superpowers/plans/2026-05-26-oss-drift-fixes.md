# OSS Drift Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix validated drift between context-service and OSS repos (mcp-client, skills, primitives, engine)

**Architecture:** Independent fixes across 4 repos. Each task is self-contained and can be executed in parallel. No dependencies between tasks.

**Tech Stack:** Rust (mcp-client), Markdown (skills, READMEs), Python (primitives)

---

## Task 1: Fix MCP Transport Type (CRITICAL)

**Repo:** `../mcp-client`

**Files:**
- Modify: `installer-cli/src/config.rs:45`
- Modify: `README.md:29`

The installer writes `"type": "sse"` but context-service expects `"type": "http"`. Clients will fail to connect.

- [ ] **Step 1: Fix config.rs**

In `installer-cli/src/config.rs`, change line 45 from:

```rust
                "type": "sse",
```

to:

```rust
                "type": "http",
```

- [ ] **Step 2: Fix README.md**

In `README.md`, change line 29 from:

```json
      "type": "sse",
```

to:

```json
      "type": "http",
```

- [ ] **Step 3: Verify changes**

```bash
cd ../mcp-client
grep -n '"type":' installer-cli/src/config.rs README.md
```

Expected: Both show `"type": "http"`

- [ ] **Step 4: Commit**

```bash
cd ../mcp-client
git add installer-cli/src/config.rs README.md
git commit -m "fix: use http transport type instead of sse

context-service expects type: http (Streamable HTTP), not sse.
Clients configured with sse will fail to connect."
```

---

## Task 2: Update MCP README Tool Table

**Repo:** `../mcp-client`

**Files:**
- Modify: `README.md:49-58`

README shows 8 tools but actual surface has 17.

- [ ] **Step 1: Replace tool table**

In `README.md`, replace lines 49-58 (the existing tool table) with:

```markdown
| Tool | Purpose |
|------|---------|
| `remember` | Store observations (no evidence needed) |
| `learn` | Store claims with evidence |
| `believe` | Form commitments grounded in facts |
| `recall` | Search and retrieve context |
| `link` | Connect related concepts |
| `trace` | Query provenance chains |
| `reason` | Record explicit reasoning steps |
| `reflect` | Store meta-observations |
| `hypothesize` | Form tentative beliefs |
| `revise` | Update tentative hypotheses |
| `commit` | Crystallize hypotheses to commitments |
| `accept` | Ratify system-synthesized beliefs |
| `reject` | Reject system-synthesized beliefs |
| `forget` | Request node deletion |
| `dismiss` | Dismiss contradiction markers |
| `patterns` | Discover workflow templates |
| `tick` | Lightweight engagement check |
```

- [ ] **Step 2: Verify changes**

```bash
cd ../mcp-client
grep -c "^\| \`" README.md
```

Expected: 17 (one per tool)

- [ ] **Step 3: Commit**

```bash
cd ../mcp-client
git add README.md
git commit -m "docs: update tool table to full 17-tool surface"
```

---

## Task 3: Fix engrammic-learn Skill

**Repo:** `../skills`

**Files:**
- Modify: `engrammic-learn/SKILL.md:19`

Line 19 references `observe` but the correct tool is `remember`.

- [ ] **Step 1: Fix the reference**

In `engrammic-learn/SKILL.md`, change line 19 from:

```markdown
**Heuristic:** If you would need to cite a source to defend this claim, it belongs here with that source as evidence. If you cannot cite a source, use `observe` instead.
```

to:

```markdown
**Heuristic:** If you would need to cite a source to defend this claim, it belongs here with that source as evidence. If you cannot cite a source, use `remember` instead.
```

- [ ] **Step 2: Verify change**

```bash
cd ../skills
grep -n "observe\|remember" engrammic-learn/SKILL.md
```

Expected: Line 19 shows `remember`, no `observe` references

- [ ] **Step 3: Commit**

```bash
cd ../skills
git add engrammic-learn/SKILL.md
git commit -m "fix(engrammic-learn): observe -> remember

observe is not an MCP tool name; remember is the correct verb"
```

---

## Task 4: Fix engrammic-crystallize Skill

**Repo:** `../skills`

**Files:**
- Modify: `engrammic-crystallize/SKILL.md:41`

Line 41 calls `belief-state(...)` which doesn't exist. Should use `recall(..., include_hypotheses: true)`.

- [ ] **Step 1: Fix the example**

In `engrammic-crystallize/SKILL.md`, change line 41 from:

```markdown
1. `belief-state(query: "auth strategy")` - surface active hypotheses on the topic
```

to:

```markdown
1. `recall(query: "auth strategy", include_hypotheses: true)` - surface active hypotheses on the topic
```

- [ ] **Step 2: Verify change**

```bash
cd ../skills
grep -n "belief-state\|include_hypotheses" engrammic-crystallize/SKILL.md
```

Expected: Line 41 shows `recall(..., include_hypotheses: true)`, no `belief-state` references

- [ ] **Step 3: Commit**

```bash
cd ../skills
git add engrammic-crystallize/SKILL.md
git commit -m "fix(engrammic-crystallize): belief-state -> recall with include_hypotheses

belief-state is not an MCP tool; use recall with include_hypotheses flag"
```

---

## Task 5: Fix primitives Version

**Repo:** `../primitives`

**Files:**
- Modify: `src/primitives/__init__.py:6`

`__init__.py` declares version 0.1.0 but pyproject.toml is at 0.1.2.

- [ ] **Step 1: Fix the version**

In `src/primitives/__init__.py`, change line 6 from:

```python
__version__ = "0.1.0"
```

to:

```python
__version__ = "0.1.2"
```

- [ ] **Step 2: Verify change**

```bash
cd ../primitives
grep __version__ src/primitives/__init__.py
```

Expected: `__version__ = "0.1.2"`

- [ ] **Step 3: Commit**

```bash
cd ../primitives
git add src/primitives/__init__.py
git commit -m "fix: sync __version__ with pyproject.toml (0.1.2)"
```

---

## Task 6: Update Engine README Tool Table

**Repo:** `../engine`

**Files:**
- Modify: `README.md:40-47`

README shows 6 tools but engine implements 11.

- [ ] **Step 1: Replace tool table**

In `README.md`, replace lines 40-47 (the existing tool table) with:

```markdown
| Tool | Purpose |
|------|---------|
| `remember` | Store observations (no evidence needed) |
| `learn` | Store claims with evidence |
| `believe` | Form commitments grounded in facts |
| `recall` | Search and retrieve context |
| `link` | Create relationships between nodes |
| `trace` | Query provenance chains |
| `reason` | Record explicit reasoning steps |
| `reflect` | Store meta-observations |
| `hypothesize` | Form tentative beliefs |
| `revise` | Update tentative hypotheses |
| `commit` | Crystallize hypotheses to commitments |
```

- [ ] **Step 2: Verify changes**

```bash
cd ../engine
grep -c "^\| \`" README.md
```

Expected: 11 (one per tool)

- [ ] **Step 3: Commit**

```bash
cd ../engine
git add README.md
git commit -m "docs: update tool table to show all 11 implemented tools"
```

---

## Summary

| Task | Repo | Severity | Description |
|------|------|----------|-------------|
| 1 | mcp-client | Critical | Transport type sse -> http |
| 2 | mcp-client | Medium | README tool table 8 -> 17 |
| 3 | skills | Medium | observe -> remember |
| 4 | skills | High | belief-state -> recall |
| 5 | primitives | Medium | Version 0.1.0 -> 0.1.2 |
| 6 | engine | Medium | README tool table 6 -> 11 |
