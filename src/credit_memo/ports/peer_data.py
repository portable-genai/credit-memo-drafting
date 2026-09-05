"""PeerDataPort — peer-financials lookup for the peer-comparison artifact.

Every managed profile reads peers from **SEC EDGAR**: the cohort is the registrants
sharing the borrower's SIC code, and each figure is one those peers filed themselves.
That replaced a curated BigQuery table, for a reason worth stating: a peer dataset is a
standing store of figures that go stale silently, and a comparison against last year's
median reads exactly like a comparison against this year's. A filing carries its own
period, so a stale one can be recognised and dropped.

The exchange is that the peer leg reaches the public internet rather than a Google API
inside the service perimeter. No borrower identity goes with it — company resolution
matches a downloaded ticker file in process — and the only borrower attribute that leaves
is the SIC code, a public industry classification.

The service layer computes the peer median and the borrower's percentile arithmetically
from the returned :class:`PeerMetric` rows, so peer numbers are never invented, and a
metric the source cannot answer is skipped rather than estimated.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Borrower, PeerMetric


@runtime_checkable
class PeerDataPort(Protocol):
    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        """Return the peer set's values for ``metric`` (same sector/size cohort)."""
        ...
