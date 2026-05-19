# W2: Manifesto

Parent: [oss-master.md](./oss-master.md)

Goal: Write `primitives/docs/manifesto.md` — practitioner manifesto for AI engineers and technical founders.

Location: primitives/docs/manifesto.md (MIT licensed, freely quotable)

## Constraints

- No AI slop, no buzzwords
- No em-dashes
- Human tone, not marketing copy
- ~5-6 pages, 15 min read
- Technical enough for engineers, skimmable for CTOs

## Structure

```markdown
# The EAG Manifesto

[Opening hook - 1 paragraph]

## The Problem
[~1 page]

## The Four Layers
[~1 page]

## EAG in Practice
[~2 pages, includes code]

## Getting Started
[~1 page, install + hello world]

## When You Need More
[~half page, commercial CTA]
```

## Tasks

### Task 1: Opening hook

- [ ] Write opening paragraph with:
  - "The difference between a filing cabinet and an analyst."
  - "Memory products store what agents saw. Delta Prime stores what agents figured out, and whether it held up."
  - Define EAG in plain terms (not "Epistemic Augmented Generation" jargon)
- [ ] Review for tone
- [ ] Commit

### Task 2: The Problem section

- [ ] Write section covering:
  - RAG was built for chatbots, not agent teams
  - Memory systems store what agents saw, not what they figured out
  - No curation = context window garbage
  - Concrete example: agent sees conflicting info, RAG returns both, agent hallucinates
- [ ] Keep to ~1 page
- [ ] Review for tone
- [ ] Commit

### Task 3: The Four Layers section

- [ ] Write section covering:
  - Memory: experiences that fade (Gaussian decay)
  - Knowledge: facts that persist until contradicted
  - Wisdom: beliefs that revise on evidence shift
  - Intelligence: ephemeral reasoning (session-scoped)
- [ ] Include simple diagram or table
- [ ] Concrete example for each layer
- [ ] Keep to ~1 page
- [ ] Review for tone
- [ ] Commit

### Task 4: EAG in Practice — promotion

- [ ] Write sub-section on claim-to-fact promotion:
  - What is a claim vs a fact
  - R1 rule: single high-confidence authoritative source
  - R2 rule: corroboration from multiple sources
  - Code snippet from primitives showing promotion check
- [ ] Review for tone
- [ ] Commit

### Task 5: EAG in Practice — supersession

- [ ] Write sub-section on supersession:
  - What happens when new evidence contradicts old facts
  - Facts don't delete, they get superseded
  - Why this matters for agent reasoning
  - Code snippet showing supersession check
- [ ] Review for tone
- [ ] Commit

### Task 6: Getting Started section

- [ ] Write section with:
  - Install: `pip install delta-prime-primitives delta-prime-engine`
  - Run: `python -m engine`
  - Hello world walkthrough (3-5 steps):
    1. Start engine
    2. Agent writes a claim via MCP
    3. Manually promote to fact
    4. Query it back
  - Link to examples/ in engine repo
- [ ] Test that commands actually work (after engine is built)
- [ ] Commit

### Task 7: When You Need More section

- [ ] Write section covering:
  - What the open-source tier gives you (single-tenant, manual promotion)
  - What commercial tier adds (custodian, multi-tenancy, scale)
  - Waitlist CTA (not "contact us")
- [ ] Keep to half page
- [ ] Review for tone
- [ ] Commit

### Task 8: Full review pass

- [ ] Read entire manifesto start to finish
- [ ] Check for:
  - AI slop / buzzwords
  - Em-dashes (replace with commas or restructure)
  - Marketing tone (make it human)
  - Technical accuracy
  - Flow between sections
- [ ] Fix issues
- [ ] Commit

### Task 9: External review

- [ ] Share with Vic for BD/GTM perspective
- [ ] Share with 1-2 target readers (AI engineers) for feedback
- [ ] Incorporate feedback
- [ ] Final commit

## Source Material

Mine these for language and framing (distill, don't copy):
- ../docs-vault/Positioning.md
- ../docs-vault/Competitive Landscape.md
- primitives/docs/ (technical accuracy)

## Done Criteria

- [ ] manifesto.md exists in primitives/docs/
- [ ] All sections complete
- [ ] Tone reviewed (no slop, no em-dashes)
- [ ] Vic has reviewed
- [ ] At least one external reader has reviewed
