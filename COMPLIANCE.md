# COMPLIANCE: Doc2 Credit-Memo / Underwriting Assistant

How Doc2 maps the catalog's General Principles (P-01..P-12) and platform Rules (R1..R6, R8) to
concrete controls in THIS repo. Items genuinely not applicable are marked n/a with a
reason. All borrower data shipped in this repo (`tests/fixtures`, `eval/datasets`) is
fictional.

## General Principles

| Principle | Status | Control in this repo |
| --- | --- | --- |
| P-01 Human accountability | Met | `CreditReviewPolicy` forces `requires_human_review=True` on every memo; the CLI/API banner states it is decision support, not a credit decision. |
| P-02 No vendor lock-in / ports and adapters | Met | Hexagonal core; `ports/` Protocols; `adapters/{gcp,local,platform,onprem}`; one `profile` switch; `tests/contract/test_port_parity.py` proves both `local` (answers in-process) and `onprem` (fails fast) parity. The `local` profile runs the whole memo pipeline off-cloud with no google-cloud package imported. |
| P-03 Least privilege | Met | MCP tool catalog exposes only the four credit-memo skills; borrower-scoped ACL tags on every Hrz2 ingest/search; IAM in `infra/terraform/iam.tf`. |
| P-04 Minimise data to the model | Met | Redaction runs first in the pipeline (`memo_service`), and again at the ADK model boundary (`agent/callbacks.py`); DLP de-identify in `dlp_redaction.py`. |
| P-05 Data residency | **Partial** | Region defaults to `asia-southeast1` in `config/settings.yaml` and every `infra/terraform` resource derives its location from it except the two that cannot; the deploy-time value is validated against the `allowed_regions` residency allowlist, and extending that list is the review point; regional Model Armor / BigQuery endpoints. The two resources that could not sit in region are **gone**: the Document AI processor (which parsed borrower financials in the `us` multi-region on the `rc` channel) and the Agent Search corpus (which serves `global`/`us`/`eu` and no Cloud region at all). Text extraction is pypdf over the uploaded bytes in-process, and retrieval is a per-request index, so every resource this stack creates is regional. `gcp.resourceLocations` admits `global` for grounded model calls only (`allow_global_endpoints`), which is a statement about where a QUERY may go: no stored data leaves the region. |
| P-06 Maker-checker | Met | `CreditReviewPolicy.requires_review()` always True; BREACH covenant or HIGH/CRITICAL flag escalates; audit decision ESCALATED; the escalation is ROUTED to the Hrz7 maker-checker console (rule R8), not left as a boolean (`ports/review_router.py`, `adapters/*/review_router.py`). |
| P-07 Everything cited and audited | Met | Every figure/covenant/risk carries a `Citation`; `AuditEvent` written to Cloud Logging (`cloud_logging_audit.py` / Hrz5) on every interaction. |
| P-08 Quality / model-risk gate | Met | `eval/run_eval.py` + `eval/rubrics/*.yaml`; thresholds enforced in CI (`eval-gate.yaml`); Hrz4 gate via `EvaluationGatePort`. |
| P-09 Determinism where it matters | Met | Covenant compliance is a deterministic calculation (`_grounded.covenant_status`); peer comps are arithmetic; the LLM never overrides either. |
| P-10 Observability / FinOps | Met | `CloudTraceTracerAdapter` spans + token-usage metrics; message-content capture OFF. |
| P-11 Secure SDLC | Met | Offline lint+type+test gate runs on the `local` profile (no GCP SDK); pinned deps; non-root Dockerfile; secrets gitignored. |
| P-12 Reversibility | Met | The `local` family proves the domain runs entirely off-cloud (SDK-free, end to end), and the `onprem` family is the documented sovereign migration exit with proven interface parity (P-02). |

## Platform Rules

| Rule | Status | Control |
| --- | --- | --- |
| R1 Hrz1 guardrail + redaction (PII vertical) | Met | Full pipeline: redact -> guardrail(INPUT) -> ... -> guardrail(OUTPUT); `GuardrailPort` + `PIIRedactionPort` bound to Model Armor / DLP (gcp) or the Hrz1 gateway (platform). |
| R2 Hrz5 audit | Met | `AuditSinkPort` -> Cloud Logging (gcp) / Hrz5 `/v1/audit` (platform); already-redacted records at the project's own retention. The locked ~7-year WORM bucket was removed: it would outlive by a factor of a hundred and seventy the analyses it describes, whose evidence is deleted after 15 days. |
| R3 Hrz2 governed RAG | Met | `KnowledgeBaseClientPort` -> Hrz2 `/v1/ingest` + `/v1/search` with borrower ACL tags; Doc2 builds no retrieval backend of its own. |
| R4 Hrz3 registry | Met | `AgentRegistryPort` -> Hrz3 `/v1/agents`; A2A AgentCard at `/.well-known/agent-card.json`. |
| R5 Hrz4 eval gate at promotion | Met | `EvaluationGatePort` -> Hrz4 `/v1/evaluations` + `/v1/gate`; offline mirror in `eval/run_eval.py`. |
| R6 Rsk3 validation at intake | n/a in code | Doc2 is validated by Rsk3 at intake as a consuming check; there is no in-repo Rsk3 client (Rsk3 calls Doc2, not the reverse). The repo exposes the contract Rsk3 validates (SPEC §6) and the eval gate Rsk3 relies on. |
| R8 Route `requires_human_review` to Hrz7 | Met | Every escalated memo is submitted to the Hrz7 Human-Review & Maker-Checker Console via the shared `review-kit` client (redact-before-wire); `local` enqueues to a transactional outbox so the routing path runs offline, `gcp`/`platform` submit over S2S to Hrz7's service intake (`HUMAN_REVIEW_URL`). `ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`, `adapters/_review_payload.py`. |

## Notes on the credit domain

- Doc2 produces a memo, not a decision. The recommendation rationale weighs the analysis,
  covenant status and risk flags but never states an approve/decline outcome.
- Covenant breach is a computed fact, not a model opinion: see `_grounded.covenant_status`
  and `tests/unit/test_sub_services.py`.
- Peer numbers come from the BigQuery peer dataset (a small synthetic in-process table
  under the `local` profile) and are summarised arithmetically; the model never invents a
  peer value.
- The `local` profile is for development, the offline test/eval gate, and demos: its
  built-in corpus and peer rows are clearly fictional and must not be used for real
  underwriting. Production residency and audit controls (P-05, R2) apply to the `gcp`
  profile.

## Adopter-owned regulator crosswalk

This appendix is intentionally adopter-owned. Before production use, the adopting bank's
compliance function must replace the reference rows, record applicability, nominate the
control owner, and link approved evidence. Repository maintainers do not assert regulatory
compliance for an adopter.

| Reference topic | Candidate control evidence | Applicability | Adopter owner | Approved evidence |
|---|---|---|---|---|
| MAS TRM model and change controls | P-06, P-08; human review and eval gate | To assess | To assign | To link |
| MAS data protection and residency | P-04, P-05; redaction, CMEK, perimeter | To assess | To assign | To link |
| Bank credit policy and delegated authority | deterministic covenant policy and maker-checker | To assess | To assign | To link |
