# On-prem migration guide

`credit-memo-drafting`'s `onprem` profile is a sovereign migration target: the same domain core, the same port
Protocols, with the managed Google Cloud adapters swapped for on-premise implementations.
This guide is the checklist for that swap. The domain orchestration and the four artifacts
do not change.

## The principle

Switching `CREDIT_MEMO_PROFILE` from `gcp` (or `platform`) to `onprem` rebinds every port to
a placeholder in `src/credit_memo/adapters/onprem/`. Each placeholder constructs cleanly
with a single `Settings` argument and structurally satisfies its port Protocol (proven by
`tests/contract/test_port_parity.py`), then raises `NotImplementedError` from each method.
Porting on-premise is "fill in the bodies", not "rewrite the domain" (P-02, P-12).

## What you implement (one adapter per port)

| Port | What the on-prem adapter must do |
| --- | --- |
| `DocumentExtractionPort` | Extract form fields + text from a filing's bytes into `DocumentExtract`. |
| `KnowledgeBaseClientPort` | Ingest a filing (with ACL tags) and retrieve ACL-filtered, page-cited passages from your governed store. |
| `PeerDataPort` | Return `PeerMetric` rows for a borrower's metric from your peer-financials store. |
| `LLMPort` | `generate` (structured JSON when a response schema is set) and `classify`. |
| `GuardrailPort` | Screen INPUT/OUTPUT and return a `GuardrailVerdict`. Never default-allow. |
| `PIIRedactionPort` | De-identify PII; never return text unredacted. |
| `AuditSinkPort` | Persist an already-redacted `AuditEvent` to a write-once store. |
| `ObservabilityTracerPort` | Open spans (content OFF) and record token usage. |
| `EvaluationGatePort` | Score a dataset to an `EvalReport`; `gate` returns pass/fail. |
| `AgentRegistryPort` / `ToolCatalogPort` | Publish/resolve the agent card and the governed tool catalog. |

## Steps

1. Implement each adapter class in its `onprem/*.py` module, keeping the constructor
   signature `(settings: Settings)` and the exact method signatures of the port.
2. Run `pytest tests/contract -q` to confirm interface parity still holds.
3. Point `config/settings.yaml` `onprem` bindings at your classes (or keep the defaults if
   you fill the shipped placeholder classes in place).
4. Run the full gate (`make lint && make test && make eval`) with
   `CREDIT_MEMO_PROFILE=onprem`.
5. Validate residency: your on-premise stores must keep borrower data in-jurisdiction, the
   audit store must be write-once, and PII must be redacted before it reaches any model.

## What does not change

The domain (`domain/`), the ports (`ports/`), the API/CLI/agent wiring, the four artifacts,
the maker-checker policy, and the eval gate are profile-agnostic. Only the adapter bodies
change.
