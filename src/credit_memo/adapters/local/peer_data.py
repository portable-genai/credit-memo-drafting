"""Local peer-data adapter (PeerDataPort) — in-process synthetic peer financials.

The ``local`` profile's stand-in for the **BigQuery** peer-financials dataset: a small,
deterministic in-process table keyed by metric. SDK-free and seedable (callers may pass a
custom table), so the peer-comparison artifact runs offline. The service layer still
computes the peer median and the borrower's percentile arithmetically, so peer numbers
are never invented by a model. There is no Google emulator for BigQuery, so this path is
unconditional and imports no google-cloud package.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Borrower, PeerMetric
from ._seed import SEED_PEERS


class LocalPeerDataAdapter:
    """In-process peer-financials table (the local stand-in for BigQuery)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._by_metric: dict[str, tuple[PeerMetric, ...]] = dict(SEED_PEERS)

    def seed(self, by_metric: dict[str, tuple[PeerMetric, ...]]) -> None:
        """Replace the peer table (deterministic test/CLI seed)."""
        self._by_metric = dict(by_metric)

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        """Return the peer set's values for ``metric`` (same sector/size cohort)."""
        return list(self._by_metric.get(metric, ()))
