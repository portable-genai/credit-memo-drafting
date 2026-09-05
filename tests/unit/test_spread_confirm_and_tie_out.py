"""The confirm gate, and the reconciliations that make it worth confirming.

Wave 0 made a ratio impossible to fake. This is the other half: making sure the figures
the ratio is computed FROM went past a person, and giving that person something to look
at other than a wall of numbers.

The confirm step is the control experts describe as the one they will not give up. A
model reads a financial table well and misreads one occasionally, and the difference is
visible to an analyst in seconds and invisible to everyone downstream forever. These
tests hold the properties that make the step real rather than ceremonial:

* a candidate cannot reach an engine without passing through ``confirm``
* confirming names a person, and rejecting drops a figure rather than zeroing it
* an adjustment keeps what the document said, beside what the analyst decided
* the reconciliations fire on the things an examiner asks about, and stay quiet otherwise
"""

from __future__ import annotations

import pytest

from credit_memo.domain.errors import SpreadNotConfirmedError
from credit_memo.domain.models import (
    Adjustment,
    Borrower,
    CandidateLineItem,
    CreditRequest,
    FinancialSpread,
    FundingLine,
    LineItem,
    LineItemCode,
    MemoInput,
    Period,
    Provenance,
    Severity,
    SourcesAndUses,
    SpreadCandidate,
    TieOutCheck,
)
from credit_memo.domain.spread_service import SpreadService, adjustment_for
from credit_memo.domain.tie_out_service import TieOutService

ANALYST = "analyst@bank.example"


def _candidate(**overrides) -> SpreadCandidate:
    return SpreadCandidate(
        borrower_id="acme",
        periods=(Period(label="FY2024"), Period(label="FY2025")),
        items=(
            CandidateLineItem(
                code=LineItemCode.EBITDA,
                period="FY2025",
                value=18.0,
                document_id="doc-fs",
                page=4,
                quote="EBITDA for the year was 18.0",
            ),
            CandidateLineItem(
                code=LineItemCode.TOTAL_DEBT,
                period="FY2025",
                value=54.0,
                document_id="doc-fs",
                page=5,
                quote="Total borrowings stood at 54.0",
            ),
        ),
        **overrides,
    )


# --------------------------------------------------------------------------- #
# The gate itself
# --------------------------------------------------------------------------- #
def test_a_candidate_cannot_be_computed_on_without_passing_through_confirm() -> None:
    """There is no route from extraction to the ratio engine that skips a person.

    Not because a check forbids it, but because the types do: a candidate's items are
    EXTRACTED and a spread refuses to hold one.
    """
    candidate = _candidate()
    with pytest.raises(ValueError, match="engine may read"):
        FinancialSpread(
            borrower_id=candidate.borrower_id,
            periods=candidate.periods,
            items=tuple(
                LineItem(
                    code=i.code,
                    period=i.period,
                    value=i.value,
                    provenance=Provenance.EXTRACTED,
                )
                for i in candidate.items
            ),
        )


def test_confirming_requires_a_named_person() -> None:
    """An unattributed confirmation says somebody looked without saying who."""
    with pytest.raises(ValueError, match="named actor"):
        SpreadService().confirm(_candidate(), actor="   ")


def test_confirmed_figures_become_computable_and_keep_their_page() -> None:
    spread = SpreadService().confirm(_candidate(), actor=ANALYST)
    assert spread.confirmed_by == ANALYST
    assert SpreadService.is_confirmed(spread)
    ebitda = next(i for i in spread.items if i.code is LineItemCode.EBITDA)
    assert ebitda.provenance is Provenance.CONFIRMED
    # The page survives confirmation, so the grid cell can still open the source.
    assert [(c.source_id, c.page) for c in ebitda.citations] == [("doc-fs", 4)]


def test_a_rejected_figure_is_absent_rather_than_zero() -> None:
    """Zero is a number an engine will happily divide by. Absent is a fact it reports."""
    spread = SpreadService().confirm(
        _candidate(), actor=ANALYST, rejected=((LineItemCode.EBITDA, "FY2025"),)
    )
    assert spread.value(LineItemCode.EBITDA, "FY2025") is None
    assert spread.value(LineItemCode.TOTAL_DEBT, "FY2025") == 54.0


def test_an_adjustment_keeps_what_the_document_said() -> None:
    """ "The statements said 18 and we normalised to 24 for the disposal" is the sentence
    a committee is entitled to, and it cannot be written from the after-value alone."""
    candidate = _candidate()
    adjustment = adjustment_for(
        candidate,
        LineItemCode.EBITDA,
        "FY2025",
        after=24.0,
        reason="add back the one-off disposal loss",
        actor=ANALYST,
    )
    assert adjustment.before == 18.0

    spread = SpreadService().confirm(candidate, actor=ANALYST, adjustments=(adjustment,))
    ebitda = next(i for i in spread.items if i.code is LineItemCode.EBITDA)
    assert ebitda.value == 24.0
    # The analyst's figure, not the document's — and the citation stays, so a reader sees
    # both the page and that somebody changed what was on it.
    assert ebitda.provenance is Provenance.USER_ENTERED
    assert ebitda.citations


def test_an_adjustment_must_say_why_and_who() -> None:
    for kwargs in (
        {"reason": "  ", "actor": ANALYST},
        {"reason": "a reason", "actor": " "},
    ):
        with pytest.raises(ValueError):
            Adjustment(code=LineItemCode.EBITDA, period="FY2025", before=18.0, after=24.0, **kwargs)


def test_a_typed_spread_is_confirmed_by_construction() -> None:
    """A person who typed every figure has, by definition, reviewed every figure."""
    typed = FinancialSpread(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=(LineItem(code=LineItemCode.EBITDA, period="FY2025", value=100.0),),
    )
    assert SpreadService.is_confirmed(typed)


def test_the_pipeline_refuses_to_build_on_an_unconfirmed_spread(
    credit_memo_service,
) -> None:
    """Skipping the confirm step is an error with a remedy, not a degraded mode.

    The spread below is constructible: its items are CONFIRMED, which an engine may read.
    What it lacks is a person's name against the confirmation, and that is the whole
    difference between "a model produced these figures" and "the bank accepted them".
    """
    unconfirmed = FinancialSpread(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=(
            LineItem(
                code=LineItemCode.EBITDA,
                period="FY2025",
                value=100.0,
                provenance=Provenance.CONFIRMED,
            ),
        ),
        confirmed_by="",
    )
    assert not SpreadService.is_confirmed(unconfirmed)

    with pytest.raises(SpreadNotConfirmedError, match="confirmed by a person"):
        credit_memo_service.build(
            MemoInput(borrower=Borrower(id="acme", name="Acme"), spreads=(unconfirmed,)),
            actor="analyst",
        )


# --------------------------------------------------------------------------- #
# The reconciliations
# --------------------------------------------------------------------------- #
def _spread(**values: float) -> FinancialSpread:
    return FinancialSpread(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=tuple(
            LineItem(code=LineItemCode(code), period="FY2025", value=value)
            for code, value in values.items()
        ),
        confirmed_by=ANALYST,
    )


def test_a_quote_that_is_not_on_the_page_is_flagged() -> None:
    """The cheapest hallucination detector available: look for the quote."""
    candidate = SpreadCandidate(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=(
            CandidateLineItem(
                code=LineItemCode.EBITDA,
                period="FY2025",
                value=99.0,
                document_id="doc-fs",
                page=2,
                quote="EBITDA for the year was 99.0",
            ),
        ),
    )
    findings = TieOutService().check(
        _spread(ebitda=99.0),
        candidate=candidate,
        pages_by_document={"doc-fs": ("page one text", "page two says nothing of the sort")},
    )
    assert [f.check for f in findings] == [TieOutCheck.QUOTE_ON_PAGE]
    assert findings[0].severity is Severity.HIGH


def test_a_quote_that_is_on_the_page_passes_despite_pdf_whitespace() -> None:
    """A PDF text layer breaks lines mid-sentence; the check is about words, not layout."""
    candidate = SpreadCandidate(
        borrower_id="acme",
        periods=(Period(label="FY2025"),),
        items=(
            CandidateLineItem(
                code=LineItemCode.EBITDA,
                period="FY2025",
                value=24.0,
                document_id="doc-fs",
                page=1,
                quote="EBITDA for the year was 24.0",
            ),
        ),
    )
    findings = TieOutService().check(
        _spread(ebitda=24.0),
        candidate=candidate,
        pages_by_document={"doc-fs": ("Group results.  EBITDA  for the\nyear was 24.0 million.",)},
    )
    assert not [f for f in findings if f.check is TieOutCheck.QUOTE_ON_PAGE]


def test_a_balance_sheet_that_does_not_balance_is_flagged() -> None:
    findings = TieOutService().check(
        _spread(total_assets=500.0, total_debt=200.0, current_liabilities=50.0, total_equity=100.0)
    )
    balance = [f for f in findings if f.check is TieOutCheck.BALANCE_SHEET_BALANCES]
    assert balance and balance[0].expected == 350.0 and balance[0].actual == 500.0


def test_a_balance_sheet_that_balances_within_rounding_is_not_flagged() -> None:
    """Statements are published in thousands; a half-unit gap is presentation."""
    findings = TieOutService().check(
        _spread(total_assets=350.4, total_debt=200.0, current_liabilities=50.0, total_equity=100.0)
    )
    assert not [f for f in findings if f.check is TieOutCheck.BALANCE_SHEET_BALANCES]


def test_sources_that_do_not_equal_uses_are_flagged() -> None:
    request = CreditRequest(
        sources_and_uses=SourcesAndUses(
            sources=(FundingLine(label="New term loan", amount=40.0),),
            uses=(
                FundingLine(label="Refinance", amount=30.0),
                FundingLine(label="Capex", amount=20.0),
            ),
        )
    )
    findings = TieOutService().check(_spread(ebitda=10.0), request=request)
    gap = [f for f in findings if f.check is TieOutCheck.SOURCES_EQUAL_USES]
    assert gap and gap[0].actual == 40.0 and gap[0].expected == 50.0


def test_a_certificate_that_disagrees_with_the_engine_is_flagged() -> None:
    findings = TieOutService().check(
        _spread(ebitda=10.0),
        reported_covenants=(("Net leverage <= 3.0x", 1.1, 4.0),),
    )
    disagreement = [f for f in findings if f.check is TieOutCheck.CERTIFICATE_AGREES]
    assert disagreement and disagreement[0].expected == 4.0 and disagreement[0].actual == 1.1


def test_a_gap_in_the_middle_of_a_series_is_flagged() -> None:
    """A gap in a trend is a different story from a decline and reads the same."""
    spread = FinancialSpread(
        borrower_id="acme",
        periods=(Period(label="FY2023"), Period(label="FY2024"), Period(label="FY2025")),
        items=(
            LineItem(code=LineItemCode.REVENUE, period="FY2023", value=100.0),
            LineItem(code=LineItemCode.REVENUE, period="FY2025", value=140.0),
        ),
        confirmed_by=ANALYST,
    )
    findings = TieOutService().check(spread)
    gaps = [f for f in findings if f.check is TieOutCheck.PERIOD_CONTINUITY]
    assert gaps and "FY2024" in gaps[0].detail


def test_a_clean_file_raises_nothing_loud() -> None:
    """A tie-out that cries wolf gets switched off, and then it is not a control at all."""
    findings = TieOutService().check(
        _spread(total_assets=350.0, total_debt=200.0, current_liabilities=50.0, total_equity=100.0),
        narrative="The borrower's leverage of 2.0x sits inside the 3.0x covenant.",
    )
    loud = [f for f in findings if f.severity in {Severity.HIGH, Severity.CRITICAL}]
    assert not loud, [f.detail for f in loud]


def test_findings_come_back_most_severe_first() -> None:
    """A reviewer reads the gutter top-down and stops when it stops mattering."""
    findings = TieOutService().check(
        _spread(total_assets=500.0, total_debt=200.0, current_liabilities=50.0, total_equity=100.0),
        narrative="Revenue reached 9,999,999.00 for the year.",
    )
    severities = [f.severity for f in findings]
    assert severities == sorted(
        severities,
        key=lambda s: {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}[
            s
        ],
    )
