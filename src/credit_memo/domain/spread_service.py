"""SpreadService — the stop between what a model read and what the bank computes on.

The whole of this module is one transition: :class:`SpreadCandidate` to
:class:`FinancialSpread`. Nothing else in the codebase can make it, because
``FinancialSpread`` refuses to hold an ``EXTRACTED`` line item and ``confirm`` is the
only thing that promotes one.

That gap is not ceremony. Experts describe the confirm step as the control they will not
give up: the model reads a table well and misreads one occasionally, and the difference
between those two cases is visible to an analyst in seconds and invisible to everyone
downstream forever. So the spread that feeds the ratio engine is the one a named person
accepted, and the record says who and when.

What confirmation is allowed to change, and what it is not:

* An analyst may **reject** an item. It does not enter the spread and no ratio silently
  loses an operand without saying so.
* An analyst may **adjust** an item — a normalising add-back, a reclassification. The
  original value is kept beside the new one forever, with the reason and the actor,
  because "the statements said 18 and we normalised to 24 for the disposal" is a
  sentence a committee is entitled to and cannot be written from the after-value alone.
* An analyst may **add** an item the extraction missed, which lands as USER_ENTERED.
* Nothing may change a figure without leaving a record. There is no in-place edit.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

from .models import (
    Adjustment,
    CandidateLineItem,
    Citation,
    FinancialSpread,
    LineItem,
    LineItemCode,
    Provenance,
    SourceType,
    SpreadCandidate,
    utcnow,
)


class SpreadService:
    """Promote a reviewed candidate to a spread the engines may compute from."""

    def confirm(
        self,
        candidate: SpreadCandidate,
        actor: str,
        rejected: tuple[tuple[LineItemCode, str], ...] = (),
        adjustments: tuple[Adjustment, ...] = (),
        added: tuple[LineItem, ...] = (),
    ) -> FinancialSpread:
        """Accept ``candidate`` as reviewed by ``actor`` and return the spread.

        ``rejected`` names (code, period) pairs the analyst threw out. ``adjustments``
        replace a candidate's value and carry the reason. ``added`` are figures the
        analyst supplied that extraction never proposed.
        """
        if not actor.strip():
            raise ValueError(
                "confirming a spread requires a named actor. An unattributed confirmation "
                "is the same as no confirmation: it says a person looked without saying "
                "which person, which is exactly what the committee will ask."
            )

        refused = set(rejected)
        by_slot = {(a.code, a.period): a for a in adjustments}
        items: list[LineItem] = []

        for item in candidate.items:
            slot = (item.code, item.period)
            if slot in refused:
                continue
            adjustment = by_slot.get(slot)
            if adjustment is not None:
                items.append(self._adjusted(item, adjustment, candidate.currency))
                continue
            items.append(self._confirmed(item, candidate.currency))

        # An adjustment against a slot extraction never proposed is still a figure the
        # analyst is asserting, so it lands rather than being dropped for want of a
        # candidate to attach to.
        proposed = {(i.code, i.period) for i in candidate.items}
        for slot, adjustment in by_slot.items():
            if slot in proposed or slot in refused:
                continue
            items.append(
                LineItem(
                    code=adjustment.code,
                    period=adjustment.period,
                    value=adjustment.after,
                    currency=candidate.currency,
                    provenance=Provenance.USER_ENTERED,
                )
            )

        items.extend(added)
        return FinancialSpread(
            borrower_id=candidate.borrower_id,
            periods=candidate.periods,
            items=tuple(items),
            currency=candidate.currency,
            unit=candidate.unit,
            confirmed_by=actor,
            confirmed_at=utcnow(),
        )

    @staticmethod
    def is_confirmed(spread: FinancialSpread | None) -> bool:
        """Whether this spread was accepted by a person.

        A spread the analyst typed by hand is confirmed by construction: every item is
        USER_ENTERED, which is to say a person put it there. One that came from
        extraction needs ``confirmed_by`` set, which only :meth:`confirm` does.
        """
        if spread is None or not spread.items:
            return False
        if spread.confirmed_by.strip():
            return True
        return all(item.provenance is Provenance.USER_ENTERED for item in spread.items)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _citation(item: CandidateLineItem) -> tuple[Citation, ...]:
        """The page the figure was read from, so the grid cell can open it.

        Dropped when the extraction could not name a document: a citation to nothing is
        worse than none, because it looks like provenance from a distance.
        """
        if not item.document_id:
            return ()
        return (
            Citation(
                source_id=item.document_id,
                source_type=SourceType.FILING,
                title=item.document_id,
                page=item.page,
                snippet=item.quote,
            ),
        )

    @classmethod
    def _confirmed(cls, item: CandidateLineItem, currency: str) -> LineItem:
        return LineItem(
            code=item.code,
            period=item.period,
            value=item.value,
            currency=item.currency or currency,
            provenance=Provenance.CONFIRMED,
            citations=cls._citation(item),
        )

    @classmethod
    def _adjusted(cls, item: CandidateLineItem, adjustment: Adjustment, currency: str) -> LineItem:
        """An adjusted figure is the analyst's, not the document's.

        USER_ENTERED rather than CONFIRMED, and it keeps the citation to where the
        original came from: the reader needs to see both the page and that somebody
        changed what was on it.
        """
        return LineItem(
            code=item.code,
            period=item.period,
            value=adjustment.after,
            currency=item.currency or currency,
            provenance=Provenance.USER_ENTERED,
            citations=cls._citation(item),
        )


def adjustment_for(
    candidate: SpreadCandidate,
    code: LineItemCode,
    period: str,
    after: float,
    reason: str,
    actor: str,
) -> Adjustment:
    """Build an :class:`Adjustment` that remembers what the document actually said.

    A caller can construct one directly, but then it is their job to look up the before
    value, and a caller that gets that wrong produces a record which reads as though the
    statements said something they did not.
    """
    return Adjustment(
        code=code,
        period=period,
        before=candidate.value(code, period),
        after=after,
        reason=reason,
        actor=actor,
    )
