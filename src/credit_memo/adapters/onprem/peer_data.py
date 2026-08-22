"""On-prem placeholder for ``PeerDataPort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the BigQuery peer-data adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Porting B2 on-premise is *only* a matter of filling this body
in: the domain orchestration and service callers do not change.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Borrower, PeerMetric

_MESSAGE = (
    "On-prem PeerDataPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremPeerDataAdapter:
    """Placeholder peer-data adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        raise NotImplementedError(_MESSAGE)
