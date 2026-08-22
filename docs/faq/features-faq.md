# Features FAQ

For product, compliance, and delivery teams: what this agent does, what is deterministic vs
LLM, and, importantly, where its responsibilities **stop** and a sibling catalog system
takes over. Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`SPEC.md`](../../SPEC.md).

### What does Doc2 actually produce?

Four cited artifacts from a borrower's financial statements and filings:

1. A **`CreditMemo`**: borrower overview, financial analysis, a covenant section, a risk
   assessment, a peer comparison, and a recommendation rationale. It is decision SUPPORT for
   a credit officer, never a credit decision, and always sets `requires_human_review=True`.
2. **`Covenant[]`**: extracted from filings and agreements, each with a type, a threshold and
   operator, the current value, a status (`COMPLIANT` / `AT_RISK` / `BREACH`) and citations.
3. **`RiskFlag[]`**: identified risks with category, severity, detail and citations.
4. A **`PeerComparison`**: borrower metrics versus a peer set drawn from BigQuery, with the
   peer median, percentile and deltas.

Every claim carries a source-and-page `Citation`, and the whole run writes an immutable audit
trail.

### What is deterministic vs done by the LLM?

The consequential math is **deterministic and replayable** (pure stdlib, unit-tested): the
covenant compliance status (a single auditable comparison against the threshold, with the
`_AT_RISK_BAND` thin-headroom band), the peer median / percentile, and the maker-checker
escalation policy. The LLM only **narrates and drafts** (the memo prose, the recommendation
rationale) and **classifies** (covenant extraction, risk-flag severity). It never overrides a
covenant status: a `BREACH` computed from the numbers stays a `BREACH`. An auditor can
recompute every decision without the model. This is the "deterministic domain service"
pattern.

### Is anything auto-approved?

No. Every `CreditMemo` sets `requires_human_review=True`; `CreditReviewPolicy.requires_review()`
always returns True and `escalates()` only ever raises the bar (a `BREACH` covenant, a HIGH or
CRITICAL risk flag). The agent proposes and a qualified credit officer disposes; escalation
signals never lower the review bar and never auto-execute.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the credit-memo /
underwriting domain logic and its four artifacts. It **integrates** (via the `platform`
profile's thin HTTP adapters) several cross-cutting concerns owned by sibling platform
systems, do not rebuild these in a fork:

| Concern | Owned by (catalog id / repo) | Doc2's role |
|---|---|---|
| Runtime guardrail: PII redaction, prompt-injection / jailbreak defense | **Hrz1** `agent-guardrail-gateway` | consumes it on every run (input + output screen, rule R1) |
| Governed RAG / ACL-aware knowledge base with citations | **Hrz2** `enterprise-knowledge-base` | ingests filings into it, retrieves grounded passages from it |
| Agent registry, versioning, identity, entitlements | **Hrz3** `agent-registry` | publishes its A2A AgentCard for discovery |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | its eval metrics gate promotion; the offline gate mirrors it |
| Observability + immutable WORM prompt/response audit | **Hrz5** `agent-observability` | writes audit events to it; traces spans through it |
| Maker-checker review console for escalations | **Hrz7** (review console, rule R8) | routes a `requires_human_review` memo to it via `review-kit` |
| Regulatory Q&A / lending control checklists | **Rsk1** `compliance-advisory` | consumes it for regulatory compliance checks |
| On-prem, CPU-only DLP scrub before egress | **Rsk6** `onprem-dlp` | the sovereign-DLP option behind the redaction port |

So the guardrail, knowledge base, audit sink, eval platform and review console are
*dependencies*, not features of this repo. Doc2's own covenant / risk / peer logic is the
underwriting slice, distinct from the platform's runtime controls.

### Can I use this for a non-credit document-diligence product?

Yes, that is the point of the kernel/vertical seam. The reusable machinery (citations,
grounding, the deterministic engines, audit, eval, maker-checker) transfers to CDD / KYC,
trade-finance checking, claims triage, ESG due diligence, and similar. You replace the artifact
models (`Borrower`, `Covenant`, `RiskFlag`, `CreditMemo`, `PeerComparison`) and the prompts,
and retune the policy and taxonomy. See [`docs/ADOPTING.md`](../ADOPTING.md) and
[adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` builds a cited memo offline, writes the JSON, and renders a static audit-first HTML
view. `make demo-server` runs the live presenter-controlled server on `:8094`. Everything runs
on synthetic, fictional data (`Acme Manufacturing (FICTIONAL)`) with no cloud and no API key.
