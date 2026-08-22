"""PeerDataPort — peer-financials lookup for the peer-comparison artifact.

Primary GCP adapter: **BigQuery** (a curated peer-financials dataset in
``asia-southeast1``, CMEK-encrypted). This is internal data, so there is no ``platform``
HTTP adapter, only the GCP adapter and the on-prem placeholder stub. The service layer
computes the peer median and the borrower's percentile arithmetically from the returned
:class:`PeerMetric` rows, so peer numbers are never invented.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Borrower, PeerMetric


@runtime_checkable
class PeerDataPort(Protocol):
    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        """Return the peer set's values for ``metric`` (same sector/size cohort)."""
        ...
