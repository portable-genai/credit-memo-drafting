"""On-prem placeholder for ``SpreadExtractionPort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders. In the managed profile this
binds to Gemini reading the uploaded PDFs in region; switching ``profile`` to ``onprem``
rebinds it to the adopter's own extraction stack.

The contract an implementer must keep, because the rest of the system depends on it: the
result is a CANDIDATE, every figure carries the page it was read from and a verbatim
quote, and a figure that cannot be supported is omitted rather than derived.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import LlmDocument, Period, SpreadCandidate

_MESSAGE = (
    "On-prem SpreadExtractionPort adapter is a migration placeholder; implement against your "
    "on-premise extraction stack. It must return a candidate whose every figure carries a "
    "page and a verbatim quote, and must omit rather than derive what it cannot support. "
    "Core domain logic is unchanged."
)


class OnPremSpreadExtractionAdapter:
    """Placeholder spread-extraction adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_spread(
        self,
        borrower_id: str,
        documents: tuple[LlmDocument, ...],
        periods: tuple[Period, ...] = (),
        currency: str = "SGD",
        unit: str = "thousands",
    ) -> SpreadCandidate:
        raise NotImplementedError(_MESSAGE)
