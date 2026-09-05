"""RiskRatingService — arithmetic over the bank's scorecard, offered to an officer.

This service proposes a grade. It never assigns one, and the distinction is the whole
design rather than a caveat bolted on.

Supervisors expect a risk rating to be the bank's own judgement: arrived at by the bank's
methodology, owned by a named officer, and justified in the memo itself. What can
legitimately be automated is the arithmetic — take the bank's uploaded scorecard, measure
each factor against the confirmed spread and the computed ratios, band it, total it, and
show the officer what that produces along with every driver that got it there.

What is deliberately not automated:

* **The grade of record.** It lives in the bank's rating system, which this service reads
  and never writes. A grade here is a proposal on a memo.
* **The judgement.** An officer who disagrees overrides, and an override must name them
  and give a reason — a scorecard overridden silently is a scorecard that was never
  really used, which is a finding supervisors write up by name.
* **The number.** No model touches it, and the type will not let one:
  :class:`RiskRatingProposal` refuses any provenance but COMPUTED. ``rationale`` is
  accepted but left empty by the pipeline, because the drivers justify the grade better
  than a paragraph about them would: each names the factor, the measured value, the band
  it fell into and what it contributed. Prose belongs where an analyst can own the words.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

from .models import (
    FinancialSpread,
    LineItemCode,
    RatingDriver,
    RatingScorecard,
    Ratio,
    RiskRatingProposal,
)


class RiskRatingService:
    """Score the bank's scorecard against this borrower's confirmed figures."""

    def propose(
        self,
        scorecard: RatingScorecard,
        ratios: tuple[Ratio, ...] = (),
        spread: FinancialSpread | None = None,
        period: str = "",
        rationale: str = "",
    ) -> RiskRatingProposal | None:
        """The grade this scorecard produces, with every driver that got it there.

        Returns None when the scorecard has no factors or none of them could be measured:
        a grade derived from nothing is worse than no grade, because it looks like an
        assessment.
        """
        if not scorecard.factors:
            return None

        drivers: list[RatingDriver] = []
        total = 0.0
        weight_used = 0.0
        for name, metric, weight, bands in scorecard.factors:
            measured = self._measure(metric, ratios, spread, period)
            if measured is None:
                # An unmeasured factor is recorded so the officer can see the gap, and
                # contributes nothing. Scoring it as zero would read as "this borrower
                # scored badly here" when the truth is "we were not given the figure".
                drivers.append(
                    RatingDriver(
                        name=name,
                        measured=None,
                        band="not measured",
                        points=0.0,
                        weight=weight,
                        detail=f"{metric} was not available from the confirmed figures",
                    )
                )
                continue
            points, band = self._band(measured, bands)
            drivers.append(
                RatingDriver(
                    name=name,
                    measured=measured,
                    band=band,
                    points=points,
                    weight=weight,
                    detail=f"{metric} = {measured:,.2f}",
                )
            )
            total += points * weight
            weight_used += weight

        if weight_used == 0.0:
            return None

        # Normalise by the weight actually used, so a scorecard with one unmeasured
        # factor produces the grade its measured factors support rather than a
        # mechanically depressed one.
        score = round(total / weight_used, 4)
        return RiskRatingProposal(
            obligor_grade=self._grade(score, scorecard.grade_bands),
            score=score,
            drivers=tuple(drivers),
            scorecard_version=scorecard.version,
            definitions_url=scorecard.definitions_url,
            rationale=rationale,
        )

    @staticmethod
    def override(
        proposal: RiskRatingProposal, grade: str, reason: str, by: str
    ) -> RiskRatingProposal:
        """Record an officer's disagreement without erasing what the scorecard said.

        Both figures survive. A memo that shows only the final grade cannot answer "did
        the scorecard agree", and that question is the entire point of running one.
        """
        return RiskRatingProposal(
            obligor_grade=proposal.obligor_grade,
            score=proposal.score,
            drivers=proposal.drivers,
            scorecard_version=proposal.scorecard_version,
            definitions_url=proposal.definitions_url,
            rationale=proposal.rationale,
            facility_grade=proposal.facility_grade,
            override_grade=grade,
            override_reason=reason,
            override_by=by,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _measure(
        metric: str,
        ratios: tuple[Ratio, ...],
        spread: FinancialSpread | None,
        period: str,
    ) -> float | None:
        matching = [
            r
            for r in ratios
            if r.formula_id == metric and r.value is not None and (not period or r.period == period)
        ]
        if matching:
            return matching[-1].value
        if spread is None:
            return None
        try:
            code = LineItemCode(metric)
        except ValueError:
            return None
        wanted = period or (spread.period_labels[-1] if spread.periods else "")
        return spread.value(code, wanted)

    @staticmethod
    def _band(measured: float, bands: tuple[tuple[float, float], ...]) -> tuple[float, str]:
        """The points for this value, by the first band whose upper bound it fits.

        Bands are read in the order the bank wrote them, so a pack that lists them out of
        order gets the answer its own ordering implies rather than one this code invented
        by sorting them.
        """
        previous = None
        for upper, points in bands:
            if measured <= upper:
                label = (
                    f"<= {upper:,.2f}" if previous is None else f"{previous:,.2f} to {upper:,.2f}"
                )
                return points, label
            previous = upper
        return (
            (bands[-1][1] if bands else 0.0),
            f"> {previous:,.2f}" if previous is not None else "unbanded",
        )

    @staticmethod
    def _grade(score: float, grade_bands: tuple[tuple[float, str], ...]) -> str:
        for upper, grade in grade_bands:
            if score <= upper:
                return grade
        return grade_bands[-1][1] if grade_bands else "ungraded"
