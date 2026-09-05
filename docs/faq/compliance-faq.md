# Compliance FAQ

For compliance, MLRO, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle-to-control map),
[`SPEC.md`](../../SPEC.md).

### Is this making credit decisions autonomously?

No. It is a **decision-support** agent (P-05): every `CreditMemo` requires human review
(maker-checker, P-06), and `requires_human_review` is `True` by default and cannot be lowered by
the agent. The deterministic engines produce a documented, replayable assessment (covenant
status, peer comparison, risk flags); a qualified credit officer disposes. A `BREACH` covenant,
a HIGH or CRITICAL risk flag, or other escalation signals *raise* the review bar, never lower it
and never auto-execute.

### How is customer / borrower PII handled?

Redact-before-everything (P-04, R1): the memo service redacts case inputs as its first step,
before any guardrail, model, index or audit call, and the `AuditEvent` stores only the redacted
prompt and response. National-identifier detection is **jurisdiction-driven** (`pii.jurisdictions`
in `config/settings.yaml`, `CREDIT_MEMO_PII_JURISDICTIONS`), reading the shared, versioned
`pii-kit` package so a deployment scrubs, and gates on, its own identifiers across
SG / HK / JP / AU rather than a single market. The runtime guardrail / DLP itself is the sibling
**Hrz1** gateway; this repo consumes it rather than re-implementing it.

### How is the work auditable / reproducible?

Every run writes an immutable, already-redacted `AuditEvent` with the decision and the citation
set (P-07), and every memo statement carries a source-and-page `Citation` (P-10). The
consequential math (covenant status, peer median / percentile) is deterministic, so an auditor
can recompute any figure or decision from the same inputs. The enterprise audit system is
**Hrz5**; the in-repo hash-chained store is the offline / local stand-in (see
[security-faq.md](security-faq.md) for its exact tamper-evidence limits). Escalations route to
the **Hrz7** maker-checker console (rule R8) via the shared `review-kit`.

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`) scores groundedness, covenant-status accuracy, citation
accuracy, and PII safety against a golden set, failing the build below threshold (P-08). It has a
`--mode smoke|gate` split: smoke guards every merge locally, and gate mode (which refuses to run
outside `CREDIT_MEMO_PROFILE=platform|gcp`) speaks to the enterprise promotion gate. That
promotion gate, the model documentation and the red-team harness are the sibling **Hrz4** system
(registered bundle `doc2-credit-memo`); this repo's gate mirrors its thresholds so merges are
guarded locally. A fork must rebuild the golden set for its own vertical, or the gate measures
the wrong thing.

### How does the PII safety metric avoid a false green?

`pii_safety >= 0.99` is the strictest threshold, and the leak check reads the **same** shared
`pii-kit` rows the runtime redactor masks with, so a leak means the pipeline re-introduced PII,
not that two implementations disagreed. The gate runs the production regex redactor (not a fake),
and adds a pack-independent literal check of each case's planted identifier alongside the
pack-based check, so a narrowed pack row cannot score a vacuous 1.0. With redaction disabled every
PII-bearing case drops from 1.0 to 0.0 and the gate goes RED (executed and pinned). See check E2
in [`docs/practices-audit.md`](../practices-audit.md).

### Which regulators does this map to?

`COMPLIANCE.md` maps the internal P-01..P-12 and R1..R6 (plus R8, the Hrz7 review routing)
controls to concrete code. The build is region-pinned to `asia-southeast1` (Singapore, MAS) with
HKMA / APRA / FSA also in view for residency. The practices audit records one gap here (G2):
there is not yet a per-regulator crosswalk appendix marked adopter-owned. When you add
FCA / RBI / OJK / HKMA / APRA mappings, keep the Doc2-control column stable and swap only the
regulator-reference column, and re-review with local counsel. At scale the sibling **Rsk1**
`compliance-advisory` and its control-mapping module (`domain/control_mapping/`) generate and
maintain these crosswalks; a large estate should integrate them rather than hand-maintain the
table.

### Is data residency enforced?

At deploy time via `infra/terraform/*`: a single in-country region (default `asia-southeast1`),
CMEK (`kms.tf`), a VPC-SC perimeter (`vpc_sc.tf`), data-access audit logging (`logging.tf`) and a
`gcp.resourceLocations` Org Policy (`org_policy.tf`), with region and tenant as variables (P-03,
P-09). **The two services that could not follow the region are gone.** Document AI extracted
in the `us` multi-region on the `rc` channel, and Agent Search serves only `global` /
`us` / `eu`, so neither could hold borrower evidence in Singapore under any configuration.
Text extraction is now pypdf over the uploaded bytes in-process and retrieval is a per-request
index, so every resource this stack creates is regional. `gcp.resourceLocations` admits
`global` for grounded model calls only (`allow_global_endpoints`): a statement about where a
QUERY may go, not where data lives. Widening it further (`resource_location_values`) is a
jurisdiction statement, not plumbing — state the residency claim at that width. The remaining
open gap (check D5) is that there is no CI Terraform validate job, so close that before you rely
on the pin in automation. The residency-violation CI gate is the sibling **Rsk3**
`architecture-validator` (`domain/residency/`); the exit / concentration-risk plan is **Rgc9**
`operational-resilience-mapping` (`domain/concentration_exit/`). This repo enforces residency in
its own infra and is one of the systems those tools reason about.

### Can we run it against real borrower data today?

Not without your own legal, security, and model-risk sign-off. Every fixture and figure is
obviously fictional (`Acme Manufacturing (FICTIONAL)`), and the docs state throughout that this
is a reference build. The adoption checklist ([`docs/ADOPTING.md`](../ADOPTING.md)) lists the
steps, replace reference data, own the risk policy, wire your IdP, rebuild the eval golden set,
that must precede any live-data use.
