# Vic GTM Workspace Design

**Date:** 2026-05-20  
**Status:** Ready to ship  
**Location:** `../cursor/`

## Summary

Cursor-based workspace for Vic (BD/GTM cofounder) with Engrammic MCP integration. Provides persistent memory across sessions for sales, content, and competitive research workflows.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Vic's Machine (Windows)                            │
│  ┌───────────────────────────────────────────────┐  │
│  │ Cursor IDE                                    │  │
│  │  - Chat sidebar (primary interface)           │  │
│  │  - CURSOR.md (GTM workflows)                  │  │
│  │  - skills/ (engrammic-* with Windows paths)   │  │
│  │  - templates/ (blog, outreach, intel, pitch)  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                          │
                          │ MCP over HTTPS + OAuth (PKCE)
                          ▼
┌─────────────────────────────────────────────────────┐
│  beta.engrammic.ai                                  │
│  - WorkOS OAuth (Vic needs WorkOS account)         │
│  - Shared silo (you + Vic)                         │
│  - Nodes tagged with agent_id = user:{workos_id}   │
└─────────────────────────────────────────────────────┘
```

## Components

### MCP Configuration (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "engrammic": {
      "url": "https://beta.engrammic.ai/mcp",
      "transport": "streamable-http",
      "oauth": {
        "client_id": "engrammic-cursor",
        "authorization_url": "https://beta.engrammic.ai/oauth/authorize",
        "token_url": "https://beta.engrammic.ai/oauth/token",
        "scopes": ["read", "write"]
      }
    }
  }
}
```

No client pre-registration required - server uses PKCE (public clients). Redirect to localhost is allowed by default.

### Workflows (CURSOR.md)

Four GTM workflows defined:
1. **Content Creation** - recall, research, draft, store learnings
2. **Sales Outreach** - recall prospect, research, personalize, track
3. **Competitive Intel** - recall, research, store with evidence, link
4. **Pitch Prep** - recall context + objections, prep, store outcomes

### Skills (`skills/`)

Engrammic skills with Windows-safe names (`:` replaced with `-`):
- `engrammic-eag-guide` - cognitive guide for memory usage
- `engrammic-observe` - store observations
- `engrammic-learn` - store facts with evidence
- `engrammic-recall` - search knowledge
- `engrammic-connect` - link concepts

### Templates (`templates/`)

- `blog-post.md` - structure + memory workflow
- `sales-outreach.md` - research + personalization workflow
- `competitive-intel.md` - research + analysis framework
- `pitch-prep.md` - prep + post-call capture

## Node Attribution

Nodes automatically tagged with `agent_id = user:{vic_workos_id}` from OAuth. No manual tagging needed. Shared silo allows cross-pollination of knowledge between you and Vic.

## Setup Steps

1. Add Vic to WorkOS org
2. Push `../cursor/` repo to GitHub
3. Vic clones repo, opens in Cursor
4. On first MCP use, Cursor prompts OAuth login
5. Vic authenticates via WorkOS, connected

## Future Enhancements (Optional)

- Add `agent_id` filter to recall for user-specific queries
- Add tag filtering to recall for workflow categorization
- Seed knowledge base with existing competitive intel from docs-vault
