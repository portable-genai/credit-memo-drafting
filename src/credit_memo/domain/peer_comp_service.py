"""PeerCompService — deterministic borrower-vs-peer comparison (SPEC §5).

A thin domain service over the :class:`PeerDataPort`: for each of the borrower's key
financial metrics it asks the peer-data source for the peer set's values, then computes
the peer median and the borrower's percentile within the set. The comparison is purely
arithmetic (no LLM), so peer numbers are never invented: a metric with no peer data is
simply skipped.

Pure domain code: talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from .models import (
    Borrower,
    FinancialMetric,
    PeerComparison,
    PeerMetric,
)


class PeerCompService:
    """Compare borrower metrics against a peer set. Signature fixed by SPEC §5."""

    def __init__(self, peer_data: Any, tracer: Any) -> None:
        self._peer_data = peer_data
        self._tracer = tracer

    def compare(
        self,
        borrower: Borrower,
        metrics: tuple[FinancialMetric, ...],
        actor: str,
    ) -> tuple[PeerComparison, ...]:
        """Build peer comparisons for ``borrower``'s metrics against the peer set."""
        out: list[PeerComparison] = []
        for metric in metrics:
            peers = self._peers_for(borrower, metric.name)
            if not peers:
                continue
            comparison = self._build_comparison(metric, peers)
            if comparison is not None:
                out.append(comparison)
        return tuple(out)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        try:
            peers = self._peer_data.peers_for(borrower, metric) or []
        except Exception:  # noqa: BLE001 - peer data is best-effort, never fatal
            return []
        return [p for p in peers if isinstance(p, PeerMetric)]

    @staticmethod
    def _build_comparison(
        metric: FinancialMetric,
        peers: list[PeerMetric],
    ) -> PeerComparison | None:
        values = sorted(p.value for p in peers)
        if not values:
            return None
        median = _median(values)
        percentile = _percentile(values, metric.value)
        return PeerComparison(
            metric=metric.name,
            borrower_value=metric.value,
            peer_median=median,
            percentile=percentile,
            peers=tuple(peers),
        )


def _median(values: list[float]) -> float:
    """Median of a non-empty, ascending list of floats."""
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _percentile(values: list[float], target: float) -> float:
    """Fraction of peer values at or below ``target`` (the borrower's percentile)."""
    if not values:
        return 0.0
    at_or_below = sum(1 for v in values if v <= target)
    return round(at_or_below / len(values), 4)
