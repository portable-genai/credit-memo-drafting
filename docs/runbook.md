# Runbook: `credit-memo-drafting` Credit-Memo / Underwriting Assistant

Operational notes for running, deploying and triaging `credit-memo-drafting`. The region is chosen at deploy
time and validated against the `allowed_regions` residency allowlist; it defaults to
`asia-southeast1`.

## Profiles

| Profile | Use | Needs GCP SDK |
| --- | --- | --- |
| `local` | Local dev, CI, the test/eval gate (SDK-free offline stack) | No |
| `onprem` | Fail-fast Google Distributed Cloud migration placeholders | No |
| `platform` | Inside the full platform (`agent-guardrail-gateway` / `enterprise-knowledge-base` / `agent-registry` / `model-quality-gate` / `agent-observability` over HTTP) | No (uses httpx) |
| `gcp` | Standalone managed deployment | Yes (`pip install -e ".[gcp]"`) |

Set with `CREDIT_MEMO_PROFILE`, or write a `profile:` into `config/settings.yaml`. Production deploys set `CREDIT_MEMO_PROFILE=gcp` explicitly (see `Dockerfile`). CI and tests run on `local`.

**Unset is a third state, not a synonym for `local`.** When neither the variable nor the settings file names a profile, the SDK-free `local` adapters still bind (nothing else can, with no cloud SDK installed) but the run counts as unconsented: the seeded no-auth personas are refused, the localhost CORS fallback is empty, and the bind guard still confines the process to loopback. A dev or demo run must therefore name `local` deliberately. This is what stops a missing environment variable from serving an underwriting assistant with dev credit approvers.

## Run locally

```bash
. .venv/bin/activate
export CREDIT_MEMO_PROFILE=onprem
credit-memo --help
credit-memo serve --port 8093          # FastAPI on :8093
curl localhost:8093/healthz
curl localhost:8093/.well-known/agent-card.json
```

Under `onprem` the adapters are placeholders that raise on use; use `gcp` or `platform`
for a live build.

## Deploy (gcp)

1. `make install-gcp`
2. Provision infra: `cd infra/terraform && terraform init && terraform apply` (sets up
   the analysis-bundle bucket (regional, CMEK, 15-day lifecycle), DLP, Model Armor, KMS,
   IAM and VPC-SC, all in `asia-southeast1`).
3. Build and push the image (`Dockerfile`), deploy to Agent Runtime / Cloud Run.
   Name the review console (`HUMAN_REVIEW_URL`) or state `CREDIT_MEMO_REVIEW_ROUTING=off`:
   under `gcp` or `platform` with routing on, the service refuses to boot without one.
4. Register the agent card with `agent-registry` and confirm `model-quality-gate` eval gate is green before promotion.

## Health and observability

- `GET /healthz` reports `{status, profile, region}`.
- Traces: Cloud Trace via OpenTelemetry, message-content capture OFF.
- Audit: Cloud Logging `credit-memo-audit` at the project's own retention. No locked WORM
  bucket: it would outlive the analyses it describes, which are deleted after 15 days.
- FinOps: token usage is recorded as span attributes per LLM call.

## Triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `NotImplementedError` from a method | Running `onprem` | Switch to `gcp`/`platform` or implement the on-prem adapter. |
| `RetrievalEmptyError` | No evidence in `enterprise-knowledge-base` for the borrower | Ingest the borrower's filings; check ACL tags. |
| Memo returns a blocked envelope | Guardrail blocked input/output | Inspect the `agent-guardrail-gateway` finding; the request is audited as BLOCKED. |
| Covenant status looks wrong | Bad extracted threshold/operator/value | Status is deterministic; check the extracted terms and their citations. |
| Boot refuses: `Review routing is on ... HUMAN_REVIEW_URL is not set` | Managed profile, routing on, no console named | Set `HUMAN_REVIEW_URL`, or set `CREDIT_MEMO_REVIEW_ROUTING=off` to run without routing. |
| Memo says "Could not reach the review console" | The hand-off failed (`review_routing: "failed"`) | The memo and its audit record stand; check the console's reachability and the S2S credentials. The service logs the exception type. |
| Eval gate fails | A metric below threshold | Inspect `python eval/run_eval.py` output; fix groundedness/citation discipline. |

## Runtime controls

`CREDIT_MEMO_GUARDRAIL`, `CREDIT_MEMO_PII_REDACTION` and `CREDIT_MEMO_REVIEW_ROUTING` each
switch one cheap control. Each is read in three states: unset is on, `true`/`false` (or
`on`/`off`) wins, and an emptied or unrecognised value refuses at boot. A process with any of
them off logs one warning at startup naming each.

- **Review routing** is on by default, like the other two. Off binds a router that
  submits nothing; the ESCALATED audit record is still written and every memo says it is not
  queued for review. Every caller reports it: the two build routes, the agent and MCP tools,
  and the CLI.
- **Redaction disclosure:** a memo built from a case that redaction changed carries
  `input_redacted: true`, and the console says so.
- **Redaction tuning:** DLP masks only `LIKELY` findings, replaces each with its info-type name
  (`[PERSON_NAME]`) rather than `#` characters, and excludes credit vocabulary (legal-entity
  suffixes, regulators, ratios, rating agencies) from `PERSON_NAME`, both inline and in the
  `infra/terraform/dlp.tf` template. The local redactor leaves an amount after a currency
  marker (`SGD 85000000`) or before a decimal fraction (`98765432.10`) alone.

## Data handling

Borrower PII is redacted before any model, index, span or audit write (P-04, R1). Audit
records store already-redacted prompt/response only. All sample data in the repo is
fictional.
