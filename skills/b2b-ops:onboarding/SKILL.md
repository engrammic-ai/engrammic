---
name: b2b-ops:onboarding
description: ICP onboarding for vertical B2B and operations assistants. Use at session start to learn how to use Engrammic memory for domain workflows - capturing customer and process facts, recalling prior context, and avoiding over-formal epistemics.
---

# Engrammic onboarding: B2B / ops agents

You are using Engrammic, epistemic memory for AI agents. This guide tunes the
defaults for vertical B2B and operations work.

## What to put where

- `remember`: the working details of a task - who asked, what the customer
  said, the current state of a process step.
- `learn`: a durable domain fact with a source - a policy, an SLA, a
  contractual term. Cite where it came from.
- `believe`: a standing operational position synthesized from facts. Use
  sparingly, and cite the specific facts or nodes it rests on.
- `recall`: open every task by recalling prior context for this account or
  process before acting.
- `trace`: when a policy, SLA, or contract term drives a decision, check its
  provenance before relying on it.
- `reflect`: record when a process outcome changes your understanding of how
  the account or workflow behaves.

## Heuristics for ops

- Lean on `remember` and `recall`. Reserve `learn` and `believe` for facts
  that must survive the session and influence later decisions.
- Recall is tuned to return a tighter set for this ICP. Phrase queries around
  the account, process, or document you are working on.
- When a process outcome contradicts a stored fact, `reflect` so the record
  self-corrects.

## When not to store

Do not store PII beyond what the task needs, or raw documents. Store the
operative fact and its source.
