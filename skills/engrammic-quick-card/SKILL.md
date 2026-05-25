---
name: engrammic:quick-card
description: 10-line EAG workflow reference. Embed inline for sticky reminders.
---

# EAG Quick Card

**Protocol:** RECALL → STORE → LINK → REFLECT

| Step | Action |
|------|--------|
| Before store | `recall(query="<topic>")` - check existing |
| Raw observation | `remember(content, tags)` |
| Fact with source | `learn(claim, evidence=[...], source)` |
| Conclusion from facts | `recall` facts → `believe(conclusion, about=[node_ids])` |
| Related nodes | `link(from, to, relationship)` |
| Understanding changed | `reflect(observation, type, about)` |
| Uncertain conclusion | `hypothesize` → `revise` → `commit` |

**Never:** Store without recalling first. Form beliefs without about_node_ids. Ignore contradictions.
