"""PolicyExceptionService — where this request sits against the bank's own policy.

An exception is not a refusal. Banks lend outside their own guidelines constantly and on
purpose; what supervisors ask is that the bank knows when it is doing so, at what level
that was approved, and how many such exceptions are outstanding. So every finding here
carries the measured value, the limit it missed, and the authority named to waive it —
everything a committee needs to decide and everything a reviewer needs to count.

The policy is the bank's. It arrives as an uploaded, versioned pack and is evaluated
here; nothing in this module decides what a prudent leverage cap is. That separation is
what makes an exception credible: it means "your policy says X and this deal is Y", not
"our software disapproves". It is also why the shipped
``config/policy_pack.example.yaml`` is named an example rather than a default.

Deterministic throughout: the measured value comes from the ratio engine or the confirmed
spread, the comparison is arithmetic, and the model is not consulted. A
:class:`PolicyException` refuses any provenance but COMPUTED.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

from .models import (
    CreditRequest,
    FinancialSpread,
    LineItemCode,
    PolicyException,
    PolicyOperator,
    PolicyPack,
    PolicyRule,
    Ratio,
)

#: Request attributes a rule may test by name, alongside line items and ratio ids. These
#: are the terms of the ask rather than the borrower's financials, and a policy that caps
#: tenor or facility size needs them.
_REQUEST_METRICS = frozenset({"facility_amount", "tenor_months", "total_amount"})


def _passes(measured: float, rule: PolicyRule) -> bool:
    limit = rule.limit
    if limit is None:
        return True
    if rule.operator is PolicyOperator.LE:
        return measured <= limit
    if rule.operator is PolicyOperator.LT:
        return measured < limit
    if rule.operator is PolicyOperator.GE:
        return measured >= limit
    if rule.operator is PolicyOperator.GT:
        return measured > limit
    return measured == limit


class PolicyExceptionService:
    """Test a request against the bank's policy pack and report what it missed."""

    def evaluate(
        self,
        pack: PolicyPack,
        request: CreditRequest | None,
        ratios: tuple[Ratio, ...] = (),
        spread: FinancialSpread | None = None,
        period: str = "",
    ) -> tuple[PolicyException, ...]:
        """Every applicable rule this request does not meet, most severe first.

        A rule whose metric cannot be measured is skipped rather than failed. "We could
        not test this" and "this breached policy" are different sentences, and reporting
        the first as the second would make every thin file look like a bad deal.
        """
        if request is None:
            return ()
        exceptions: list[PolicyException] = []
        for rule in pack.applicable(request.kind, request.loan_type):
            measured, measured_period = self._measure(rule, request, ratios, spread, period)
            if measured is None:
                continue
            if _passes(measured, rule):
                continue
            exceptions.append(
                PolicyException(
                    rule_id=rule.id,
                    description=rule.description,
                    measured=measured,
                    limit=rule.limit,
                    operator=rule.operator,
                    severity=rule.severity,
                    waiver_authority=rule.waiver_authority,
                    period=measured_period,
                    citation=rule.citation,
                    detail=(
                        f"{rule.description}: policy requires {rule.operator.value} "
                        f"{rule.limit:,.2f}, this request measures {measured:,.2f}"
                        + (f" for {measured_period}" if measured_period else "")
                        + (
                            f". Waiver authority: {rule.waiver_authority}."
                            if rule.waiver_authority
                            else ". No waiver authority is named in the pack for this rule."
                        )
                    ),
                )
            )
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return tuple(sorted(exceptions, key=lambda e: rank[e.severity.value]))

    def knockouts(
        self,
        pack: PolicyPack,
        request: CreditRequest | None,
        ratios: tuple[Ratio, ...] = (),
        spread: FinancialSpread | None = None,
        period: str = "",
    ) -> tuple[PolicyException, ...]:
        """The subset of exceptions the pack marks as knockouts.

        A knockout stops a pre-screen dead rather than being logged for a committee.
        Banks reserve them for the handful of rules no amount of appetite overrides, so
        they are the right answer to "is this worth working up" and the wrong answer to
        "should we approve this".
        """
        by_id = {rule.id: rule for rule in pack.rules}
        return tuple(
            exception
            for exception in self.evaluate(pack, request, ratios, spread, period)
            if by_id.get(
                exception.rule_id,
                PolicyRule(id="", description="", metric="", operator=PolicyOperator.LE),
            ).knockout
        )

    # ------------------------------------------------------------------ #
    # Measuring
    # ------------------------------------------------------------------ #
    @staticmethod
    def _measure(
        rule: PolicyRule,
        request: CreditRequest,
        ratios: tuple[Ratio, ...],
        spread: FinancialSpread | None,
        period: str,
    ) -> tuple[float | None, str]:
        """The value this rule tests, and the period it came from.

        Three sources in order: a computed ratio (the usual case), a confirmed spread
        line, or an attribute of the request itself. Nothing else — a rule naming a metric
        none of these supply is a rule this pack cannot test here, and saying so is better
        than approximating it.
        """
        if rule.metric in _REQUEST_METRICS:
            if rule.metric == "tenor_months":
                tenors = [f.tenor_months for f in request.facilities if f.tenor_months]
                return (float(max(tenors)) if tenors else None), ""
            return (request.total_amount or None), ""

        matching = [
            r
            for r in ratios
            if r.formula_id == rule.metric
            and r.value is not None
            and (not period or r.period == period)
        ]
        if matching:
            chosen = matching[-1]
            return chosen.value, chosen.period

        if spread is not None:
            try:
                code = LineItemCode(rule.metric)
            except ValueError:
                return None, ""
            wanted = period or (spread.period_labels[-1] if spread.periods else "")
            return spread.value(code, wanted), wanted
        return None, ""
