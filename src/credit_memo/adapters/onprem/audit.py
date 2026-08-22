"""On-prem placeholder for ``AuditSinkPort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed/platform
profiles this port binds to Cloud Logging WORM / the A5 service; switching ``profile``
to ``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so
the contract tests prove interface parity. The body deliberately raises rather than
silently dropping the record: an unimplemented audit sink must never lose a regulated
record (rule R2). Filling this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AuditEvent

_MESSAGE = (
    "On-prem AuditSinkPort adapter is a migration placeholder; implement against your "
    "on-premise WORM store. Core domain logic is unchanged."
)


class OnPremAuditAdapter:
    """Placeholder audit-sink adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def record(self, event: AuditEvent) -> None:
        raise NotImplementedError(_MESSAGE)
