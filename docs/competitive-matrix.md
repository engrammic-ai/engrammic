# Competitive Landscape Matrix

Last updated: 2026-05-18

## Top Competitors

| Capability          | Mem0    | Zep     | NeoCognition | Google Memory Bank | Engrammic |
| ------------------- | ------- | ------- | ------------ | ------------------ | --------- |
| Multi-agent sharing | Y       | -       | ?            | Y                  | Y         |
| Org-level scope     | partial | -       | ?            | Y                  | Y         |
| Evidence required   | -       | -       | -            | -                  | Y         |
| Provenance ("why?") | -       | partial | ?            | -                  | Y         |
| Self-host           | Y       | Y       | -            | -                  | Y         |
| MCP support         | Y       | Y       | -            | Y                  | Y         |

Legend: Y = yes, - = no, ? = unclear/claimed, partial = limited support

## Notes

**Mem0** - Funded incumbent ($24M, AWS deal). Multi-agent via user_id/session_id keying. 55k+ GitHub stars. Graph memory paywalled at Pro tier. Their own community audit found 97% of stored memories were noise.

**Zep/Graphiti** - YC-backed temporal knowledge graph. 20k GitHub stars. Tracks when facts were true/superseded (partial provenance). Single-agent enrichment focus.

**NeoCognition** - $40M seed (April 2026). Ohio State research pedigree. Claims "world model" and self-learning agents but hasn't shipped details. Sells finished agents, not infrastructure.

**Google Memory Bank** - Part of Gemini Enterprise Agent Platform (GA April 2026). Memory Profiles for long-term context. Org-level scoping. GCP-only, no self-host.

## Engrammic Differentiators

1. **Evidence at write** - `learn` requires evidence URI, not post-hoc verification
2. **Provenance chains** - `trace` answers "why do I believe X?"
3. **Org-level as primitive** - silos and scope-gated retrieval from day one
4. **Open-core + MCP-native** - self-host or managed, drops into any MCP client

## Sources

- [Mem0 State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Zep Graphiti GitHub](https://github.com/getzep/graphiti)
- [NeoCognition $40M Announcement](https://www.prnewswire.com/news-releases/neocognition-emerges-from-stealth-with-40-million-seed-round-to-advance-specialized-intelligence-and-expert-agents-302749108.html)
- [Google Memory Bank Docs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank)
