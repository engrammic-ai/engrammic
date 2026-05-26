# Auth Strategy Decision

**Date:** 2026-05-26  
**Status:** Decided  
**Context:** MCP authentication for hosted Engrammic service

## Problem

Users need to authenticate their AI harnesses (Claude Code, Cursor, Cline, Windsurf, etc.) to use Engrammic MCP.

OAuth is the standard approach for remote MCP servers, but it relies on the harness correctly implementing token refresh. Research shows this is unreliable:

| Harness | OAuth Support | Auto Refresh |
|---------|---------------|--------------|
| Claude Code | Yes | Buggy (cache issues) |
| Cursor | Yes | Unclear |
| Cline | Partial | Broken ("Invalid OAuth state") |
| Windsurf | Yes | Works (April 2026 fix) |
| Codex CLI | Yes (HTTP) | Manual (`codex mcp login`) |

With 1-hour access tokens (previous default), users would need to re-authenticate frequently when refresh fails.

## Research: How Others Handle This

| MCP Server | Primary Auth | Token Lifetime |
|------------|--------------|----------------|
| GitHub | OAuth or PAT | PAT: long-lived |
| Notion | Integration token / OAuth | Integration: indefinite |
| Linear | OAuth (remote) / API key (local) | API keys: long-lived |
| Slack | OAuth tokens | Long-lived |

Pattern: Remote servers use OAuth but effectively rely on long token lifetimes. Local servers use indefinite API keys.

## Decision

### Short Term (Beta)

**Extend access token TTL to 30 days.**

- Change: `access_token_ttl_seconds: 3600` → `access_token_ttl_seconds: 2592000`
- Refresh token remains 90 days
- Users authenticate once, good for a month even if harness refresh is broken
- Zero additional code, just config change

### Medium Term (Post-Beta)

**Add API key authentication.**

- Spec drafted at `docs/superpowers/plans/2026-05-26-api-key-auth.md`
- Keys are silo-scoped, long-lived, revocable
- Primary use: CI/CD, headless agents, harnesses with broken OAuth
- Effort: ~2 days
- Trigger: When we build admin UI, or when a user needs headless access

### Not Doing

- **Device auth flow in installer** - Adds complexity, OAuth with long TTL is sufficient
- **Dashboard for key management** - Overkill for beta with manual invites
- **Short-lived tokens + rely on harness refresh** - Ecosystem isn't ready

## Trade-offs

**30-day access tokens:**
- Pro: Works everywhere, no code change
- Con: Longer window if token is compromised (mitigated by refresh token revocation)

**API keys (future):**
- Pro: Indefinite, no refresh dance, works in all contexts
- Con: Must be stored securely by user, need admin endpoints to manage

## Related

- API key spec: `docs/superpowers/plans/2026-05-26-api-key-auth.md`
- Evidence validation gap: GitHub #52
- Current OAuth implementation: `src/context_service/services/oauth.py`
