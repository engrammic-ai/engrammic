# Notion Docs Update

Chore: update Notion wiki pages to reflect v2 architecture changes.

## Branch

`chore/notion-docs-update`

## Pages to update

1. **MCP Tool Reference** - now 9 tools (was 7), add context_accept_belief / context_reject_belief
2. **Error Handling** - document error envelope format `{success, error: {code, message, details}}`
3. **Architecture Overview** - add outbox pattern, raw Cypher mixin, hydration registry
4. **ProposedBelief Flow** - new page documenting the accept/reject workflow
5. **Confidence Computation** - document partial_confidence for uncorroborated claims

## Notes

- Use Notion MCP tools for updates
- Keep tone human, no AI-slop (per feedback_doc_tone.md)
- No em-dashes (per feedback_no_em_dashes.md)

## Done criteria

- [ ] All 5 pages updated/created
- [ ] Tool count matches CLAUDE.md (9 tools)
- [ ] Error envelope examples added
