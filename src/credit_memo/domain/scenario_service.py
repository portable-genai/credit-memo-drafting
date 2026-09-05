"""ScenarioService — how far this can fall before it breaks.

Stress testing in a credit memo is usually done backwards. A memo states the DSCR under
a 15% EBITDA decline, and a committee has no way to judge whether 15% is the right test
for this sector this year. The more useful number is the break-even: how far EBITDA can
fall before the covenant is breached. A committee can hold that against their own view of
the sector, which is a judgement they are qualified to make and this service is not.

So every result carries both. ``stressed_value`` answers the scenario the bank's policy
pack defined; ``breaks_at`` answers the question underneath it.

The scenario set is the bank's, uploaded with the policy pack. Nothing here decides that a
200 basis point rate rise is the right test, because that is a risk-appetite question and
this service does not have an appetite.

Arithmetic over a confirmed spread, so a scenario is as replayable as the ratio it
stresses. No ports, no I/O, no model.
"""

from __future__ import annotations

from . import ratio_catalogue as catalogue
from .models import (
    FinancialSpread,
    LineItem,
    LineItemCode,
    Period,
    Scenario,
    ScenarioResult,
)
from .ratio_service import RatioService

#: A shipped set, and an example like the policy pack's limits. Named for what they test
#: rather than for a number, so a bank replacing them can see what each was for.
DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="earnings-decline-15",
        name="Earnings decline, 15%",
        description="Trading deteriorates: EBITDA falls 15% with debt service unchanged.",
        shocks=((LineItemCode.EBITDA, 0.85),),
    ),
    Scenario(
        id="rate-rise-200bp",
        name="Rate rise, 200bp",
        description=(
            "Floating-rate cost rises: interest expense and scheduled debt service each "
            "increase 25%, approximating a 200bp move on a mid-single-digit coupon."
        ),
        shocks=(
            (LineItemCode.INTEREST_EXPENSE, 1.25),
            (LineItemCode.SCHEDULED_DEBT_SERVICE, 1.25),
        ),
    ),
    Scenario(
        id="combined",
        name="Earnings decline with a rate rise",
        description="Both at once, which is how they usually arrive.",
        shocks=(
            (LineItemCode.EBITDA, 0.85),
            (LineItemCode.INTEREST_EXPENSE, 1.25),
            (LineItemCode.SCHEDULED_DEBT_SERVICE, 1.25),
        ),
    ),
)

#: Break-even search bounds. Below 0.30 a business is not stressed, it has stopped, and a
#: covenant test on a 70% earnings decline tells a committee nothing they did not know.
_SEARCH_FLOOR = 0.30
_SEARCH_STEPS = 140


class ScenarioService:
    """Apply the bank's shocks to a confirmed spread and report what breaks."""

    def __init__(self) -> None:
        self._ratios = RatioService()

    def run(
        self,
        spread: FinancialSpread,
        formula_id: str,
        threshold: float | None = None,
        higher_is_better: bool = True,
        period: str = "",
        scenarios: tuple[Scenario, ...] = (),
    ) -> tuple[ScenarioResult, ...]:
        """Every scenario's effect on one ratio, plus where it breaks.

        ``threshold`` is normally a covenant's. Without one the result still carries the
        stressed value: "leverage becomes 4.1x under a 15% decline" is useful even when
        no covenant tests it.
        """
        formula = catalogue.formula(formula_id)
        if formula is None or not spread.items:
            return ()
        wanted = period or (spread.period_labels[-1] if spread.periods else "")
        if not wanted:
            return ()

        base = self._ratios.compute(spread, formula, wanted)
        out: list[ScenarioResult] = []
        for scenario in scenarios or DEFAULT_SCENARIOS:
            stressed = self._ratios.compute(self._shocked(spread, scenario), formula, wanted)
            out.append(
                ScenarioResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    formula_id=formula.id,
                    period=wanted,
                    base_value=base.value,
                    stressed_value=stressed.value,
                    threshold=threshold,
                    passes=self._passes(stressed.value, threshold, higher_is_better),
                    breaks_at=self._break_even(
                        spread, formula, wanted, scenario, threshold, higher_is_better
                    ),
                )
            )
        return tuple(out)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _shocked(
        spread: FinancialSpread, scenario: Scenario, severity: float = 1.0
    ) -> FinancialSpread:
        """The spread with the scenario applied, scaled by ``severity``.

        ``severity`` of 1.0 is the scenario as written; 0.5 is half of it. Scaling the
        DEVIATION from 1.0 rather than the multiplier itself keeps the direction right:
        half of "EBITDA falls 15%" is a 7.5% fall, not a multiplier of 0.425.
        """
        shocks = dict(scenario.shocks)
        return FinancialSpread(
            borrower_id=spread.borrower_id,
            periods=spread.periods or tuple(Period(label=p) for p in spread.period_labels),
            items=tuple(
                LineItem(
                    code=item.code,
                    period=item.period,
                    value=item.value * (1.0 + (shocks.get(item.code, 1.0) - 1.0) * severity),
                    currency=item.currency,
                    provenance=item.provenance,
                    citations=item.citations,
                )
                for item in spread.items
            ),
            currency=spread.currency,
            unit=spread.unit,
            confirmed_by=spread.confirmed_by,
            confirmed_at=spread.confirmed_at,
        )

    @staticmethod
    def _passes(
        value: float | None, threshold: float | None, higher_is_better: bool
    ) -> bool | None:
        if value is None or threshold is None:
            return None
        return value >= threshold if higher_is_better else value <= threshold

    def _break_even(
        self,
        spread: FinancialSpread,
        formula: object,
        period: str,
        scenario: Scenario,
        threshold: float | None,
        higher_is_better: bool,
    ) -> float | None:
        """How much of this scenario the borrower absorbs before the test fails.

        Returned as a severity multiple of the scenario: 2.0 means it takes twice the
        shock, 0.5 means half of it is already too much. Expressed against the scenario
        rather than in absolute terms because that is what a committee compares against
        their own view — "it survives twice the decline we modelled" is a sentence they
        can argue with.

        A linear scan rather than a bisection: the ratio is not guaranteed monotonic in
        severity (a formula can have shocked lines in both numerator and denominator),
        and a bisection over a non-monotonic function silently returns a wrong answer
        while looking precise.
        """
        if threshold is None:
            return None
        base = self._ratios.compute(spread, formula, period)  # type: ignore[arg-type]
        if base.value is None or not self._passes(base.value, threshold, higher_is_better):
            return 0.0  # already failing before any stress is applied

        for step in range(1, _SEARCH_STEPS + 1):
            severity = step * (1.0 / 20.0)  # 0.05 increments out to 7x the scenario
            probe = self._ratios.compute(self._shocked(spread, scenario, severity), formula, period)  # type: ignore[arg-type]
            if probe.value is None:
                return None
            if not self._passes(probe.value, threshold, higher_is_better):
                return round(severity, 2)
            if severity >= 1.0 and all(
                v * (1.0 + (dict(scenario.shocks).get(c, 1.0) - 1.0) * severity) < _SEARCH_FLOOR * v
                for c, v in ((i.code, i.value) for i in spread.items)
                if c in dict(scenario.shocks) and v
            ):
                break
        return None  # survives everything worth modelling
