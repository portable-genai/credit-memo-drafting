# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in, demonstrably" (General Principles P-02 / P-12), and it is designed to be
*shown*, not asserted. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`docs/onprem-migration.md`](../onprem-migration.md), [`DEMO.md`](../../DEMO.md).

### What does "portable" actually mean here?

Three axes, each with a rehearsed exit: **compute** (the whole stack migrates by a one-line
profile change, no domain edits), **data** (the audit trail exports in an open, documented
format and reloads elsewhere with integrity re-verified), and **experience / identity**
(identity resolves across hosts by an adapter swap, not a rewrite). Run
`PYTHONPATH=src python scripts/portability_demo.py` for the executable proof; exit code 0 means
every check passed (check F3).

### How does the profile switch work?

The pure-domain core speaks only to `typing.Protocol` **ports**; four **adapter families**
implement them, and `config/settings.yaml` binds one adapter per port per profile. Setting
`CREDIT_MEMO_PROFILE` (or `profile:` in the settings) rebinds the entire stack:

- `local`: a WORKING offline stack (SQLite FTS5 retrieval, a deterministic LLM, regex DLP, a
  heuristic guardrail, append-only local audit). No Google Cloud SDK. The default for
  dev / test / CI; runs the whole memo pipeline end to end.
- `gcp`: real managed services (Gemini, DLP, Model Armor, a regional analysis-bundle bucket, a
  BigQuery peer dataset, Cloud Logging, Cloud Trace, Gen AI Evals), with lazy SDK imports.
  Extraction and retrieval are in-process on every profile: there is no processor to call and
  no standing index to place.
- `platform`: thin HTTP clients delegating to the sibling horizontal-platform and
  de-risking services.
- `onprem`: fail-fast Google Distributed Cloud placeholders that still satisfy every Protocol
  (the sovereign-exit target); a primary command exits non-zero by design.

No `domain/` code changes across any of these. The contract tests
(`tests/contract/test_port_parity.py`, `test_behavioral_parity.py`) prove both `local` and
`onprem` construct and satisfy all ports with no cloud SDK installed, and the port map cannot
drift silently (check A6).

### How do we get our data out?

The audit trail is a hash chain over canonical JSON and exports to JSON Lines, one
`{seq, prev_hash, entry_hash, event}` object per line, reloading into a fresh store with the
chain re-verified line by line (the shared `hex_service_kit.audit.HashChainedAuditLog` behind
`LocalAppendOnlyAuditAdapter`). The exit story for the audit trail is "copy the JSONL file",
not "migrate a product". Memos and their citations serialize the same way via `to_jsonable`.

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders that nonetheless satisfy every
Protocol and construct with a single `Settings` arg, so the *interface contract* for a sovereign
migration is proven and enforced by CI today. The actual on-prem implementations are the
migration work, scoped in [`docs/onprem-migration.md`](../onprem-migration.md). This repo is not
the sovereign-exit *planner* (that is the sibling **Rgc9** `operational-resilience-mapping`,
module `domain/concentration_exit/`: APRA CPS 230, MAS / HKMA outsourcing); this repo is one of
the systems whose exit that planner reasons about.

### Does residency compromise portability?

No: residency is a deploy-time pin (the region, CMEK, VPC-SC), and portability is the ability to
change *where* the stack runs by configuration. They are orthogonal. `infra/terraform/*` pins
`var.region` (default `asia-southeast1`, Singapore) across the agent runtime, BigQuery, Document
AI, DLP and KMS, and a second enterprise or region is a tfvars change, not a fork. Residency
enforcement infra overlaps with the sibling **Rsk3** `architecture-validator`
(`domain/residency/`, a CI gate for region violations), which a fork should run rather than
re-implement.

### What is NOT yet portable?

The practices audit records a gap on check D5: there is no CI Terraform `fmt` / `validate` job
and no Org Policy resource-location allowlist resource yet, so the residency pin is enforced by
the Terraform variables but not yet by an offline CI validation. Close that before you rely on
the pin in an automated pipeline. Everything in the memo pipeline itself is exercised across
`local`, and the managed leg across `gcp`.
