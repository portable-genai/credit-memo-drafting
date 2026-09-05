"""Local spread extraction (SpreadExtractionPort) — deterministic, offline, no model.

The SDK-free profile's extractor. It reads a CSV the analyst supplies rather than a PDF
a model interprets, which is not a limitation of the local profile so much as the
strongest form of the same idea: the analyst's own figures are canonical everywhere, and
here they are the only source.

Accepts a header row of ``code,period,value`` (in any column order), which is the shape
of every spread export an analyst already has. Anything it cannot parse it omits and
does not guess: a candidate is a proposal, and a proposal containing an invented figure
is worse than a short one.

Standard library only.
"""

from __future__ import annotations

import csv
import io

from ...config import Settings
from ...domain.models import (
    CandidateLineItem,
    LineItemCode,
    LlmDocument,
    Period,
    Provenance,
    SpreadCandidate,
)


class LocalCsvSpreadExtractionAdapter:
    """Read spread line items out of a CSV the analyst uploaded."""

    VERSION = "local-csv-v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_spread(
        self,
        borrower_id: str,
        documents: tuple[LlmDocument, ...],
        periods: tuple[Period, ...] = (),
        currency: str = "SGD",
        unit: str = "thousands",
    ) -> SpreadCandidate:
        wanted = {p.label for p in periods}
        items: list[CandidateLineItem] = []
        seen: set[tuple[LineItemCode, str]] = set()

        for document in documents:
            for row in self._rows(document):
                code_raw = (row.get("code") or "").strip()
                period = (row.get("period") or "").strip()
                value_raw = (row.get("value") or "").strip().replace(",", "")
                if not code_raw or not period or not value_raw:
                    continue
                if wanted and period not in wanted:
                    continue
                try:
                    code = LineItemCode(code_raw)
                    value = float(value_raw)
                except ValueError:
                    continue  # a line the catalogue cannot use, or a figure that is not one
                if (code, period) in seen:
                    continue
                seen.add((code, period))
                items.append(
                    CandidateLineItem(
                        code=code,
                        period=period,
                        value=value,
                        currency=currency,
                        document_id=document.document_id,
                        # A CSV has rows, not pages. Saying page 1 would be a guess, and a
                        # guessed page sends a reviewer somewhere the figure is not.
                        page=None,
                        quote=f"{code.value},{period},{value_raw}",
                        confidence=1.0,
                        provenance=Provenance.EXTRACTED,
                    )
                )

        return SpreadCandidate(
            borrower_id=borrower_id,
            periods=periods,
            items=tuple(items),
            currency=currency,
            unit=unit,
            extractor=type(self).__name__,
            extractor_version=self.VERSION,
        )

    @staticmethod
    def _rows(document: LlmDocument) -> list[dict[str, str]]:
        try:
            text = document.content.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - a file that is not text is simply not a spread
            return []
        try:
            reader = csv.DictReader(io.StringIO(text))
            return [
                {(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader
            ]
        except csv.Error:
            return []
