"""Local peer-data adapter (PeerDataPort) — in-process synthetic peer financials.

The ``local`` profile's offline stand-in for SEC EDGAR: a small, deterministic in-process
table keyed by metric. SDK-free and seedable (callers may pass a custom table), so the
peer-comparison artifact runs with no network at all. The service layer still computes the
peer median and the borrower's percentile arithmetically, so peer numbers are never
invented by a model.

Deliberately fictional rather than a cached slice of real filings. A cache would go stale
without saying so, which is the failure the managed profile moved away from a curated
dataset to avoid; a table that is obviously synthetic cannot be mistaken for current
market data by anyone reading the local demo.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Borrower, PeerMetric
from ._seed import SEED_PEERS


class LocalPeerDataAdapter:
    """In-process peer-financials table: the offline stand-in for SEC EDGAR."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._by_metric: dict[str, tuple[PeerMetric, ...]] = dict(SEED_PEERS)

    def seed(self, by_metric: dict[str, tuple[PeerMetric, ...]]) -> None:
        """Replace the peer table (deterministic test/CLI seed)."""
        self._by_metric = dict(by_metric)

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        """Return the peer set's values for ``metric`` (same sector/size cohort)."""
        return list(self._by_metric.get(metric, ()))
