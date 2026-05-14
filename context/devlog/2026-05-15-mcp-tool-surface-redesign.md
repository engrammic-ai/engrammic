# MCP Tool Surface Redesign

Date: 2026-05-15
Branch: feat/mcp-tool-surface-redesign
Status: Ready for merge

## Summary

Replaced layer-based MCP tools with intent-based naming for better agent discoverability. The old `context_store`/`context_recall` pattern required agents to understand CITE layers; the new surface uses action verbs that map naturally to what agents want to do.

## Changes

### New Tool Surface

**Standard profile (7 tools):**
| Tool | Purpose | Replaces |
|------|---------|----------|
| `remember` | Store observations | `context_store` layer=memory |
| `learn` | Assert claims with evidence | `context_store` layer=knowledge |
| `believe` | Declare commitments | `context_store` layer=wisdom |
| `recall` | Unified search | `context_recall` |
| `trace` | Provenance chain | `context_admin` action=provenance |
| `link` | Typed relationships | `context_link` |
| `patterns` | Workflow examples | `context_skills` |

**Reasoning profile adds 5 more:**
- `reason` - start reasoning chains
- `reflect` - meta-observations
- `hypothesize` - create working hypotheses
- `revise` - update tentative beliefs
- `commit` - crystallize to commitments

### Infrastructure

- YAML config at `src/context_service/config/mcp_tools.yaml`
- Profile-based registration via `register_profile_tools()`
- `MCP_TOOL_PROFILE` env var (standard | reasoning)
- `mcp_tool_profile` setting in Settings class

### Internal Tools (unchanged)

These remain for SAGE/admin use but are not in agent profiles:
- `context_admin` - silo management, provenance, history
- `context_belief_state` - query live session hypotheses
- `context_accept_belief` / `context_reject_belief` - ProposedBelief flow

## Design Decisions

1. **Thin wrappers**: New tools delegate to existing `_context_*` implementations. No business logic duplication.

2. **YAML config**: Tool descriptions, profiles, and MCP instructions all in one place. Easy to tweak without code changes.

3. **Profile resolution**: param > env > settings > default. Allows per-deployment or per-request customization.

4. **`include_hypotheses` on recall**: Agents can opt-in to see working hypotheses in search results.

## Testing

- 13 new tool tests in `tests/mcp/tools/`
- 116 total MCP tests passing
- `just check` clean (mypy + ruff)

## Commits

```
051db06 fix(mcp): derive silo_id in link/commit/revise tools
6cabdf2 feat(mcp): wire profile-based tool registration
2380249 feat(mcp): add remaining intent-based tools
d3edf9b feat(mcp): add intent-based tools (remember, learn, believe, trace)
fc3fc22 feat(mcp): add tool registry for YAML-based configuration
71cdb74 feat(mcp): add YAML config for intent-based tool surface
78ab395 docs(plan): add MCP tool surface redesign implementation plan
```

## Follow-up

- Task 11 (workflow pattern SKILLs) deferred - low priority docs
- Consider deprecation warnings on old tools in next release
