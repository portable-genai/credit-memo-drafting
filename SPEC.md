# SPEC: Doc2 Credit-Memo / Underwriting Assistant

Catalog id **Doc2** · group `doc` · priority **P1** · buyer Credit / Commercial Banking.
Python package `credit_memo` · CLI `credit-memo` · service port `8093`.

## 1. Purpose and scope

Doc2 is a grounded underwriting assistant. From a borrower's financial statements and
filings it produces a cited **credit memo**, extracts **covenants** (with a deterministic
compliance status), raises **risk flags**, and assembles **peer comparisons**. It is
decision SUPPORT for a credit officer, not a credit decision. It handles borrower
financial and PII data, so rule R1 (full Hrz1 redaction + guardrail pipeline) applies, and
every memo is maker-checker gated (P-06).

Out of scope: making or communicating a credit decision; pricing; limit setting; any
autonomous action on a facility.

## 2. Runtime, residency and profiles

- Region pinned to `asia-southeast1` (Singapore) for data residency.
- Profile selected by `CREDIT_MEMO_PROFILE` (`gcp` | `local` | `platform` | `onprem`;
  production default `gcp`, dev/tests/CI `local`). One switch rebinds every port; the
  domain core never changes. The three primary profiles:
  - `gcp`: Google Cloud managed services (lazy SDK imports).
  - `local`: a WORKING offline laptop stack: SQLite FTS5 retrieval, a deterministic
    schema-driven LLM, regex DLP, a heuristic guardrail, an append-only local audit, and
    in-process registry / tool-catalog / eval. SDK-free, no API key, no emulator
    required; runs the whole memo pipeline end to end. Optionally routes the in-process
    stores to Google's official emulators when a `*_EMULATOR_HOST` env var is set (opt-in;
    the google client is imported lazily, only on that branch).
  - `onprem`: fail-fast Google Distributed Cloud migration placeholders (every method
    raises; the CLI exits 2 with the migration message).
- Models: reasoning `gemini-3.5-flash` (thinking=high), triage `gemini-3.1-flash-lite`.
  Never a floating default model and never `gemini-2.0-flash`.
- Public-web grounding is off by default (`grounding_enabled=false`).

## 3. Architecture

Hexagonal ports-and-adapters. The domain core (`domain/`) is pure standard library: frozen
dataclasses, enums, pure orchestration services that take explicit port instances, the
maker-checker policy, prompts, serialization, and a shared grounded helper. Ports
(`ports/`) are `@runtime_checkable` Protocols. Adapters live under
`adapters/{gcp,platform,onprem}`; all google-cloud / genai / adk imports are lazy, never at
module import time. Wiring layers: `api/` (FastAPI), `cli/` (Typer), `agent/` (ADK root
agent + A2A card + MCP tools), all import-safe.

## 4. Artifacts

1. **CreditMemo**: borrower overview, financial analysis, covenant section, risk
   assessment, peer comparison, recommendation rationale. `requires_human_review=True`.
2. **Covenant[]**: type, threshold + operator, current value, status
   (`COMPLIANT` | `AT_RISK` | `BREACH`), citations. Status is deterministic.
3. **RiskFlag[]**: category, severity, detail, citations.
4. **PeerComparison**: borrower metric vs peer set (median, percentile, deltas).

## 5. Services and the build pipeline

- `CreditMemoService(extraction, knowledge_base, peer_data, llm, guardrail, redaction,
  tracer, audit, review_policy=None).build(memo_input, actor, principals=()) -> CreditMemo`.
  `actor` is the server-verified audit subject and `principals` are the verified entitlement
  principals (from the `IdentityPort`); both come from the resolved `Principal`, never a
  client-asserted value (see Section 10).
- `MemoSynthService` (LLM: summary + normalised metrics + rationale, with a self-critique
  groundedness pass), `CovenantService` (extract + deterministic status),
  `RiskFlagService`, `PeerCompService` (arithmetic median/percentile).
- `CreditReviewPolicy`: a memo always `requires_human_review=True`; any BREACH covenant or
  HIGH/CRITICAL risk flag escalates.

The deterministic guarantee: covenant status is computed by
`_grounded.covenant_status(current_value, threshold, operator)`, the single auditable place
where compliance is decided. The LLM drafts prose and never overrides a breach.

Pipeline (R1 full safety; each step in `tracer.span`; audited at the end):

```
redact -> guardrail(INPUT) -> per-doc extract + ingest (Hrz2, borrower ACL)
-> Hrz2 retrieve (filings + credit-policy/sector context)
-> llm normalise financials + draft memo
-> deterministic covenant status + risk flags -> peer comps
-> assemble CreditMemo -> guardrail(OUTPUT) -> review (always) -> audit
```

A blocked input and an empty retrieval are hard errors so a memo is never built on
screened-out or absent evidence.

## 6. Interfaces

### 6.1 Endpoints this repo DEFINES (consumed by the UI, CLI, peers)

| Method | Path | Body -> Response |
| --- | --- | --- |
| POST | `/v1/credit-memo` | `{borrower, documents[]}` -> CreditMemo |
| POST | `/v1/covenants` | `{borrower, documents[]}` -> Covenant[] |
| POST | `/v1/risk-flags` | `{borrower, documents[]}` -> RiskFlag[] |
| GET | `/v1/personas` | -> `[{id, subject, tenant, principals}]` (local profile only) |
| GET | `/healthz` | -> `{status, profile, region}` |
| GET | `/.well-known/agent-card.json` | -> AgentCard |

There is no `actor` in any request body: identity is server-verified (Section 10). In the
`local` profile a demo/test selects a seeded persona with the `X-Dev-Persona` header;
secure profiles resolve it from the IAP assertion. Agent skills: `build_credit_memo`,
`extract_covenants`, `flag_risks`, `peer_compare`.

### 6.2 Endpoints this repo CONSUMES (existing siblings)

- **Hrz1 guardrail** (`HRZ_GUARDRAIL_URL`): `POST /v1/guardrail/screen`, `POST /v1/redact`.
- **Hrz2 enterprise KB** (`HRZ_KB_URL`): `POST /v1/ingest`, `POST /v1/search` (Doc2's RAG store).
- **Hrz3 registry** (`HRZ_REGISTRY_URL`): `POST /v1/agents`, `GET /v1/agents/{name}`, `GET /v1/agents`.
- **Hrz4 AI quality** (`HRZ_QUALITY_URL`): `POST /v1/evaluations` and `POST /v1/gate`, both with a
  structured body `{target: {model, prompt_version, dataset_id, system}, dataset_id, bundle: "doc2-credit-memo"}`
  (the top-level `dataset_id` must equal `target.dataset_id`, else Hrz4 returns `422`). Metric selection is
  by the registered bundle name `doc2-credit-memo` (no bare metric names); the eval response is parsed from
  `results[]` and the gate returns `{passed}`.
- **Hrz5 observability/audit** (`HRZ_OBSERVABILITY_URL`): `POST /v1/audit`.

Peer data is internal (BigQuery): no platform HTTP adapter.

## 7. Ports and adapter families

| Port | gcp | local | platform | onprem |
| --- | --- | --- | --- | --- |
| DocumentExtractionPort | Document AI | local parser (pypdf/text) | n/a | stub |
| KnowledgeBaseClientPort | Agent Search | SQLite FTS5 (BM25) | Hrz2 `/v1/*` | stub |
| PeerDataPort | BigQuery | in-process peer table | n/a | stub |
| LLMPort | Gemini | deterministic schema-driven | n/a | stub |
| GuardrailPort | Model Armor | heuristic injection screen | Hrz1 | stub |
| PIIRedactionPort | DLP | regex de-identify | Hrz1 | stub |
| AuditSinkPort | Cloud Logging WORM | append-only SQLite | Hrz5 | stub |
| ObservabilityTracerPort | Cloud Trace | no-op spans | n/a | stub |
| EvaluationGatePort | Gen AI eval | in-repo offline gate | Hrz4 | stub |
| AgentRegistryPort | A2A card | in-process registry | Hrz3 | stub |
| ToolCatalogPort | MCP catalog | in-process catalog | n/a | stub |

Under `local`, the platform-client ports (knowledge base, guardrail, redaction, audit,
eval, registry) use in-process implementations, not HTTP to sibling services: a laptop
runs one app, not the whole platform. There is no Google emulator for Agent Search,
Gemini, Model Armor, DLP, Document AI or BigQuery, so those local adapters are
unconditionally SDK-free; the registry can opt into the Firestore emulator.

## 8. Eval gate (Hrz4 / P-08)

`eval/run_eval.py` drives the real `CreditMemoService` against the offline local adapters
over a golden JSONL set and scores: `groundedness` (>= 0.80), `covenant_accuracy`
(>= 0.90), `citation_accuracy` (>= 0.90), `pii_safety` (>= 0.99). Exit non-zero on fail;
CI runs it. The local `EvaluationGatePort` adapter delegates to this same gate.

## 9. Test gate (offline, no GCP SDK)

`ruff check`, `ruff format --check`, `pytest -m 'not integration'` must pass with only the
`[dev]` extra installed (the suite runs on the `local` profile, driven by the offline
`adapters/local` family). `mypy src` and `python eval/run_eval.py` should pass. An
end-to-end smoke (`credit-memo build ...` under `CREDIT_MEMO_PROFILE=local`) returns a real
cited memo offline. The contract test proves every `local` and `onprem` adapter constructs
with one `Settings` arg and structurally satisfies its Protocol, that `onprem` fails fast,
and that `local` answers in-process.

## 10. Identity and embedding (server-verified)

The API never trusts a client-asserted `actor` or ACL. An `IdentityPort`
(`ports/identity.py`) resolves a verified `Principal` server-side from the inbound request
context; `api/security.py` (`get_principal`) maps a failure to a 401. The active profile
selects the adapter: `local` = seeded dev personas (no IdP, `X-Dev-Persona` selects one),
`gcp`/`platform` = verify the IAP-injected `x-goog-iap-jwt-assertion`, `onprem` = client-IdP
placeholder (fail-fast). The verified `Principal` supplies the audit `actor` and the
entitlement `principals` merged into governed-retrieval ACLs. Embedding-surface controls:
env-driven CORS allowlist (`CREDIT_MEMO_CORS_ORIGINS`, never `"*"`) and CSP `frame-ancestors`
(`CREDIT_MEMO_FRAME_ANCESTORS`, default `'self'`), plus a UI embed mode and reverse-proxy
base path. Full guide: [`docs/embedding-and-identity.md`](docs/embedding-and-identity.md).
