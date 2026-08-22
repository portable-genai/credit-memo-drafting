"""CreditMemoService — the credit-memo orchestrator (SPEC §5).

Owns the full assembly pipeline and calls only ports. Because the memo handles borrower
financial/PII data (rule R1), the complete A1 safety pipeline is mandatory: redact then
guardrail(INPUT) before any model/index call, and guardrail(OUTPUT) before the memo is
returned. Every memo is maker-checker gated (P-06): it always requires human review.

Pipeline (each step in ``tracer.span``; audited at the end):

    tracer.span("credit_memo.build"):
      redact(case inputs)
      -> guardrail.screen(INPUT)             [blocked -> audit BLOCKED + raise]
      -> for each filing: extraction.extract then knowledge_base.ingest (borrower ACL)
      -> knowledge_base.search (filings + credit-policy/sector context)  [empty -> error]
      -> llm normalise financials + draft memo (summary + rationale)
      -> deterministic covenant status + risk flags
      -> peer comps (BigQuery)
      -> assemble CreditMemo
      -> guardrail.screen(OUTPUT)            [blocked -> audit BLOCKED + raise]
      -> review policy (always requires_human_review=True; escalation flag)
      -> audit.record(already-redacted)

Defensive throughout: extraction / ingestion / peer-data failures degrade rather than
crash, but a blocked input and an ungrounded memo are hard errors so a memo is never
built on screened-out or absent evidence.

Pure domain code: no Google Cloud / ADK / FastAPI imports.
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Any

from . import _grounded as g
from .covenant_service import CovenantService
from .entitlements import borrower_acl
from .errors import GuardrailBlockedError, RetrievalEmptyError
from .memo_synth_service import MemoSynthService
from .models import (
    AuditEvent,
    Borrower,
    Citation,
    Covenant,
    CreditMemo,
    Decision,
    Direction,
    Filing,
    GuardrailVerdict,
    MemoInput,
    PeerComparison,
    RetrievedPassage,
    RiskFlag,
)
from .peer_comp_service import PeerCompService
from .review_policy import CreditReviewPolicy
from .risk_flag_service import RiskFlagService
from .serialization import to_jsonable


class CreditMemoService:
    """Build a cited credit memo for a borrower. Constructor takes explicit ports."""

    def __init__(
        self,
        extraction: Any,
        knowledge_base: Any,
        peer_data: Any,
        llm: Any,
        guardrail: Any,
        redaction: Any,
        tracer: Any,
        audit: Any,
        review_policy: CreditReviewPolicy | None = None,
        review_router: Any = None,
        covenant_at_risk_band: float = 0.05,
    ) -> None:
        self._extraction = extraction
        self._knowledge_base = knowledge_base
        self._peer_data = peer_data
        self._llm = llm
        self._guardrail = guardrail
        self._redaction = redaction
        self._tracer = tracer
        self._audit = audit
        self._review = review_policy or CreditReviewPolicy()
        # Rule R8: when the memo requires human review it is routed to Hrz7 (the maker-checker
        # console), not left as a boolean. Optional so unit tests and the CLI can omit it; when
        # unset the escalation still audits ESCALATED, it just is not forwarded to a console.
        self._review_router = review_router

        # Sub-services compose the same ports (explicit-DI per SPEC §5).
        self._synth = MemoSynthService(llm=llm, tracer=tracer)
        self._covenants = CovenantService(
            llm=llm, tracer=tracer, at_risk_band=covenant_at_risk_band
        )
        self._risk = RiskFlagService(llm=llm, tracer=tracer)
        self._peers = PeerCompService(peer_data=peer_data, tracer=tracer)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def build(
        self,
        memo_input: MemoInput,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> CreditMemo:
        """Build a cited credit memo for ``memo_input`` (SPEC §5).

        ``actor``, ``principals`` and ``tenant`` are the server-verified end-user identity
        (from the ``IdentityPort``, never the request body). ``actor`` is the audit
        subject, ``principals`` are the entitlement principals, and ``tenant`` (when set) is
        stamped onto the evidence ACL at ingest AND onto the retrieval principals, so the
        subset/fail-closed KB ACL scopes the data path to the caller's tenant: a borrower id
        guessed from the body alone never crosses a tenant boundary. The default empty
        ``principals``/``tenant`` keeps existing callers/tests unaffected.
        """
        span = self._tracer.span("credit_memo.build", action="build_credit_memo", actor=actor)
        with span if span is not None else nullcontext():
            return self._build_inner(memo_input, actor, principals, tenant)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _build_inner(
        self,
        memo_input: MemoInput,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> CreditMemo:
        borrower = memo_input.borrower

        # 1) Redact the case inputs (P-04) before they touch a model, index or audit.
        raw_summary = self._case_summary(memo_input)
        redacted_summary = self._redaction.redact(raw_summary).text

        # 2) Guardrail screen (INPUT). Blocked -> audit BLOCKED + raise (no partial memo).
        in_verdict: GuardrailVerdict = self._guardrail.screen(redacted_summary, Direction.INPUT)
        if not in_verdict.allowed:
            self._write_audit(actor, redacted_summary, "", Decision.BLOCKED)
            raise GuardrailBlockedError(in_verdict.reason or "credit-memo request blocked")

        acl_tags = self._acl_tags(borrower.id, tenant)

        # 3) Extract + ingest each filing into the governed RAG store (A2, borrower+tenant ACL).
        for document in memo_input.documents:
            self._extract_and_ingest(document, acl_tags)

        # 4) Retrieve grounding passages from A2. Empty -> hard error (never ungrounded).
        #    Scope the ACL to the borrower + tenant tags plus the verified user's entitlement
        #    principals, so retrieval is limited to what this user may actually see. The
        #    tenant principal is server-verified, so tagged evidence never crosses tenants.
        passages: list[RetrievedPassage] = g.retrieve_passages(
            self._knowledge_base,
            self._retrieval_query(borrower),
            acl_principals=(*acl_tags, *principals),
            top_k=self._knowledge_base_top_k(),
        )
        if not passages:
            self._write_audit(actor, redacted_summary, "", Decision.ESCALATED)
            raise RetrievalEmptyError(f"no borrower evidence retrieved: {borrower.id!r}")

        # 5) Synthesise the memo prose + normalise financial metrics (LLM, grounded).
        draft = self._synth.synthesise(borrower, passages, actor)

        # 6) Deterministic covenant status + grounded risk flags.
        covenants: tuple[Covenant, ...] = self._covenants.extract(borrower, passages, actor)
        risk_flags: tuple[RiskFlag, ...] = self._risk.flag(borrower, passages, actor)

        # 7) Peer comparisons (BigQuery peer dataset; arithmetic only).
        peer_comparison: tuple[PeerComparison, ...] = self._peers.compare(
            borrower, draft.financial_metrics, actor
        )

        # 8) Assemble the memo.
        citations = self._memo_citations(draft.citations, covenants, risk_flags)
        memo = CreditMemo(
            borrower=borrower,
            summary=draft.summary,
            financial_metrics=draft.financial_metrics,
            covenants=covenants,
            risk_flags=risk_flags,
            peer_comparison=peer_comparison,
            recommendation_rationale=draft.recommendation_rationale,
            citations=citations,
            requires_human_review=self._review.requires_review(),
        )

        # 9) Guardrail screen (OUTPUT) on the assembled prose.
        out_text = f"{memo.summary}\n{memo.recommendation_rationale}"
        out_verdict: GuardrailVerdict = self._guardrail.screen(out_text, Direction.OUTPUT)
        if not out_verdict.allowed:
            self._write_audit(actor, redacted_summary, "", Decision.BLOCKED, direction="output")
            raise GuardrailBlockedError(out_verdict.reason or "credit memo blocked by guardrail")

        # 10) Review policy: a memo is consequential, so it is always routed to a human
        #     checker (audit decision ESCALATED); a breach/high-severity flag escalates.
        escalated = self._review.escalates(covenants, risk_flags)

        # 11) Audit (already-redacted prompt + a redacted response summary).
        self._audit_memo(actor, redacted_summary, memo, Decision.ESCALATED, escalated)

        # 12) Route the escalation to Hrz7 (rule R8). A memo always requires human review, so it is
        #     handed to the maker-checker console rather than terminating in a boolean; the adapter
        #     redacts before the wire. Best-effort: a console outage must not fail an already-
        #     assembled, already-audited memo (the audit ESCALATED record is the durable escalation
        #     of record, and the outbox path retries).
        if self._review_router is not None and memo.requires_human_review:
            with contextlib.suppress(Exception):
                self._review_router.route(memo, maker=actor, tenant=tenant)
        return memo

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    def _extract_and_ingest(self, document: Filing, acl_tags: tuple[str, ...]) -> None:
        """Extract a filing and ingest it into A2; best-effort per document."""
        try:
            extract = self._extraction.extract(document, b"", self._mime_for(document))
        except Exception:  # noqa: BLE001 - a single bad document must not fail the memo
            extract = None
        try:
            content = (extract.text if extract is not None else "").encode("utf-8")
            self._knowledge_base.ingest(document, content, acl_tags)
        except Exception:  # noqa: BLE001 - ingestion is best-effort; retrieval is the gate
            return

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _case_summary(memo_input: MemoInput) -> str:
        borrower = memo_input.borrower
        docs = ", ".join(f"{d.id}:{d.doc_type.value}" for d in memo_input.documents) or "none"
        return (
            f"Credit memo for borrower {borrower.name} (id={borrower.id}, "
            f"sector={borrower.sector or 'unknown'}, "
            f"jurisdiction={borrower.jurisdiction or 'unknown'}); documents=[{docs}]"
        )

    @staticmethod
    def _acl_tags(borrower_id: str, tenant: str = "") -> tuple[str, ...]:
        """ACL tags stamped onto ingested evidence AND onto the retrieval principals.

        Delegates to ``domain/entitlements.borrower_acl`` so the tags written at ingest and
        the tags an entitlement check grants at retrieval have exactly one definition: if
        they drifted, evidence would be written with a tag no reader could ever hold.

        With a verified tenant, evidence carries BOTH ``borrower:<id>`` and
        ``tenant:<tenant>``, so the subset/fail-closed KB ACL requires a caller to hold the
        tenant principal to see it: a borrower id guessed from the request body alone never
        crosses a tenant boundary (object-level authorization). Whether this caller may read
        THIS borrower at all is the API layer's entitlement check (``borrower_scope``), since
        that is where a verified Principal exists; the CLI/agent path stays single-tenant.
        """
        return borrower_acl(borrower_id, tenant)

    @staticmethod
    def _retrieval_query(borrower: Borrower) -> str:
        return (
            f"financial statements, covenants, credit policy and {borrower.sector or 'sector'} "
            f"context for {borrower.name}"
        )

    def _knowledge_base_top_k(self) -> int:
        settings = getattr(self._knowledge_base, "settings", None)
        kb = getattr(settings, "knowledge_base", None)
        return getattr(kb, "top_k", 10)

    @staticmethod
    def _mime_for(document: Filing) -> str:
        return "application/pdf"

    @staticmethod
    def _memo_citations(
        memo_citations: tuple[Citation, ...],
        covenants: tuple[Covenant, ...],
        risk_flags: tuple[RiskFlag, ...],
    ) -> tuple[Citation, ...]:
        out: list[Citation] = list(memo_citations)
        for covenant in covenants:
            out.extend(covenant.citations)
        for flag in risk_flags:
            out.extend(flag.citations)
        seen: set[tuple[str, int | None]] = set()
        deduped: list[Citation] = []
        for c in out:
            key = (c.source_id, c.page)
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        return tuple(deduped)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit_memo(
        self,
        actor: str,
        redacted_prompt: str,
        memo: CreditMemo,
        decision: Decision,
        escalated: bool,
    ) -> None:
        breaches = sum(1 for c in memo.covenants if c.status.value == "breach")
        summary = (
            f"metrics={len(memo.financial_metrics)}; covenants={len(memo.covenants)}; "
            f"breaches={breaches}; risk_flags={len(memo.risk_flags)}; "
            f"peers={len(memo.peer_comparison)}"
        )
        self._write_audit(
            actor,
            redacted_prompt,
            summary,
            decision,
            citations=memo.citations,
            metadata={
                "requires_human_review": str(memo.requires_human_review).lower(),
                "escalated": str(escalated).lower(),
                "covenant_breaches": str(breaches),
                "n_citations": str(len(memo.citations)),
            },
        )

    def _write_audit(
        self,
        actor: str,
        redacted_prompt: str,
        redacted_response: str,
        decision: Decision,
        citations: tuple[Citation, ...] = (),
        metadata: dict[str, str] | None = None,
        direction: str = "input",
    ) -> None:
        event = AuditEvent(
            action="build_credit_memo",
            actor=actor,
            decision=decision,
            redacted_prompt=redacted_prompt,
            redacted_response=redacted_response,
            citations=citations,
            metadata={**(metadata or {}), "direction": direction},
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            to_jsonable(event)
