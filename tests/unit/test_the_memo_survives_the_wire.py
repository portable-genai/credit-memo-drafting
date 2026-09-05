"""Everything the pipeline computes has to reach the client and the committee pack.

The export endpoint does not re-run the build. It reads the memo the build stored, which
is the API's own wire shape, and rebuilds a domain memo from it — so anything the wire
shape drops is missing from the pack a committee actually receives, and missing silently.

That had already happened. `CreditMemoResponse` carried no `policy_exceptions`, no
`tie_out` and no `rating`, so a memo with a HIGH-severity breach of the bank's own limit
and a failed balance-sheet check exported as a pack with neither section in it. The
document builder had the code to render both; it was handed a memo where both were empty.

The guard below is structural rather than a list of fields, because a list is exactly what
went stale: it compares the memo's own dataclass fields against the round trip, so a field
added in a later wave and forgotten here fails on the day it is added.
"""

from __future__ import annotations

import dataclasses

import pytest

from credit_memo.api.schemas import CreditMemoResponse, to_domain_memo
from credit_memo.domain import models as m
from credit_memo.domain.memo_document import build_document

#: Fields whose absence from the wire is deliberate, each with the reason. Anything not
#: named here must survive the round trip.
INTENTIONALLY_DERIVED: dict[str, str] = {
    "generated_at": "carried as an ISO string and re-parsed, so it is checked separately",
}


def _memo() -> m.CreditMemo:
    """A memo carrying one of everything the pipeline can attach."""
    entity = m.RelatedEntity(id="holdco", name="Acme Holdco", role=m.EntityRole.PARENT)
    return m.CreditMemo(
        borrower=m.Borrower(id="acme", name="Acme Manufacturing"),
        summary="A summary.",
        recommendation_rationale="Because the numbers say so.",
        ratios=(
            m.Ratio(
                formula_id="leverage.v1",
                name="Leverage",
                period="FY2025",
                value=4.1,
                definition="total debt / EBITDA",
            ),
        ),
        tie_out=(
            m.TieOutFinding(
                check=m.TieOutCheck.BALANCE_SHEET_BALANCES,
                severity=m.Severity.HIGH,
                detail="assets do not equal liabilities plus equity",
                expected=100.0,
                actual=88.0,
            ),
        ),
        policy_exceptions=(
            m.PolicyException(
                rule_id="LEV-01",
                description="maximum leverage 3.0x",
                measured=4.1,
                limit=3.0,
                operator=m.PolicyOperator.LE,
                severity=m.Severity.HIGH,
                period="FY2025",
                waiver_authority="Credit Committee",
            ),
        ),
        policy_version="bank-policy-2026.1",
        rating=m.RiskRatingProposal(
            obligor_grade="6",
            score=4.2,
            scorecard_version="scorecard-v3",
            drivers=(m.RatingDriver(name="Leverage", measured=4.1, band="4.0-4.5", points=3.0),),
        ),
        renewal_delta=m.RenewalDelta(
            prior_version="rev-2",
            ratios=(m.SectionDelta(label="Leverage", before=3.2, after=4.1, unit="x"),),
            new_exceptions=("LEV-01",),
        ),
        related_entities=(entity,),
        guarantors=(m.Guarantor(entity_id="director", name="A Director", is_personal=True),),
        global_cash_flow=m.GlobalCashFlow(
            periods=("FY2025",),
            lines=(
                m.GlobalCashFlowLine(
                    code=m.LineItemCode.EBITDA,
                    period="FY2025",
                    total=115.0,
                    contributions=(
                        m.EntityContribution(
                            entity_id="holdco",
                            entity_name="Acme Holdco",
                            role=m.EntityRole.PARENT,
                            value=115.0,
                        ),
                    ),
                ),
            ),
            entities=(entity,),
            entities_without_figures=("A Director",),
        ),
        scenarios=(
            m.ScenarioResult(
                scenario_id="earnings-decline-15",
                scenario_name="Earnings decline, 15%",
                formula_id="dscr.v1",
                period="FY2025",
                base_value=1.96,
                stressed_value=1.62,
                threshold=1.25,
                passes=True,
                breaks_at=2.4,
            ),
        ),
        recommendation=m.Recommendation(
            action="Approve subject to conditions",
            conditions=(m.Condition(kind=m.ConditionKind.PRECEDENT, detail="security perfected"),),
            required_authority="Credit Committee",
        ),
        authorship={"summary": "edited"},
        confidence=0.8,
        caveats=("one",),
        questions_for_client=("ask about the receivable",),
    )


def _round_trip(memo: m.CreditMemo) -> m.CreditMemo:
    """Exactly what the export path does: build the memo, store the wire form, read back."""
    stored = CreditMemoResponse.from_domain(memo).model_dump(mode="json")
    return to_domain_memo(CreditMemoResponse.model_validate(stored))


# --------------------------------------------------------------------------- #
# The structural guard
# --------------------------------------------------------------------------- #
def test_the_wire_shape_carries_every_memo_field() -> None:
    """A field on the memo and not on the wire is a field the committee never sees.

    Checked against ``dataclasses.fields`` rather than a hand-written list, because a
    hand-written list is what went stale: three waves added artifacts to the memo and none
    of them added the field here.
    """
    memo = _memo()
    missing = [
        f.name
        for f in dataclasses.fields(m.CreditMemo)
        if f.name not in INTENTIONALLY_DERIVED and f.name not in CreditMemoResponse.model_fields
    ]
    assert not missing, (
        f"CreditMemo carries {missing} and CreditMemoResponse does not. The export reads "
        "the stored response, so anything missing here is absent from the pack a "
        "committee receives — and absent silently, which is the part that matters."
    )
    # And present is not the same as preserved: prove each survives the trip.
    after = _round_trip(memo)
    for field in dataclasses.fields(m.CreditMemo):
        if field.name in INTENTIONALLY_DERIVED:
            continue
        before_value = getattr(memo, field.name)
        assert bool(getattr(after, field.name)) == bool(before_value), (
            f"{field.name} was set on the memo and is empty after the round trip"
        )


@pytest.mark.parametrize(
    "heading",
    ["Policy exceptions", "Reconciliation findings", "Risk rating"],
    ids=["policy exceptions", "tie-out", "proposed grade"],
)
def test_the_exported_pack_keeps_the_sections_the_build_computed(heading: str) -> None:
    """The three sections the wire shape used to drop, asserted on the built document.

    Asserted on the pack rather than on the response, because the pack is what a
    committee reads and the document builder had always been able to render these — it
    was simply being handed a memo where they were empty.
    """
    headings = {b.text for b in build_document(_round_trip(_memo())).blocks if b.kind == "heading"}
    assert heading in headings


def test_a_figure_keeps_its_value_and_not_merely_its_shape() -> None:
    """`bool()` above proves presence; this proves the numbers are the same numbers."""
    after = _round_trip(_memo())
    assert after.policy_exceptions[0].measured == 4.1
    assert after.policy_exceptions[0].operator is m.PolicyOperator.LE
    assert after.rating is not None and after.rating.obligor_grade == "6"
    assert after.tie_out[0].check is m.TieOutCheck.BALANCE_SHEET_BALANCES
    assert after.scenarios[0].breaks_at == 2.4
    assert after.global_cash_flow is not None
    assert after.global_cash_flow.entities_without_figures == ("A Director",)
    assert after.global_cash_flow.complete is False


def test_completeness_is_recomputed_rather_than_carried() -> None:
    """A stored boolean that disagrees with the list it summarises fools exactly one
    reader: the next one."""
    stored = CreditMemoResponse.from_domain(_memo()).model_dump(mode="json")
    stored["global_cash_flow"]["complete"] = True  # a lie, planted
    after = to_domain_memo(CreditMemoResponse.model_validate(stored))
    assert after.global_cash_flow is not None
    assert after.global_cash_flow.complete is False
