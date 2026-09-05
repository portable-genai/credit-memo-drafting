"""CDD ownership resolution (EntityResolutionPort) — the sibling that already does this.

`cdd-sow-research` resolves cross-jurisdiction beneficial ownership: every percentage is
the deterministic product of cited registry hops, computed by code an auditor can recompute,
and the result is already governed, tenanted and human-review gated over there. A credit
memo needs the same structure to know whose cash it should be consolidating.

So this repository asks rather than re-implements. Reproducing an ownership resolver here
would be a second answer to one question, and the two would disagree the first time a
registry changed — which is the failure mode the fleet's A2A boundary exists to prevent.
The SPEC already places adverse media and UBO with that sibling; this is the consuming half
of that placement.

**What crosses, and what does not.** Every entity comes back `VENDOR`, so nothing here can
supply an operand to a ratio, a covenant test, a policy rule or a scorecard. `ownership_pct`
IS populated on this path, and that is a deliberate exception to the "never inferred" rule
on that field rather than a hole in it: the sibling's percentage is a cited registry product
and not a guess from a consolidated statement. A guard test holds that no deterministic
service reads the field.

**What is not carried over.** PEP flags, opacity scores, adverse-media findings and the
control narrative all stop here. They are financial-crime findings with their own review
path and their own audience, and a credit memo that quietly restated one would be
publishing another team's conclusion under this service's name.

A sibling that is unreachable, that refuses the caller, or that has no case for this
subject returns None — "we could not look" — because that leads an analyst somewhere
different from "there is no group".
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...domain.models import (
    EntityGroup,
    EntityRole,
    MatchQuality,
    Provenance,
    RelatedEntity,
)
from ...envread import setting_or_default
from . import _s2s

_LOG = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8087"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

COVERAGE = (
    "Resolved by cdd-sow-research from cited company registries. Percentages are the "
    "product of the registry hops it cites; nothing here is inferred from a financial "
    "statement. Financial-crime findings (PEP status, adverse media, opacity) stay with "
    "that service and its own review path."
)

#: How the sibling's node kinds map onto the roles a group cash flow understands. A natural
#: person is a personal guarantor candidate rather than a subsidiary, and the difference
#: decides whether the analyst goes looking for company accounts or a statement of assets.
_ROLE_FOR_KIND = {
    "individual": EntityRole.GUARANTOR_PERSONAL,
    "person": EntityRole.GUARANTOR_PERSONAL,
    "natural_person": EntityRole.GUARANTOR_PERSONAL,
}


class CddUboEntityResolutionAdapter:
    """Ask `cdd-sow-research` who owns this borrower, and map it onto the group."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("CDD_SOW_RESEARCH_URL", _DEFAULT_URL), service="cdd-sow-research"
        )
        self._actor = str(getattr(settings, "service_name", "") or "credit-memo-drafting")

    def resolve_group(
        self,
        name: str,
        jurisdiction: str = "",
        max_members: int = 25,
    ) -> EntityGroup | None:
        cleaned = " ".join(name.split())[:200]
        if not cleaned:
            return None
        subject_id = cleaned.lower().replace(" ", "-")
        try:
            response = httpx.post(
                f"{self._base_url}/v1/ubo-graph",
                json={
                    "subject": {
                        "id": subject_id,
                        "name": cleaned,
                        "type": "entity",
                        "jurisdiction": jurisdiction,
                    }
                },
                headers={**_s2s.headers(self._actor), "Content-Type": "application/json"},
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:  # a sibling outage must never fail a memo
            _LOG.warning("UBO lookup degraded for %r: %s", subject_id, exc)
            return None

        if response.status_code // 100 != 2:
            # 403 in particular is worth not swallowing into "no group": the caller has no
            # case entitlement for this subject, which is a different thing to fix.
            _LOG.warning(
                "UBO lookup for %r returned %s; treating as could-not-look",
                subject_id,
                response.status_code,
            )
            return None

        return self._group(response.json(), cleaned, subject_id, jurisdiction, max_members)

    # ------------------------------------------------------------------ #
    @classmethod
    def _group(
        cls,
        payload: dict[str, Any],
        name: str,
        subject_id: str,
        jurisdiction: str,
        max_members: int,
    ) -> EntityGroup:
        graph = payload.get("graph") or {}
        root_id = str(graph.get("root_id") or payload.get("subject_id") or subject_id)
        subject = RelatedEntity(
            id=f"cdd:{root_id}",
            name=str(payload.get("subject_name") or name),
            role=EntityRole.BORROWER,
            jurisdiction=jurisdiction,
            provenance=Provenance.VENDOR,
        )

        # ``ownership_pct`` means "the stake the PARENT holds in this entity", so the
        # figure comes from the edge whose TARGET is this node. Reading the outbound edge
        # instead would print "Acme Holdings, 100%" when 100% is what Holdings owns of the
        # BORROWER — a true number under a label that says something else, which is the
        # most convincing kind of wrong figure a memo can carry.
        pct_by_target: dict[str, float] = {}
        for edge in graph.get("edges") or []:
            target = str(edge.get("target_id") or "")
            if target and edge.get("pct") is not None:
                pct_by_target.setdefault(target, float(edge["pct"]))

        members: list[RelatedEntity] = []
        for node in graph.get("nodes") or []:
            node_id = str(node.get("id") or "")
            if not node_id or node_id == root_id:
                continue
            kind = str(node.get("kind") or "unknown").lower()
            members.append(
                RelatedEntity(
                    id=f"cdd:{node_id}",
                    name=str(node.get("name") or node_id),
                    role=_ROLE_FOR_KIND.get(kind, EntityRole.PARENT),
                    ownership_pct=pct_by_target.get(node_id),
                    jurisdiction=str(node.get("jurisdiction") or ""),
                    provenance=Provenance.VENDOR,
                )
            )
            if len(members) >= max_members:
                break

        return EntityGroup(
            subject=subject,
            members=tuple(members),
            source="cdd-sow-research",
            quality=MatchQuality.EXACT if members else MatchQuality.AMBIGUOUS,
            # The sibling reports what it could not resolve. Passing that through is the
            # difference between "this structure is simple" and "we stopped looking".
            coverage_note=cls._coverage(graph),
        )

    @staticmethod
    def _coverage(graph: dict[str, Any]) -> str:
        note = COVERAGE
        if graph.get("truncated"):
            note += " The sibling truncated this structure at its depth limit."
        unresolved = list(graph.get("unresolved_ids") or [])
        if unresolved:
            note += (
                f" {len(unresolved)} part(s) of the structure could not be resolved, so "
                "the group below is not the whole of it."
            )
        return note
