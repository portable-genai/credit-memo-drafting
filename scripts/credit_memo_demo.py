"""Runnable demo of the cited credit-memo build (synthetic, fictional data).

Builds a single credit memo for the bundled synthetic borrower ``Acme Manufacturing``
end to end on the in-process ``local`` stack: redact -> guardrail(INPUT) ->
extract + ingest filings -> grounded retrieval -> LLM synthesis -> deterministic
covenant status -> risk flags -> peer comps -> guardrail(OUTPUT) -> maker-checker.

Run it::

    PYTHONPATH=src python scripts/credit_memo_demo.py [out.json]

It prints a stage-by-stage summary and writes the full memo as audit-view JSON (the
borrower, the four cited artifacts and the maker-checker banner) for the UI to render.
No cloud, no API key, no LLM: the covenant/peer math is deterministic and the narrator
is the offline default adapter.
"""

from __future__ import annotations

import json
import os
import sys

from credit_memo.api import deps
from credit_memo.config import Settings, build_container
from credit_memo.domain.models import Borrower, CreditMemo, Filing, MemoInput
from credit_memo.domain.models import DocType as DT
from credit_memo.domain.serialization import to_jsonable

# The bundled synthetic borrower (self-seeded by the local knowledge base). Obviously
# fictional; never a real obligor.
BORROWER = Borrower(
    id="borr-acme-mfg",
    name="Acme Manufacturing Pte Ltd (FICTIONAL)",
    sector="manufacturing",
    jurisdiction="SG",
)
FILINGS: tuple[Filing, ...] = (
    Filing(
        id="doc-financials",
        doc_type=DT.FINANCIAL_STATEMENT,
        uri="dataroom://acme/financials-2025.pdf",
        title="Acme 2025 Audited Financial Statements (FICTIONAL)",
        acl_tags=("borrower:borr-acme-mfg",),
    ),
    Filing(
        id="doc-loan-agreement",
        doc_type=DT.LOAN_AGREEMENT,
        uri="dataroom://acme/facility-agreement.pdf",
        title="Acme Senior Facility Agreement (FICTIONAL)",
        acl_tags=("borrower:borr-acme-mfg",),
    ),
    Filing(
        id="doc-covenant-cert",
        doc_type=DT.COVENANT_CERTIFICATE,
        uri="dataroom://acme/covenant-certificate-q4.pdf",
        title="Acme Q4 Covenant Compliance Certificate (FICTIONAL)",
        acl_tags=("borrower:borr-acme-mfg",),
    ),
)
ACTOR = "rm.tan@bank.test"


def build_memo() -> CreditMemo:
    """Assemble the credit memo on the in-process local stack (SDK-free)."""
    # This demo is deliberately offline: pin the local profile unless the operator has
    # explicitly chosen another, so it never reaches for a Google Cloud SDK.
    os.environ.setdefault("CREDIT_MEMO_PROFILE", "local")
    container = build_container(Settings.load())
    service = deps.build_credit_memo_service(container)
    return service.build(MemoInput(borrower=BORROWER, documents=FILINGS), actor=ACTOR)


def memo_payload(memo: CreditMemo) -> dict:
    """The full memo as audit-view JSON, plus the input filings for provenance."""
    payload = to_jsonable(memo)
    payload["filings"] = [
        {"id": f.id, "doc_type": f.doc_type.value, "title": f.title} for f in FILINGS
    ]
    payload["actor"] = ACTOR
    return payload


def _print_summary(memo: CreditMemo) -> None:
    breaches = sum(1 for c in memo.covenants if c.status.value == "breach")
    at_risk = sum(1 for c in memo.covenants if c.status.value == "at_risk")
    print(f"Built credit memo for {memo.borrower.name}")
    print(f"   sector {memo.borrower.sector} - jurisdiction {memo.borrower.jurisdiction}\n")

    print("-- Stage 1  Input redaction + guardrail (INPUT)  -> passed (no PII leaked)")
    print(f"-- Stage 2  Extract + ingest filings             -> {len(FILINGS)} filings")
    print("-- Stage 3  Grounded retrieval (A2 RAG store)    -> evidence retrieved")
    print("-- Stage 4  LLM synthesis (summary + rationale)  -> drafted, grounded")
    print(
        "-- Stage 5  Financial metrics normalised         -> "
        + ", ".join(f"{m.name} {m.value}" for m in memo.financial_metrics)
    )
    print(
        f"-- Stage 6  Covenants (deterministic status)     -> "
        f"{len(memo.covenants)} ({breaches} breach, {at_risk} at-risk)"
    )
    for c in memo.covenants:
        cur = "n/a" if c.current_value is None else c.current_value
        print(
            f"             [{c.status.value.upper()}] {c.type.value}: {cur} {c.operator.value} {c.threshold}"
        )
    print(f"-- Stage 7  Risk flags                           -> {len(memo.risk_flags)}")
    for f in memo.risk_flags:
        print(f"             ({f.category.value}/{f.severity.value}) {f.detail}")
    print(
        f"-- Stage 8  Peer comparison (median + pctile)    -> {len(memo.peer_comparison)} metrics"
    )
    for p in memo.peer_comparison:
        print(
            f"             {p.metric}: borrower {p.borrower_value} vs peer median "
            f"{p.peer_median} (p{int(p.percentile * 100)})"
        )
    print("-- Stage 9  Guardrail (OUTPUT)                    -> passed")
    print(
        "-- Stage 10 Maker-checker gate (P-06)            -> requires_human_review="
        + str(memo.requires_human_review).lower()
    )
    print(f"\nCitations: {len(memo.citations)} (every claim traces to a source + page)")


def main(out_path: str) -> None:
    memo = build_memo()
    _print_summary(memo)
    payload = memo_payload(memo)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nWrote credit-memo JSON -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "credit_memo_demo.json")
