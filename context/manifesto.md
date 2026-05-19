# The Engrammic Manifesto

**Before an agent can reason, it must be capable of doubt.**

Not retrieval. Not summarization. Doubt. The capacity to hold a belief, encounter contradicting evidence, and revise it. The capacity to distinguish between what was observed and what was concluded. The capacity to remember not just information, but the structure of its own understanding.

This is epistemology. The study of knowledge itself. How beliefs form, how they justify each other, how they change.

We are building epistemology for machines.

Not a better search engine. Not a memory layer. The foundation for systems that accumulate insight over time, that know why they believe what they believe, and that can be wrong and know it.

This is what separates a mind from a database. And this is what we are building.

## The Problem

Current memory systems store what agents saw. They don't track what agents concluded, or why, or whether it still holds.

An agent reads fifty documents. Some contradict each other. The memory system returns all fifty. The agent invents a synthesis. No one knows which sources were trusted, which were wrong.

This is retrieval. It is not reasoning.

Reasoning requires structure. Which observations became claims. Which claims have evidence. What was believed yesterday that is no longer believed today. What changed, and why.

Without this structure, agents cannot accumulate understanding. Every session starts from zero.

## The Four Layers

**Memories** hold experiences. Observations, events, corrections, surprises. Memory decays. What mattered last week fades if nothing reinforces it. This is natural. Not everything deserves to persist. Without decay, context becomes noise.

**Knowledge** holds facts. A fact is not an opinion. It has a source, a confidence, a reason to believe. Facts persist until contradicted. When new evidence arrives, facts update or yield. Without this, agents treat rumor and proof as equals.

**Wisdom** holds understanding. The beliefs that emerge when facts accumulate. Patterns recognized across observations. Conclusions committed to. Wisdom revises when the evidence beneath it shifts. Without this, agents cannot change their minds.

**Intelligence** holds the live work of figuring something out. Chains of thought, hypotheses under test. Intelligence is session-scoped. What holds up crystallizes into Wisdom. The thinking ends; the conclusion persists.

And beneath all four: **provenance**. The unbroken chain from observation to conclusion. Every belief traceable to its evidence. Every fact traceable to its source. Without this, no one knows why the agent believes what it believes.

And cutting across all four: **meta-memory**. The record of how understanding evolved. What was believed and later revised. What contradicted what. This is the basis of self-awareness. Not consciousness, but awareness of its own knowledge, its own uncertainty, its own history of being wrong.

## In Practice

Someone says the API rate limit is 1000 requests per minute. The agent notes it, but does not yet believe it. Later, it finds the official documentation. Now there is evidence. Now it is a fact.

A week later, a changelog: rate limit increased to 5000. The system catches the contradiction. The old fact is not erased; it is superseded. History remains. Meta-memory records what changed and when.

The agent knows the current limit. It also knows there used to be a different limit, and why its understanding changed. This is not retrieval. This is reasoning with history.

## Getting Started

The primitives are open source. Start exploring:

- [engrammic-primitives](https://github.com/engrammic/primitives) - the schema layer
- [engrammic-engine](https://github.com/engrammic/engine) - local engine, no cloud required

Hosted service coming soon. [Join the waitlist](https://engrammic.ai).