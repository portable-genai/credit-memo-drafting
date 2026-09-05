"""RatioService — the deterministic ratio engine.

The one place a credit ratio is calculated. It takes a
:class:`~credit_memo.domain.models.FinancialSpread` (whose type already refuses
unconfirmed figures) and a formula from
:mod:`credit_memo.domain.ratio_catalogue`, and returns a
:class:`~credit_memo.domain.models.Ratio` (whose type already refuses any provenance but
``COMPUTED``). Between those two refusals there is no route by which a model-asserted
number becomes a ratio in the memo.

Two rules the arithmetic follows, both of which are "say so" rather than "guess":

* **A missing operand yields no ratio.** The result carries ``value=None`` and names the
  line and period that were absent. Imputing a zero would turn "we were not given the
  interest expense" into "interest cover is infinite".
* **A zero denominator yields no ratio.** Same treatment, different reason.

Takes no ports and does no I/O, so it is replayable: the same spread and the same
catalogue version produce the same numbers, byte for byte, forever.
"""

from __future__ import annotations

from . import ratio_catalogue as catalogue
from .models import (
    CovenantType,
    FinancialSpread,
    FormulaTerm,
    LineItemCode,
    Ratio,
    RatioFormula,
    RatioInput,
)


class RatioService:
    """Compute credit ratios from a confirmed spread. No ports, no I/O, no model."""

    def compute(
        self,
        spread: FinancialSpread,
        formula: RatioFormula,
        period: str,
    ) -> Ratio:
        """Compute one ratio for one period, or say which input was missing."""
        numerator, missing_num = self._side(spread, formula.numerator, period, "numerator")
        denominator, missing_den = self._side(spread, formula.denominator, period, "denominator")
        missing = missing_num + missing_den
        if missing:
            return self._absent(
                formula,
                period,
                f"{self._describe(missing)} not supplied for {period}",
            )

        num_total = sum(i.value * i.coefficient for i in numerator)
        if not formula.denominator:
            # A subtraction, not a ratio: tangible net worth is the numerator itself.
            return Ratio(
                formula_id=formula.id,
                name=formula.name,
                period=period,
                value=num_total,
                unit=formula.unit,
                higher_is_better=formula.higher_is_better,
                inputs=tuple(numerator),
                definition=formula.definition,
            )

        den_total = sum(i.value * i.coefficient for i in denominator)
        if den_total == 0:
            return self._absent(
                formula,
                period,
                f"denominator ({formula.definition.split('/')[-1].strip()}) is zero for {period}",
            )

        return Ratio(
            formula_id=formula.id,
            name=formula.name,
            period=period,
            value=num_total / den_total,
            unit=formula.unit,
            higher_is_better=formula.higher_is_better,
            inputs=tuple(numerator) + tuple(denominator),
            definition=formula.definition,
        )

    def compute_all(
        self,
        spread: FinancialSpread,
        periods: tuple[str, ...] = (),
        formulas: tuple[RatioFormula, ...] = (),
    ) -> tuple[Ratio, ...]:
        """Every catalogue ratio for every period of the spread, computable or not.

        Ratios that could not be computed are returned too, carrying their reason. A
        panel that silently omitted them would read as "we did not think leverage was
        worth stating" rather than "you did not give us the debt figure".
        """
        wanted_periods = periods or spread.period_labels
        wanted_formulas = formulas or catalogue.FORMULAS
        return tuple(
            self.compute(spread, formula, period)
            for period in wanted_periods
            for formula in wanted_formulas
        )

    def measure_covenant(
        self,
        spread: FinancialSpread,
        covenant_type: CovenantType,
        period: str,
    ) -> Ratio | None:
        """The computed value a covenant of this type should be tested against.

        Returns None when the policy table maps this covenant type to no formula, or
        when the spread cannot support it. The caller then falls back to whatever the
        extraction reported, clearly labelled as unmeasured.
        """
        formula = catalogue.formula_for_covenant(covenant_type)
        if formula is None:
            return None
        ratio = self.compute(spread, formula, period)
        return ratio if ratio.value is not None else None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _side(
        spread: FinancialSpread,
        terms: tuple[FormulaTerm, ...],
        period: str,
        side: str,
    ) -> tuple[list[RatioInput], list[LineItemCode]]:
        inputs: list[RatioInput] = []
        missing: list[LineItemCode] = []
        for term in terms:
            value = spread.value(term.code, period)
            if value is None:
                missing.append(term.code)
                continue
            inputs.append(
                RatioInput(
                    code=term.code,
                    period=period,
                    value=value,
                    coefficient=term.coefficient,
                    side=side,
                )
            )
        return inputs, missing

    @staticmethod
    def _describe(codes: list[LineItemCode]) -> str:
        names = [code.value.replace("_", " ") for code in dict.fromkeys(codes)]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + f" and {names[-1]}"

    @staticmethod
    def _absent(formula: RatioFormula, period: str, reason: str) -> Ratio:
        return Ratio(
            formula_id=formula.id,
            name=formula.name,
            period=period,
            value=None,
            unit=formula.unit,
            higher_is_better=formula.higher_is_better,
            definition=formula.definition,
            reason_missing=reason,
        )


def latest_period(spread: FinancialSpread) -> str:
    """The spread's most recent period label, by ``ends_on`` where supplied.

    Periods without an ``ends_on`` keep the order they were given in, which is the order
    the analyst typed them, so a spread that never states its dates still behaves.
    """
    if not spread.periods:
        return ""
    dated = [p for p in spread.periods if p.ends_on]
    if dated:
        return max(dated, key=lambda p: p.ends_on).label
    return spread.periods[-1].label
