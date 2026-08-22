"""Live peer data (PeerDataPort): real same-industry peers from SEC EDGAR.

The peer cohort is the registrants sharing the borrower's SIC code (from the
browse-edgar company feed), and each peer's value is read from its own XBRL company
facts, so every number in the peer comparison is a real filed figure. Metrics EDGAR
does not carry (ratios such as leverage or DSCR) return an empty list, which the
deterministic PeerCompService treats as "skip this metric" rather than inventing data.

Best-effort by contract: any EDGAR failure returns [] so a network blip degrades the
peer panel instead of failing the memo.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from ...config import Settings
from ...domain.models import Borrower, PeerMetric
from ._edgar import EdgarClient, EdgarError

_LOG = logging.getLogger(__name__)

#: A peer figure older than this is a shell/stale registrant, not a comparable.
_MAX_FACT_AGE = timedelta(days=30 * 30)

#: Metric names (as the memo synthesis labels them) EDGAR facts can answer.
_SUPPORTED = {
    "revenue": "revenue",
    "net_income": "net_income",
    "net income": "net_income",
    "operating_income": "operating_income",
    "operating income": "operating_income",
    "total_assets": "total_assets",
    "total assets": "total_assets",
}


class LiveEdgarPeerDataAdapter:
    """Same-SIC peers with real filed values; [] for anything EDGAR cannot answer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._edgar = EdgarClient(settings)
        self._limit = settings.live.peer_limit

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        fact_key = _SUPPORTED.get(metric.strip().lower())
        if fact_key is None:
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
            # candidate must not shrink the peer set.
            cutoff = datetime.now(UTC) - _MAX_FACT_AGE
            for cik in self._edgar.peer_ciks(sic, entry["cik"], self._limit * 8):
                try:
                    facts = self._edgar.latest_annual_facts(cik)
                except EdgarError:
                    continue  # inactive registrant (no XBRL facts); try the next one
                fact = facts.get(fact_key)
                if fact is None or not self._is_current(str(fact.get("end", "")), cutoff):
                    continue
                peers.append(
                    PeerMetric(
                        peer_name=self._edgar.entity_name(cik),
                        metric=metric,
                        # USD millions: the same unit the memo's normalised metrics use
                        # (the grounding passages state every figure in USD millions),
                        # so the deterministic median/percentile compares like with like.
                        value=float(fact["value"]) / 1e6,
                    )
                )
                if len(peers) >= self._limit:
                    break
            return peers
        except EdgarError as exc:
            _LOG.warning("peer lookup degraded for %r/%s: %s", borrower.id, metric, exc)
            return []

    @staticmethod
    def _is_current(end: str, cutoff: datetime) -> bool:
        try:
            ended = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return False
        return ended >= cutoff
