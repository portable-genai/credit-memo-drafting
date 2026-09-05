"""Local web research (WebResearchPort) — a fixture, and honest about being one.

The SDK-free profile does not reach the internet, so this returns seeded results for a
demo and ``None`` for anything it has no fixture for. ``None`` rather than an empty
result is the point: it means "this deployment cannot search", which is a different
answer from "the search found nothing", and an analyst deciding whether to go and look
themselves needs to know which one they got.

The fixtures are fictional and say so in their titles. A demo that showed plausible real
headlines about a fictional borrower would be teaching its audience to trust a search
that never happened.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import MarketContext, WebEvidence

#: Keyed on a lowercase substring of the query. Deliberately sparse: a fixture set that
#: answers everything would make the local profile look like it can search.
_FIXTURES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "manufacturing": (
        (
            "Singapore manufacturing output, August 2026 (FICTIONAL FIXTURE)",
            "https://example.invalid/fictional/singstat-manufacturing-2026-08",
            "example.invalid",
        ),
        (
            "Sector outlook: precision engineering (FICTIONAL FIXTURE)",
            "https://example.invalid/fictional/sector-outlook-precision",
            "example.invalid",
        ),
    ),
    "logistics": (
        (
            "Freight volumes and warehousing demand, Q3 2026 (FICTIONAL FIXTURE)",
            "https://example.invalid/fictional/freight-q3-2026",
            "example.invalid",
        ),
    ),
}


class LocalFixtureWebResearchAdapter:
    """Seeded public-web context for the offline profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def research(
        self,
        query: str,
        purpose: str = "",
        max_results: int = 8,
    ) -> MarketContext | None:
        lowered = query.lower()
        for key, rows in _FIXTURES.items():
            if key in lowered:
                return MarketContext(
                    query=query,
                    purpose=purpose,
                    evidence=tuple(
                        WebEvidence(title=title, url=url, snippet=snippet)
                        for title, url, snippet in rows[:max_results]
                    ),
                    search_suggestions=("Searches related to this topic (fixture)",),
                    provider="local-fixture",
                )
        # No fixture. Not an empty search: this deployment cannot search at all, and
        # saying so is what stops an analyst reading silence as "nothing out there".
        return None
