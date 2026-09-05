"""GLEIF entity resolution (EntityResolutionPort) — who else is in the group, per the register.

The Global Legal Entity Identifier Foundation publishes the LEI register and its Level 2
relationship data under CC0, with no key and no contract. That makes it the one group source
this project can use without signing for data, which is why it is here and a commercial
company-graph vendor is not.

What it is for: an analyst assembling a group cash flow has to know who else is in the group
before they can go and fetch those entities' statements. Today they know it from memory or
from the relationship manager. This turns that into a list with a source on it — and a list
whose gaps are visible, because an entity the register names and nobody uploaded shows up on
the memo as one the consolidation could not include.

What it is not for: figures. Everything returned is a :class:`RelatedEntity`, which holds no
number, marked ``VENDOR``, which is not ``ENGINE_READABLE``. There is no path from here to a
ratio and no float on the type to make one.

**This leg sends the borrower's registered legal name outside the deploy region**, which is
weaker than the peer leg (that sends no borrower identity at all), so it is off unless a
deployment switches it on and the deviation is recorded rather than inherited. The query
carries public identity only, and anything that looks like an account number, a UEN/NRIC, an
IBAN or an email address is refused rather than scrubbed.

Standard library plus ``httpx``, which is a base dependency: no Google SDK on this path, so
every profile can import this module.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ...config import Settings
from ...domain.models import (
    EntityGroup,
    EntityRole,
    ExternalIds,
    MatchQuality,
    Provenance,
    RelatedEntity,
)
from ...envread import setting_or_default

_LOG = logging.getLogger(__name__)

API = "https://api.gleif.org/api/v1"

#: GLEIF holds relationships only for entities that have an LEI, which most private SME
#: borrowers do not. An empty answer is therefore frequently a statement about the register
#: rather than about the group, and saying so is the difference between "this borrower has no
#: parent" and "this register would not know".
COVERAGE = (
    "GLEIF records relationships only between entities that hold an LEI. A private company "
    "without one is invisible here, so an empty result is not evidence that the group is "
    "empty."
)

#: Legal-form suffixes stripped before comparing names. Not a normalisation of the query —
#: the register is asked for the name as given — but of the ANSWER, so "Acme Pte Ltd" and
#: "ACME PTE. LTD." are recognised as one candidate rather than reported as ambiguity.
_LEGAL_FORMS = re.compile(
    r"\b(pte|pvt|private|limited|ltd|llc|inc|incorporated|corp|corporation|plc|gmbh|ag|sa|"
    r"bv|nv|holdings?|company|co)\b\.?",
    re.I,
)


def _normalise(name: str) -> str:
    return " ".join(_LEGAL_FORMS.sub(" ", name).replace(".", " ").split()).lower()


class GleifEntityResolutionAdapter:
    """Resolve a borrower to its LEI record and report the group around it."""

    #: Ceiling per analysis. Unmetered and free, but an unbounded loop against somebody
    #: else's free service is rude regardless of whether they bill for it.
    MAX_LOOKUPS_PER_ANALYSIS = 20

    #: Patterns that must never reach a register query. A borrower's registered name is
    #: public; its identifiers and its people are the bank's business.
    _FORBIDDEN = (
        re.compile(r"\b\d{6,}\b"),  # account numbers, long identifiers
        re.compile(r"\b[0-9]{8,9}[A-Z]\b", re.I),  # SG UEN / NRIC shapes
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),  # IBAN
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),  # anything addressed to a person
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lookups = 0
        self._timeout = float(setting_or_default("GLEIF_TIMEOUT_SECONDS", "8"))

    # ------------------------------------------------------------------ #
    def resolve_group(
        self,
        name: str,
        jurisdiction: str = "",
        max_members: int = 25,
    ) -> EntityGroup | None:
        """The register's view of this company's group, or None if it could not look."""
        safe = self._safe_name(name)
        if not safe or self._lookups >= self.MAX_LOOKUPS_PER_ANALYSIS:
            return None

        try:
            records = self._search(safe, jurisdiction)
        except httpx.HTTPError as exc:  # a register outage must never fail a memo
            _LOG.warning("GLEIF lookup degraded for %r: %s", safe, exc)
            return None
        if not records:
            return None

        chosen, quality, candidates = self._choose(safe, records)
        subject = self._entity(chosen, EntityRole.BORROWER)
        lei = str(chosen.get("id", ""))
        if quality is MatchQuality.AMBIGUOUS or not lei:
            # Reported, not resolved. Two similar names in one jurisdiction is the normal
            # case, and attaching the wrong group to a credit file is worse than attaching
            # none.
            return EntityGroup(
                subject=subject,
                source="GLEIF",
                quality=MatchQuality.AMBIGUOUS,
                coverage_note=COVERAGE,
                candidates=candidates,
            )

        parents, reported_none = self._parents(lei)
        children = self._children(lei, max_members)
        return EntityGroup(
            subject=subject,
            members=tuple((*parents, *children))[:max_members],
            source="GLEIF",
            quality=quality,
            register_reports_no_parent=reported_none,
            coverage_note=COVERAGE,
        )

    # ------------------------------------------------------------------ #
    # Query hygiene
    # ------------------------------------------------------------------ #
    def _safe_name(self, name: str) -> str:
        """The name with nothing on it that must not leave the region, or "" to refuse."""
        cleaned = " ".join(name.split())[:200]
        if not cleaned:
            return ""
        return "" if any(p.search(cleaned) for p in self._FORBIDDEN) else cleaned

    # ------------------------------------------------------------------ #
    # The register
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        self._lookups += 1
        response = httpx.get(
            f"{API}{path}",
            params=params or {},
            timeout=self._timeout,
            headers={"Accept": "application/vnd.api+json"},
            follow_redirects=True,
        )
        if response.status_code == 404:
            return None  # GLEIF answers 404 for "no such relationship", which is an answer
        response.raise_for_status()
        return response.json()

    def _search(self, name: str, jurisdiction: str) -> list[dict[str, Any]]:
        params = {"filter[entity.legalName]": name, "page[size]": "10"}
        if jurisdiction.strip():
            params["filter[entity.legalAddress.country]"] = jurisdiction.strip().upper()
        payload = self._get("/lei-records", params)
        return list((payload or {}).get("data") or [])

    def _parents(self, lei: str) -> tuple[tuple[RelatedEntity, ...], bool]:
        """The direct and ultimate parents, and whether the register says there are none.

        A 404 from these endpoints means GLEIF holds no parent relationship. That is an
        answer, not a failure, and it is reported as one.
        """
        out: list[RelatedEntity] = []
        seen: set[str] = set()
        reported_none = True
        for path, role in (
            (f"/lei-records/{lei}/direct-parent", EntityRole.PARENT),
            (f"/lei-records/{lei}/ultimate-parent", EntityRole.PARENT),
        ):
            try:
                payload = self._get(path)
            except httpx.HTTPError:
                reported_none = False  # could not look; not the same as "there is none"
                continue
            record = (payload or {}).get("data")
            if not record:
                continue
            reported_none = False
            entity = self._entity(record, role)
            if entity.id not in seen:
                seen.add(entity.id)
                out.append(entity)
        return tuple(out), reported_none and not out

    def _children(self, lei: str, limit: int) -> tuple[RelatedEntity, ...]:
        try:
            payload = self._get(
                f"/lei-records/{lei}/direct-children", {"page[size]": str(min(limit, 50))}
            )
        except httpx.HTTPError:
            return ()
        return tuple(
            self._entity(record, EntityRole.SUBSIDIARY)
            for record in ((payload or {}).get("data") or [])[:limit]
        )

    # ------------------------------------------------------------------ #
    # Reading a record
    # ------------------------------------------------------------------ #
    @staticmethod
    def _entity(record: dict[str, Any], role: EntityRole) -> RelatedEntity:
        """One LEI record as a RelatedEntity.

        ``ownership_pct`` is left None on purpose. GLEIF's relationship records carry
        accounting consolidation status rather than a shareholding, and reading one as the
        other would put a control assertion in the memo that nobody made.
        """
        attributes = record.get("attributes") or {}
        entity = attributes.get("entity") or {}
        legal_name = (entity.get("legalName") or {}).get("name") or ""
        lei = str(record.get("id") or attributes.get("lei") or "")
        country = ((entity.get("legalAddress") or {}).get("country")) or ""
        return RelatedEntity(
            id=f"lei:{lei}" if lei else f"gleif:{_normalise(legal_name) or 'unknown'}",
            name=legal_name or lei,
            role=role,
            jurisdiction=country,
            external_ids=ExternalIds(lei=lei),
            provenance=Provenance.VENDOR,
        )

    @staticmethod
    def _choose(
        wanted: str, records: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], MatchQuality, tuple[str, ...]]:
        """Which record the name meant, or an honest admission that it is not clear."""

        def legal_name(record: dict[str, Any]) -> str:
            attributes = record.get("attributes") or {}
            return ((attributes.get("entity") or {}).get("legalName") or {}).get("name") or ""

        exact = [r for r in records if legal_name(r).strip().lower() == wanted.strip().lower()]
        if len(exact) == 1:
            return exact[0], MatchQuality.EXACT, ()

        target = _normalise(wanted)
        close = [r for r in records if _normalise(legal_name(r)) == target]
        if len(close) == 1:
            return close[0], MatchQuality.STRONG, ()

        pool = close or exact or records
        return pool[0], MatchQuality.AMBIGUOUS, tuple(legal_name(r) for r in pool[:10])
