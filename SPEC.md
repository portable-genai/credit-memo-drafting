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
- Models: reasoning `gemini-3.5-flash` (thinking=high), triage `gemini-3.5-flash`.
  Never a floating default model and never `gemini-2.0-flash`.
- Public-web grounding is off by default (`grounding_enabled=false`).

## 3. Architecture

Hexagonal ports-and-adapters. The domain core (`domain/`) is pure standard library: frozen
dataclasses, enums, the ratio catalogue, pure services that take explicit port instances or
none at all, the maker-checker policy, prompts, serialization, and a shared grounded
helper. Ports (`ports/`) are `@runtime_checkable` Protocols. Adapters live under
`adapters/{gcp,platform,local,live,onprem}`; all google-cloud / genai / adk imports are
lazy, never at module import time. Wiring layers: `api/` (FastAPI), `cli/` (Typer),
`agent/` (ADK root agent + A2A card + MCP tools), all import-safe.

Provenance is a type, not a convention. `Provenance` marks where every figure came from;
`ENGINE_READABLE` is the subset an engine may compute on; and the invariants live in the
constructors, so the boundary is enforced at build time rather than at review time. That is
what makes "the model never supplied this number" a property rather than a promise.

## 4. Artifacts

1. **CreditMemo**: borrower overview, financial analysis, covenant section, risk
   assessment, peer comparison, recommendation rationale, the ask, the computed ratios,
   the reconciliations, the policy exceptions, the proposed grade, and the input manifest.
   `requires_human_review=True`.
2. **Covenant[]**: type, threshold + operator, current value, status
   (`COMPLIANT` | `AT_RISK` | `BREACH`), citations. Status is deterministic, and tested
   against the COMPUTED value wherever the confirmed spread supports it.
3. **RiskFlag[]**: category, severity, detail, citations.
4. **PeerComparison**: borrower metric vs peer set (median, percentile, deltas).
5. **SpreadCandidate -> FinancialSpread**: what extraction proposed, and what a named
   person accepted. Kept apart forever: "what the model read" and "what the analyst
   confirmed" are different claims.
6. **Ratio[]**: every catalogue formula over every period, computable or not. One that
   could not be computed is returned carrying the line and period that were missing,
   because omitting it reads as "we did not think leverage was worth stating".
7. **TieOutFinding[]**: the reconciliations a credit file is expected to survive — quote
   on page, balance sheet, sources = uses, certificate vs computed, period continuity.
8. **PolicyException[]** and **RiskRatingProposal**: the bank's own uploaded limits and
   scorecard, applied arithmetically. The grade is a proposal, never a grade of record.
9. **AnalysisManifest**: every uploaded file with sha256, type, pages and the uploader's
   own as-of date, plus the date the analysis stops being readable.
10. **MemoRevision[]**: each saved version, digest-chained, with per-section authorship
    (model / edited / analyst) and what each section said before.

## 5. Services and the build pipeline

- `CreditMemoService(...).build(memo_input, actor, principals=(), tenant="") -> CreditMemo`.
  `actor` is the server-verified audit subject and `principals` are the verified entitlement
  principals (from the `IdentityPort`); both come from the resolved `Principal`, never a
  client-asserted value (see Section 10).
- **Model services**: `MemoSynthService` (summary + normalised metrics + rationale, with a
  self-critique groundedness pass), `CovenantService` (extract, then deterministic status),
  `RiskFlagService`.
- **Deterministic services, no ports and no model**: `RatioService` over
  `ratio_catalogue` (nine versioned formulas), `SpreadService` (the confirm gate),
  `TieOutService`, `PolicyExceptionService`, `RiskRatingService`, `PeerCompService`
  (arithmetic median/percentile), `GlobalCashFlowService`, `ScenarioService`,
  `RenewalDiffService`, `RevisionService`, `CommentService`.
- `CreditReviewPolicy`: a memo always `requires_human_review=True`; any BREACH covenant or
  HIGH/CRITICAL risk flag escalates. Routing that escalation to the Hrz7 console is
  OPT-IN (`CREDIT_MEMO_REVIEW_ENABLED`); the flag and the audit record stand either way.

The deterministic guarantee has two halves. Covenant status is computed by
`_grounded.covenant_status(current_value, threshold, operator)`, the single auditable place
where compliance is decided. And a `Ratio` is constructible only as `COMPUTED` while a
`FinancialSpread` refuses any item an engine may not read, so between those two refusals
there is no route by which a model-asserted number becomes a ratio in the memo. The LLM
drafts prose and never overrides a breach.

Pipeline (R1 full safety; each step in `tracer.span`; audited at the end):

```
redact -> guardrail(INPUT)
-> per-doc extract + ingest into the per-request index (borrower + tenant ACL)
-> retrieve (filings + credit-policy/sector context)          [empty -> hard error]
-> refuse an unconfirmed spread, then COMPUTE the ratios      [before any drafting]
-> llm draft memo, handed the ask and the computed ratios as authoritative
-> covenant status against the computed value where the spread supports it; risk flags
-> the bank's own policy limits and scorecard, arithmetically
-> reconcile (quote on page, balance sheet, sources = uses, certificate, continuity)
-> peer comps -> assemble CreditMemo (with its input manifest)
-> guardrail(OUTPUT) -> review policy -> audit -> optional escalation routing
```

Order is load-bearing in two places. Ratios are computed **before** drafting so the
narrative is written around numbers the bank calculated rather than numbers the model
inferred. Policy and rating run before assembly so the drafter's rationale explains drivers
it did not pick.

A blocked input, an empty retrieval and an unconfirmed spread are hard errors, so a memo is
never built on screened-out evidence, absent evidence, or figures nobody looked at.

## 6. Interfaces

### 6.1 Endpoints this repo DEFINES (consumed by the UI, CLI, peers)

An analysis is the unit of work: open one with its evidence, spread it, confirm it, build,
edit, export, and let it expire. The stateless artifact routes remain for a caller that
carries its own documents in the body.

| Method | Path | Body -> Response |
| --- | --- | --- |
| POST | `/v1/analyses` | multipart `{borrower_id, files[], doc_types, declared_as_of, borrower_name?}` -> AnalysisManifest |
| GET | `/v1/analyses/{id}` | -> AnalysisManifest (what was given, and until when) |
| GET | `/v1/analyses/{id}/documents/{doc}` | -> the file inline, so `#page=N` opens the cited page |
| DELETE | `/v1/analyses/{id}` | -> 204, without waiting for the retention window |
| POST | `/v1/analyses/{id}/spreads/extract` | `{document_ids[], periods[], currency, unit}` -> SpreadCandidate |
| POST | `/v1/analyses/{id}/spreads/confirm` | `{rejected[], adjustments[], added[]}` -> FinancialSpread |
| GET | `/v1/analyses/{id}/spreads` | -> `{candidate, confirmed}` |
| GET | `/v1/analyses/{id}/group/suggestions` | `?name=&jurisdiction=` -> EntityGroup (opt-in) |
| POST | `/v1/analyses/{id}/build` | `{request?, spreads[]?, related_entities[]?, guarantors[]?, entity_spreads{}?, eliminations[]?}` -> CreditMemo |
| PATCH | `/v1/analyses/{id}/memo` | `{sections{}, reason, note}` -> MemoRevision |
| GET | `/v1/analyses/{id}/revisions` | -> `{revisions[], chain_intact, chain_detail}` |
| POST | `/v1/analyses/{id}/comments` | `{section, body}` -> MemoComment (anchored to the current revision) |
| GET | `/v1/analyses/{id}/comments` | -> `{comments[], open_count, stale_count}` |
| POST | `/v1/analyses/{id}/comments/{cid}/resolve` | `{resolution}` -> MemoComment |
| POST | `/v1/analyses/{id}/export?fmt=` | -> the committee pack as bytes |
| GET | `/v1/analyses/{id}/export/formats` | -> `{formats[]}` this deployment can actually produce |
| POST | `/v1/documents` | multipart borrower evidence -> `{chunks, borrower_id}` |
| GET | `/v1/documents/template` | -> the upload CSV template |
| POST | `/v1/credit-memo` | `{borrower, documents[], request?, spreads[]?}` -> CreditMemo |
| POST | `/v1/covenants` | `{borrower, documents[]}` -> Covenant[] |
| POST | `/v1/risk-flags` | `{borrower, documents[]}` -> RiskFlag[] |
| GET | `/v1/personas` | -> `[{id, subject, tenant, principals}]` (local profile only) |
| GET | `/healthz` | -> `{status, profile, region}` |
| GET | `/.well-known/agent-card.json` | -> AgentCard |

Three rules the analysis routes enforce and the table cannot show. Confirmation applies to
the candidate the analysis already holds, never to a table the caller composes, so a
"confirmed" spread cannot hold figures nobody saw beside a document. `PATCH .../memo`
accepts the prose sections only: the figures belong to the deterministic engines. And the
group route SUGGESTS entities and never figures — every entity it returns is `VENDOR`,
which is not `ENGINE_READABLE`, and one the analyst does not then supply statements for is
reported on the memo as an entity the consolidation could not include.

Two ports are off unless a deployment switches them on, both for a residency reason rather
than a cautious one: `CREDIT_MEMO_RESEARCH_ENABLED` (the search leg is served only from the
`global` endpoint) and `CREDIT_MEMO_ENTITY_RESOLUTION_ENABLED` (a register lookup sends the
borrower's registered legal name outside the region). Both deviations are recorded in
org-metadata's region alignment record rather than inherited.

There is no `actor` in any request body: identity is server-verified (Section 10). In the
`local` profile a demo/test selects a seeded persona with the `X-Dev-Persona` header;
secure profiles resolve it from the IAP assertion. Agent skills: `build_credit_memo`,
`extract_covenants`, `flag_risks`, `peer_compare`.

### 6.2 Endpoints this repo CONSUMES (existing siblings)

- **Hrz1 guardrail** (`GUARDRAIL_GATEWAY_URL`): `POST /v1/guardrail/screen`, `POST /v1/redact`.
- **Hrz2 enterprise KB** (`KNOWLEDGE_BASE_URL`): `POST /v1/ingest`, `POST /v1/search` (Doc2's RAG store).
- **Hrz3 registry** (`AGENT_REGISTRY_URL`): `POST /v1/agents`, `GET /v1/agents/{name}`, `GET /v1/agents`.
- **Hrz4 AI quality** (`QUALITY_GATE_URL`): `POST /v1/evaluations` and `POST /v1/gate`, both with a
  structured body `{target: {model, prompt_version, dataset_id, system}, dataset_id, bundle: "doc2-credit-memo"}`
  (the top-level `dataset_id` must equal `target.dataset_id`, else Hrz4 returns `422`). Metric selection is
  by the registered bundle name `doc2-credit-memo` (no bare metric names); the eval response is parsed from
  `results[]` and the gate returns `{passed}`.
- **Hrz5 observability/audit** (`OBSERVABILITY_URL`): `POST /v1/audit`.
- **B1 `cdd-sow-research`** (`CDD_SOW_RESEARCH_URL`): `POST /v1/ubo-graph` -> the borrower's
  beneficial-ownership structure, consumed on the `platform` profile as the
  `EntityResolutionPort`. Asked rather than re-implemented: that service computes every
  percentage as the product of cited registry hops an auditor can recompute, and a second
  resolver here would be a second answer to one question. Its financial-crime findings —
  PEP status, adverse media, opacity score, the control narrative — are deliberately NOT
  carried over: they have their own review path and their own audience, and a credit memo
  restating one would publish another team's conclusion under this service's name.

Peer data is public filing data read over HTTPS: no platform HTTP adapter of our own.

## 7. Ports and adapter families

| Port | gcp | local | platform | onprem |
| --- | --- | --- | --- | --- |
| DocumentExtractionPort | local parser (pypdf/text) | local parser (pypdf/text) | same as gcp | stub |
| SpreadExtractionPort | Gemini, PDF parts + schema | analyst CSV | same as gcp | stub |
| KnowledgeBaseClientPort | per-request SQLite FTS5 | SQLite FTS5 (BM25) | Hrz2 `/v1/*` | stub |
| AnalysisBundlePort | regional CMEK bucket, 15-day lifecycle | directory | regional CMEK bucket | stub |
| PolicyPackPort | uploaded YAML/JSON | uploaded YAML/JSON | same as gcp | stub |
| ExportPort | DOCX/HTML + PDF (reportlab, in process) | DOCX/HTML (stdlib) | same as gcp | stub |
| WebResearchPort | Gemini grounding at `global`, opt-in | fixture | same as gcp | stub |
| EntityResolutionPort | GLEIF register, opt-in | fixture register | B1 `/v1/ubo-graph` | stub |
| PeerDataPort | SEC EDGAR | in-process peer table | same as gcp | stub |
| LLMPort | Gemini | deterministic schema-driven | same as gcp | stub |
| GuardrailPort | Model Armor | heuristic injection screen | Hrz1 | stub |
| PIIRedactionPort | DLP | regex de-identify | Hrz1 | stub |
| AuditSinkPort | Cloud Logging | append-only SQLite | Hrz5 | stub |
| ReviewRouterPort | Hrz7 console (opt-in) | in-process recorder | Hrz7 console | stub |
| IdentityPort | IAP assertion | seeded persona | IAP assertion | stub |
| ObservabilityTracerPort | Cloud Trace | no-op spans | same as gcp | stub |
| EvaluationGatePort | Gen AI eval | in-repo offline gate | Hrz4 | stub |
| AgentRegistryPort | A2A card | in-process registry | Hrz3 | stub |
| ToolCatalogPort | MCP catalog | in-process catalog | same as gcp | stub |

A fifth profile, `live`, sits beside these: SDK-free but not offline. It reads real SEC
EDGAR filings for both retrieval and peers and calls a real model, which is how a claim
about real data gets tested without a managed deployment.

Under `local`, the platform-client ports (knowledge base, guardrail, redaction, audit,
eval, registry) use in-process implementations, not HTTP to sibling services: a laptop
runs one app, not the whole platform. There is no Google emulator for
Gemini, Model Armor or DLP, so those local adapters are
unconditionally SDK-free; the registry can opt into the Firestore emulator.

## 8. Eval gate (Hrz4 / P-08)

`eval/run_eval.py` drives the real `CreditMemoService` against the offline local adapters
over a golden JSONL set and scores nine metrics:

| metric | threshold | what it would catch |
| --- | --- | --- |
| `groundedness` | >= 0.80 | prose asserting what the evidence does not say |
| `covenant_accuracy` | >= 0.90 | a status that disagrees with the arithmetic |
| `citation_accuracy` | >= 0.90 | a citation pointing at a source that does not support it |
| `pii_safety` | >= 0.99 | borrower personal data reaching a model, an index or the log |
| `ratio_reproducibility` | == 1.0 | the same spread and catalogue version giving two answers |
| `spread_accuracy` | >= 0.90 | a figure read off the wrong row |
| `tie_out_precision` | >= 0.95 | a reconciliation that passes something it should flag |
| `revision_integrity` | == 1.0 | an edited memo whose chain still claims to be intact |
| `research_isolation` | == 1.0 | a web-grounded result reaching the memo or an export |

Exit non-zero on fail; CI runs it. The local `EvaluationGatePort` adapter delegates to this
same gate. `--adversarial` inverts the verdict and runs the same set against planted
defects: a metric that cannot be shown RED has not been shown to measure anything, so every
threshold above was demonstrated failing before it was trusted.

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
