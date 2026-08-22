"""On-prem placeholder for ``PIIRedactionPort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed/platform
profiles this port binds to DLP / the A1 gateway; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. The body deliberately raises rather than returning the text
unredacted: an unimplemented redactor must never leak borrower PII (P-04, rule R1).
Filling this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import RedactionResult

_MESSAGE = (
    "On-prem PIIRedactionPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremRedactionAdapter:
    """Placeholder redaction adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def redact(self, text: str) -> RedactionResult:
        raise NotImplementedError(_MESSAGE)
