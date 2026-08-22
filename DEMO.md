# Demo guide - Doc2 Credit-Memo / Underwriting Assistant

Step-by-step scripts for demoing Doc2 two ways:

- **Demo A - A cited credit memo, fully offline** (the headline flow): for a synthetic
  borrower the assistant runs the whole build pipeline - redact, guardrail, grounded
  retrieval, LLM synthesis, deterministic covenant testing, risk flags, peer comps - and
  returns a credit memo where every claim carries a source-and-page citation, under a
  maker-checker (human-review) gate. Runs **fully offline** (no cloud, no API key).
- **Demo B - The same memo on the managed GCP stack**: the identical artifact produced
  against real Document AI / Gemini / DLP / BigQuery in `asia-southeast1`, shown via the
  REST API and the Next.js console.

- **Demo C - REAL borrowers under the `live` profile** (the audience-facing demo): type
  any US-listed company name and the memo grounds on that company's **real SEC EDGAR
  record** (registrant profile, latest 10-K XBRL figures, filing accession), with real
  same-industry peers (same SIC code, real filed figures) and generation on a local
  Gemma model server. For a private borrower, upload its financial statements (PDF or
  text; template downloadable) and the memo grounds on the uploaded evidence instead.

> Demo A / B use **fictional** synthetic borrower data. Do not run against live borrower
> data without your own legal, security and model-risk sign-off. Demo C never serves the
> fictional corpus: the live profile grounds only on EDGAR records and uploads.

### Demo C in three commands

```bash
# 1. Start a local OpenAI-compatible model server on :8001 (MLX / Ollama / vLLM).

# 2. Declare your EDGAR traffic (SEC fair-access policy) and serve live.
SEC_EDGAR_CONTACT=you@example.com CREDIT_MEMO_PROFILE=live python -m credit_memo.api.app

# 3. Build a memo for a real company (or use the UI on :3000).
curl -s -X POST localhost:8093/v1/credit-memo -H 'Content-Type: application/json' \
  -H 'X-Dev-Persona: analyst' \
  -d '{"borrower": {"id": "apple-inc", "name": "Apple Inc", "sector": "technology", "jurisdiction": "US"}}'
```

Audience data: `GET /v1/documents/template` (CSV of the form fields) and
`POST /v1/documents` (multipart: file + borrower_id + title), or the "Upload borrower
evidence" panel in the UI; the next memo build for that borrower cites the upload.

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ & npm | for the UI / Playwright | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | no | Demo A's presenter walkthrough |
| A GCP project + `gcloud` | no | yes | billing enabled; `asia-southeast1` available |
| Terraform | no | yes | provisions Document AI, DLP, BigQuery, WORM bucket, CMEK |
| Cloud KMS key (regional) | no | yes | CMEK; set `CREDIT_MEMO_KMS_KEY` |

Install/setup references (read these once):

- Local install & profiles -> [README "Run locally"](README.md#run-locally-a-real-cited-memo-fully-offline)
- GCP install & deploy -> [`docs/runbook.md`](docs/runbook.md#deploy-gcp)
- HTTP API surface -> [README "HTTP API"](README.md#http-api)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/credit-memo-drafting.git
cd credit-memo-drafting

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export CREDIT_MEMO_PROFILE=local
make lint test                   # ruff + mypy + pytest (all local, no cloud)
```

See [README "Run locally"](README.md#run-locally-a-real-cited-memo-fully-offline) for details.

---

## 2. Demo A - A cited credit memo (local, offline)

The build runs on an in-process `local` stack (SQLite FTS5 retrieval + a deterministic
LLM), so it needs **no Google Cloud and no API key** - ideal for a laptop demo. Four ways
to present it, in order of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1 - the live demo server (http://localhost:8094)
source .venv/bin/activate
PYTHONPATH=src python scripts/credit_memo_demo_server.py

# Terminal 2 - the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/credit_memo_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **Memo built** - summary on screen; the amber maker-checker banner says decision support, not a credit decision.
2. **Financial analysis** - revenue USD 120m, EBITDA USD 24m, net leverage 2.5x, each traceable to a filing.
3. **Covenants** - leverage `2.5 <= 3.0` and DSCR `1.4 >= 1.25`, both **compliant**; status is computed deterministically.
4. **Risk flags** - a concentration risk, grounded in the manufacturing sector credit policy (cited to its page).
5. **Peer comparison** - borrower vs cohort median and percentile, computed arithmetically.
6. **Maker-checker** - the memo always requires human review (P-06); every claim is cited on the Sources & audit page.

**What to point at on screen:** the maker-checker banner, the covenant table with its
deterministic status pills, the citation chips on every section, and the peer bars. Full
options (`SLOWMO_MS`, `HEADLESS`, `CHROME_PATH`, ...) are in
[`scripts/README.md`](scripts/README.md).

### 2.2 Manual, click-through (no Playwright)

Run only the server and drive it yourself in any browser:

```bash
PYTHONPATH=src python scripts/credit_memo_demo_server.py     # http://localhost:8094
```

Open `http://localhost:8094` and click **Next** to reveal each cited section, **Restart**
to reset, and the **Sources & audit** link for the filings and citation list. Or run the
real console against the live API instead:

```bash
make run-api PROFILE=local      # FastAPI on :8093
make run-ui                     # Next.js console on http://localhost:3000
```

The console submits the borrower to `POST /v1/credit-memo` and renders the same memo.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src python scripts/credit_memo_demo.py credit_memo_demo.json   # prints the stage-by-stage summary
PYTHONPATH=src python scripts/render_credit_memo_ui.py credit_memo_demo.json ./out
# -> ./out/memo.html, ./out/sources.html
```

Or simply `make demo` (writes `credit_memo_demo.json` and renders `./out`).

### 2.4 One-shot memo via the CLI (quick variant)

If you only want the cited memo in the terminal (not the browser):

```bash
export CREDIT_MEMO_PROFILE=local
credit-memo build "Acme Manufacturing Pte Ltd" --sector manufacturing --jurisdiction SG
```

`credit-memo covenants ...` and `credit-memo risk-flags ...` show the individual artifacts.

---

## 3. Demo B - The same memo on the managed GCP stack

Shows the identical artifact produced against **real managed services** in
`asia-southeast1`. Follow [`docs/runbook.md`](docs/runbook.md#deploy-gcp) for the
authoritative deploy steps; the short version:

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, documentai, bigquery, dlp, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export CREDIT_MEMO_PROFILE=gcp
export CREDIT_MEMO_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan - the WORM bucket lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
# Export the outputs the app reads (see docs/runbook.md):
export CREDIT_MEMO_DOCAI_PROCESSOR="$(terraform -chdir=infra/terraform output -raw documentai_processor_id)"
export CREDIT_MEMO_DLP_INSPECT_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_inspect_template)"
export CREDIT_MEMO_DLP_DEIDENTIFY_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_deidentify_template)"
```

Details and gotchas (region fail-fast, key rotation, retention): [`docs/runbook.md`](docs/runbook.md).

### 3.3 Run and show

```bash
make run-api PROFILE=gcp          # FastAPI on :8093, profile=gcp
```

Then demo any surface ([README "HTTP API"](README.md#http-api)):

Identity is server-verified, so no request carries an `actor`. In the local profile a
demo picks a seeded persona with the `X-Dev-Persona` header (list them at
`GET /v1/personas`); omit it to use the default (analyst) persona.

```bash
# List the seeded dev personas (local profile only)
curl -s localhost:8093/v1/personas | python -m json.tool

# REST - build a cited credit memo (audit actor = the selected persona's subject)
curl -s localhost:8093/v1/credit-memo -H 'content-type: application/json' -H 'X-Dev-Persona: analyst' -d '{
  "borrower": {"id":"borr-acme-mfg","name":"Acme Manufacturing Pte Ltd (FICTIONAL)","sector":"manufacturing","jurisdiction":"SG"},
  "documents": [{"id":"doc-financials","doc_type":"financial_statement"}]
}' | python -m json.tool

# Covenants / risk flags only
curl -s localhost:8093/v1/covenants  -H 'content-type: application/json' -H 'X-Dev-Persona: analyst' -d '{"borrower":{"id":"borr-acme-mfg","name":"Acme Manufacturing Pte Ltd (FICTIONAL)","sector":"manufacturing"}}' | python -m json.tool

# Agent card / health
curl -s localhost:8093/.well-known/agent-card.json | python -m json.tool
curl -s localhost:8093/healthz
```

Or the browser console (talks to the API on :8093) - see [`ui/README.md`](ui/README.md):

```bash
make run-ui           # http://localhost:3000
```

**What to highlight:** every claim carries a source-and-page **citation**; PII is redacted
before any model/index/audit call; covenant status is **computed deterministically** (the
LLM never overrides a breach); the memo is **always** marked human-review (maker-checker);
everything stays in `asia-southeast1` with CMEK.

---

## 4. Talking points

- **It's grounded, not generative guesswork.** Retrieval is the gate: with no borrower
  evidence the build refuses rather than inventing a memo. Every figure, covenant and risk
  statement points back to its exact source filing, policy passage or peer data point.
- **The system does the math, deterministically.** Covenant compliance and peer medians /
  percentiles are pure functions (replayable by an auditor); the LLM only narrates and
  drafts prose. A breach computation is never overridden by the model.
- **Audit-first output.** Sections at a glance, each proven by a citation chip, with the
  input filings and the full citation list on the Sources & audit page.
- **Guardrails hold.** Redact-before-everything, guardrail on input and output, borrower-
  scoped ACL on retrieval, always-on maker-checker (decision support, not a credit
  decision), single-region + CMEK residency.

---

## 5. Troubleshooting & cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| `ModuleNotFoundError: opentelemetry` from a script | You ran with a non-local profile. The demo scripts pin `CREDIT_MEMO_PROFILE=local`; do not override it to `gcp` without `pip install -e ".[gcp,dev]"`. |
| Playwright: "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use 2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/credit_memo_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start 2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Port 8094 / 8093 in use | `python scripts/credit_memo_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `make run-api API_PORT=...`. |
| `NotImplementedError` / exit 2 from a CLI command | You're on `CREDIT_MEMO_PROFILE=onprem` (fail-fast). Use `local` (Demo A) or `gcp` (Demo B). |
| GCP deploy/region errors | See [`docs/runbook.md`](docs/runbook.md#triage). |

**Stop / clean up:** Ctrl-C the demo server and `make run-api`. For GCP, scale the
deployment to zero or remove the app SA's model access - the audit trail and evidence
remain intact ([runbook](docs/runbook.md#triage)). `make clean` removes local
caches/artefacts (and you can delete `credit_memo_demo.json` and `./out`).
