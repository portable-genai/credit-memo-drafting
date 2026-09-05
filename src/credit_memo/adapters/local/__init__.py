"""Local deployment profile adapters — a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed Google
Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole credit-memo pipeline end to end with **no Google
Cloud, no API key, and no running emulators by default**:

* Knowledge base (governed RAG) -> a ``sqlite3`` **FTS5** index over the borrower /
  policy passages (BM25 rank), ``ingest`` + ``search``, with page-level citations.
* Document extraction -> a local plain-text / pypdf parser (no Document AI).
* LLM -> a deterministic, schema-driven generator (no model, no network).
* Guardrail -> a heuristic that blocks prompt-injection / jailbreak text.
* PII redaction -> regex de-identification (SG NRIC/FIN, emails, SG phone numbers).
* Peer data -> a small in-process synthetic peer-financials table (no network).
* Audit -> an append-only local store (SQLite or in-memory), read-back supported.
* Tracer -> no-op spans.
* Agent registry / tool catalog -> in-process stores (no HTTP to A3).
* Evaluation -> delegates to the in-repo offline eval gate.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST``
env vars are set (the google client is imported lazily, only on that branch); see
:mod:`credit_memo.adapters.local._emulator`.
"""
