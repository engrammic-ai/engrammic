# Engrammic Skill Rename

## Problem

The MCP scenario skills are broken due to a naming mismatch from the Delta Prime to Engrammic rebrand:
- Skills reference `mcp__delta-prime__*` tools which don't exist
- Actual MCP tools are `mcp__engrammic__*`
- Parameter names are also mismatched (e.g., `relation_type` vs `relationship`)

This causes skills to fail silently or store placeholder text instead of real content.

## Solution

Rename all skill references from `delta-prime` to `engrammic` and fix parameter names.

## Changes

### 1. MCP Config (`.claude/.mcp.json`)

```json
// Before
{ "mcpServers": { "delta-prime": { "url": "..." } } }

// After
{ "mcpServers": { "engrammic": { "url": "..." } } }
```

### 2. Skill Directory Renames

| Old | New |
|-----|-----|
| `~/.claude/skills/delta-prime:observe/` | `~/.claude/skills/engrammic:observe/` |
| `~/.claude/skills/delta-prime:learn/` | `~/.claude/skills/engrammic:learn/` |
| `~/.claude/skills/delta-prime:recall/` | `~/.claude/skills/engrammic:recall/` |
| `~/.claude/skills/delta-prime:connect/` | `~/.claude/skills/engrammic:connect/` |
| `~/.claude/skills/delta-prime:trace/` | `~/.claude/skills/engrammic:trace/` |
| `~/.claude/skills/delta-prime:reflect/` | `~/.claude/skills/engrammic:reflect/` |
| `~/.claude/skills/delta-prime:reason/` | `~/.claude/skills/engrammic:reason/` |

### 3. Skill Content Updates

Each SKILL.md needs:
- `name:` field updated from `delta-prime:*` to `engrammic:*`
- `allowed-tools:` updated from `mcp__delta-prime__*` to `mcp__engrammic__*`
- Parameter names fixed to match actual MCP tool schema

### 4. Parameter Fixes

| Skill | Old Param | Correct Param |
|-------|-----------|---------------|
| connect | `relation_type` | `relationship` |

### 5. Manual Cleanup

Delete junk test data via direct Memgraph query:
```cypher
MATCH (n)
WHERE n.content IN ['annotated source', 'memory layer content', 'test content']
DETACH DELETE n
```

### 6. New Skills for Recent MCP Tools

Add skills for the 5 new belief-layer tools:

| Skill | Tool | Use Case |
|-------|------|----------|
| `engrammic:belief-state` | `context_belief_state` | Query working hypotheses in a session |
| `engrammic:update-belief` | `context_update_belief` | Mutate a working hypothesis |
| `engrammic:crystallize` | `context_crystallize` | Promote hypotheses to commitments |
| `engrammic:accept` | `context_accept_belief` | Accept a proposed belief |
| `engrammic:reject` | `context_reject_belief` | Reject a proposed belief |

## Files Affected

- `~/.claude/.mcp.json`
- `~/.claude/skills/delta-prime:*/SKILL.md` (7 files to rename/update)
- `~/.claude/skills/engrammic:*/SKILL.md` (5 new files to create)

## Testing

After changes:
1. Run `/mcp` to reconnect
2. Invoke `engrammic:observe` with test content
3. Verify via `engrammic:recall` that content was stored correctly
