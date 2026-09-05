"""A public register may suggest who is in the group. It may never supply a figure.

This is the one leg of the service that sends the borrower's own registered name outside the
deploy region — weaker than the peer leg, which sends no borrower identity at all — so it is
fenced the way the research panel is, and for the same reasons written down in the same
places.

Four properties, each of which fails silently if it breaks:

* **Off unless a deployment switches it on.** The residency deviation is one a deployment
  takes deliberately rather than inherits.
* **A query carrying bank data is refused, not scrubbed.** A scrubbed query is a different
  question, and an answer to a question nobody asked misleads more quietly than no answer.
* **Nothing it returns can supply a number.** Every entity is VENDOR-provenanced, which is
  not ENGINE_READABLE, and a related entity holds no figure at all. Match quality is an enum
  rather than a score for the same reason: a float on this path is a number.
* **Ambiguity is reported, not resolved.** Two similar names in one jurisdiction is the
  normal case, and attaching the wrong group to a credit file is worse than attaching none.
"""

from __future__ import annotations

import dataclasses

import pytest

from credit_memo.adapters.live.gleif_entity_resolution import (
    GleifEntityResolutionAdapter,
    _normalise,
)
from credit_memo.adapters.local.entity_resolution import LocalFixtureEntityResolutionAdapter
from credit_memo.config import Container, Settings
from credit_memo.domain.global_cash_flow_service import GlobalCashFlowService
from credit_memo.domain.models import (
    EntityGroup,
    EntityRole,
    FinancialSpread,
    LineItem,
    LineItemCode,
    MatchQuality,
    Period,
    Provenance,
    RelatedEntity,
)


def _settings() -> Settings:
    return Settings(profile="local")


# --------------------------------------------------------------------------- #
# 1. Off unless a deployment switches it on
# --------------------------------------------------------------------------- #
def test_the_register_is_not_consulted_by_default(monkeypatch) -> None:
    """The lookup sends the borrower's registered name outside the region."""
    monkeypatch.delenv("CREDIT_MEMO_ENTITY_RESOLUTION_ENABLED", raising=False)
    assert Container(Settings.load("config/settings.yaml")).entity_resolution is None


def test_it_binds_when_switched_on(monkeypatch) -> None:
    monkeypatch.setenv("CREDIT_MEMO_ENTITY_RESOLUTION_ENABLED", "1")
    assert Container(Settings.load("config/settings.yaml")).entity_resolution is not None


# --------------------------------------------------------------------------- #
# 2. The query carries public identity only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "unsafe",
    [
        pytest.param("Acme Pte Ltd account 0123456789", id="account number"),
        pytest.param("Acme Pte Ltd UEN 201812345K", id="SG UEN"),
        pytest.param("Acme SG12ABCD1234567890123", id="IBAN"),
        pytest.param("tan.wei.ming@acme.example", id="a person"),
    ],
)
def test_a_name_carrying_bank_data_is_refused_rather_than_scrubbed(unsafe: str) -> None:
    adapter = GleifEntityResolutionAdapter(_settings())
    assert adapter._safe_name(unsafe) == ""
    assert adapter.resolve_group(unsafe) is None


def test_a_registered_name_passes() -> None:
    adapter = GleifEntityResolutionAdapter(_settings())
    assert adapter._safe_name("Acme Manufacturing Pte Ltd") == "Acme Manufacturing Pte Ltd"


def test_the_per_analysis_lookup_cap_is_enforced() -> None:
    """Unmetered and free, but an unbounded loop against a free public service is rude."""
    adapter = GleifEntityResolutionAdapter(_settings())
    adapter._lookups = adapter.MAX_LOOKUPS_PER_ANALYSIS
    assert adapter.resolve_group("Acme Manufacturing Pte Ltd") is None


# --------------------------------------------------------------------------- #
# 3. Nothing it returns can supply a number
# --------------------------------------------------------------------------- #
def test_a_register_answer_cannot_hold_an_entity_of_another_provenance() -> None:
    with pytest.raises(ValueError, match="vendor-supplied by definition"):
        EntityGroup(
            subject=RelatedEntity(id="a", name="A", provenance=Provenance.USER_ENTERED),
        )


def test_match_quality_is_not_a_number() -> None:
    """A float here is a number, and a number is the thing that must not cross.

    The rule holds by type: this fails if a future edit adds a score to the group.
    """
    numeric = [
        f.name
        for f in dataclasses.fields(EntityGroup)
        if f.type in {"float", "int", "float | None", "int | None"}
    ]
    assert not numeric, f"EntityGroup gained numeric field(s) {numeric}"
    assert isinstance(MatchQuality.EXACT.value, str)


def test_a_suggested_entity_with_no_statements_is_named_rather_than_counted() -> None:
    """The property the whole port exists to serve.

    The register says the group has three entities; the analyst uploaded two. The
    consolidation reports the third by name instead of quietly totalling two and looking
    complete — which is the difference between a group cash flow and a plausible one.
    """
    adapter = LocalFixtureEntityResolutionAdapter(_settings())
    group = adapter.resolve_group("Acme Manufacturing Pte Ltd (FICTIONAL)")
    assert group is not None and group.members

    entities = (group.subject, *group.members)
    spread = FinancialSpread(
        borrower_id=group.subject.id,
        periods=(Period(label="FY2025"),),
        items=(LineItem(code=LineItemCode.EBITDA, period="FY2025", value=100.0),),
        confirmed_by="analyst@bank.example",
    )
    gcf = GlobalCashFlowService().consolidate(entities, {group.subject.id: spread})

    assert not gcf.complete
    assert set(gcf.entities_without_figures) == {e.name for e in group.members}


# --------------------------------------------------------------------------- #
# 4. Ambiguity is reported, not resolved
# --------------------------------------------------------------------------- #
def test_an_ambiguous_name_returns_its_candidates_and_no_group() -> None:
    """Attaching the wrong group to a credit file is worse than attaching none."""
    group = LocalFixtureEntityResolutionAdapter(_settings()).resolve_group("Meridian")
    assert group is not None
    assert group.quality is MatchQuality.AMBIGUOUS
    assert len(group.candidates) > 1
    assert group.found_nothing, "no members are claimed while the subject is unresolved"


def test_a_name_the_register_does_not_hold_is_none_not_an_empty_group() -> None:
    """ "We could not look" and "the register knows of nobody" are different answers."""
    assert LocalFixtureEntityResolutionAdapter(_settings()).resolve_group("Nobody Ltd") is None


def test_the_legal_form_is_normalised_on_the_answer_not_the_question() -> None:
    """ "Acme Pte Ltd" and "ACME PTE. LTD." are one candidate, not an ambiguity."""
    assert _normalise("Acme Pte. Ltd.") == _normalise("ACME PTE LTD")
    assert _normalise("Acme Holdings Pte Ltd") == "acme"


def test_a_clean_match_carries_the_roles_the_group_service_reads() -> None:
    group = LocalFixtureEntityResolutionAdapter(_settings()).resolve_group(
        "Acme Manufacturing Pte Ltd (FICTIONAL)"
    )
    assert group is not None
    assert group.quality is MatchQuality.EXACT
    assert {e.role for e in group.members} == {EntityRole.PARENT, EntityRole.SUBSIDIARY}
    assert all(e.external_ids.lei for e in group.members), (
        "a suggestion without an id is not checkable"
    )
    assert group.coverage_note, "an empty answer is often about the register, and it says so"
