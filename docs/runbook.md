# Runbook: Doc2 Credit-Memo / Underwriting Assistant

Operational notes for running, deploying and triaging Doc2. The region is chosen at deploy
time and validated against the `allowed_regions` residency allowlist; it defaults to
`asia-southeast1`.

## Profiles

| Profile | Use | Needs GCP SDK |
| --- | --- | --- |
| `local` | Local dev, CI, the test/eval gate (SDK-free offline stack) | No |
| `onprem` | Fail-fast Google Distributed Cloud migration placeholders | No |
| `platform` | Inside the full platform (Hrz1..Hrz5 over HTTP) | No (uses httpx) |
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
   Document AI, BigQuery peer dataset, DLP, Model Armor, KMS, the WORM log bucket, IAM and
   VPC-SC, all in `asia-southeast1`).
3. Build and push the image (`Dockerfile`), deploy to Agent Runtime / Cloud Run.
4. Register the agent card with Hrz3 and confirm Hrz4 eval gate is green before promotion.

## Health and observability

- `GET /healthz` reports `{status, profile, region}`.
- Traces: Cloud Trace via OpenTelemetry, message-content capture OFF.
- Audit: Cloud Logging `credit-memo-audit` routed to the locked WORM bucket.
- FinOps: token usage is recorded as span attributes per LLM call.

## Triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `NotImplementedError` from a method | Running `onprem` | Switch to `gcp`/`platform` or implement the on-prem adapter. |
| `RetrievalEmptyError` | No evidence in Hrz2 for the borrower | Ingest the borrower's filings; check ACL tags. |
| Memo returns a blocked envelope | Guardrail blocked input/output | Inspect the Hrz1 finding; the request is audited as BLOCKED. |
| Covenant status looks wrong | Bad extracted threshold/operator/value | Status is deterministic; check the extracted terms and their citations. |
| Eval gate fails | A metric below threshold | Inspect `python eval/run_eval.py` output; fix groundedness/citation discipline. |

## Data handling

Borrower PII is redacted before any model, index, span or audit write (P-04, R1). Audit
records store already-redacted prompt/response only. All sample data in the repo is
fictional.
