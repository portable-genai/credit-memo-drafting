"""On-prem placeholder for ``WebResearchPort`` — the sovereign target.

A reversibility (P-02, P-12) migration placeholder, and the one port an adopter may
legitimately choose never to implement: an on-premises deployment that does not reach the
public internet has no web research, and returning ``None`` forever is a correct
implementation of this contract.

An adopter that DOES implement it inherits the constraints rather than the code. Results
may be shown only to the person who ran the query; they must never enter the memo, an
export or a review payload; the query must carry public identity only; and the evidence
type carries no numeric field, so nothing retrieved can reach a calculation.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import MarketContext

_MESSAGE = (
    "On-prem WebResearchPort adapter is a migration placeholder. An on-premises deployment "
    "with no internet egress may legitimately leave this unimplemented; one that implements "
    "it must keep the constraints in ports/research.py, which are licensing and residency "
    "rather than style. Core domain logic is unchanged."
)


class OnPremWebResearchAdapter:
    """Placeholder web-research adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def research(
        self,
        query: str,
        purpose: str = "",
        max_results: int = 8,
    ) -> MarketContext | None:
        raise NotImplementedError(_MESSAGE)
