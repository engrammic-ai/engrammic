# Source Tier Classification

Source tier classification controls how claims are evaluated for promotion to facts. When you store a claim via `learn`, Engrammic resolves its evidence URLs against a set of rules and assigns a quality tier. The Custodian uses that tier when running promotion checks.

## Tier definitions

| Tier | Meaning | Examples |
|------|---------|---------|
| `authoritative` | Primary legal or regulatory source; highest trust | Government domains, EUR-Lex, SEC filings, court records |
| `validated` | Professional data provider or curated academic source | Bloomberg, PitchBook, arXiv, `.edu` institutions |
| `community` | User-generated or self-reported content | LinkedIn, Medium, Wikipedia |
| `unknown` | No rule matched, no agent hint | Default when classification cannot be determined |

Claims with `authoritative` tier (and confidence >= 0.7) satisfy the R1 promotion rule. Claims with `community` or `unknown` tier will not promote to facts regardless of confidence.

## Resolution order

For each claim, Engrammic checks evidence in this order and returns the highest tier found across all evidence refs:

1. **Evidence node inheritance** - If evidence is a `node:<id>` reference and that node already has a `source_tier`, it is inherited. Documents ingested via connectors carry their tier forward.
2. **Silo rules** - Custom rules your organization configured. Checked before global rules.
3. **Global defaults** - Engrammic-maintained rules for common patterns (`.gov`, `.edu`, major data providers).
4. **Agent hint** - The `source_tier` parameter passed to `learn`. Used only when no rules match.
5. **Unknown** - Final fallback.

All evidence refs are checked. The highest-ranking tier across all matches wins.

## Global defaults (always active)

| Pattern | Tier | Note |
|---------|------|------|
| `https://*.gov/*` | authoritative | US federal/state government |
| `https://*.gov.*/*` | authoritative | Government country TLDs |
| `https://eur-lex.europa.eu/*` | authoritative | EU law |
| `https://*.europa.eu/*` | authoritative | EU institutions |
| `https://courtlistener.com/*` | authoritative | US court records |
| `sec://*` | authoritative | SEC filings |
| `https://*.edu/*` | validated | Educational institutions |
| `pitchbook://*` | validated | PitchBook |
| `bloomberg://*` | validated | Bloomberg |
| `crunchbase://*` | validated | Crunchbase |
| `https://arxiv.org/*` | validated | arXiv preprints |
| `https://linkedin.com/*` | community | LinkedIn (self-reported) |
| `https://medium.com/*` | community | Medium |
| `wikipedia://*` | community | Wikipedia |

## Admin API

The admin API uses static bearer key auth. Set `ADMIN_API_KEY` in your environment.

All patterns use [fnmatch glob syntax](https://docs.python.org/3/library/fnmatch.html). Use `/test` to validate before adding.

### List rules

```bash
# Global rules only
curl https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY"

# Silo rules plus global
curl "https://api.engrammic.ai/admin/source-rules?silo_id=$SILO_ID&include_global=true" \
  -H "Authorization: Bearer $ADMIN_API_KEY"
```

Response:

```json
{
  "rules": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "silo_id": "b9e1c234-...",
      "pattern": "https://eur-lex.europa.eu/*",
      "tier": "authoritative",
      "reason": "EU law",
      "priority": 100,
      "created_at": "2026-05-18T12:00:00Z",
      "created_by": null,
      "source": "silo"
    },
    {
      "id": "...",
      "silo_id": null,
      "pattern": "https://*.gov/*",
      "tier": "authoritative",
      "source": "global"
    }
  ]
}
```

### Add a rule

```bash
curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pattern": "https://eur-lex.europa.eu/*",
    "tier": "authoritative",
    "reason": "EU official law database",
    "priority": 100,
    "silo_id": "'"$SILO_ID"'"
  }'
```

To create a global rule (applies to all silos), omit `silo_id`. Returns `201` with the created rule. Returns `409` if the pattern already exists for that silo.

Field reference:

| Field | Required | Notes |
|-------|----------|-------|
| `pattern` | yes | fnmatch glob, max 500 chars |
| `tier` | yes | `authoritative`, `validated`, or `community` |
| `reason` | no | Human-readable description |
| `priority` | no | 0-1000, default 0. Higher = checked first. |
| `silo_id` | no | Target silo UUID. Omit for global rule. |

### Delete a rule

```bash
curl -X DELETE "https://api.engrammic.ai/admin/source-rules/$RULE_ID" \
  -H "Authorization: Bearer $ADMIN_API_KEY"
```

Returns `204` on success, `404` if not found. The `rule_id` comes from the `id` field in list or add responses.

### Test resolution (debug)

Run the resolver against a set of evidence refs without storing anything. Use this before adding rules to verify they match the right URLs.

```bash
curl -X POST https://api.engrammic.ai/admin/source-rules/test \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "evidence_refs": ["https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679"],
    "silo_id": "'"$SILO_ID"'",
    "agent_hint": "validated"
  }'
```

Response:

```json
{
  "resolved_tier": "authoritative",
  "resolution_layer": "global_rule",
  "matched_rule": {
    "id": "...",
    "pattern": "https://eur-lex.europa.eu/*",
    "tier": "authoritative",
    "silo_id": null
  }
}
```

`resolution_layer` values: `evidence_node`, `silo_rule`, `global_rule`, `agent_hint`, `fallback`.

When `silo_id` is omitted from the test request, only global rules apply.

## Common patterns by partner type

### Regulatory / compliance (e.g. AiBen)

```bash
# EU law and GDPR guidance
curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "https://finlex.fi/*", "tier": "authoritative", "reason": "Finnish law", "priority": 100, "silo_id": "'"$SILO_ID"'"}'

curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "https://curia.europa.eu/*", "tier": "authoritative", "reason": "EU court decisions", "priority": 95, "silo_id": "'"$SILO_ID"'"}'

curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "https://*.edpb.europa.eu/*", "tier": "authoritative", "reason": "GDPR guidance", "priority": 90, "silo_id": "'"$SILO_ID"'"}'
```

Note: `https://eur-lex.europa.eu/*` is already in global defaults as `authoritative`.

### M&A intelligence (e.g. Comparables.ai)

```bash
# PitchBook as authoritative (already validated in global; override for this silo)
curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "pitchbook://*", "tier": "authoritative", "reason": "Primary deal database", "priority": 100, "silo_id": "'"$SILO_ID"'"}'

curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "https://pitchbook.com/*", "tier": "authoritative", "reason": "PitchBook web", "priority": 100, "silo_id": "'"$SILO_ID"'"}'

# Company self-reported pages as community
curl -X POST https://api.engrammic.ai/admin/source-rules \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "https://*.com/about*", "tier": "community", "reason": "Company self-reported", "priority": 10, "silo_id": "'"$SILO_ID"'"}'
```

## Caching behavior

Rules are cached with a 5-minute TTL. Changes take effect within 5 minutes. If you need immediate propagation during onboarding setup, adding rules before running any `learn` calls avoids the cache window.

## Pattern tips

- Use `*` for any path segment: `https://example.com/*` matches all pages on that domain.
- Use `https://*.example.com/*` to match all subdomains.
- Custom URI schemes are supported: `pitchbook://*`, `sec://*`, `bloomberg://*`.
- Patterns are matched with fnmatch (not regex). Test with the `/test` endpoint before deploying.
- Silo rules always take precedence over global rules of the same priority.
