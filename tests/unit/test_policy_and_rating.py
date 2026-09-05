"""Policy exceptions and the rating proposal: the bank's judgement, arithmetic applied.

Both services exist to do one thing and refuse another.

**Policy exceptions** apply the bank's own uploaded limits and report what a request
misses, with the authority named to waive it. An exception is not a refusal — banks lend
outside their guidelines on purpose, and what supervisors ask is that they know when, at
what level it was approved, and how many are outstanding. What makes the finding credible
is that the limit came from the bank: "your policy requires <= 3.0x and this measures
4.1x" is actionable in a way "our software disapproves" is not.

**The rating** is arithmetic over the bank's own scorecard, offered to an officer. It is
never assigned. An officer who disagrees overrides, and an override that does not name
them and give a reason refuses to construct — a scorecard overridden silently is a
scorecard that was never really used, which is a finding supervisors write up by name.
"""

from __future__ import annotations

import pytest

from credit_memo.domain.memo_templates import (
    recommended_documents,
    required_documents,
    template_for,
)
from credit_memo.domain.models import (
    CreditRequest,
    DocType,
    Facility,
    FinancialSpread,
    LineItem,
    LineItemCode,
    LoanType,
    MemoKind,
    Period,
    PolicyOperator,
    PolicyPack,
    PolicyRule,
    Provenance,
    RatingScorecard,
    Ratio,
    RiskRatingProposal,
    Severity,
)
from credit_memo.domain.policy_exception_service import PolicyExceptionService
from credit_memo.domain.risk_rating_service import RiskRatingService

OFFICER = "officer@bank.example"


def _ratio(formula_id: str, value: float, period: str = "FY2025") -> Ratio:
    return Ratio(formula_id=formula_id, name=formula_id, period=period, value=value)


def _request(**overrides) -> CreditRequest:
    return CreditRequest(
        kind=overrides.pop("kind", MemoKind.NEW_FACILITY),
        loan_type=overrides.pop("loan_type", LoanType.CI_TERM),
        facilities=overrides.pop(
            "facilities", (Facility(id="fac-1", amount=40.0, tenor_months=60),)
        ),
        **overrides,
    )


PACK = PolicyPack(
    version="test-pack-1",
    rules=(
        PolicyRule(
            id="LEV-01",
            description="Maximum senior leverage",
            metric="leverage.v1",
            operator=PolicyOperator.LE,
            limit=3.0,
            severity=Severity.HIGH,
            waiver_authority="Regional Credit Committee",
        ),
        PolicyRule(
            id="DSCR-01",
            description="Minimum debt-service coverage",
            metric="dscr.v1",
            operator=PolicyOperator.GE,
            limit=1.25,
            severity=Severity.MEDIUM,
            waiver_authority="Head of Credit",
        ),
        PolicyRule(
            id="TEN-01",
            description="Maximum tenor",
            metric="tenor_months",
            operator=PolicyOperator.LE,
            limit=84,
            severity=Severity.HIGH,
            knockout=True,
            waiver_authority="Board Credit Committee",
        ),
        PolicyRule(
            id="CRE-01",
            description="CRE-only leverage cap",
            metric="leverage.v1",
            operator=PolicyOperator.LE,
            limit=4.5,
            severity=Severity.HIGH,
            applies_to_loan_types=(LoanType.CRE_INVESTOR,),
        ),
    ),
)


# --------------------------------------------------------------------------- #
# Policy exceptions
# --------------------------------------------------------------------------- #
def test_a_breach_names_the_limit_the_measure_and_who_can_waive_it() -> None:
    """Everything a committee needs to decide, and a reviewer needs to count."""
    (exception,) = PolicyExceptionService().evaluate(
        PACK, _request(), ratios=(_ratio("leverage.v1", 4.1),)
    )
    assert exception.rule_id == "LEV-01"
    assert exception.measured == 4.1
    assert exception.limit == 3.0
    assert exception.waiver_authority == "Regional Credit Committee"
    assert "4.10" in exception.detail and "3.00" in exception.detail
    assert exception.severity is Severity.HIGH


def test_a_request_inside_policy_raises_nothing() -> None:
    assert not PolicyExceptionService().evaluate(
        PACK, _request(), ratios=(_ratio("leverage.v1", 2.4), _ratio("dscr.v1", 1.6))
    )


def test_a_rule_that_cannot_be_measured_is_skipped_not_failed() -> None:
    """ "We could not test this" and "this breached policy" are different sentences.

    Reporting the first as the second would make every thin file look like a bad deal,
    which is how a policy engine gets switched off.
    """
    exceptions = PolicyExceptionService().evaluate(PACK, _request(), ratios=())
    assert [e.rule_id for e in exceptions] == []


def test_a_rule_scoped_to_another_loan_type_does_not_fire() -> None:
    """A CRE cap firing on every C&I memo is noise, and noise gets ignored."""
    exceptions = PolicyExceptionService().evaluate(
        PACK, _request(loan_type=LoanType.CI_TERM), ratios=(_ratio("leverage.v1", 4.1),)
    )
    assert [e.rule_id for e in exceptions] == ["LEV-01"]

    cre = PolicyExceptionService().evaluate(
        PACK, _request(loan_type=LoanType.CRE_INVESTOR), ratios=(_ratio("leverage.v1", 4.1),)
    )
    # 4.1x breaches the 3.0x general cap but sits inside the 4.5x CRE addendum.
    assert {e.rule_id for e in cre} == {"LEV-01"}


def test_a_rule_can_test_the_terms_of_the_ask_not_only_the_financials() -> None:
    (exception,) = PolicyExceptionService().evaluate(
        PACK, _request(facilities=(Facility(id="fac-1", amount=40.0, tenor_months=120),))
    )
    assert exception.rule_id == "TEN-01" and exception.measured == 120.0


def test_knockouts_are_the_subset_a_pre_screen_stops_on() -> None:
    """The handful of rules no amount of committee appetite overrides."""
    service = PolicyExceptionService()
    request = _request(facilities=(Facility(id="fac-1", amount=40.0, tenor_months=120),))
    ratios = (_ratio("leverage.v1", 4.1),)
    assert {e.rule_id for e in service.evaluate(PACK, request, ratios)} == {"LEV-01", "TEN-01"}
    assert {e.rule_id for e in service.knockouts(PACK, request, ratios)} == {"TEN-01"}


def test_exceptions_come_back_most_severe_first() -> None:
    exceptions = PolicyExceptionService().evaluate(
        PACK,
        _request(facilities=(Facility(id="fac-1", amount=40.0, tenor_months=120),)),
        ratios=(_ratio("leverage.v1", 4.1), _ratio("dscr.v1", 1.0)),
    )
    assert [e.severity for e in exceptions] == [Severity.HIGH, Severity.HIGH, Severity.MEDIUM]


def test_an_exception_cannot_be_an_opinion() -> None:
    """It is the result of testing a rule, and the type says so."""
    from credit_memo.domain.models import PolicyException

    with pytest.raises(ValueError, match="not an opinion"):
        PolicyException(
            rule_id="LEV-01",
            description="x",
            measured=4.1,
            limit=3.0,
            operator=PolicyOperator.LE,
            severity=Severity.HIGH,
            provenance=Provenance.MODEL_DRAFTED,
        )


def test_an_empty_pack_raises_nothing_rather_than_inventing_limits() -> None:
    """A deployment that has supplied no policy reports no exceptions, honestly."""
    assert not PolicyExceptionService().evaluate(
        PolicyPack(version="none"), _request(), ratios=(_ratio("leverage.v1", 99.0),)
    )


# --------------------------------------------------------------------------- #
# The rating proposal
# --------------------------------------------------------------------------- #
SCORECARD = RatingScorecard(
    version="test-scorecard-1",
    factors=(
        ("Leverage", "leverage.v1", 2.0, ((1.5, 1.0), (2.5, 2.0), (3.5, 3.0), (999.0, 6.0))),
        ("Interest cover", "interest_cover.v1", 1.0, ((1.5, 7.0), (3.0, 4.0), (999.0, 1.0))),
    ),
    grade_bands=(
        (1.5, "1 - Strong"),
        (2.5, "2 - Good"),
        (3.5, "3 - Satisfactory"),
        (999.0, "5 - Watch"),
    ),
    definitions_url="https://example.internal/rating-definitions",
)


def test_the_grade_is_the_scorecards_arithmetic_and_shows_its_drivers() -> None:
    proposal = RiskRatingService().propose(
        SCORECARD, ratios=(_ratio("leverage.v1", 2.4), _ratio("interest_cover.v1", 5.0))
    )
    assert proposal is not None
    # (2.0 points x weight 2) + (1.0 points x weight 1) = 5.0 over weight 3 => 1.667
    assert proposal.score == pytest.approx(1.6667, abs=1e-3)
    assert proposal.obligor_grade == "2 - Good"
    assert proposal.scorecard_version == "test-scorecard-1"
    assert proposal.definitions_url  # shown at the point of rating, not buried
    leverage = next(d for d in proposal.drivers if d.name == "Leverage")
    assert leverage.measured == 2.4 and leverage.points == 2.0


def test_an_unmeasured_factor_is_shown_and_does_not_count_against_the_borrower() -> None:
    """Scoring a missing figure as zero would read as "they scored badly here"."""
    proposal = RiskRatingService().propose(SCORECARD, ratios=(_ratio("leverage.v1", 2.4),))
    assert proposal is not None
    cover = next(d for d in proposal.drivers if d.name == "Interest cover")
    assert cover.measured is None and cover.band == "not measured"
    # Only the leverage factor's weight counted, so the grade reflects what was measured.
    assert proposal.score == pytest.approx(2.0)


def test_no_measurable_factor_produces_no_grade_at_all() -> None:
    """A grade derived from nothing is worse than none: it looks like an assessment."""
    assert RiskRatingService().propose(SCORECARD, ratios=()) is None


def test_the_scorecard_reads_from_the_confirmed_spread_too() -> None:
    scorecard = RatingScorecard(
        version="v1",
        factors=(("Debt", "total_debt", 1.0, ((100.0, 1.0), (999.0, 5.0))),),
        grade_bands=((2.0, "1 - Strong"), (999.0, "5 - Watch")),
    )
    spread = FinancialSpread(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=(LineItem(code=LineItemCode.TOTAL_DEBT, period="FY2025", value=50.0),),
        confirmed_by=OFFICER,
    )
    proposal = RiskRatingService().propose(scorecard, spread=spread)
    assert proposal is not None and proposal.obligor_grade == "1 - Strong"


def test_an_override_keeps_what_the_scorecard_said() -> None:
    """A memo showing only the final grade cannot answer "did the scorecard agree"."""
    proposal = RiskRatingService().propose(
        SCORECARD, ratios=(_ratio("leverage.v1", 2.4), _ratio("interest_cover.v1", 5.0))
    )
    assert proposal is not None
    overridden = RiskRatingService.override(
        proposal,
        grade="3 - Satisfactory",
        reason="sector headwinds not in the scorecard",
        by=OFFICER,
    )
    assert overridden.obligor_grade == "2 - Good"  # what the arithmetic said
    assert overridden.grade == "3 - Satisfactory"  # what the officer decided
    assert overridden.override_by == OFFICER


@pytest.mark.parametrize(
    ("reason", "by"),
    [("", OFFICER), ("a reason", ""), ("  ", "  ")],
)
def test_a_silent_override_refuses_to_construct(reason: str, by: str) -> None:
    """The finding supervisors write up by name: a scorecard overridden without a word."""
    with pytest.raises(ValueError, match="name the officer and the reason"):
        RiskRatingProposal(
            obligor_grade="2 - Good",
            score=1.7,
            override_grade="1 - Strong",
            override_reason=reason,
            override_by=by,
        )


def test_a_rating_cannot_be_a_models_opinion() -> None:
    with pytest.raises(ValueError, match="not a model's opinion"):
        RiskRatingProposal(
            obligor_grade="1 - Strong", score=1.0, provenance=Provenance.MODEL_DRAFTED
        )


# --------------------------------------------------------------------------- #
# Memo kinds
# --------------------------------------------------------------------------- #
def test_each_kind_leads_with_what_its_reader_came_for() -> None:
    assert template_for(MemoKind.NEW_FACILITY).sections[0] == "The request"
    assert template_for(MemoKind.RENEWAL).sections[0] == "What changed since the last review"
    assert template_for(MemoKind.PRE_SCREEN).sections[0] == "Bankability"
    assert template_for(MemoKind.DECLINE).sections[1] == "Reasons"


def test_a_renewal_requires_the_prior_memo() -> None:
    """Without it this is a new-facility memo wearing a renewal's title."""
    assert DocType.PRIOR_MEMO in required_documents(MemoKind.RENEWAL, LoanType.CI_TERM)


def test_loan_type_adds_to_the_checklist_rather_than_replacing_it() -> None:
    required = required_documents(MemoKind.NEW_FACILITY, LoanType.CRE_INVESTOR)
    assert DocType.FINANCIAL_STATEMENT in required  # from the kind
    assert DocType.RENT_ROLL in required  # from the loan type


def test_a_pre_screen_demands_nothing_and_proposes_no_grade() -> None:
    """A pre-screen that demands a full credit file is a pre-screen nobody runs.

    And a grade from a two-document package puts a number in front of a committee that
    the package cannot support.
    """
    assert required_documents(MemoKind.PRE_SCREEN, LoanType.OTHER) == ()
    assert not template_for(MemoKind.PRE_SCREEN).proposes_rating
    assert not template_for(MemoKind.DECLINE).proposes_rating


def test_recommended_never_repeats_what_is_already_required() -> None:
    for kind in MemoKind:
        for loan_type in LoanType:
            overlap = set(required_documents(kind, loan_type)) & set(
                recommended_documents(kind, loan_type)
            )
            assert not overlap, f"{kind.value}/{loan_type.value} lists {overlap} twice"


def test_every_kind_has_a_template_and_a_purpose() -> None:
    """A kind with no template would silently fall back to a new-facility memo."""
    for kind in MemoKind:
        template = template_for(kind)
        assert template.kind is kind, f"{kind.value} falls back to {template.kind.value}"
        assert template.sections and template.purpose
