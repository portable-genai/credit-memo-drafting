"""Every section the console puts on screen is one the committee pack carries out.

The pack is what reaches people who cannot log in: a committee reading a document, an
examiner asking for one years later. The analyst signs off on a SCREEN, so a pack that
quietly carries less than that screen is a different document wearing the same name, and the
difference is invisible from inside either one.

It had already happened twice over, in two different ways:

* `CreditMemoResponse` carried no `policy_exceptions`, no `tie_out` and no `rating`, so the
  document builder was handed a memo where all three were empty and rendered a complete
  looking pack with none of them. `tests/unit/test_the_memo_survives_the_wire.py` is the
  structural guard for that half, and it compares the memo's dataclass fields to the wire.
* The builder itself simply had no code for the peer comparison, the group, the global cash
  flow, the stress results or the model's normalised metrics. The wire carried all five and
  the console rendered all five; the pack a committee receives dropped them. The wire guard
  could not see it, because nothing was missing from the wire.

So this guard compares the two SURFACES rather than a surface and a list. `_HEADING_FOR_HOOK`
is the only hand-written part and it is checked both ways: a console section with no entry
fails, and an entry naming a heading the builder does not emit fails. A section added to the
console in a later wave therefore fails on the day it is added, which is exactly what a list
of expected headings would not do.

Three things this deliberately does NOT assert, each for a reason rather than an oversight:

* **The order.** The pack puts the input manifest near the front, where a reader deciding how
  much weight to give it needs it, and the console puts it last under the memo. Both choices
  are recorded where they are made.
* **The wording inside a section.** A pack spells a provenance out in words because its
  reader has no tooltip to hover. Matching the screen's phrasing is not the goal.
* **Web-grounded research.** It is on no screen that an export reads from, and
  `tests/unit/test_export_contract.py` holds the stronger claim: there is no branch in the
  builder that could include one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from credit_memo.domain.memo_document import build_document
from credit_memo.domain.models import (
    AnalysisManifest,
    Borrower,
    Citation,
    Covenant,
    CovenantOperator,
    CovenantStatus,
    CovenantType,
    CreditMemo,
    CreditRequest,
    DocType,
    Elimination,
    EntityContribution,
    EntityRole,
    FinancialMetric,
    GlobalCashFlow,
    GlobalCashFlowLine,
    Guarantor,
    LineItemCode,
    MemoKind,
    PeerComparison,
    PeerMetric,
    PolicyException,
    PolicyOperator,
    Ratio,
    RelatedEntity,
    RenewalDelta,
    RiskCategory,
    RiskFlag,
    RiskRatingProposal,
    ScenarioResult,
    Severity,
    SourceType,
    StoredDocument,
    TieOutCheck,
    TieOutFinding,
)

MEMO_VIEW = Path(__file__).resolve().parents[2] / "ui" / "components" / "MemoView.tsx"

#: The console's `data-section` hook, and the pack heading that carries the same content.
#: Hand-written on purpose: the two surfaces legitimately word their headings differently,
#: and a reader of this file should be able to see which pairs were decided. What stops it
#: going stale is that both directions are asserted below.
_HEADING_FOR_HOOK: dict[str, str] = {
    "renewal-delta": "What changed since the last review",
    "summary": "Summary",
    "ratios": "Ratios",
    "financial-analysis": "Financial analysis",
    "covenants": "Covenants",
    "risk-assessment": "Risks and mitigants",
    "peer-comparison": "Peer comparison",
    "policy-exceptions": "Policy exceptions",
    "rating": "Risk rating",
    "tie-out": "Reconciliation findings",
    "group": "The group",
    "global-cash-flow": "Global cash flow",
    "stress": "Stress",
    "recommendation-rationale": "Recommendation",
    "questions": "Questions for the borrower",
    "citations": "Sources",
    "manifest": "What this was assessed on",
}


def _console_hooks() -> set[str]:
    """Every section the console renders, read off its own source."""
    source = MEMO_VIEW.read_text(encoding="utf-8")
    hooks = set(re.findall(r'<Section\s+title="[^"]*"\s+hook="([a-z-]+)"', source))
    assert len(hooks) >= 15, (
        f"parsed only {len(hooks)} sections out of {MEMO_VIEW.name}, so this asserts nothing"
    )
    return hooks


def _everything() -> CreditMemo:
    """A memo carrying one of everything a section could render.

    Every conditional section must be populated, or an absent heading would read as a pack
    that omits it rather than as a memo that had nothing to put there.
    """
    entity = RelatedEntity(
        id="holdco",
        name="Acme Holdco (FICTIONAL)",
        role=EntityRole.PARENT,
        ownership_pct=100.0,
        jurisdiction="SG",
    )
    return CreditMemo(
        borrower=Borrower(id="acme", name="Acme Manufacturing (FICTIONAL)"),
        summary="A summary.",
        recommendation_rationale="Support.",
        request=CreditRequest(kind=MemoKind.RENEWAL),
        renewal_delta=RenewalDelta(prior_filename="prior.json"),
        financial_metrics=(FinancialMetric(name="revenue", value=620.0, period="FY2025"),),
        ratios=(
            Ratio(
                formula_id="leverage.v1",
                name="Leverage",
                period="FY2025",
                value=4.1,
                definition="total debt / EBITDA",
            ),
        ),
        covenants=(
            Covenant(
                type=CovenantType.LEVERAGE,
                description="Net leverage",
                threshold=3.0,
                operator=CovenantOperator.LE,
                current_value=4.1,
                status=CovenantStatus.BREACH,
            ),
        ),
        risk_flags=(
            RiskFlag(category=RiskCategory.LEVERAGE, severity=Severity.HIGH, detail="Levered."),
        ),
        peer_comparison=(
            PeerComparison(
                metric="leverage",
                borrower_value=4.1,
                peer_median=2.4,
                percentile=0.9,
                peers=(PeerMetric(peer_name="Peer A (FICTIONAL)", metric="leverage", value=2.4),),
            ),
        ),
        policy_exceptions=(
            PolicyException(
                rule_id="LEV-01",
                description="Maximum leverage",
                measured=4.1,
                limit=3.0,
                operator=PolicyOperator.LE,
                severity=Severity.HIGH,
            ),
        ),
        rating=RiskRatingProposal(obligor_grade="6", score=5.5),
        tie_out=(
            TieOutFinding(
                check=TieOutCheck.BALANCE_SHEET_BALANCES,
                severity=Severity.HIGH,
                detail="Assets do not equal liabilities plus equity.",
            ),
        ),
        related_entities=(entity,),
        guarantors=(
            Guarantor(
                entity_id="director-1",
                name="A Director (FICTIONAL)",
                is_personal=True,
                reliance="Unverified net worth.",
            ),
        ),
        global_cash_flow=GlobalCashFlow(
            periods=("FY2025",),
            lines=(
                GlobalCashFlowLine(
                    code=LineItemCode.EBITDA,
                    period="FY2025",
                    total=115.0,
                    contributions=(
                        EntityContribution(
                            entity_id="acme",
                            entity_name="Acme",
                            role=EntityRole.BORROWER,
                            value=120.0,
                        ),
                    ),
                    eliminations=(
                        Elimination(
                            code=LineItemCode.EBITDA,
                            period="FY2025",
                            amount=5.0,
                            reason="intragroup management fee",
                        ),
                    ),
                ),
            ),
            entities=(entity,),
            entities_without_figures=("A Director (FICTIONAL)",),
        ),
        scenarios=(
            ScenarioResult(
                scenario_id="earnings-decline-15",
                scenario_name="Earnings decline 15%",
                formula_id="dscr.v1",
                period="FY2025",
                base_value=1.8,
                stressed_value=1.5,
                threshold=1.25,
                passes=True,
                breaks_at=2.4,
            ),
        ),
        questions_for_client=("Provide the debt schedule.",),
        citations=(
            Citation(
                source_id="doc-fs",
                source_type=SourceType.FILING,
                title="Audited statements",
                page=4,
            ),
        ),
        manifest=AnalysisManifest(
            analysis_id="an-1",
            borrower_id="acme",
            documents=(
                StoredDocument(
                    id="doc-fs", filename="fs-2025.pdf", doc_type=DocType.FINANCIAL_STATEMENT
                ),
            ),
        ),
    )


def _headings() -> set[str]:
    return {b.text for b in build_document(_everything()).blocks if b.kind == "heading"}


# --------------------------------------------------------------------------- #
# The guard, both directions
# --------------------------------------------------------------------------- #
def test_every_console_section_is_one_the_pairing_accounts_for() -> None:
    """A section added to the console and not decided about here fails on that day."""
    unaccounted = sorted(_console_hooks() - set(_HEADING_FOR_HOOK))
    assert not unaccounted, (
        f"ui/components/MemoView.tsx renders {unaccounted} and this pairing does not name "
        "them, so nothing says whether the committee pack carries that content. Add the "
        "section to src/credit_memo/domain/memo_document.py and pair it here."
    )


def test_the_pairing_names_no_section_the_console_stopped_rendering() -> None:
    """A pair left behind would quietly excuse a pack heading nobody can see on screen."""
    stale = sorted(set(_HEADING_FOR_HOOK) - _console_hooks())
    assert not stale, f"this pairing names console sections that no longer exist: {stale}"


@pytest.mark.parametrize("hook", sorted(_HEADING_FOR_HOOK))
def test_the_pack_carries_the_section_the_console_shows(hook: str) -> None:
    """Parametrised so a failure names the one section that went missing."""
    heading = _HEADING_FOR_HOOK[hook]
    assert heading in _headings(), (
        f"the console shows {hook!r} and the committee pack has no {heading!r} section. The "
        "pack is what reaches a committee, and a pack that carries less than the screen the "
        "analyst signed off differs from it silently."
    )


# --------------------------------------------------------------------------- #
# The five the builder had no code for, asserted on their content
# --------------------------------------------------------------------------- #
def _text() -> str:
    lines: list[str] = []
    for block in build_document(_everything()).blocks:
        lines.extend([block.text, *block.items, *(" ".join(row) for row in block.rows)])
    return "\n".join(lines)


def test_the_peer_comparison_carries_the_percentile_and_not_only_the_median() -> None:
    """4.1x means one thing where the median is 2.4x and another where it is 4.0x."""
    text = _text()
    assert "90th" in text
    assert "Peer A (FICTIONAL)" in text


def test_the_group_names_every_entity_and_what_each_guarantee_is_worth() -> None:
    text = _text()
    assert "Acme Holdco (FICTIONAL)" in text and "parent" in text
    assert "personal guarantee" in text
    assert "Unverified net worth." in text


def test_the_global_cash_flow_leads_with_who_was_left_out_of_it() -> None:
    """A total that silently omits the guarantor nobody filed for is a stronger claim."""
    text = _text()
    assert "Incomplete." in text
    assert "A Director (FICTIONAL)" in text
    # And the contributions behind the total, because 115 is one strong entity or three weak.
    assert "Acme 120.0" in text
    assert "intragroup management fee" in text


def test_the_stress_section_carries_the_break_even_a_committee_can_argue_with() -> None:
    text = _text()
    assert "Earnings decline 15%" in text
    assert "2.40x this scenario" in text
    assert "passes 1.25x" in text


def test_a_scenario_nothing_breaks_says_so_rather_than_leaving_a_blank() -> None:
    memo = _everything()
    survives = ScenarioResult(
        scenario_id="rates-up-200",
        scenario_name="Rates up 200bp",
        formula_id="dscr.v1",
        period="FY2025",
        base_value=5.4,
        stressed_value=4.9,
        threshold=None,
        breaks_at=None,
    )
    lines: list[str] = []
    for block in build_document(
        CreditMemo(
            borrower=memo.borrower,
            summary=memo.summary,
            request=memo.request,
            scenarios=(survives,),
        )
    ).blocks:
        lines.extend([block.text, *(" ".join(row) for row in block.rows)])
    text = "\n".join(lines)
    assert "survives everything modelled" in text
    assert "no covenant states one" in text


def test_the_normalised_metrics_say_the_engine_wins_where_they_disagree() -> None:
    """They are the model's, and a pack that did not say so would read as the bank's."""
    text = _text()
    assert "drafted by the model" in text
    assert "where the two disagree, the engine is the memo" in text
