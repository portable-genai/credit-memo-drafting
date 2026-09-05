"""TieOutService — the reconciliations a credit file is expected to survive.

Every check here is one an analyst does by hand and an examiner asks about. None of them
needs a model, which is the point: they are arithmetic and string comparison over
figures that already exist, so they are cheap, they are replayable, and they cannot
themselves be wrong in an interesting way.

The most valuable is the least obvious. ``quote_on_page`` takes the verbatim text the
extraction claimed to read a figure from and checks it actually appears on the page it
named. A model that invents a figure has to invent a quote to go with it, and an
invented quote does not survive being looked for. It is the cheapest hallucination
detector available at this point in the pipeline, and it costs one substring search.

A finding is not a failure. It is a sentence in the reviewer's gutter saying "these two
numbers should agree and they do not", with both numbers, so the analyst can decide
which one is wrong. Severity says how much that matters, not how certain the check is.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

import re

from .models import (
    CreditRequest,
    FinancialSpread,
    LineItemCode,
    Severity,
    SpreadCandidate,
    TieOutCheck,
    TieOutFinding,
)

#: Balance-sheet and coverage checks tolerate rounding: statements are published in
#: thousands or millions and a half-unit difference is presentation, not error. A
#: fraction of the larger side rather than an absolute, so the tolerance scales with
#: the borrower.
_RELATIVE_TOLERANCE = 0.005  # 0.5%


def _close(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= scale * _RELATIVE_TOLERANCE


def _normalise(text: str) -> str:
    """Collapse whitespace and case so a quote match is about words, not formatting.

    A PDF text layer inserts line breaks mid-sentence and doubles spaces around figures,
    so a quote that is genuinely on the page frequently fails an exact match. Comparing
    on collapsed lowercase text keeps the check about whether the words are there.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


class TieOutService:
    """Reconcile a spread against its documents, its certificate and its own prose."""

    def check(
        self,
        spread: FinancialSpread,
        candidate: SpreadCandidate | None = None,
        pages_by_document: dict[str, tuple[str, ...]] | None = None,
        request: CreditRequest | None = None,
        narrative: str = "",
        reported_covenants: tuple[tuple[str, float, float], ...] = (),
    ) -> tuple[TieOutFinding, ...]:
        """Every reconciliation that did not hold, most severe first.

        ``pages_by_document`` maps a document id to its pages of text, which is what
        makes the quote check possible. ``reported_covenants`` are
        (description, reported, computed) triples from the covenant service.
        """
        findings: list[TieOutFinding] = []
        findings.extend(self._quotes_on_pages(candidate, pages_by_document or {}))
        findings.extend(self._balance_sheet(spread))
        findings.extend(self._period_continuity(spread))
        findings.extend(self._sources_equal_uses(request))
        findings.extend(self._certificate(reported_covenants))
        findings.extend(self._narrative(spread, narrative))
        rank = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
        return tuple(sorted(findings, key=lambda f: rank[f.severity]))

    # ------------------------------------------------------------------ #
    # 1. Did the model read this off the page it says it did?
    # ------------------------------------------------------------------ #
    def _quotes_on_pages(
        self,
        candidate: SpreadCandidate | None,
        pages_by_document: dict[str, tuple[str, ...]],
    ) -> list[TieOutFinding]:
        if candidate is None or not pages_by_document:
            return []
        findings: list[TieOutFinding] = []
        for item in candidate.items:
            pages = pages_by_document.get(item.document_id)
            if not pages or item.page is None or not item.quote:
                continue  # nothing to check against is not the same as a failed check
            if not 1 <= item.page <= len(pages):
                findings.append(
                    TieOutFinding(
                        check=TieOutCheck.QUOTE_ON_PAGE,
                        severity=Severity.HIGH,
                        detail=(
                            f"{item.code.value.replace('_', ' ')} for {item.period} cites "
                            f"page {item.page} of a document with {len(pages)} pages."
                        ),
                        document_id=item.document_id,
                        page=item.page,
                        period=item.period,
                    )
                )
                continue
            if _normalise(item.quote) not in _normalise(pages[item.page - 1]):
                findings.append(
                    TieOutFinding(
                        check=TieOutCheck.QUOTE_ON_PAGE,
                        severity=Severity.HIGH,
                        detail=(
                            f"{item.code.value.replace('_', ' ')} for {item.period} was "
                            f"read as {item.value:,.2f} from a quote that is not on page "
                            f"{item.page}: {item.quote[:120]!r}. Check the figure before "
                            "confirming it."
                        ),
                        actual=item.value,
                        document_id=item.document_id,
                        page=item.page,
                        period=item.period,
                    )
                )
        return findings

    # ------------------------------------------------------------------ #
    # 2. Does the balance sheet balance?
    # ------------------------------------------------------------------ #
    def _balance_sheet(self, spread: FinancialSpread) -> list[TieOutFinding]:
        findings: list[TieOutFinding] = []
        for period in spread.period_labels:
            assets = spread.value(LineItemCode.TOTAL_ASSETS, period)
            debt = spread.value(LineItemCode.TOTAL_DEBT, period)
            equity = spread.value(LineItemCode.TOTAL_EQUITY, period)
            current = spread.value(LineItemCode.CURRENT_LIABILITIES, period)
            if assets is None or equity is None or debt is None:
                continue
            liabilities = debt + (current or 0.0)
            if not _close(assets, liabilities + equity):
                findings.append(
                    TieOutFinding(
                        check=TieOutCheck.BALANCE_SHEET_BALANCES,
                        severity=Severity.HIGH,
                        detail=(
                            f"{period}: total assets {assets:,.0f} against liabilities plus "
                            f"equity {liabilities + equity:,.0f}. One of the three is wrong, "
                            "or a liability line is missing from the spread."
                        ),
                        expected=liabilities + equity,
                        actual=assets,
                        period=period,
                    )
                )
        return findings

    # ------------------------------------------------------------------ #
    # 3. Is a period missing from the middle of the series?
    # ------------------------------------------------------------------ #
    def _period_continuity(self, spread: FinancialSpread) -> list[TieOutFinding]:
        """A gap in a trend is a different story from a decline, and reads the same."""
        findings: list[TieOutFinding] = []
        for code in (LineItemCode.REVENUE, LineItemCode.EBITDA, LineItemCode.TOTAL_DEBT):
            present = [p for p in spread.period_labels if spread.value(code, p) is not None]
            if len(present) < 2:
                continue
            first, last = (
                spread.period_labels.index(present[0]),
                spread.period_labels.index(present[-1]),
            )
            gaps = [
                p for p in spread.period_labels[first : last + 1] if spread.value(code, p) is None
            ]
            if gaps:
                findings.append(
                    TieOutFinding(
                        check=TieOutCheck.PERIOD_CONTINUITY,
                        severity=Severity.MEDIUM,
                        detail=(
                            f"{code.value.replace('_', ' ')} is missing for "
                            f"{', '.join(gaps)} but present either side. A trend drawn "
                            "across the gap will read as a movement that did not happen."
                        ),
                        period=gaps[0],
                    )
                )
        return findings

    # ------------------------------------------------------------------ #
    # 4. Do sources equal uses?
    # ------------------------------------------------------------------ #
    def _sources_equal_uses(self, request: CreditRequest | None) -> list[TieOutFinding]:
        if request is None:
            return []
        table = request.sources_and_uses
        if not table.sources and not table.uses:
            return []
        if _close(table.total_sources, table.total_uses):
            return []
        return [
            TieOutFinding(
                check=TieOutCheck.SOURCES_EQUAL_USES,
                severity=Severity.HIGH,
                detail=(
                    f"Sources {table.total_sources:,.0f} do not equal uses "
                    f"{table.total_uses:,.0f}: a gap of {table.imbalance:,.0f}. Either a "
                    "funding line is missing or the transaction does not close."
                ),
                expected=table.total_uses,
                actual=table.total_sources,
            )
        ]

    # ------------------------------------------------------------------ #
    # 5. Does the covenant certificate agree with the engine?
    # ------------------------------------------------------------------ #
    def _certificate(self, reported: tuple[tuple[str, float, float], ...]) -> list[TieOutFinding]:
        findings: list[TieOutFinding] = []
        for description, reported_value, computed_value in reported:
            if _close(reported_value, computed_value):
                continue
            findings.append(
                TieOutFinding(
                    check=TieOutCheck.CERTIFICATE_AGREES,
                    severity=Severity.HIGH,
                    detail=(
                        f"{description}: the evidence reports {reported_value:,.2f} and the "
                        f"engine computes {computed_value:,.2f} from the confirmed spread. "
                        "The test used the computed figure; reconcile the two before relying "
                        "on the status."
                    ),
                    expected=computed_value,
                    actual=reported_value,
                )
            )
        return findings

    # ------------------------------------------------------------------ #
    # 6. Do the figures in the prose appear in the spread?
    # ------------------------------------------------------------------ #
    def _narrative(self, spread: FinancialSpread, narrative: str) -> list[TieOutFinding]:
        """Catch a drafted figure that matches nothing the bank confirmed.

        Deliberately conservative. Prose is full of numbers that are not spread items —
        percentages, years, facility amounts, page references — so only figures written
        with a thousands separator or a decimal are considered, and only their magnitude
        is compared. The check is looking for "EBITDA of 24.0m" when the spread says
        18.0, not for every integer in a sentence.
        """
        if not narrative.strip() or not spread.items:
            return []
        magnitudes = {round(abs(item.value), 2) for item in spread.items}
        findings: list[TieOutFinding] = []
        seen: set[float] = set()
        for raw in re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d+\b", narrative):
            try:
                value = round(abs(float(raw.replace(",", ""))), 2)
            except ValueError:
                continue
            if value in seen or value in magnitudes or value < 1.0:
                continue
            # A ratio quoted to two places (2.5, 1.4) is almost never a spread line.
            if value < 100 and any(_close(value, m) for m in magnitudes):
                continue
            seen.add(value)
            findings.append(
                TieOutFinding(
                    check=TieOutCheck.NARRATIVE_AGREES,
                    severity=Severity.LOW,
                    detail=(
                        f"The narrative states {raw}, which matches no confirmed figure in "
                        "the spread. Check it is not a number the drafter supplied itself."
                    ),
                    actual=value,
                )
            )
        return findings
