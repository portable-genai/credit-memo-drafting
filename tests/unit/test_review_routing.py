"""R8 routing: an escalated credit memo is routed to Hrz7 via the shared review-kit.

Every credit memo requires human review (P-06), so rule R8 says it MUST be handed to the Hrz7
maker-checker console rather than left as a boolean. These tests prove the producer half of that
loop end-to-end against the offline local router (an in-memory outbox), and prove the redact-
before-wire boundary so no raw borrower identifier reaches the console.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_service
from tests.fixtures import sample_cases

from credit_memo.adapters._review_payload import memo_to_review
from credit_memo.adapters.local.review_router import LocalReviewRouter
from credit_memo.config import Settings
from credit_memo.domain.models import (
    Borrower,
    Citation,
    Covenant,
    CovenantOperator,
    CovenantStatus,
    CovenantType,
    CreditMemo,
    RiskCategory,
    RiskFlag,
    Severity,
    SourceType,
)

ACTOR = "officer@bank.test"
TENANT = "demo-bank"


def _service_with_router(
    extraction,
    knowledge_base,
    peer_data,
    llm,
    guardrail,
    redaction,
    tracer,
    audit,
    router,
):
    return load_service("CreditMemoService")(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        review_router=router,
    )


def test_build_routes_escalated_memo_to_outbox(
    extraction,
    knowledge_base,
    peer_data,
    llm,
    guardrail,
    redaction,
    tracer,
    audit,
):
    """A completed build enqueues one review to the router's outbox, carrying the tenant (R8)."""
    router = LocalReviewRouter(Settings())
    service = _service_with_router(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        router,
    )
    assert not router.outbox.pending()

    memo = service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR, tenant=TENANT)
    assert memo.requires_human_review

    pending = router.outbox.pending()
    assert len(pending) == 1, "the escalated memo must be routed to Hrz7 exactly once"
    review = pending[0].review
    assert review.action == "credit_memo:build"
    assert review.case_ref == memo.borrower.id
    assert review.maker == ACTOR
    assert review.tenant == TENANT


def _breaching_memo_with_pii() -> CreditMemo:
    borrower = Borrower(
        id="borr-acme",
        name="Acme Manufacturing (FICTIONAL)",
        sector="manufacturing",
        jurisdiction="SG",
    )
    # A citation snippet carrying a synthetic SG NRIC: it must be masked before the wire.
    cite = Citation(
        source_id="doc-1",
        source_type=SourceType.FILING,
        title="Loan agreement",
        snippet="Guarantor NRIC S1234567D named in the schedule.",
    )
    covenant = Covenant(
        type=CovenantType.LEVERAGE,
        description="Net debt / EBITDA <= 3.0x",
        threshold=3.0,
        operator=CovenantOperator.LE,
        current_value=4.2,
        status=CovenantStatus.BREACH,
        citations=(cite,),
    )
    flag = RiskFlag(
        category=RiskCategory.LIQUIDITY,
        severity=Severity.HIGH,
        detail="DSCR below 1.0",
        citations=(cite,),
    )
    return CreditMemo(
        borrower=borrower,
        summary="Leverage covenant breached.",
        covenants=(covenant,),
        risk_flags=(flag,),
        citations=(cite,),
    )


def test_payload_is_redacted_and_escalates_on_breach():
    """The wire payload masks identifiers, maps severity, and dual-controls a breach (R1/R8)."""
    review = memo_to_review(_breaching_memo_with_pii(), maker=ACTOR, tenant=TENANT)

    assert review.tenant == TENANT
    assert review.severity == "high"
    assert review.required_approvals == 2, "a covenant breach / HIGH flag warrants dual control"
    # No raw NRIC survives into the payload the console receives.
    assert "S1234567D" not in review.summary
    for citation in review.citations:
        assert "S1234567D" not in citation.snippet
    assert any(c.title == "Loan agreement" for c in review.citations)


def test_no_router_still_builds_memo(
    extraction,
    knowledge_base,
    peer_data,
    llm,
    guardrail,
    redaction,
    tracer,
    audit,
):
    """Routing is optional: with no router bound, build still returns an escalated memo."""
    service = _service_with_router(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        None,
    )
    memo = service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=ACTOR)
    assert memo.requires_human_review


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
