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
      -> compute ratios from the confirmed spread (deterministic, no ports)
      -> llm normalise financials + draft memo (summary + rationale), handed the ask
         and the computed ratios as authoritative blocks
      -> covenant status tested against the COMPUTED value where the spread supports
         it, otherwise against the extracted one; risk flags
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
    AnalysisManifest,
    AuditEvent,
    Borrower,
    Citation,
    Covenant,
    CreditMemo,
    Decision,
    Direction,
    Filing,
    FinancialSpread,
    GuardrailVerdict,
    MemoInput,
    PeerComparison,
    Ratio,
    RetrievedPassage,
    RiskFlag,
)
from .peer_comp_service import PeerCompService
from .ratio_catalogue import catalogue_version
from .ratio_service import RatioService
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
        analysis_bundle: Any = None,
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
        # Custody of the files this analysis was given. Optional so the CLI, the agent
        # and unit tests can build a memo from filings they already hold; when it is
        # bound, extraction receives the real bytes instead of b"".
        self._analysis_bundle = analysis_bundle

        # Sub-services compose the same ports (explicit-DI per SPEC §5).
        self._synth = MemoSynthService(llm=llm, tracer=tracer)
        self._covenants = CovenantService(
            llm=llm, tracer=tracer, at_risk_band=covenant_at_risk_band
        )
        self._risk = RiskFlagService(llm=llm, tracer=tracer)
        self._peers = PeerCompService(peer_data=peer_data, tracer=tracer)
        # No ports and no I/O: the ratio engine is arithmetic over a confirmed spread,
        # which is what makes a memo's figures replayable years after it was written.
        self._ratios = RatioService()

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

        # 3) Extract + ingest each uploaded file into the governed RAG store.
        manifest = self._manifest(memo_input, (*acl_tags, *principals))
        self._ingest_all(memo_input, manifest, acl_tags, (*acl_tags, *principals))
        # Re-read: extraction discovered the page counts, and the manifest the memo
        # carries should state them rather than the zeros it was opened with.
        manifest = self._manifest(memo_input, (*acl_tags, *principals)) or manifest

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

        # 5) Compute the ratios BEFORE drafting. Order matters: the engine's figures are
        #    handed to the drafter as authoritative fact, so the narrative is written
        #    around numbers the bank calculated rather than numbers the model inferred.
        spread = self._primary_spread(memo_input)
        ratios: tuple[Ratio, ...] = self._ratios.compute_all(spread) if spread is not None else ()

        # 6) Synthesise the memo prose + normalise financial metrics (LLM, grounded).
        draft = self._synth.synthesise(
            borrower, passages, actor, request=memo_input.request, ratios=ratios
        )

        # 7) Covenant status computed against the engine's value where the spread
        #    supports it, and grounded risk flags.
        covenants: tuple[Covenant, ...] = self._covenants.extract(
            borrower, passages, actor, spread=spread
        )
        risk_flags: tuple[RiskFlag, ...] = self._risk.flag(borrower, passages, actor)

        # 8) Peer comparisons (BigQuery peer dataset; arithmetic only).
        peer_comparison: tuple[PeerComparison, ...] = self._peers.compare(
            borrower, draft.financial_metrics, actor
        )

        # 9) Assemble the memo. The draft's confidence, caveats and questions were
        #    computed and then dropped on the floor before this: a reader could not see
        #    how sure the drafter was, nor what it had said it could not support.
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
            request=memo_input.request,
            spreads=memo_input.spreads,
            ratios=ratios,
            confidence=draft.confidence,
            caveats=draft.caveats,
            questions_for_client=draft.questions_for_client,
            manifest=manifest,
        )

        # 10) Guardrail screen (OUTPUT) on the assembled prose.
        out_text = f"{memo.summary}\n{memo.recommendation_rationale}"
        out_verdict: GuardrailVerdict = self._guardrail.screen(out_text, Direction.OUTPUT)
        if not out_verdict.allowed:
            self._write_audit(actor, redacted_summary, "", Decision.BLOCKED, direction="output")
            raise GuardrailBlockedError(out_verdict.reason or "credit memo blocked by guardrail")

        # 11) Review policy: a memo is consequential, so it is always routed to a human
        #     checker (audit decision ESCALATED); a breach/high-severity flag escalates.
        escalated = self._review.escalates(covenants, risk_flags)

        # 12) Audit (already-redacted prompt + a redacted response summary).
        self._audit_memo(actor, redacted_summary, memo, Decision.ESCALATED, escalated)

        # 13) Route the escalation to Hrz7 (rule R8). A memo always requires human review, so it is
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
    def _manifest(
        self, memo_input: MemoInput, acl_principals: tuple[str, ...]
    ) -> AnalysisManifest | None:
        """What this analysis was given, when it came from a bundle."""
        if self._analysis_bundle is None or not memo_input.analysis_id:
            return None
        try:
            result = self._analysis_bundle.manifest(memo_input.analysis_id, acl_principals)
        except Exception:  # noqa: BLE001 - an unreadable bundle degrades to no manifest
            return None
        return result if isinstance(result, AnalysisManifest) else None

    def _ingest_all(
        self,
        memo_input: MemoInput,
        manifest: AnalysisManifest | None,
        acl_tags: tuple[str, ...],
        acl_principals: tuple[str, ...],
    ) -> None:
        """Extract and ingest every document this memo may ground on.

        Two sources, deliberately not merged. When the caller supplied an analysis id the
        bundle IS the evidence: those are the files the user uploaded for this question,
        with their real bytes and their real content types. Otherwise the caller passed
        filings it already holds (the CLI, the agent, a test), and those are ingested as
        before.
        """
        if manifest is not None:
            for stored in manifest.documents:
                pages = self._extract_and_ingest(
                    Filing(
                        id=stored.id,
                        doc_type=stored.doc_type,
                        uri=f"analysis://{memo_input.analysis_id}/{stored.id}",
                        title=stored.filename,
                        acl_tags=acl_tags,
                    ),
                    acl_tags,
                    content=self._document_bytes(memo_input.analysis_id, stored.id, acl_principals),
                    mime_type=stored.mime_type,
                )
                self._record_pages(memo_input.analysis_id, stored.id, pages)
            return
        for document in memo_input.documents:
            self._extract_and_ingest(document, acl_tags)

    def _record_pages(self, analysis_id: str, document_id: str, pages: int) -> None:
        """Write back the page count extraction found, so the manifest can state it.

        Best-effort: a manifest that says 0 pages is a cosmetic loss, and failing a memo
        over it would not be.
        """
        if self._analysis_bundle is None or not pages:
            return
        with contextlib.suppress(Exception):
            self._analysis_bundle.set_pages(analysis_id, document_id, pages)

    def _document_bytes(
        self, analysis_id: str, document_id: str, acl_principals: tuple[str, ...]
    ) -> bytes:
        if self._analysis_bundle is None:
            return b""
        try:
            return bytes(
                self._analysis_bundle.get_document(analysis_id, document_id, acl_principals)
            )
        except Exception:  # noqa: BLE001 - one unreadable file must not fail the memo
            return b""

    def _extract_and_ingest(
        self,
        document: Filing,
        acl_tags: tuple[str, ...],
        content: bytes = b"",
        mime_type: str = "",
    ) -> int:
        """Extract a document and ingest it into the KB; best-effort per document.

        Returns the page count extraction found, so the caller can record it on the
        manifest.

        ``content`` was ``b""`` at every call site before Wave 1, so the extraction port
        was handed a filing and no bytes and could only ever return nothing. Every
        citation page, every extracted figure and the whole source viewer rest on this
        argument actually carrying the file.
        """
        try:
            extract = self._extraction.extract(
                document, content, mime_type or self._mime_for(document)
            )
        except Exception:  # noqa: BLE001 - a single bad document must not fail the memo
            extract = None
        try:
            text = extract.text if extract is not None else ""
            # Prefer the extracted text; fall back to the raw bytes so an adapter that
            # does its own parsing (the local KB reads PDFs itself) still gets the file.
            payload = text.encode("utf-8") if text else content
            self._knowledge_base.ingest(document, payload, acl_tags)
        except Exception:  # noqa: BLE001 - ingestion is best-effort; retrieval is the gate
            return 0
        return int(getattr(extract, "pages", 0) or 0)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _primary_spread(memo_input: MemoInput) -> FinancialSpread | None:
        """The spread the engines compute from: the borrower's own, where supplied.

        A multi-entity request carries a spread per entity; the borrower's own is the
        one the covenants and ratios are about, and the rest are consolidated separately
        once global cash flow exists. Falls back to the first spread so a caller that
        supplied one under a different id still gets its figures computed rather than
        silently ignored.
        """
        if not memo_input.spreads:
            return None
        for spread in memo_input.spreads:
            if spread.borrower_id == memo_input.borrower.id:
                return spread
        return memo_input.spreads[0]

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
        computed = sum(1 for r in memo.ratios if r.value is not None)
        summary = (
            f"metrics={len(memo.financial_metrics)}; covenants={len(memo.covenants)}; "
            f"breaches={breaches}; risk_flags={len(memo.risk_flags)}; "
            f"peers={len(memo.peer_comparison)}; ratios={computed}/{len(memo.ratios)}; "
            f"confidence={memo.confidence:.2f}"
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
                # Lineage: which arithmetic produced the figures in this memo, so a
                # reader years later can tell whether a replay should reproduce them.
                "ratio_catalogue_version": catalogue_version(),
                "computed_covenants": str(sum(1 for c in memo.covenants if c.measured is not None)),
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
