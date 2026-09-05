"""The group's combined position, and how far it can fall before it breaks.

Most mid-market lending is to a group. The borrower is an operating subsidiary, the
property sits in a holdco, a director has guaranteed it personally, and the question a
credit officer is actually asking is whether the combined cash covers the combined debt.

Two properties make the answer trustworthy rather than merely available, and both are
about what the calculation refuses to hide:

* **It says what it could not include.** A global cash flow is only as complete as the
  statements behind it. One that silently omits the guarantor whose accounts nobody
  uploaded reads as though that guarantor contributes nothing, which is a stronger claim
  than "we did not look".
* **It reports break-even, not just the scenario.** A committee cannot judge whether a 15%
  decline is the right test for this sector. They can judge "it survives twice that",
  which is a question about their own view of the world rather than about the model's.
"""

from __future__ import annotations

import pytest

from credit_memo.domain.global_cash_flow_service import GlobalCashFlowService
from credit_memo.domain.models import (
    Elimination,
    EntityRole,
    FinancialSpread,
    GlobalCashFlowLine,
    LineItem,
    LineItemCode,
    Period,
    Provenance,
    RelatedEntity,
    Scenario,
)
from credit_memo.domain.scenario_service import DEFAULT_SCENARIOS, ScenarioService

OPCO = RelatedEntity(id="opco", name="Acme Opco", role=EntityRole.BORROWER)
HOLDCO = RelatedEntity(id="holdco", name="Acme Holdco", role=EntityRole.PARENT)
DIRECTOR = RelatedEntity(id="director", name="A Director", role=EntityRole.GUARANTOR_PERSONAL)


def _spread(entity_id: str, period: str = "FY2025", **values: float) -> FinancialSpread:
    return FinancialSpread(
        borrower_id=entity_id,
        periods=(Period(label=period),),
        items=tuple(
            LineItem(code=LineItemCode(code), period=period, value=value)
            for code, value in values.items()
        ),
        confirmed_by="analyst@bank.example",
    )


# --------------------------------------------------------------------------- #
# Consolidation
# --------------------------------------------------------------------------- #
def test_every_entitys_contribution_is_visible() -> None:
    """A consolidated 115 says nothing about whether it is one strong entity or three.

    That distinction is the difference between a group that can support the facility and
    one where a single subsidiary can.
    """
    gcf = GlobalCashFlowService().consolidate(
        (OPCO, HOLDCO),
        {"opco": _spread("opco", ebitda=100.0), "holdco": _spread("holdco", ebitda=15.0)},
    )
    (line,) = [line for line in gcf.lines if line.code is LineItemCode.EBITDA]
    assert line.total == 115.0
    assert {(c.entity_name, c.value) for c in line.contributions} == {
        ("Acme Opco", 100.0),
        ("Acme Holdco", 15.0),
    }


def test_eliminations_are_shown_not_netted_silently() -> None:
    """A group whose revenue halves on consolidation is saying something important."""
    gcf = GlobalCashFlowService().consolidate(
        (OPCO, HOLDCO),
        {"opco": _spread("opco", revenue=620.0), "holdco": _spread("holdco", revenue=80.0)},
        eliminations=(
            Elimination(
                code=LineItemCode.REVENUE,
                period="FY2025",
                amount=60.0,
                between="opco -> holdco",
                reason="management fee",
            ),
        ),
    )
    (line,) = [line for line in gcf.lines if line.code is LineItemCode.REVENUE]
    assert line.total == 640.0
    assert line.eliminated == 60.0
    assert line.eliminations[0].reason == "management fee"


def test_an_entity_with_no_figures_is_named_rather_than_omitted() -> None:
    """The property that keeps the whole calculation honest."""
    gcf = GlobalCashFlowService().consolidate(
        (OPCO, HOLDCO, DIRECTOR),
        {"opco": _spread("opco", ebitda=100.0), "holdco": _spread("holdco", ebitda=15.0)},
    )
    assert not gcf.complete
    assert gcf.entities_without_figures == ("A Director",)


def test_a_group_where_everyone_reported_is_complete() -> None:
    gcf = GlobalCashFlowService().consolidate(
        (OPCO, HOLDCO),
        {"opco": _spread("opco", ebitda=100.0), "holdco": _spread("holdco", ebitda=15.0)},
    )
    assert gcf.complete and gcf.entities_without_figures == ()


def test_only_periods_every_entity_reports_are_consolidated() -> None:
    """The intersection, not the union.

    Consolidating a period one entity reports and another does not produces a total that
    silently excludes an entity — the most misleading shape this calculation can take,
    because it looks complete.
    """
    opco = FinancialSpread(
        borrower_id="opco",
        periods=(Period(label="FY2024"), Period(label="FY2025")),
        items=(
            LineItem(code=LineItemCode.EBITDA, period="FY2024", value=90.0),
            LineItem(code=LineItemCode.EBITDA, period="FY2025", value=100.0),
        ),
        confirmed_by="analyst",
    )
    holdco = _spread("holdco", period="FY2025", ebitda=15.0)
    gcf = GlobalCashFlowService().consolidate((OPCO, HOLDCO), {"opco": opco, "holdco": holdco})

    assert gcf.periods == ("FY2025",)
    assert gcf.value(LineItemCode.EBITDA, "FY2024") is None
    assert gcf.value(LineItemCode.EBITDA, "FY2025") == 115.0


def test_a_consolidated_line_cannot_be_an_assertion() -> None:
    with pytest.raises(ValueError, match="not an assertion"):
        GlobalCashFlowLine(
            code=LineItemCode.EBITDA,
            period="FY2025",
            total=115.0,
            provenance=Provenance.MODEL_DRAFTED,
        )


def test_the_consolidated_spread_is_computable_and_says_where_it_came_from() -> None:
    """Every item is CONFIRMED: each is the sum of figures a person confirmed.

    ``Ratio`` stays the only COMPUTED thing, so a ratio over this spread is still
    properly marked as calculated.
    """
    service = GlobalCashFlowService()
    gcf = service.consolidate(
        (OPCO, HOLDCO),
        {"opco": _spread("opco", ebitda=100.0), "holdco": _spread("holdco", ebitda=15.0)},
    )
    spread = service.as_spread(gcf, "acme-group")
    assert spread.value(LineItemCode.EBITDA, "FY2025") == 115.0
    assert all(i.provenance is Provenance.CONFIRMED for i in spread.items)
    assert "consolidated" in spread.confirmed_by


# --------------------------------------------------------------------------- #
# Stress
# --------------------------------------------------------------------------- #
def _group() -> FinancialSpread:
    return _spread(
        "acme-group",
        ebitda=115.0,
        interest_expense=25.0,
        capex=10.0,
        tax_expense=7.0,
        scheduled_debt_service=50.0,
    )


def test_a_scenario_reports_both_the_shocked_value_and_the_break_even() -> None:
    """The break-even is the number a committee can actually argue with.

    They cannot judge whether 15% is the right decline for this sector. They can judge
    "it survives twice that".
    """
    results = ScenarioService().run(_group(), "dscr.v1", threshold=1.25)
    decline = next(r for r in results if r.scenario_id == "earnings-decline-15")
    assert decline.base_value == pytest.approx(1.96, abs=0.01)
    assert decline.stressed_value is not None
    assert decline.stressed_value < decline.base_value
    assert decline.passes is True
    assert decline.breaks_at and decline.breaks_at > 1.0


def test_a_combined_shock_bites_harder_than_either_alone() -> None:
    """And the break-even makes that visible as a single comparable number."""
    results = {r.scenario_id: r for r in ScenarioService().run(_group(), "dscr.v1", threshold=1.25)}
    combined = results["combined"]
    assert combined.breaks_at is not None
    assert combined.breaks_at < results["earnings-decline-15"].breaks_at
    assert combined.breaks_at < results["rate-rise-200bp"].breaks_at


def test_a_ratio_already_failing_breaks_at_zero() -> None:
    """No stress is needed to break something already broken, and 0.0 says exactly that."""
    weak = _spread("weak", ebitda=40.0, capex=5.0, tax_expense=5.0, scheduled_debt_service=50.0)
    (result,) = ScenarioService().run(
        weak, "dscr.v1", threshold=1.25, scenarios=(DEFAULT_SCENARIOS[0],)
    )
    assert result.passes is False
    assert result.breaks_at == 0.0


def test_without_a_threshold_the_stressed_value_is_still_reported() -> None:
    """ "Leverage becomes 4.1x under a 15% decline" is useful with no covenant behind it."""
    (result,) = ScenarioService().run(
        _group(), "interest_cover.v1", scenarios=(DEFAULT_SCENARIOS[0],)
    )
    assert result.stressed_value is not None
    assert result.threshold is None and result.passes is None and result.breaks_at is None


def test_half_a_scenario_is_half_the_deviation_not_half_the_multiplier() -> None:
    """Half of "EBITDA falls 15%" is a 7.5% fall, not a multiplier of 0.425."""
    shocked = ScenarioService._shocked(
        _group(),
        Scenario(id="s", name="s", shocks=((LineItemCode.EBITDA, 0.85),)),
        severity=0.5,
    )
    assert shocked.value(LineItemCode.EBITDA, "FY2025") == pytest.approx(115.0 * 0.925)


def test_a_scenario_leaves_unshocked_lines_alone() -> None:
    shocked = ScenarioService._shocked(
        _group(),
        Scenario(id="s", name="s", shocks=((LineItemCode.EBITDA, 0.85),)),
    )
    assert shocked.value(LineItemCode.SCHEDULED_DEBT_SERVICE, "FY2025") == 50.0


def test_an_uncomputable_ratio_produces_no_scenario_rather_than_a_guess() -> None:
    """DSCR needs capex and tax; a group that did not supply them gets no stress test."""
    thin = _spread("thin", ebitda=115.0, interest_expense=25.0)
    (result,) = ScenarioService().run(
        thin, "dscr.v1", threshold=1.25, scenarios=(DEFAULT_SCENARIOS[0],)
    )
    assert result.base_value is None and result.stressed_value is None


def test_an_unknown_formula_returns_nothing() -> None:
    assert ScenarioService().run(_group(), "not-a-formula.v9", threshold=1.0) == ()
