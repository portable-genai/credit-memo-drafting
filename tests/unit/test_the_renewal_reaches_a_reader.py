"""The renewal, from an uploaded prior memo to a reader who can see what moved.

`RenewalDiffService` was written, unit-tested and reachable by nobody: no route computed a
`renewal_delta`, nothing read an uploaded `prior_memo`, and `AnalysisManifest.missing()` -
which is what tells an analyst a renewal needs the memo being renewed - was not on the wire.
From outside that is indistinguishable from a capability nobody built, and the sixth instance
of the pattern in this repository.

`tests/unit/test_revisions_and_renewal.py` owns the comparison arithmetic. What these tests
own is everything between that service and a person:

1. **A renewal computes a delta from a file somebody uploaded.** There is no memo of record
   here, so the baseline is an upload, and the delta NAMES it: a reader can see which prior
   memo this is a delta from, which is part of the claim rather than a nicety.
2. **"Nothing to compare against" is said, never implied.** An empty delta would read as
   "nothing moved", which is a claim about the borrower. The two causes - no prior memo, and
   an upload that is not a memo this service produced - each reach the reader as a sentence.
3. **Only the kinds written AGAINST a prior memo compare.** A new facility with last cycle's
   memo in its credit file has evidence, not a baseline, and "what changed" about a facility
   that did not exist last year answers a question nobody asked.
4. **The prior memo is never read for this period's figures.** Extracting from it would
   propose last cycle's numbers as this period's, with a quote and a page to make them look
   read off the borrower's own statements.
5. **The checklist reaches the analyst at intake**, with the kind they actually picked, which
   is the only moment the answer is any use.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.domain.memo_document import build_document
from credit_memo.domain.models import (
    Borrower,
    CreditMemo,
    CreditRequest,
    MemoKind,
    RenewalDelta,
    SectionDelta,
)
from credit_memo.domain.renewal_diff_service import read_prior_memo

ANALYST = {"X-Dev-Persona": "analyst"}

SPREAD_CSV = b"""code,period,value
revenue,FY2025,4200
ebitda,FY2025,760
interest_expense,FY2025,150
total_debt,FY2025,2400
current_assets,FY2025,1800
current_liabilities,FY2025,900
"""

#: Last cycle's figures, in the same shape. Lower debt and higher earnings than the spread
#: above, so the comparison has something real to report in both directions.
PRIOR_MEMO = {
    "generated_at": "2025-01-31T00:00:00+00:00",
    "policy_version": "policy-pack-2024.1",
    "summary": "Last cycle's summary.",
    "recommendation_rationale": "Support, on the strength of coverage.",
    "ratios": [{"formula_id": "leverage.v1", "period": "FY2025", "value": 1.9}],
    "covenants": [{"type": "leverage", "current_value": 1.9}],
    "spreads": [
        {"items": [{"code": "total_debt", "period": "FY2025", "value": 1800.0}]},
    ],
    "policy_exceptions": [{"rule_id": "DSCR-01"}],
    "rating": {"obligor_grade": "2 - Good"},
}

RENEWAL = {"kind": "renewal", "loan_type": "ci_term"}
NEW_FACILITY = {"kind": "new_facility", "loan_type": "ci_term"}


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


def _open(client: TestClient, *extra: tuple[str, bytes, str, str]) -> str:
    """An analysis holding the spread CSV, plus ``extra`` as (filename, bytes, mime, kind)."""
    files = [("files", ("spread.csv", SPREAD_CSV, "text/csv"))]
    kinds = ["financial_statement"]
    for filename, content, mime_type, doc_type in extra:
        files.append(("files", (filename, content, mime_type)))
        kinds.append(doc_type)
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=files,
        data={"borrower_id": "acme-manufacturing", "doc_types": ",".join(kinds)},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["analysis_id"])


def _with_prior(client: TestClient, prior: dict | bytes = PRIOR_MEMO, name: str = "prior.json"):
    content = prior if isinstance(prior, bytes) else json.dumps(prior).encode("utf-8")
    return _open(client, (name, content, "application/json", "prior_memo"))


def _build(client: TestClient, analysis_id: str, request: dict) -> dict:
    client.post(f"/v1/analyses/{analysis_id}/spreads/extract", headers=ANALYST, json={})
    client.post(f"/v1/analyses/{analysis_id}/spreads/confirm", headers=ANALYST, json={})
    response = client.post(
        f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={"request": request}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


# --------------------------------------------------------------------------- #
# 1. A renewal computes a delta, against a file it names
# --------------------------------------------------------------------------- #
def test_a_renewal_reports_what_moved_since_the_memo_that_was_uploaded(
    client: TestClient,
) -> None:
    memo = _build(client, _with_prior(client), RENEWAL)
    delta = memo["renewal_delta"]
    assert delta is not None, "the route computed no delta, which is the defect this closes"
    assert not delta["no_comparison_reason"]
    moved = {line["label"] for line in (*delta["ratios"], *delta["covenants"], *delta["spread"])}
    assert any("everage" in label for label in moved), (
        f"leverage went from 1.9x to something well above it and was not reported: {moved}"
    )


def test_the_delta_names_the_upload_it_was_measured_against(client: TestClient) -> None:
    """There is no memo of record here, so WHICH prior memo is part of the claim."""
    memo = _build(client, _with_prior(client, name="acme-renewal-2025.json"), RENEWAL)
    delta = memo["renewal_delta"]
    assert delta["prior_filename"] == "acme-renewal-2025.json"
    assert delta["prior_at"].startswith("2025-01-31")
    assert delta["prior_version"] == "policy-pack-2024.1"


def test_a_movement_carries_the_direction_the_engine_computed(client: TestClient) -> None:
    """The browser must not have to reimplement what counts as up, down, new or gone."""
    memo = _build(client, _with_prior(client), RENEWAL)
    lines = [*memo["renewal_delta"]["ratios"], *memo["renewal_delta"]["spread"]]
    assert lines, "nothing moved, so the direction this test is about was never exercised"
    assert all(line["direction"] in {"up", "down", "unchanged", "new", "gone"} for line in lines)
    assert all(line["change"] is not None or line["before"] is None for line in lines)


def test_an_exception_that_cleared_is_reported_as_well_as_one_that_is_new(
    client: TestClient,
) -> None:
    """A cleared exception is the argument FOR the renewal, and is invisible unless said."""
    delta = _build(client, _with_prior(client), RENEWAL)["renewal_delta"]
    assert "DSCR-01" in delta["cleared_exceptions"]


# --------------------------------------------------------------------------- #
# 2. Nothing to compare against is said, not implied
# --------------------------------------------------------------------------- #
def test_a_renewal_with_no_prior_memo_says_so_instead_of_reporting_no_movement(
    client: TestClient,
) -> None:
    """An empty delta would claim nothing moved. That is a claim about the BORROWER.

    The claim this one needs to make is about the inputs, and the two are not
    interchangeable: a committee reading "nothing moved" has been told something false.
    """
    delta = _build(client, _open(client), RENEWAL)["renewal_delta"]
    assert delta is not None, "a renewal with nothing to compare dropped the section entirely"
    assert "no prior memo was uploaded" in delta["no_comparison_reason"]
    assert not delta["ratios"] and not delta["covenants"] and not delta["spread"]
    # And it says what to do about it, which is the difference between a notice and a remedy.
    assert "export it as JSON" in delta["no_comparison_reason"]


def test_a_prior_memo_that_is_not_a_memo_is_refused_by_name(client: TestClient) -> None:
    """A PDF of last year's memo is a perfectly good document and a useless baseline."""
    scan = b"%PDF-1.7 a scan of last year's memo, unreadable figure by figure"
    delta = _build(client, _with_prior(client, scan, name="last-year.pdf"), RENEWAL)[
        "renewal_delta"
    ]
    assert delta["prior_filename"] == "last-year.pdf"
    assert "last-year.pdf" in delta["no_comparison_reason"]
    assert "Export the memo being renewed as JSON" in delta["no_comparison_reason"]


def test_json_that_is_not_a_memo_is_refused_rather_than_parsed_hopefully() -> None:
    """Every figure in this memo would otherwise be reported as new."""
    assert read_prior_memo(json.dumps({"note": "not a memo"}).encode()) is None
    assert read_prior_memo(b"not json at all") is None
    assert read_prior_memo(b"") is None
    assert read_prior_memo(json.dumps(["a list"]).encode()) is None
    assert read_prior_memo(json.dumps({"summary": "a memo"}).encode()) == {"summary": "a memo"}


# --------------------------------------------------------------------------- #
# 3. Only the kinds written against a prior memo compare
# --------------------------------------------------------------------------- #
def test_a_new_facility_holding_a_prior_memo_does_not_claim_to_know_what_changed(
    client: TestClient,
) -> None:
    """ "What changed" about a facility that did not exist last year answers nothing."""
    memo = _build(client, _with_prior(client), NEW_FACILITY)
    assert memo["renewal_delta"] is None


@pytest.mark.parametrize("kind", ["renewal", "annual_review", "rating_action"])
def test_every_kind_written_against_the_memo_before_it_compares(
    client: TestClient, kind: str
) -> None:
    memo = _build(client, _with_prior(client), {"kind": kind, "loan_type": "ci_term"})
    assert memo["renewal_delta"] is not None
    assert not memo["renewal_delta"]["no_comparison_reason"]


# --------------------------------------------------------------------------- #
# 4. The prior memo is a baseline, never evidence about the borrower now
# --------------------------------------------------------------------------- #
def test_no_figure_in_this_period_is_read_off_last_cycles_memo(client: TestClient) -> None:
    """It would arrive with a quote and a page, looking read off the borrower's statements."""
    analysis_id = _with_prior(client)
    manifest = client.get(f"/v1/analyses/{analysis_id}", headers=ANALYST).json()
    prior_id = next(d["id"] for d in manifest["documents"] if d["doc_type"] == "prior_memo")
    candidate = client.post(
        f"/v1/analyses/{analysis_id}/spreads/extract", headers=ANALYST, json={}
    ).json()
    assert candidate["items"], "nothing was extracted, so this asserts nothing"
    assert prior_id not in {item["document_id"] for item in candidate["items"]}


def test_nothing_in_the_renewal_cites_the_prior_memo(client: TestClient) -> None:
    """Indexed as evidence, last cycle's figures could ground this cycle's covenant."""
    analysis_id = _with_prior(client)
    manifest = client.get(f"/v1/analyses/{analysis_id}", headers=ANALYST).json()
    prior_id = next(d["id"] for d in manifest["documents"] if d["doc_type"] == "prior_memo")
    memo = _build(client, analysis_id, RENEWAL)
    cited = {c.get("document_id") for c in memo["citations"]}
    assert prior_id not in cited
    # The file is still in the manifest: it was used, as the baseline, and a reader can open it.
    assert prior_id in {d["id"] for d in memo["manifest"]["documents"]}


# --------------------------------------------------------------------------- #
# 5. The checklist, at intake, about the kind the analyst actually picked
# --------------------------------------------------------------------------- #
def test_a_renewal_missing_its_prior_memo_is_reported_before_any_memo_is_built(
    client: TestClient,
) -> None:
    response = client.get(
        f"/v1/analyses/{_open(client)}/checklist", headers=ANALYST, params=RENEWAL
    )
    assert response.status_code == 200, response.text
    checklist = response.json()
    assert "prior_memo" in checklist["required"]
    assert "prior_memo" in checklist["missing_required"]
    assert checklist["compares_with_prior"] is True
    assert "financial_statement" in checklist["present"]


def test_the_checklist_reports_a_complete_credit_file_as_complete(client: TestClient) -> None:
    """A check that can only ever report a gap reports nothing."""
    analysis_id = _open(
        client,
        ("prior.json", json.dumps(PRIOR_MEMO).encode(), "application/json", "prior_memo"),
        ("debt.csv", b"facility,amount\nterm,2400\n", "text/csv", "debt_schedule"),
    )
    checklist = client.get(
        f"/v1/analyses/{analysis_id}/checklist", headers=ANALYST, params=RENEWAL
    ).json()
    assert checklist["missing_required"] == []
    assert "prior_memo" in checklist["present"]


def test_the_loan_type_changes_what_is_required_not_only_the_memo_kind(
    client: TestClient,
) -> None:
    """An investor-CRE renewal wants a rent roll; a C&I one wants a debt schedule.

    Both are read off the same analysis, so a console that asked about one loan type and
    rendered the answer as though it were about another would be reporting a gap the analyst
    does not have, or hiding one they do.
    """
    analysis_id = _with_prior(client)
    cre = client.get(
        f"/v1/analyses/{analysis_id}/checklist",
        headers=ANALYST,
        params={"kind": "renewal", "loan_type": "cre_investor"},
    ).json()
    ci = client.get(f"/v1/analyses/{analysis_id}/checklist", headers=ANALYST, params=RENEWAL).json()
    assert "rent_roll" in cre["missing_required"] and "rent_roll" not in ci["required"]
    assert "debt_schedule" in ci["missing_required"] and "debt_schedule" not in cre["required"]


def test_the_checklist_will_not_answer_about_a_kind_nobody_named(client: TestClient) -> None:
    """A defaulted answer would be confident about a different memo than the one being written.

    And the omission it would hide is precisely the one this route exists to report.
    """
    assert client.get(f"/v1/analyses/{_open(client)}/checklist", headers=ANALYST).status_code == 422


def test_an_unknown_kind_is_refused_with_the_kinds_that_exist(client: TestClient) -> None:
    response = client.get(
        f"/v1/analyses/{_open(client)}/checklist",
        headers=ANALYST,
        params={"kind": "re-newal", "loan_type": "ci_term"},
    )
    assert response.status_code == 422
    assert "renewal" in response.text and "annual_review" in response.text


def test_a_checklist_for_somebody_elses_analysis_is_absent_not_forbidden(
    client: TestClient,
) -> None:
    """Absent and forbidden are the same answer, or the status confirms the analysis exists."""
    analysis_id = _open(client)
    response = client.get(
        f"/v1/analyses/{analysis_id}/checklist",
        headers={"X-Dev-Persona": "other-tenant"},
        params=RENEWAL,
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# 6. The pack a committee reads carries it too
# --------------------------------------------------------------------------- #
def _renewal_memo(delta: RenewalDelta | None) -> CreditMemo:
    return CreditMemo(
        borrower=Borrower(id="acme", name="Acme"),
        summary="This cycle.",
        request=CreditRequest(kind=MemoKind.RENEWAL),
        renewal_delta=delta,
    )


def _document_text(memo: CreditMemo) -> str:
    lines: list[str] = []
    for block in build_document(memo).blocks:
        lines.extend([block.text, *block.items, *(" ".join(row) for row in block.rows)])
    return "\n".join(lines)


def test_the_exported_renewal_leads_with_what_changed(client: TestClient) -> None:
    """The console showing a movement the pack drops is the regression worth guarding.

    The pack is what actually reaches a committee, and it is built from the STORED memo
    rather than from a fresh build, which is where a section has gone missing before.
    """
    analysis_id = _with_prior(client)
    _build(client, analysis_id, RENEWAL)
    pack = client.post(f"/v1/analyses/{analysis_id}/export?fmt=html", headers=ANALYST)
    assert pack.status_code == 200, pack.text
    assert "What changed since the last review" in pack.text
    assert "prior.json" in pack.text


def test_a_pack_with_nothing_to_compare_says_so_where_the_comparison_would_be() -> None:
    reason = "no prior memo was uploaded, so there is nothing to compare this against."
    text = _document_text(_renewal_memo(RenewalDelta(no_comparison_reason=reason)))
    assert "What changed since the last review" in text
    assert reason in text
    assert "full assessment rather than as a delta" in text


def test_a_pack_states_that_the_figures_held_rather_than_leaving_it_out() -> None:
    text = _document_text(_renewal_memo(RenewalDelta(prior_filename="prior.json")))
    assert "prior.json" in text
    assert "moved materially" in text


def test_a_pack_prints_every_line_that_moved() -> None:
    delta = RenewalDelta(
        prior_filename="prior.json",
        ratios=(SectionDelta(label="Leverage (FY2025)", before=1.9, after=3.2, unit="x"),),
        cleared_exceptions=("DSCR-01",),
    )
    text = _document_text(_renewal_memo(delta))
    assert "Leverage (FY2025)" in text
    assert "1.90x" in text and "3.20x" in text
    assert "DSCR-01" in text


def test_a_kind_that_is_not_written_against_a_prior_memo_gets_no_such_section() -> None:
    """A new-facility pack carrying an empty "what changed" would invite the question."""
    memo = CreditMemo(
        borrower=Borrower(id="acme", name="Acme"),
        summary="A new facility.",
        request=CreditRequest(kind=MemoKind.NEW_FACILITY),
    )
    assert "What changed since the last review" not in _document_text(memo)
