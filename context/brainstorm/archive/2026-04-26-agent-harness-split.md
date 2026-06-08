# Agent Harness Protocol Split

**Date:** 2026-04-26
**Status:** resolved
**Resolution:** Protocol in primitives (open), implementations in context-service (private)

## Context

The context-service codebase contains pydantic-ai agent harnesses for the Custodian visit phases (fast, plan, deep, stitch). Each agent combines:

1. **Model selection** (flash vs pro)
2. **System prompts** (proprietary reasoning instructions)
3. **Output types** (Pydantic models for structured responses)
4. **Budget constraints** (token limits, tool call limits, wrap-up signals)
5. **Tool definitions** (fetch_members, commit_claim, finalize_visit, etc.)

As primitives becomes the open-source foundation for EAG, we need to decide what lives here vs what stays private.

## Options Considered

### Option A: Everything in primitives

- Description: Move agents, prompts, and tools wholesale to primitives
- Pros: Single source of truth; community can run full Custodian locally
- Cons: Exposes proprietary prompts (core IP); tool definitions leak product-specific semantics; tightly couples open library to product

### Option B: Protocol in primitives, implementations private

- Description: Define AgentProtocol, ToolProtocol, result types in primitives; keep actual agents, prompts, and tool implementations in context-service
- Pros: Clear separation of interface vs implementation; community can build agents following the protocol; prompts stay proprietary
- Cons: Two repos to coordinate; community can't run Custodian out of the box

### Option C: Nothing in primitives

- Description: Keep all agent code in context-service; primitives stays pure data types
- Pros: Simplest; no coordination overhead
- Cons: No public contract for agent development; harder for community to build compatible tooling

## Decision

**Option B: Protocol in primitives, implementations private.**

Rationale:
1. **Prompts are IP.** The system prompts encode years of iteration on how to make agents reason correctly about knowledge synthesis. Publishing them erases a moat.
2. **Tool definitions are product-specific.** fetch_members, commit_claim, etc. expose internal data model details (clusters, findings, citations). The protocol abstracts over this.
3. **Community value is in the interface.** Developers building EAG-compatible agents need to know what shape deps take, what results look like, how budget flows through. They don't need our specific prompt text.
4. **Matches industry pattern.** OpenAI's assistants SDK defines tool schema without exposing implementation; LangChain separates base types from integrations.

## Consequences

1. **primitives exports:**
   - `AgentProtocol`, `AgentResult`, `AgentConfig`, `AgentPhase`
   - `ToolProtocol`, `ToolResult`, `ToolDefinition`
   - `DepsProtocol`, `BudgetStatus`, `BudgetConfig`

2. **context-service keeps:**
   - `build_*_agent()` factories
   - System prompts in config/prompts/custodian/
   - Tool implementations (fetch_members, commit_claim, etc.)
   - VisitDeps concrete class
   - Output recovery and validation logic

3. **Community can:**
   - Build agents that implement AgentProtocol
   - Define tools that implement ToolProtocol
   - Integrate with EAG infrastructure by respecting the protocol contract

4. **We must:**
   - Keep protocol stable (semantic versioning)
   - Document the expected behavior (budget rebuild, seen_node_ids tracking, commit patterns)
   - Ensure context-service implements the protocol (not just compatible shapes)

## Open Questions

None. Implementation complete.
