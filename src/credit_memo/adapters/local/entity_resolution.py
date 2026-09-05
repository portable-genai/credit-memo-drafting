"""Local entity resolution (EntityResolutionPort) — a fixture register, offline.

The offline stand-in for GLEIF. Deliberately fictional rather than a cached slice of the
real register: a cache goes stale without saying so, and a group graph that is quietly a
year old attaches last year's subsidiaries to this year's credit file.

It answers the same three shapes the live adapter can produce, because those are what a
console has to handle and a fixture that only ever returns the happy one teaches the
console nothing:

* a clean match with a parent and a subsidiary,
* an ambiguous name, reported as ambiguous with its candidates rather than resolved,
* a company the register has never heard of, which is ``None`` — "we could not look".

Standard library only.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import (
    EntityGroup,
    EntityRole,
    ExternalIds,
    MatchQuality,
    Provenance,
    RelatedEntity,
)

_COVERAGE = (
    "Fixture register (offline profile). A real deployment reads GLEIF, which records "
    "relationships only between entities that hold an LEI."
)


def _entity(entity_id: str, name: str, role: EntityRole, lei: str = "") -> RelatedEntity:
    return RelatedEntity(
        id=entity_id,
        name=name,
        role=role,
        jurisdiction="SG",
        external_ids=ExternalIds(lei=lei),
        provenance=Provenance.VENDOR,
    )


#: One group, one ambiguous name. Both are (FICTIONAL) in the fixture corpus's own style so
#: nobody mistakes a demo for market data.
_GROUPS: dict[str, EntityGroup] = {
    "acme manufacturing pte ltd (fictional)": EntityGroup(
        subject=_entity(
            "lei:5493001KJTIIGC8Y1R12",
            "Acme Manufacturing Pte Ltd (FICTIONAL)",
            EntityRole.BORROWER,
            lei="5493001KJTIIGC8Y1R12",
        ),
        members=(
            _entity(
                "lei:5493001KJTIIGC8Y1R99",
                "Acme Holdings Pte Ltd (FICTIONAL)",
                EntityRole.PARENT,
                lei="5493001KJTIIGC8Y1R99",
            ),
            _entity(
                "lei:5493001KJTIIGC8Y1R55",
                "Acme Logistics Pte Ltd (FICTIONAL)",
                EntityRole.SUBSIDIARY,
                lei="5493001KJTIIGC8Y1R55",
            ),
        ),
        source="fixture-register",
        quality=MatchQuality.EXACT,
        coverage_note=_COVERAGE,
    ),
}

#: A name two fictional companies share, so the ambiguous path is exercised offline.
_AMBIGUOUS: dict[str, tuple[str, ...]] = {
    "meridian": (
        "Meridian Robotics Pte Ltd (FICTIONAL)",
        "Meridian Logistics Pte Ltd (FICTIONAL)",
    ),
}


class LocalFixtureEntityResolutionAdapter:
    """Answer from a small fixture register; None for a name it does not hold."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_group(
        self,
        name: str,
        jurisdiction: str = "",
        max_members: int = 25,
    ) -> EntityGroup | None:
        wanted = " ".join(name.split()).lower()
        if not wanted:
            return None

        group = _GROUPS.get(wanted)
        if group is not None:
            return EntityGroup(
                subject=group.subject,
                members=group.members[:max_members],
                source=group.source,
                quality=group.quality,
                coverage_note=group.coverage_note,
            )

        for stem, candidates in _AMBIGUOUS.items():
            if stem in wanted:
                return EntityGroup(
                    subject=_entity(f"fixture:{stem}", name, EntityRole.BORROWER),
                    source="fixture-register",
                    quality=MatchQuality.AMBIGUOUS,
                    coverage_note=_COVERAGE,
                    candidates=candidates,
                )
        return None
