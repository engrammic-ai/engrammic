---
name: coding:onboarding
description: ICP onboarding for coding and dev agents. Use at session start to learn how to use Engrammic memory while writing, reviewing, and debugging code - what to remember, when to learn with evidence, and when to form beliefs.
---

# Engrammic onboarding: coding agents

You are using Engrammic, epistemic memory for AI agents. This guide tunes the
defaults for code work.

## What to put where

- `remember`: transient context you will want later this session - a failing
  command, a file path, a stack trace. No evidence needed.
- `learn`: a durable claim about the codebase with evidence (a file:line, a
  test result, a commit). Example: "Auth tokens expire after 15m" with the
  config line as evidence.
- `believe`: a synthesized engineering position drawn from several facts.
  Example: "this module is the right integration point." Cite the nodes it
  rests on.
- `recall`: before solving, query what is already known about the area.
- `trace`: when a belief drives a risky change, check its provenance first.
- `reflect`: record when a debugging session or test result changes your
  understanding of how the code behaves.

## Heuristics for code

- Prefer `learn` over `remember` for anything another engineer would need to
  trust. Evidence is the difference between a note and a fact.
- After a debugging session, `reflect` when your understanding changed.
- Recall is tuned to return more candidates for this ICP. Narrow with a
  specific query rather than broad terms.

## When not to store

Do not store generated code, secrets, or anything reconstructable from the
repo. Store the decision and its evidence, not the diff.
