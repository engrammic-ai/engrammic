# ICP and GTM strategy (2026-05-29)

Status: working decision, formed during Antler residency week 4 of 8.

## The deadline that frames everything

Antler funds us in June only if we show concrete LOIs or paying customers. They will be
strict about it. We have roughly four to five weeks. Paying customers in that window are
unrealistic, so the target is LOIs. An LOI only counts if it is concrete: named company,
specific use case, an intent to pay with a rough number, and a near-term condition. "Excited
to explore" does not count.

Open question still to confirm with Antler: how many LOIs, and does one strong enterprise
letter substitute for several smaller ones?

## The diagnosis: we were selling memory to people who build memory

Our warm pipeline is mostly other AI-infra and AI-trust companies, which are peers and
near-competitors, not buyers. Infra companies are the least likely customers for an infra
product because the thing we sell is the thing they treat as their own IP. This is why
"memory" has not converted. It is an audience problem, not a pitch problem.

Pipeline triage as of today:

- AiBEN (aiben.io): zero-hallucination AI for document-critical regulated industries
  (compliance, legal, audit, insurance, finance), page-level citations, on-prem,
  model-agnostic. Finnish. This is our value proposition productized for a vertical. Strongest
  name but murkiest fit: either a near-competitor or an OEM partner, and enterprise-slow.
  Pursue only for a lightweight champion-signed LOI, and only if a champion can sign without
  invoking legal. Demote from deadline to pipeline if it needs procurement.
- Realm (withrealm.com): AI agents for enterprise sales RFPs and security questionnaires.
  Built their own context graph. Builds, does not buy. Peer.
- control.dev / Agent Control: open-source control plane for agent fleets. Infra peer.
- flow.ai: likely agent infra, still ambiguous. Probable peer.
- zero inc: unknown, weak.

Lesson Realm hands us for free: they sell "filled RFPs and answered security questionnaires,"
a concrete outcome with a number, not "a context graph." Never sell the graph. Sell the
outcome and the number.

## The ICP: the mem0 graduate

We still sell memory. We just sell it to a specific slice of the memory market: teams who
already adopted a memory tool, scaled, and are now getting burned by it. Not first-time
shoppers (they pick the cheap default and it is good enough), not infra peers (they build
their own).

Profile:

- Has an AI agent in production, past the demo stage
- Already using mem0, Zep, Letta, or homegrown memory, so the category and budget exist
- Memory store has grown past the toy phase, big enough to be noisy
- Hitting the reliability wall: stale recall, contradictory memories, hallucinated entries,
  no way to audit why the agent believed something
- Those failures cause visible, costly agent mistakes
- Application layer, buys infra rather than building it
- Champion is the eng lead or founder who owns the agent and is personally annoyed by the
  memory bugs

Trigger event we sell into: "our agent did something wrong because it remembered something
stale or false, and we could not explain why." The pitch is "you have outgrown mem0." That is
far easier than selling memory from scratch, because they already believe in memory and are
bleeding from the cheap version.

Anti-ICP: first-time memory shoppers, infra and platform peers who build their own, and cold
enterprises (slowest, need the most credibility, worst fit for our timeline).

## Positioning: cost opens the door, wrong-cost closes the deal

"Token cost reduction" is what the market is pulling on, but it is also mem0's headline claim
and our infra is heavier, so we would lose a head-on cost fight. So:

- Use the cost angle as the outreach hook to get the meeting.
- In the room, pivot to the differentiated angle we own: the cost of the agent being
  confidently wrong, plus auditability. Cost gets us in, correctness wins it.

Never lead with "epistemic memory" or the layer vocabulary. Lead with the outcome and a
number.

## Credibility, without a brand yet

Two founders, no track record, selling reliability infra. "Get lucky with enterprise" is the
wrong path on this clock: enterprise needs the most credibility and moves slowest. The paths
that actually work:

1. Self-generated: a fair, public Engrammic-vs-mem0 benchmark on memory accuracy,
   contradiction handling, and stale recall. For infra, the benchmark is the credential. It
   also doubles as the proof-number for LOIs and as content for the channel below. This is the
   highest-leverage thing the technical founder builds this week. Caveat: it has to be honest.
   If we do not clearly win, that is critical information about differentiation, not something
   to hide, and it is a pivot signal.
2. Borrowed: get one operator to vouch (an operator-angel, a weighty advisor, or a first
   design partner willing to be a public reference). Use the Antler name in outreach. Realm
   got the Slack and Deel founders to back them and it is in every headline about them.
3. Low-trust entry: never ask anyone to rip out mem0. Ask for a side-by-side eval or a shadow
   run on their real data. They bet on a test, not on us. Converts to an LOI on results, and
   neutralizes the credibility gap.

## Distribution channel: go where mem0's burned users complain

For a memory product with no brand, the channel is the incumbent's pain, voiced in public:

- mem0's own GitHub issues (open source): "stale facts," "contradictory memories,"
  "hallucinated entries." Named, pain-identified leads.
- Letta/MemGPT and Zep Discords, r/LocalLLaMA, AI-engineering X, Hacker News agent-memory
  threads.

Reach out referencing their specific complaint. This beats the MCP listing and the installer
funnel for finding paying intent. The self-serve surfaces are credibility and retention
layers, not a revenue channel at this stage.

## Sales motion

Founder-led, concierge, design-partner sales. Vic runs outreach full-time starting now, both
working the qualified existing names and generating fresh application-layer top-of-funnel
(30 to 40 names) outside the builder pond. Rough funnel: three LOIs needs about 15 to 20
qualified conversations, which needs about 50 touches. Whichever pain converts during these
four weeks is also our pivot thesis if June does not land, so the sprint pays off either way.

## What to do this week

- Technical founder: build the honest Engrammic-vs-mem0 benchmark and get one real
  before/after number.
- Vic: audit the pipeline buyer-vs-peer, fast-qualify AiBEN's champion-LOI question, and start
  fresh application-layer outreach sourced from mem0 complaint threads.
- Both: confirm Antler's exact LOI bar (count, and whether quality substitutes for quantity).
