"""GlobalCashFlowService — whose cash actually services this debt.

Most mid-market lending is to a group, not a company. The borrower is an operating
subsidiary, the property sits in a holdco, the director has guaranteed it personally, and
the question a credit officer is really asking is whether the combined cash covers the
combined debt. A memo that answers it for the borrowing entity alone has answered a
narrower question than the one that was asked.

Three things this service does that a plain sum would not:

* **It shows every contribution.** A consolidated EBITDA of 40 tells a reader nothing
  about whether that is one strong entity and two weak ones, which is the difference
  between a group that can support the facility and one where a single subsidiary can.
* **It shows the eliminations.** A group whose revenue halves on consolidation is telling
  the reader something important about how it trades with itself. Netting silently hides
  exactly that.
* **It names the entities it could not include.** A global cash flow is only as complete
  as the statements behind it, and one that quietly omits the guarantor whose accounts
  nobody uploaded reads as though that guarantor contributes nothing — a stronger claim
  than "we did not look".

The group is whatever the analyst uploaded into this analysis. This service holds nothing
between analyses, so there is no standing ownership graph to consult, and the manifest
makes that visible rather than hiding it.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

from .models import (
    Elimination,
    EntityContribution,
    FinancialSpread,
    GlobalCashFlow,
    GlobalCashFlowLine,
    LineItemCode,
    RelatedEntity,
)

#: The lines a global cash flow consolidates. Deliberately not every line in the spread:
#: consolidating a balance-sheet total across entities with different year ends produces a
#: figure that looks authoritative and means very little. These are the flows and the debt
#: that service them, which is the question being asked.
CONSOLIDATED_LINES: tuple[LineItemCode, ...] = (
    LineItemCode.REVENUE,
    LineItemCode.EBITDA,
    LineItemCode.INTEREST_EXPENSE,
    LineItemCode.TAX_EXPENSE,
    LineItemCode.CAPEX,
    LineItemCode.SCHEDULED_DEBT_SERVICE,
    LineItemCode.TOTAL_DEBT,
)


class GlobalCashFlowService:
    """Consolidate the group's confirmed spreads, showing the work."""

    def consolidate(
        self,
        entities: tuple[RelatedEntity, ...],
        spreads_by_entity: dict[str, FinancialSpread],
        eliminations: tuple[Elimination, ...] = (),
        currency: str = "SGD",
    ) -> GlobalCashFlow:
        """Combine the entities that have figures, and name the ones that do not."""
        contributing = {e.id: e for e in entities if e.id in spreads_by_entity}
        missing = tuple(sorted(e.name or e.id for e in entities if e.id not in spreads_by_entity))

        periods = self._periods(spreads_by_entity, contributing)
        lines: list[GlobalCashFlowLine] = []
        for period in periods:
            for code in CONSOLIDATED_LINES:
                contributions = tuple(
                    EntityContribution(
                        entity_id=entity_id,
                        entity_name=contributing[entity_id].name,
                        role=contributing[entity_id].role,
                        value=value,
                    )
                    for entity_id, spread in spreads_by_entity.items()
                    if entity_id in contributing
                    and (value := spread.value(code, period)) is not None
                )
                if not contributions:
                    continue
                applicable = tuple(e for e in eliminations if e.code is code and e.period == period)
                lines.append(
                    GlobalCashFlowLine(
                        code=code,
                        period=period,
                        total=sum(c.value for c in contributions)
                        - sum(e.amount for e in applicable),
                        contributions=contributions,
                        eliminations=applicable,
                    )
                )

        return GlobalCashFlow(
            periods=periods,
            lines=tuple(lines),
            entities=entities,
            entities_without_figures=missing,
            currency=currency,
        )

    def as_spread(self, global_cash_flow: GlobalCashFlow, borrower_id: str) -> FinancialSpread:
        """The consolidated figures as a spread, so the ratio engine can compute on them.

        Every item is CONFIRMED rather than COMPUTED, which looks wrong for a sum and is
        not: the spread's contract is about whether a PERSON stands behind each figure,
        and each of these is the sum of figures a person confirmed. ``Ratio`` remains the
        only COMPUTED thing, and the ratios computed from this spread are properly
        marked as such.
        """
        from .models import LineItem, Period, Provenance, utcnow

        return FinancialSpread(
            borrower_id=borrower_id,
            periods=tuple(Period(label=p) for p in global_cash_flow.periods),
            items=tuple(
                LineItem(
                    code=line.code,
                    period=line.period,
                    value=line.total,
                    currency=global_cash_flow.currency,
                    provenance=Provenance.CONFIRMED,
                )
                for line in global_cash_flow.lines
            ),
            currency=global_cash_flow.currency,
            confirmed_by="global cash flow (consolidated from confirmed entity spreads)",
            confirmed_at=utcnow(),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _periods(
        spreads_by_entity: dict[str, FinancialSpread],
        contributing: dict[str, RelatedEntity],
    ) -> tuple[str, ...]:
        """Periods every contributing entity has, in the borrower's own order.

        The INTERSECTION, not the union. Consolidating a period one entity reports and
        another does not produces a total that silently excludes an entity, which is the
        most misleading shape this calculation can take: it looks complete.
        """
        relevant = [s for entity_id, s in spreads_by_entity.items() if entity_id in contributing]
        if not relevant:
            return ()
        shared = set(relevant[0].period_labels)
        for spread in relevant[1:]:
            shared &= set(spread.period_labels)
        return tuple(p for p in relevant[0].period_labels if p in shared)
