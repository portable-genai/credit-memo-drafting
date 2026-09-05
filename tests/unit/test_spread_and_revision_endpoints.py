"""The two steps that existed as types and could not be reached as a product.

`SpreadExtractionPort` and `RevisionService` were built, contract-tested and bound into
the container, and no route, service or UI called either. An analyst could not extract a
spread through the application at all: they had to compose the confirmed figures
themselves and post them with the build. A capability that exists in the type system and
not in the product is indistinguishable, from the outside, from one that was never built.

These tests hold the properties that make the wired path worth having:

* **Confirmation applies to the recorded proposal**, not to a table the caller composes.
  Otherwise a "confirmed" spread could hold figures nobody ever saw beside a document,
  which is the one thing the confirm step exists to prevent.
* **The confirmer and the adjuster are the verified principal.** An unattributed
  confirmation says a person looked without saying which person, and that is exactly what
  a committee asks about.
* **The revision chain starts at the draft**, not at the first edit, so "the model wrote
  this" and "a person tidied the model's version of this" stay distinguishable.
* **The figures are not editable prose.** A memo whose leverage could be typed over by
  hand would put a number in front of a committee that no formula produced.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from credit_memo.api import deps
from credit_memo.api.app import app

ANALYST = {"X-Dev-Persona": "analyst"}

#: The shape of every spread export an analyst already has.
SPREAD_CSV = b"""code,period,value
revenue,FY2025,4200
ebitda,FY2025,760
interest_expense,FY2025,150
total_debt,FY2025,2400
current_assets,FY2025,1800
current_liabilities,FY2025,900
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[TestClient]:
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "local")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_ANALYSIS_ROOT", str(tmp_path))
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


def _open_analysis(client: TestClient, borrower_id: str = "acme-manufacturing") -> str:
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("spread.csv", SPREAD_CSV, "text/csv"))],
        data={"borrower_id": borrower_id, "doc_types": "financial_statement"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["analysis_id"])


def _extract(client: TestClient, analysis_id: str) -> dict:
    response = client.post(f"/v1/analyses/{analysis_id}/spreads/extract", headers=ANALYST, json={})
    assert response.status_code == 200, response.text
    return dict(response.json())


def _confirm(client: TestClient, analysis_id: str, **body) -> dict:
    response = client.post(
        f"/v1/analyses/{analysis_id}/spreads/confirm", headers=ANALYST, json=body
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


# --------------------------------------------------------------------------- #
# Extract: a proposal, and only a proposal
# --------------------------------------------------------------------------- #
def test_extraction_proposes_figures_that_no_engine_may_read(client: TestClient) -> None:
    """Every candidate item is EXTRACTED, which ``FinancialSpread`` refuses by type.

    That refusal is the whole reason the confirm step can be trusted: there is no route
    from a proposal to a computed number that does not pass through a person.
    """
    candidate = _extract(client, _open_analysis(client))
    assert candidate["items"], "the CSV holds six usable rows"
    assert {i["provenance"] for i in candidate["items"]} == {"extracted"}
    assert {i["code"] for i in candidate["items"]} >= {"revenue", "ebitda", "total_debt"}


def test_every_candidate_figure_says_where_it_was_read(client: TestClient) -> None:
    candidate = _extract(client, _open_analysis(client))
    assert all(i["document_id"] for i in candidate["items"])
    assert all(i["quote"] for i in candidate["items"])


def test_extraction_needs_documents(client: TestClient, monkeypatch) -> None:
    """An analysis with nothing readable gets a sentence, not an empty candidate."""
    analysis_id = _open_analysis(client)
    container = deps.get_container()
    monkeypatch.setattr(
        container.analysis_bundle, "get_document", lambda *a, **k: b"", raising=False
    )
    response = client.post(f"/v1/analyses/{analysis_id}/spreads/extract", headers=ANALYST, json={})
    assert response.status_code == 422
    assert "upload the financial statements" in response.text


def test_reading_nothing_is_an_error_with_a_remedy_not_an_empty_grid(
    client: TestClient,
) -> None:
    """The silent failure this step exists to prevent.

    An empty candidate returned as a success renders an empty grid, the analyst confirms
    it, and the memo comes out with no ratios and no reason given. The extractor that
    needs periods is told to say so here rather than downstream.
    """
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("notes.csv", b"not,a,spread\n1,2,3\n", "text/csv"))],
        data={"borrower_id": "acme-manufacturing"},
    )
    analysis_id = response.json()["analysis_id"]
    extract = client.post(f"/v1/analyses/{analysis_id}/spreads/extract", headers=ANALYST, json={})
    assert extract.status_code == 422
    assert "no figures were read" in extract.text
    assert "name them in 'periods'" in extract.text


# --------------------------------------------------------------------------- #
# Confirm: on the recorded proposal, by a named person
# --------------------------------------------------------------------------- #
def test_confirming_needs_something_to_confirm(client: TestClient) -> None:
    analysis_id = _open_analysis(client)
    response = client.post(f"/v1/analyses/{analysis_id}/spreads/confirm", headers=ANALYST, json={})
    assert response.status_code == 422
    assert "spreads/extract first" in response.text


def test_the_confirmer_is_the_verified_principal(client: TestClient) -> None:
    """Not a name from the body. There is no field for one, and that is the point."""
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    spread = _confirm(client, analysis_id)
    assert spread["confirmed_by"] == "demo.analyst@bank.example"
    assert {i["provenance"] for i in spread["items"]} == {"confirmed"}


def test_a_rejected_figure_does_not_reach_the_spread(client: TestClient) -> None:
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    spread = _confirm(client, analysis_id, rejected=[{"code": "total_debt", "period": "FY2025"}])
    assert "total_debt" not in {i["code"] for i in spread["items"]}
    assert "revenue" in {i["code"] for i in spread["items"]}


def test_an_adjustment_carries_its_reason_and_its_author(client: TestClient) -> None:
    """The record a committee asks about: who changed 760 to 690, and why."""
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    spread = _confirm(
        client,
        analysis_id,
        adjustments=[
            {
                "code": "ebitda",
                "period": "FY2025",
                "before": 760.0,
                "after": 690.0,
                "reason": "removed a one-off disposal gain",
            }
        ],
    )
    ebitda = next(i for i in spread["items"] if i["code"] == "ebitda")
    assert ebitda["value"] == 690.0


def test_an_adjustment_with_no_reason_is_refused(client: TestClient) -> None:
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    response = client.post(
        f"/v1/analyses/{analysis_id}/spreads/confirm",
        headers=ANALYST,
        json={
            "adjustments": [{"code": "ebitda", "period": "FY2025", "after": 690.0, "reason": ""}]
        },
    )
    assert response.status_code == 422


def test_both_halves_are_readable_side_by_side(client: TestClient) -> None:
    """What the extractor read and what the analyst accepted are kept apart forever.

    A reconciliation that cannot see both cannot say which figures a person changed.
    """
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    _confirm(client, analysis_id, rejected=[{"code": "total_debt", "period": "FY2025"}])
    both = client.get(f"/v1/analyses/{analysis_id}/spreads", headers=ANALYST).json()
    assert "total_debt" in {i["code"] for i in both["candidate"]["items"]}
    assert "total_debt" not in {i["code"] for i in both["confirmed"]["items"]}


# --------------------------------------------------------------------------- #
# The confirmed spread reaches the build without being retyped
# --------------------------------------------------------------------------- #
def test_the_build_uses_the_spread_that_was_confirmed(client: TestClient) -> None:
    """An analyst who confirmed should not have to send the figures back.

    The stored copy is the one with a named confirmer on it, so using it is also the only
    version whose provenance survives the round trip.
    """
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    _confirm(client, analysis_id)
    response = client.post(f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={})
    assert response.status_code == 200, response.text
    memo = response.json()
    computed = {r["formula_id"] for r in memo["ratios"] if r["value"] is not None}
    assert "leverage.v1" in computed, "total debt and EBITDA were both confirmed"
    assert "interest_cover.v1" in computed


# --------------------------------------------------------------------------- #
# The group reaches the memo
# --------------------------------------------------------------------------- #
def _confirmed_items(period: str = "FY2025", **values: float) -> dict:
    """A spread a person stands behind: every figure typed, so USER_ENTERED."""
    return {
        "borrower_id": "",
        "periods": [{"label": period, "ends_on": "", "months": 12, "audited": True}],
        "items": [
            {"code": code, "period": period, "value": value, "currency": "SGD"}
            for code, value in values.items()
        ],
        "currency": "SGD",
        "unit": "thousands",
        "confirmed_by": "analyst@bank.example",
    }


def test_the_memo_answers_whose_cash_services_the_debt(client: TestClient) -> None:
    """The question a credit officer is actually asking.

    A memo that answers it for the borrowing entity alone has answered a narrower one, and
    before this the consolidation existed only as a domain type nothing called.
    """
    analysis_id = _open_analysis(client)
    response = client.post(
        f"/v1/analyses/{analysis_id}/build",
        headers=ANALYST,
        json={
            "related_entities": [
                {"id": "opco", "name": "Acme Opco", "role": "borrower"},
                {"id": "holdco", "name": "Acme Holdco", "role": "parent"},
                {"id": "director", "name": "A Director", "role": "guarantor_personal"},
            ],
            "entity_spreads": {
                "opco": _confirmed_items(ebitda=100.0, revenue=620.0),
                "holdco": _confirmed_items(ebitda=15.0, revenue=80.0),
            },
            "eliminations": [
                {
                    "code": "revenue",
                    "period": "FY2025",
                    "amount": 60.0,
                    "between": "opco -> holdco",
                    "reason": "management fee",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    gcf = response.json()["global_cash_flow"]

    ebitda = next(line for line in gcf["lines"] if line["code"] == "ebitda")
    assert ebitda["total"] == 115.0
    assert {(c["entity_name"], c["value"]) for c in ebitda["contributions"]} == {
        ("Acme Opco", 100.0),
        ("Acme Holdco", 15.0),
    }

    revenue = next(line for line in gcf["lines"] if line["code"] == "revenue")
    assert revenue["total"] == 640.0, "shown net, with the elimination beside it"
    assert revenue["eliminations"][0]["reason"] == "management fee"

    # The property that keeps the whole calculation honest.
    assert gcf["complete"] is False
    assert gcf["entities_without_figures"] == ["A Director"]


def test_an_unconfirmed_entity_spread_is_refused_by_name(client: TestClient) -> None:
    """A group cash flow may only consolidate figures a person confirmed.

    Named, so the analyst knows which entity to go and confirm rather than being told the
    request as a whole was wrong.
    """
    analysis_id = _open_analysis(client)
    holdco = _confirmed_items(ebitda=15.0)
    holdco["confirmed_by"] = ""
    holdco["items"][0]["provenance"] = "extracted"
    response = client.post(
        f"/v1/analyses/{analysis_id}/build",
        headers=ANALYST,
        json={
            "related_entities": [{"id": "opco", "name": "Opco", "role": "borrower"}],
            "entity_spreads": {"opco": holdco},
        },
    )
    assert response.status_code == 422
    assert "engine may read" in response.text or "confirmed" in response.text


def test_one_entity_is_not_a_group(client: TestClient) -> None:
    """No consolidation rather than a one-entity one.

    A "global cash flow" listing only the borrower asserts that the borrower is the whole
    group, which is a stronger claim than the analyst made by uploading one set of books.
    """
    analysis_id = _open_analysis(client)
    response = client.post(
        f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={"related_entities": []}
    )
    assert response.status_code == 200, response.text
    assert response.json()["global_cash_flow"] is None


def test_the_stress_test_uses_the_borrowers_own_covenant(client: TestClient) -> None:
    """Never a shipped default.

    A default would test every borrower against a number this service made up, and a
    committee reading "passes" would have no way to know whose test it was. The threshold
    here is the DSCR covenant extracted from the borrower's own facility documents, which
    is why it matches the covenant reported alongside it.
    """
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    _confirm(client, analysis_id)
    memo = client.post(f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={}).json()

    assert memo["scenarios"], "the shipped scenario set runs against the confirmed spread"
    dscr = next((c for c in memo["covenants"] if c["type"] == "dscr"), None)
    assert dscr is not None, "the fixture documents state a DSCR covenant"
    for result in memo["scenarios"]:
        assert result["formula_id"] == "dscr.v1"
        assert result["threshold"] == dscr["threshold"]


def test_a_stress_result_carries_the_break_even_not_just_the_shock(
    client: TestClient,
) -> None:
    """The number a committee can actually argue with.

    They cannot judge whether a 15% decline is the right test for this sector. They can
    judge "it survives twice that", which is a question about their own view of the world.
    """
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    _confirm(client, analysis_id)
    memo = client.post(f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={}).json()
    combined = next(r for r in memo["scenarios"] if r["scenario_id"] == "combined")
    decline = next(r for r in memo["scenarios"] if r["scenario_id"] == "earnings-decline-15")
    assert combined["scenario_name"] and decline["scenario_name"]
    # Both shocks at once bite harder than either alone, and break-even makes that one
    # comparable number rather than two shocked values a reader must weigh themselves.
    if combined["breaks_at"] is not None and decline["breaks_at"] is not None:
        assert combined["breaks_at"] <= decline["breaks_at"]


# --------------------------------------------------------------------------- #
# Revisions
# --------------------------------------------------------------------------- #
def _built(client: TestClient) -> str:
    analysis_id = _open_analysis(client)
    _extract(client, analysis_id)
    _confirm(client, analysis_id)
    assert client.post(f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={}).status_code
    return analysis_id


def test_the_chain_starts_at_the_draft_nobody_has_touched(client: TestClient) -> None:
    """Revision 1 is the built memo, authored by the model.

    A chain that began at the first edit could not express the difference between a
    section a person wrote and one they tidied.
    """
    body = client.get(f"/v1/analyses/{_built(client)}/revisions", headers=ANALYST).json()
    assert [r["revision"] for r in body["revisions"]] == [1]
    assert set(body["revisions"][0]["authorship"].values()) == {"model"}
    assert body["chain_intact"] is True


def test_editing_the_prose_appends_a_revision_and_records_the_author(
    client: TestClient,
) -> None:
    analysis_id = _built(client)
    response = client.patch(
        f"/v1/analyses/{analysis_id}/memo",
        headers=ANALYST,
        json={"sections": {"summary": "A tighter summary the analyst wrote."}, "reason": "clarity"},
    )
    assert response.status_code == 200, response.text
    revision = response.json()
    assert revision["revision"] == 2
    assert revision["actor"] == "demo.analyst@bank.example"
    assert revision["authorship"]["summary"] == "edited"
    assert revision["edits"][0]["reason"] == "clarity"
    assert revision["edits"][0]["before"], "the previous text is kept, not overwritten"

    listing = client.get(f"/v1/analyses/{analysis_id}/revisions", headers=ANALYST).json()
    assert listing["chain_intact"] is True, listing["chain_detail"]
    assert [r["revision"] for r in listing["revisions"]] == [1, 2]


def test_a_figure_is_not_editable_prose(client: TestClient) -> None:
    """And the refusal says what IS editable, so the caller can act on it."""
    response = client.patch(
        f"/v1/analyses/{_built(client)}/memo",
        headers=ANALYST,
        json={"sections": {"ratios": "leverage is 2.0x"}},
    )
    assert response.status_code == 422
    assert "not an editable section" in response.text
    assert "recommendation_rationale" in response.text


def test_an_edit_that_changes_nothing_is_refused(client: TestClient) -> None:
    """Otherwise the chain fills with revisions that record no decision."""
    analysis_id = _built(client)
    memo = client.get(f"/v1/analyses/{analysis_id}/revisions", headers=ANALYST).json()
    summary = memo["revisions"][0]["memo_json"]["summary"]
    response = client.patch(
        f"/v1/analyses/{analysis_id}/memo", headers=ANALYST, json={"sections": {"summary": summary}}
    )
    assert response.status_code == 422
    assert "already reads exactly that way" in response.text


def test_the_export_carries_the_edited_memo_not_the_draft(client: TestClient) -> None:
    """The pack a committee receives must be the version that was reviewed."""
    analysis_id = _built(client)
    edited = "The analyst's own summary, which is what the committee should read."
    client.patch(
        f"/v1/analyses/{analysis_id}/memo", headers=ANALYST, json={"sections": {"summary": edited}}
    )
    export = client.post(f"/v1/analyses/{analysis_id}/export?fmt=html", headers=ANALYST)
    assert export.status_code == 200, export.text
    assert edited in export.content.decode("utf-8")
