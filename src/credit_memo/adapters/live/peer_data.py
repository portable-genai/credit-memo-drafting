"""Live peer data (PeerDataPort): real same-industry peers from SEC EDGAR.

The peer cohort is the registrants sharing the borrower's SIC code (from the
browse-edgar company feed), and each peer's figures are read from its own XBRL company
facts, so every number in the peer comparison is a real filed figure.

Two kinds of metric come back:

**Levels** — revenue, net income, operating income, total assets — are read straight off
the filing and reported in USD millions, the unit the memo's normalised metrics use.

**Ratios** — leverage, interest cover, current ratio, gearing and the rest — are computed
by :class:`~credit_memo.domain.ratio_service.RatioService` from the *same versioned
catalogue formula* the borrower's own ratio was computed from. That is the only way the
comparison means anything: a peer median assembled from a vendor's definition of leverage
and a borrower figure from the bank's own is a comparison of two different quantities that
happen to share a name.

Assembling a peer's spread imposes two rules that keep the arithmetic honest:

* **One period per spread.** Only facts sharing the peer's fiscal year end are used. A
  ratio whose numerator comes from one year and denominator from another is wrong in a way
  that is invisible in the output.
* **A missing operand is missing.** EDGAR carries no scheduled debt service, so DSCR and
  fixed-charge coverage are not computable from it and come back empty rather than
  approximated. The ratio engine already says which line was absent; this adapter does not
  substitute a guess for it.

Best-effort by contract: any EDGAR failure returns [] so a network blip degrades the peer
panel instead of failing the memo.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from ...config import Settings
from ...domain import ratio_catalogue as catalogue
from ...domain.models import (
    Borrower,
    FinancialSpread,
    LineItem,
    LineItemCode,
    PeerMetric,
    Period,
    Provenance,
)
from ...domain.ratio_service import RatioService
from ._edgar import DEBT_TAGS_INCLUDING_CURRENT, EdgarClient, EdgarError

_LOG = logging.getLogger(__name__)

#: A peer figure older than this is a shell/stale registrant, not a comparable.
_MAX_FACT_AGE = timedelta(days=30 * 30)

#: Metric names (as the memo synthesis labels them) EDGAR facts can answer directly.
_LEVEL_METRICS = {
    "revenue": "revenue",
    "net_income": "net_income",
    "operating_income": "operating_income",
    "total_assets": "total_assets",
}

#: Metric names that are computed, and the catalogue formula that computes them. The
#: borrower's ratio came from the same formula id, so the median is a like-for-like one.
#: ``dscr.v1`` and ``fccr.v1`` are deliberately absent: both need scheduled debt service,
#: which no filer tags, and a coverage ratio built on a guessed denominator would look
#: exactly like one built on a filed figure.
_RATIO_METRICS = {
    "leverage": "leverage.v1",
    "interest_cover": "interest_cover.v1",
    "current_ratio": "current_ratio.v1",
    "quick_ratio": "quick_ratio.v1",
    "tangible_net_worth": "tangible_net_worth.v1",
    "gearing": "gearing.v1",
    "ebitda_margin": "ebitda_margin.v1",
}

#: EDGAR fact key -> spread line, where the filing reports the line directly.
_DIRECT_LINES: dict[str, LineItemCode] = {
    "revenue": LineItemCode.REVENUE,
    "operating_income": LineItemCode.EBIT,
    "net_income": LineItemCode.NET_INCOME,
    "total_assets": LineItemCode.TOTAL_ASSETS,
    "cash": LineItemCode.CASH,
    "equity": LineItemCode.TOTAL_EQUITY,
    "current_assets": LineItemCode.CURRENT_ASSETS,
    "current_liabilities": LineItemCode.CURRENT_LIABILITIES,
    "inventory": LineItemCode.INVENTORY,
    "interest_expense": LineItemCode.INTEREST_EXPENSE,
    "tax_expense": LineItemCode.TAX_EXPENSE,
    "capex": LineItemCode.CAPEX,
    "depreciation_amortisation": LineItemCode.DEPRECIATION_AMORTISATION,
}

_MILLIONS = 1e6


def _normalise(metric: str) -> str:
    """ "Interest cover", "interest_cover" and "Interest Cover" are one metric."""
    return metric.strip().lower().replace(" ", "_").replace("-", "_")


class LiveEdgarPeerDataAdapter:
    """Same-SIC peers with real filed values; [] for anything EDGAR cannot answer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._edgar = EdgarClient(settings)
        self._limit = settings.live.peer_limit
        self._ratios = RatioService()

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        wanted = _normalise(metric)
        fact_key = _LEVEL_METRICS.get(wanted)
        formula = catalogue.formula(_RATIO_METRICS[wanted]) if wanted in _RATIO_METRICS else None
        if fact_key is None and formula is None:
            return []
        try:
            entry = self._edgar.resolve(borrower.id or borrower.name)
            if entry is None:
                return []
            sub = self._edgar.submissions(entry["cik"])
            sic = str(sub.get("sic", "")).strip()
            if not sic:
                return []
            peers: list[PeerMetric] = []
            # Over-fetch candidates: the SIC cohort includes stale registrants whose
            # companyfacts 404 or whose latest figures are a decade old, and a skipped
            # candidate must not shrink the peer set. A ratio needs several tags at once,
            # so more candidates are skipped than for a level metric.
            cutoff = datetime.now(UTC) - _MAX_FACT_AGE
            for cik in self._edgar.peer_ciks(sic, entry["cik"], self._limit * 8):
                try:
                    facts = self._edgar.latest_annual_facts(cik)
                except EdgarError:
                    continue  # inactive registrant (no XBRL facts); try the next one
                value = (
                    self._level(facts, fact_key, cutoff)
                    if fact_key is not None
                    else self._ratio(facts, formula, cutoff, cik)
                )
                if value is None:
                    continue
                peers.append(
                    PeerMetric(
                        peer_name=self._edgar.entity_name(cik),
                        metric=metric,
                        value=value,
                    )
                )
                if len(peers) >= self._limit:
                    break
            return peers
        except EdgarError as exc:
            _LOG.warning("peer lookup degraded for %r/%s: %s", borrower.id, metric, exc)
            return []

    # ------------------------------------------------------------------ #
    # One peer's value
    # ------------------------------------------------------------------ #
    def _level(
        self, facts: dict[str, dict[str, Any]], fact_key: str, cutoff: datetime
    ) -> float | None:
        """A figure read straight off the filing, in USD millions.

        The same unit the memo's normalised metrics use (the grounding passages state
        every figure in USD millions), so the deterministic median compares like with
        like.
        """
        fact = facts.get(fact_key)
        if fact is None or not self._is_current(str(fact.get("end", "")), cutoff):
            return None
        return float(fact["value"]) / _MILLIONS

    def _ratio(
        self,
        facts: dict[str, dict[str, Any]],
        formula: Any,
        cutoff: datetime,
        cik: str,
    ) -> float | None:
        """The catalogue formula computed over this peer's own filed figures."""
        spread = self._spread(facts, cutoff, cik)
        if spread is None:
            return None
        return self._ratios.compute(spread, formula, spread.period_labels[0]).value

    # ------------------------------------------------------------------ #
    # A peer's filing as a spread
    # ------------------------------------------------------------------ #
    def _spread(
        self, facts: dict[str, dict[str, Any]], cutoff: datetime, cik: str
    ) -> FinancialSpread | None:
        """This peer's latest annual figures as a one-column spread.

        Provenance is CONFIRMED, which is the accurate reading rather than a convenient
        one: the contract on that value is that a named party stands behind the figure,
        and a 10-K is signed by the registrant's officers under Sarbanes-Oxley section
        302. ``confirmed_by`` names the filing and the period so a reader of the peer
        panel can go and check it.
        """
        ends = [str(f.get("end", "")) for f in facts.values() if f.get("end")]
        if not ends:
            return None
        # The peer's fiscal year end: the date most of its facts share, latest on a tie.
        end = max(Counter(ends).items(), key=lambda kv: (kv[1], kv[0]))[0]
        if not self._is_current(end, cutoff):
            return None
        current = {k: v for k, v in facts.items() if str(v.get("end", "")) == end}

        values: dict[LineItemCode, float] = {}
        for key, code in _DIRECT_LINES.items():
            fact = current.get(key)
            if fact is not None:
                values[code] = float(fact["value"]) / _MILLIONS
        self._derive(current, values)
        if not values:
            return None

        return FinancialSpread(
            borrower_id=f"edgar:{cik}",
            periods=(Period(label=end, ends_on=end, audited=True),),
            items=tuple(
                LineItem(
                    code=code,
                    period=end,
                    value=value,
                    currency="USD",
                    provenance=Provenance.CONFIRMED,
                )
                for code, value in values.items()
            ),
            currency="USD",
            unit="millions",
            confirmed_by=f"SEC EDGAR 10-K XBRL facts, period ended {end}",
            confirmed_at=datetime.now(UTC),
        )

    @staticmethod
    def _derive(current: dict[str, dict[str, Any]], values: dict[LineItemCode, float]) -> None:
        """The three lines a filer reports in parts rather than as a total.

        Each is a sum of figures from the same signed filing, so the result is as
        CONFIRMED as its parts. Where a part is absent the line is left out entirely: a
        partial total is worse than no total, because nothing downstream can tell the
        difference between the two.
        """
        # EBITDA is not a GAAP measure and nobody tags it. Operating income plus D&A is
        # the standard build, and is what a credit analyst would do by hand.
        ebit = values.get(LineItemCode.EBIT)
        dna = values.get(LineItemCode.DEPRECIATION_AMORTISATION)
        if ebit is not None and dna is not None:
            values[LineItemCode.EBITDA] = ebit + dna

        # Total debt is the non-current balance plus the current portion — unless the tag
        # that matched already includes the current portion, in which case adding it
        # counts the same borrowings twice.
        ltd = current.get("long_term_debt")
        if ltd is not None:
            total = float(ltd["value"]) / _MILLIONS
            std = current.get("current_debt")
            if std is not None and str(ltd.get("tag", "")) not in DEBT_TAGS_INCLUDING_CURRENT:
                total += float(std["value"]) / _MILLIONS
            values[LineItemCode.TOTAL_DEBT] = total

        # Goodwill is tagged apart from other intangibles and is usually the larger of the
        # two, so tangible net worth that ignores it overstates by the size of the peer's
        # acquisitions.
        intangibles = [
            float(current[key]["value"]) / _MILLIONS
            for key in ("intangible_assets", "goodwill")
            if key in current
        ]
        if intangibles:
            values[LineItemCode.INTANGIBLE_ASSETS] = sum(intangibles)

    @staticmethod
    def _is_current(end: str, cutoff: datetime) -> bool:
        try:
            ended = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return False
        return ended >= cutoff
