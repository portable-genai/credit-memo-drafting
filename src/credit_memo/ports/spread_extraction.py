"""SpreadExtractionPort — read the figures off the documents, and say where from.

Distinct from :class:`~credit_memo.ports.extraction.DocumentExtractionPort`, which pulls
a document's *text* out for retrieval and citation. This port answers a narrower and
harder question: which line of the spread does each number belong to, for which period,
and on which page did you find it.

Two rules the contract insists on, and both exist because the alternative is a memo full
of numbers nobody checked:

* **It returns a candidate, never a spread.** A
  :class:`~credit_memo.domain.models.SpreadCandidate` cannot be handed to the ratio
  engine: :class:`~credit_memo.domain.models.FinancialSpread` refuses to hold an
  unconfirmed figure. Turning one into the other takes a person and is recorded.
* **Every figure carries a page and a verbatim quote.** The page is what makes a
  citation clickable. The quote is what makes the extraction falsifiable: the tie-out
  service checks the quote really appears on the page named, and a model that invents a
  figure rarely invents a quote that survives it.

An adapter that cannot supply a page returns the item with ``page=None`` rather than
guessing one. A guessed page is worse than no page: it sends a reviewer to the wrong
place and looks like diligence while doing it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmDocument, Period, SpreadCandidate


@runtime_checkable
class SpreadExtractionPort(Protocol):
    def extract_spread(
        self,
        borrower_id: str,
        documents: tuple[LlmDocument, ...],
        periods: tuple[Period, ...] = (),
        currency: str = "SGD",
        unit: str = "thousands",
    ) -> SpreadCandidate:
        """Propose spread line items from ``documents``.

        ``periods`` is what the analyst asked for. An adapter may return fewer (the
        documents did not cover them) but must not silently return a period nobody asked
        about under a label that looks like one that was: a reader comparing FY2025
        against FY2024 must be able to trust that both columns mean what they say.
        """
        ...
