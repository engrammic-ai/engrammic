# W3: Launch Prep

Parent: [oss-master.md](./oss-master.md)

Goal: Repo hygiene, landing page, distribution prep for launch day.

Depends on: W1 (engine) and W2 (manifesto) mostly complete.

## Tasks

### Task 1: CONTRIBUTING.md — primitives

- [ ] Create primitives/CONTRIBUTING.md with:
  - How to set up dev environment
  - How to run tests
  - PR process
  - Code style (ruff, mypy strict)
  - No CLA required (MIT)
- [ ] Commit

### Task 2: CONTRIBUTING.md — engine

- [ ] Create engine/CONTRIBUTING.md with:
  - How to set up dev environment
  - How to run tests
  - PR process
  - Code style
  - Note on Apache 2.0 license
- [ ] Commit

### Task 3: CODE_OF_CONDUCT — both repos

- [ ] Add CODE_OF_CONDUCT.md to primitives (Contributor Covenant)
- [ ] Add CODE_OF_CONDUCT.md to engine
- [ ] Commit both

### Task 4: Issue templates — primitives

- [ ] Create .github/ISSUE_TEMPLATE/bug_report.md
- [ ] Create .github/ISSUE_TEMPLATE/feature_request.md
- [ ] Commit

### Task 5: Issue templates — engine

- [ ] Create .github/ISSUE_TEMPLATE/bug_report.md
- [ ] Create .github/ISSUE_TEMPLATE/feature_request.md
- [ ] Commit

### Task 6: README update — primitives

- [ ] Update primitives/README.md with:
  - Link to manifesto
  - Clear "what this is" section
  - Installation instructions
  - Link to engine repo
- [ ] Commit

### Task 7: README update — engine

- [ ] Verify engine/README.md has:
  - Link to manifesto
  - "Why Apache 2.0" section
  - Quickstart
  - Link to primitives
- [ ] Commit

### Task 8: Landing page — design

- [ ] Decide hosting (Vercel, Cloudflare Pages, etc.)
- [ ] Wireframe layout:
  - Hero with hook
  - Manifesto content or link
  - Get started CTA
  - Waitlist form
- [ ] Document in context/brainstorm/ or design doc

### Task 9: Landing page — build

- [ ] Build landing page
- [ ] Manifesto rendered or linked
- [ ] Waitlist form (Typeform, Tally, or custom)
- [ ] Deploy to staging
- [ ] Review

### Task 10: Landing page — waitlist backend

- [ ] Set up waitlist collection (Notion, Airtable, or DB)
- [ ] Connect form to backend
- [ ] Test submission flow
- [ ] Set up notification for new signups

### Task 11: HN Show HN post — draft

- [ ] Write Show HN title (<80 chars)
  - Format: "Show HN: [Product] - [one-line hook]"
  - Example: "Show HN: Delta Prime - Memory for AI agents that knows what held up"
- [ ] Write submission text (2-3 sentences):
  - What it is
  - Why it's different
  - Link to manifesto
- [ ] Save draft in context/brainstorm/

### Task 12: HN Show HN post — timing

- [ ] Research low-competition posting times
  - Generally: Tuesday-Thursday, 8-10am PT
  - Avoid: weekends, major tech news days
- [ ] Pick target date
- [ ] Designate who posts (has HN account with karma)

### Task 13: Social posts — Twitter

- [ ] Write Twitter thread (3-5 tweets):
  1. Hook + link to manifesto
  2. The problem (RAG for chatbots)
  3. The shift (filing cabinet vs analyst)
  4. Getting started
  5. CTA (waitlist or star repo)
- [ ] Save draft

### Task 14: Social posts — LinkedIn

- [ ] Write LinkedIn post (longer form):
  - Hook
  - Problem
  - Solution
  - Link to manifesto
  - CTA
- [ ] Save draft

### Task 15: Launch day checklist

- [ ] Create launch day checklist:
  - [ ] Both repos set to public
  - [ ] Landing page live
  - [ ] Manifesto accessible
  - [ ] HN post submitted
  - [ ] Twitter thread posted
  - [ ] LinkedIn post posted
  - [ ] Monitor GitHub issues
  - [ ] Monitor HN comments
  - [ ] Respond to early questions

## Done Criteria

- [ ] Both repos have CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue templates
- [ ] Both READMEs updated with cross-links and manifesto link
- [ ] Landing page live on staging with working waitlist
- [ ] HN post drafted and timing picked
- [ ] Social posts drafted
- [ ] Launch day checklist ready
