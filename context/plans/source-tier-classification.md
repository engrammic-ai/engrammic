# Source Tier Classification

**Status:** Draft  
**Branch:** `feat/source-tier-classification`

## Problem

Claims stored via `learn` default to `source_tier=unknown`, which blocks both R1 and R2 promotion rules:

- **R1** requires `authoritative` + confidence >= 0.7
- **R2** requires at least one `authoritative` source among corroborating claims

Currently, no claims ever promote to Facts because the tier is never set.

## Goal

Enable automatic and customer-configurable source tier classification so that the Custodian can promote high-quality claims to Facts.

## Design

**Resolution layers (all checked, highest tier wins):**

| Layer | Source | When it applies |
|-------|--------|-----------------|
| 1. Evidence node inheritance | Node's `source_tier` property | When evidence is `node:<id>` and node has tier set |
| 2. Per-silo rules | `silo_source_rules` table | Customer-configured patterns |
| 3. Global defaults | `silo_source_rules` where `silo_id IS NULL` | TLD heuristics, known data providers |
| 4. Agent hint | `source_tier` param on `learn` | Fallback when no rules match |
| 5. Unknown | Hardcoded | Final fallback |

All evidence refs are checked; the **highest tier** across all matches is returned.

**Why each layer matters:**

1. **Evidence inheritance** - Documents ingested via connectors already have a tier; claims citing them should inherit it. Avoids re-classifying at claim time.

2. **Per-silo rules** - Partners have different authoritative sources. AiBen trusts EUR-Lex; Comparables trusts PitchBook. Customer-controlled, auditable.

3. **Global defaults** - Sensible baseline for common patterns (`.gov`, `.edu`, major data providers). Reduces onboarding friction.

4. **Agent hint** - Agents have context we don't (e.g., "this PDF is an official regulation vs. a blog post"). Used when no rules match.

## Schema

```sql
CREATE TABLE silo_source_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    silo_id UUID REFERENCES silos(id),  -- NULL = global default
    pattern TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('authoritative', 'validated', 'community')),
    reason TEXT,
    priority INT DEFAULT 0,  -- higher = checked first
    created_at TIMESTAMPTZ DEFAULT now(),
    created_by TEXT,
    UNIQUE(silo_id, pattern)
);

CREATE INDEX idx_source_rules_silo ON silo_source_rules(silo_id);
CREATE INDEX idx_source_rules_priority ON silo_source_rules(priority DESC);
```

## Global defaults

Seeded on migration:

```sql
INSERT INTO silo_source_rules (silo_id, pattern, tier, reason, priority) VALUES
-- Authoritative: government, courts, official registries
(NULL, 'https://*.gov/*', 'authoritative', 'Government domains', 100),
(NULL, 'https://*.gov.*/*', 'authoritative', 'Government country TLDs', 100),
(NULL, 'https://eur-lex.europa.eu/*', 'authoritative', 'EU law', 100),
(NULL, 'https://*.europa.eu/*', 'authoritative', 'EU institutions', 95),
(NULL, 'https://courtlistener.com/*', 'authoritative', 'US court records', 90),
(NULL, 'sec://*', 'authoritative', 'SEC filings', 90),

-- Validated: professional data providers, curated sources
(NULL, 'https://*.edu/*', 'validated', 'Educational institutions', 80),
(NULL, 'pitchbook://*', 'validated', 'PitchBook', 80),
(NULL, 'bloomberg://*', 'validated', 'Bloomberg', 80),
(NULL, 'crunchbase://*', 'validated', 'Crunchbase', 75),
(NULL, 'https://arxiv.org/*', 'validated', 'arXiv preprints', 70),

-- Community: user-generated, self-reported
(NULL, 'https://linkedin.com/*', 'community', 'LinkedIn (self-reported)', 50),
(NULL, 'https://medium.com/*', 'community', 'Medium articles', 50),
(NULL, 'wikipedia://*', 'community', 'Wikipedia', 50);
```

**Pattern validation**: Patterns must be valid fnmatch glob patterns. Invalid patterns rejected on insert with 400 error. Test via `/admin/source-rules/test` before adding.

## Tasks

### Phase 1: Schema + resolver

- [x] **T1.** Add migration for `silo_source_rules` table
- [x] **T2.** Create `services/source_tier_resolver.py` with resolution logic
- [x] **T3.** Seed global defaults in migration
- [x] **T4.** Unit tests for resolver (all four layers, priority ordering, pattern matching)

### Phase 2: Integration

- [x] **T5.** Update `learn` tool to accept `source_tier` param (agent hint)
- [x] **T6.** Update `_context_assert` to call resolver before storing
- [x] **T7.** Update `context.assert_claim` to use resolved tier
- [x] **T8.** Add evidence node inheritance lookup (check if `node:<id>` has `source_tier`)

### Phase 3: Admin API

- [x] **T9.** `GET /admin/source-rules` - list rules (silo + global)
- [x] **T10.** `POST /admin/source-rules` - add rule with pattern validation (reject invalid fnmatch)
- [x] **T11.** `DELETE /admin/source-rules/{id}` - remove rule (silo rules only for partners, super-admin for global)
- [x] **T12.** `POST /admin/source-rules/test` - debug endpoint to preview resolution
- [ ] **T13.** Add super-admin check for `org_id` override and global rule deletion

### Phase 4: Observability

- [ ] **T14.** Add metrics: `source_tier_resolved{tier, resolution_layer, silo_id}`
- [ ] **T15.** Log tier resolution for audit trail
- [ ] **T16.** Add to partner onboarding docs

## Performance notes

- **Rules caching**: `get_source_rules(silo_id)` cached with 5 min TTL. Rule changes take up to 5 min to propagate.
- **Batch node lookup**: Evidence node tier check uses single batched query, not N queries.
- **Query ordering**: Rules fetched with `ORDER BY silo_id IS NOT NULL DESC, priority DESC` to ensure silo rules always beat global.

## API

Silo is inferred from auth token by default. Super-admins can override with `org_id` query param.

### Add source rule

```http
# Partner self-service (silo from token)
POST /admin/source-rules
Authorization: Bearer <partner_token>
Content-Type: application/json

{
  "pattern": "https://eur-lex.europa.eu/*",
  "tier": "authoritative",
  "reason": "EU official law database",
  "priority": 100
}

# Engrammic admin configuring for a partner
POST /admin/source-rules?org_id=org_abc123
Authorization: Bearer <engrammic_admin_token>
```

### List rules

```http
GET /admin/source-rules?include_global=true
```

Response:
```json
{
  "rules": [
    {"id": "...", "pattern": "https://eur-lex.europa.eu/*", "tier": "authoritative", "source": "silo"},
    {"id": "...", "pattern": "https://*.gov/*", "tier": "authoritative", "source": "global"}
  ]
}
```

### Delete rule

```http
DELETE /admin/source-rules/{rule_id}
```

Only silo-specific rules can be deleted by partner admins. Global rules require super-admin.

### Test resolution (debug endpoint)

```http
POST /admin/source-rules/test
{
  "evidence_refs": ["https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679"],
  "agent_hint": "validated"
}
```

Response:
```json
{
  "resolved_tier": "authoritative",
  "resolution_layer": "global_rule",
  "matched_rule": {"pattern": "https://eur-lex.europa.eu/*", "tier": "authoritative"}
}
```

## Resolution algorithm

```python
_TIER_RANK = {
    SourceTier.AUTHORITATIVE: 4,
    SourceTier.VALIDATED: 3,
    SourceTier.COMMUNITY: 2,
    SourceTier.UNKNOWN: 1,
}

@lru_cache(maxsize=128, ttl=300)  # 5 min cache
async def get_source_rules_cached(silo_id: str) -> list[SourceRule]:
    """Fetch rules ordered by: silo_id IS NOT NULL DESC, priority DESC."""
    return await get_source_rules(silo_id)


async def resolve_source_tier(
    silo_id: str,
    evidence_refs: list[str],
    agent_hint: str | None = None,
) -> tuple[SourceTier, str]:
    """Returns (tier, resolution_layer) for metrics.
    
    Checks ALL evidence refs and returns the HIGHEST tier found.
    """
    best_tier: SourceTier = SourceTier.UNKNOWN
    best_layer: str = "fallback"
    
    # Batch fetch node tiers for all node:xxx refs
    node_ids = [ref[5:] for ref in evidence_refs if ref.startswith("node:")]
    node_tiers = await batch_get_node_tiers(node_ids) if node_ids else {}
    
    # Layer 1: Evidence node inheritance
    for node_id, tier in node_tiers.items():
        if tier and _TIER_RANK.get(SourceTier(tier), 0) > _TIER_RANK[best_tier]:
            best_tier = SourceTier(tier)
            best_layer = "evidence_node"
    
    # Layer 2+3: Silo rules then global rules
    rules = await get_source_rules_cached(silo_id)
    
    for ref in evidence_refs:
        if ref.startswith("node:"):
            continue
        for rule in rules:
            if fnmatch.fnmatch(ref, rule.pattern):
                rule_tier = SourceTier(rule.tier)
                if _TIER_RANK[rule_tier] > _TIER_RANK[best_tier]:
                    best_tier = rule_tier
                    best_layer = "silo_rule" if rule.silo_id else "global_rule"
                break  # first matching rule per URI
    
    # Already found something better than unknown?
    if best_tier != SourceTier.UNKNOWN:
        return best_tier, best_layer
    
    # Layer 4: Agent hint
    if agent_hint:
        try:
            return SourceTier(agent_hint), "agent_hint"
        except ValueError:
            pass
    
    return SourceTier.UNKNOWN, "fallback"
```

## Partner onboarding

Partners can self-service via API, or we can configure during onboarding.

### AiBen (regulatory/compliance)

```bash
# Partner self-service (uses their auth token)
curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $AIBEN_TOKEN" \
  -d '{"pattern": "https://eur-lex.europa.eu/*", "tier": "authoritative", "reason": "EU law"}'

# Or Engrammic admin setup
curl -X POST "https://api.engrammic.ai/admin/source-rules?org_id=$AIBEN_ORG" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"pattern": "https://finlex.fi/*", "tier": "authoritative", "reason": "Finnish law"}'
```

Typical rules for AiBen:
- `https://eur-lex.europa.eu/*` - authoritative (EU law)
- `https://finlex.fi/*` - authoritative (Finnish law)
- `https://curia.europa.eu/*` - authoritative (EU court decisions)
- `https://*.edpb.europa.eu/*` - authoritative (GDPR guidance)

### Comparables.ai (M&A intelligence)

Typical rules:
- `pitchbook://*` - authoritative (their primary data source)
- `https://pitchbook.com/*` - authoritative
- `crunchbase://*` - validated (secondary)
- `https://*.com/about*` - community (company self-reported)

## Out of scope

- LLM-based classification (expensive, slow, not obviously better than rules)
- Real-time rule updates via MCP (admin API is sufficient)
- Source tier decay over time (evidence freshness is separate concern)
- UI for rule management (CLI/API first)

## Done criteria

- [ ] Claims citing `.gov` URIs automatically get `authoritative` tier
- [ ] Claims citing nodes with `source_tier` inherit that tier
- [ ] Partners can configure custom rules via admin API
- [ ] Metrics show distribution of resolution layers
- [ ] At least one R1 or R2 promotion fires in test suite
