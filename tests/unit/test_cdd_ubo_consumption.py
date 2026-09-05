"""Ask the sibling that already resolves ownership; carry across only what belongs here.

`cdd-sow-research` resolves cross-jurisdiction beneficial ownership, with every percentage
the product of cited registry hops an auditor can recompute. Re-implementing that here would
be a second answer to one question, and the two would disagree the first time a registry
changed. So this repository consumes it.

What crosses the boundary is the shape of the group. What does not cross is everything that
service exists to decide: PEP status, adverse media, opacity, the control narrative. Those
are financial-crime findings with their own review path and their own audience, and a credit
memo restating one would publish another team's conclusion under this service's name.

The tests below hold the mapping and the boundary, plus the two failure modes that would
otherwise be silent: a sibling that refuses the caller, and a structure the sibling itself
says it could not fully resolve.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from credit_memo.adapters.platform.cdd_entity_resolution import CddUboEntityResolutionAdapter
from credit_memo.config import Settings
from credit_memo.domain.models import EntityRole, MatchQuality, Provenance

SRC = Path(__file__).resolve().parents[2] / "src" / "credit_memo"

#: One resolution as the sibling returns it, including the findings that must NOT come over.
_PAYLOAD = {
    "subject_id": "acme-manufacturing-pte-ltd",
    "subject_name": "Acme Manufacturing Pte Ltd",
    "graph": {
        "root_id": "acme-manufacturing-pte-ltd",
        "nodes": [
            {"id": "acme-manufacturing-pte-ltd", "name": "Acme Manufacturing Pte Ltd"},
            {
                "id": "acme-holdings",
                "name": "Acme Holdings Pte Ltd",
                "kind": "entity",
                "jurisdiction": "SG",
            },
            {
                "id": "a-director",
                "name": "A Director",
                "kind": "individual",
                "jurisdiction": "SG",
                "is_pep": True,
            },
        ],
        "edges": [
            {"source_id": "acme-holdings", "target_id": "acme-manufacturing-pte-ltd", "pct": 100.0},
            {"source_id": "a-director", "target_id": "acme-holdings", "pct": 60.0},
        ],
        "truncated": False,
        "unresolved_ids": [],
    },
    "opacity_score": 0.4,
    "control_basis": "ownership",
    "control_rationale": "A Director controls 60% of the parent.",
    "flags": [{"code": "pep", "detail": "A Director is a politically exposed person"}],
}


def _adapter(monkeypatch: pytest.MonkeyPatch, payload: dict, status: int = 200):
    adapter = CddUboEntityResolutionAdapter(Settings(profile="platform"))

    def fake_post(url: str, **kwargs):  # noqa: ANN003 - a stub for one call
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    return adapter


# --------------------------------------------------------------------------- #
# The mapping
# --------------------------------------------------------------------------- #
def test_the_structure_becomes_a_group_the_consolidation_understands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = _adapter(monkeypatch, _PAYLOAD).resolve_group("Acme Manufacturing Pte Ltd", "SG")
    assert group is not None
    by_name = {e.name: e for e in group.members}
    assert set(by_name) == {"Acme Holdings Pte Ltd", "A Director"}
    assert by_name["Acme Holdings Pte Ltd"].role is EntityRole.PARENT
    # A natural person is a personal guarantor candidate, not a subsidiary: the difference
    # decides whether the analyst looks for company accounts or a statement of assets.
    assert by_name["A Director"].role is EntityRole.GUARANTOR_PERSONAL
    assert group.quality is MatchQuality.EXACT


def test_a_percentage_is_the_stake_held_in_that_entity_not_by_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ownership_pct`` means "the stake the parent holds in this entity", so the number
    comes from the edge whose TARGET is this node.

    The distinction is the whole risk on this path. Holdings owns 100% of the borrower and
    A Director owns 60% of Holdings. Reading the outbound edge would print "Acme Holdings,
    100%" — a true number under a label that says something else, which is the most
    convincing kind of wrong figure a memo can carry.
    """
    group = _adapter(monkeypatch, _PAYLOAD).resolve_group("Acme Manufacturing Pte Ltd")
    assert group is not None
    by_name = {e.name: e for e in group.members}
    assert by_name["Acme Holdings Pte Ltd"].ownership_pct == 60.0, "60% OF Holdings is held"
    # Nobody in this structure owns a stake in the director, so there is no figure to state.
    assert by_name["A Director"].ownership_pct is None


def test_everything_that_crosses_is_vendor_provenanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VENDOR is not ENGINE_READABLE, so none of it can supply an operand."""
    group = _adapter(monkeypatch, _PAYLOAD).resolve_group("Acme Manufacturing Pte Ltd")
    assert group is not None
    assert all(e.provenance is Provenance.VENDOR for e in (group.subject, *group.members))


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("finding", ["pep", "opacity", "politically exposed", "controls 60%"])
def test_financial_crime_findings_do_not_cross(
    monkeypatch: pytest.MonkeyPatch, finding: str
) -> None:
    """They have their own review path and their own audience.

    Asserted on the ENTITIES rather than on the whole object, because the coverage note
    deliberately names these categories in order to say they stayed behind — and a test
    that could not tell those two apart would fail on the sentence that proves the point.
    """
    group = _adapter(monkeypatch, _PAYLOAD).resolve_group("Acme Manufacturing Pte Ltd")
    assert group is not None
    rendered = repr((group.subject, *group.members)).lower()
    assert finding not in rendered


def test_the_coverage_note_says_what_stayed_behind() -> None:
    """A reader of the group has to know this is not the financial-crime view of it."""
    from credit_memo.adapters.platform.cdd_entity_resolution import COVERAGE

    assert "adverse media" in COVERAGE and "stay with that service" in COVERAGE


def test_no_deterministic_service_reads_an_ownership_percentage() -> None:
    """`ownership_pct` is the one number this path carries, so nothing computable may read it.

    A cited registry product is not a guess, which is why the field is populated here at
    all. It is still a number that arrived from outside, so the engines must not name it.
    """
    services = (
        "ratio_service.py",
        "covenant_service.py",
        "policy_exception_service.py",
        "risk_rating_service.py",
        "tie_out_service.py",
        "peer_comp_service.py",
        "spread_service.py",
        "global_cash_flow_service.py",
        "scenario_service.py",
    )
    offenders = []
    for filename in services:
        module = ast.parse((SRC / "domain" / filename).read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Attribute) and node.attr == "ownership_pct":
                offenders.append(filename)
    assert not offenders, f"{offenders} read ownership_pct: a vendor number reached an engine"


# --------------------------------------------------------------------------- #
# The two silent failures
# --------------------------------------------------------------------------- #
def test_a_refusal_is_could_not_look_rather_than_no_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 means no case entitlement for this subject, which is a different thing to fix.

    Reporting it as an empty group would tell the analyst the borrower stands alone.
    """
    assert _adapter(monkeypatch, {}, status=403).resolve_group("Acme Manufacturing") is None


def test_an_outage_degrades_rather_than_failing_the_memo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(url: str, **kwargs):  # noqa: ANN003 - a stub for one call
        raise httpx.ConnectError("sibling unreachable")

    monkeypatch.setattr(httpx, "post", boom)
    adapter = CddUboEntityResolutionAdapter(Settings(profile="platform"))
    assert adapter.resolve_group("Acme Manufacturing") is None


def test_a_structure_the_sibling_could_not_finish_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The difference between "this structure is simple" and "we stopped looking"."""
    payload = {
        **_PAYLOAD,
        "graph": {**_PAYLOAD["graph"], "truncated": True, "unresolved_ids": ["offshore-1"]},
    }
    group = _adapter(monkeypatch, payload).resolve_group("Acme Manufacturing Pte Ltd")
    assert group is not None
    assert "truncated" in group.coverage_note
    assert "not the whole of it" in group.coverage_note


def test_an_empty_name_is_not_sent_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = CddUboEntityResolutionAdapter(Settings(profile="platform"))
    assert adapter.resolve_group("   ") is None
