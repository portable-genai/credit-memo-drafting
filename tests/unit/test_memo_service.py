"""Unit tests for CreditMemoService — the SPEC §5 build pipeline.

Pipeline (SPEC §5):
    redact(case inputs) -> guardrail.screen(INPUT)
      -> [if blocked: audit BLOCKED + raise GuardrailBlockedError]
      -> for each filing: extraction.extract then knowledge_base.ingest (borrower ACL)
      -> knowledge_base.search -> [empty: RetrievalEmptyError]
      -> llm normalise financials + draft memo
      -> deterministic covenant status + risk flags -> peer comps
      -> assemble CreditMemo -> guardrail.screen(OUTPUT)
      -> review policy (always requires_human_review) -> audit.record(redacted)

These tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

import pytest
from tests.conftest import BlockingGuardrail, load_service
from tests.fixtures import sample_cases

from credit_memo.domain.errors import GuardrailBlockedError, RetrievalEmptyError
from credit_memo.domain.models import (
    CovenantStatus,
    CreditMemo,
    Decision,
    Direction,
    MemoInput,
)

ACTOR = "officer@bank.test"


def _build(extraction, knowledge_base, peer_data, llm, guardrail, redaction, tracer, audit):
    return load_service("CreditMemoService")(
        extraction, knowledge_base, peer_data, llm, guardrail, redaction, tracer, audit
    )


# --------------------------------------------------------------------------- #
# Redaction happens BEFORE everything (P-04 / R1).
# --------------------------------------------------------------------------- #
def test_redaction_runs_before_ingest_and_search(credit_memo_service, redaction):
    credit_memo_service.build(sample_cases.PII_MEMO_INPUT, actor=ACTOR)
    assert redaction.calls, "redaction.redact was never called"
    assert "S1234567A" in redaction.calls[0]


def test_redacted_audit_has_no_raw_pii(credit_memo_service, audit):
    credit_memo_service.build(sample_cases.PII_MEMO_INPUT, actor=ACTOR)
    assert audit.events
    for event in audit.events:
        assert "S1234567A" not in event.redacted_prompt
        assert "casey.lim@example.com" not in event.redacted_prompt


# --------------------------------------------------------------------------- #
# Blocked input: BLOCKED audit + raise; no model/ingest/retrieval.
# --------------------------------------------------------------------------- #
def test_blocked_input_raises_and_audits(
    extraction, knowledge_base, peer_data, llm, redaction, tracer, audit
):
    service = _build(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        BlockingGuardrail(block_input=True),
        redaction,
        tracer,
        audit,
    )
    with pytest.raises(GuardrailBlockedError):
        service.build(sample_cases.MALICIOUS_MEMO_INPUT, actor=ACTOR)

    # No artifact generation, no retrieval, no ingest after a blocked input.
    assert llm.requests == []
    assert knowledge_base.queries == []
    assert knowledge_base.ingested == []

    blocked = [e for e in audit.events if e.decision is Decision.BLOCKED]
    assert blocked, "expected an audit event with decision=BLOCKED"
    assert blocked[0].actor == ACTOR
    assert blocked[0].action == "build_credit_memo"


def test_blocked_input_screens_input_only(
    extraction, knowledge_base, peer_data, llm, redaction, tracer, audit
):
    blocking = BlockingGuardrail(block_input=True)
    service = _build(extraction, knowledge_base, peer_data, llm, blocking, redaction, tracer, audit)
    with pytest.raises(GuardrailBlockedError):
        service.build(sample_cases.MALICIOUS_MEMO_INPUT, actor=ACTOR)
    directions = [d for _, d in blocking.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT not in directions


# --------------------------------------------------------------------------- #
# Empty governed RAG store -> hard error (never ungrounded).
# --------------------------------------------------------------------------- #
def test_empty_knowledge_base_raises(
    extraction, empty_knowledge_base, peer_data, llm, guardrail, redaction, tracer, audit
):
    service = _build(
        extraction, empty_knowledge_base, peer_data, llm, guardrail, redaction, tracer, audit
    )
    with pytest.raises(RetrievalEmptyError):
        service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)


# --------------------------------------------------------------------------- #
# Normal path: a well-formed, cited, human-review-flagged memo.
# --------------------------------------------------------------------------- #
def test_normal_path_builds_full_memo(credit_memo_service):
    memo = credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)

    assert isinstance(memo, CreditMemo)
    assert memo.requires_human_review is True

    assert memo.summary
    assert memo.recommendation_rationale
    assert "approve" not in memo.recommendation_rationale.lower() or "officer" in (
        memo.recommendation_rationale.lower()
    )

    # Financial metrics normalised and cited.
    assert memo.financial_metrics
    assert memo.citations
    for c in memo.citations:
        assert c.page is not None, "page-level citation is required"

    # Covenants extracted with a deterministic status.
    assert memo.covenants
    for cov in memo.covenants:
        assert isinstance(cov.status, CovenantStatus)

    # Risk flags identified.
    assert memo.risk_flags

    # Peer comparisons computed from the peer dataset.
    assert memo.peer_comparison


def test_normal_path_ingests_each_filing_with_borrower_acl(credit_memo_service, knowledge_base):
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    ingested_ids = {doc.id for doc, _ in knowledge_base.ingested}
    assert ingested_ids == {d.id for d in sample_cases.SAMPLE_DOCUMENTS}
    for _, acl_tags in knowledge_base.ingested:
        assert any(t.startswith("borrower:") for t in acl_tags), (
            "ingest must carry a borrower ACL tag"
        )


def test_normal_path_passes_acl_principals_to_search(credit_memo_service, knowledge_base):
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    assert knowledge_base.queries
    query = knowledge_base.queries[0]
    assert any(p.startswith("borrower:") for p in query.acl_principals)


def test_verified_principals_reach_governed_retrieval(credit_memo_service, knowledge_base):
    # The verified user's entitlement principals (from the IdentityPort) are merged into
    # the retrieval ACL alongside the borrower tag, so the data path is scoped to the user.
    credit_memo_service.build(
        sample_cases.SAMPLE_MEMO_INPUT,
        actor=ACTOR,
        principals=("group:credit-analyst", "group:risk"),
    )
    assert knowledge_base.queries
    acls = set(knowledge_base.queries[0].acl_principals)
    assert any(p.startswith("borrower:") for p in acls)
    assert "group:credit-analyst" in acls


def test_normal_path_audited_as_escalated(credit_memo_service, audit):
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    assert audit.events
    assert any(e.decision is Decision.ESCALATED for e in audit.events)
    assert audit.events[-1].action == "build_credit_memo"


def test_normal_path_wrapped_in_tracer_span(credit_memo_service, tracer):
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    assert tracer.spans, "the build pipeline must open at least one trace span"


def test_output_guardrail_screened(credit_memo_service, guardrail):
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    directions = [d for _, d in guardrail.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT in directions


def test_blocked_output_raises(
    extraction, knowledge_base, peer_data, llm, redaction, tracer, audit
):
    service = _build(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        BlockingGuardrail(block_input=False, block_output=True),
        redaction,
        tracer,
        audit,
    )
    with pytest.raises(GuardrailBlockedError):
        service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)


# --------------------------------------------------------------------------- #
# No documents: memo still builds from retrieved policy/sector context.
# --------------------------------------------------------------------------- #
def test_memo_builds_without_documents(credit_memo_service):
    memo_input = MemoInput(borrower=sample_cases.LOGISTICS_BORROWER, documents=())
    memo = credit_memo_service.build(memo_input, actor=ACTOR)
    assert memo.summary
    assert memo.requires_human_review is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
