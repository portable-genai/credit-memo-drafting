"""Public-web research, reachable at last — and fenced where it has to be.

`WebResearchPort` was built with three adapters, a per-analysis cost cap, refuse-don't-scrub
query redaction, a licence-driven isolation rule and a promotion-gate metric proving that
rule holds. No route, no client and no UI ever called it, so Grounding with Google Search
was a capability the product could not perform. `Provenance.WEB_GROUNDED` and the console
badge that renders it were unreachable for the same reason.

What these tests hold, now that a route exists:

* **Off unless the deployment switched it on**, because the search leg leaves the deploy
  region and is billed per query. That is a deviation a deployment takes deliberately.
* **"Could not look" and "looked and found nothing" stay different answers.** An analyst
  deciding whether to go and check themselves needs to know which one they got, and
  collapsing them is how silence gets read as absence of news.
* **The search suggestions survive.** Google requires the chips rendered verbatim beside
  grounded results; dropping them is a licence breach that looks like a tidy UI.
* **Nothing crosses into the memo.** The response shape carries no number, so no ratio,
  covenant test, policy rule or scorecard can read an operand off it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.domain.models import MarketContext, WebEvidence

ANALYST = {"X-Dev-Persona": "analyst"}
SPREAD_CSV = b"code,period,value\nrevenue,FY2025,4729\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "local")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_ANALYSIS_ROOT", str(tmp_path))
    monkeypatch.delenv("CREDIT_MEMO_RESEARCH_ENABLED", raising=False)
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


def _open(client: TestClient) -> str:
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("spread.csv", SPREAD_CSV, "text/csv"))],
        data={"borrower_id": "flowserve-corp", "doc_types": "financial_statement"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["analysis_id"])


class _Researcher:
    """Stands in for the Gemini grounding adapter at the port seam."""

    def __init__(self, result: MarketContext | None) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def research(self, query: str, purpose: str = "", max_results: int = 8) -> Any:
        self.calls.append((query, purpose))
        return self.result


def _enable(monkeypatch: pytest.MonkeyPatch, researcher: Any) -> None:
    monkeypatch.setenv("CREDIT_MEMO_RESEARCH_ENABLED", "1")
    container = deps.get_container()
    monkeypatch.setattr(type(container), "web_research", property(lambda self: researcher))


def test_research_is_off_until_the_deployment_switches_it_on(client: TestClient) -> None:
    response = client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "CREDIT_MEMO_RESEARCH_ENABLED" in detail
    # The reason is residency and cost, not caution: a deployment should be able to read
    # what it is agreeing to before it agrees.
    assert "global endpoint" in detail and "billed per query" in detail


def test_a_search_that_found_something_reaches_the_analyst_with_its_chips(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = MarketContext(
        query="Flowserve Corporation recent news",
        purpose="credit analyst context",
        evidence=(
            WebEvidence(
                title="Flowserve reports fourth-quarter results",
                url="https://example.invalid/fls-q4",
                snippet="The company reported full-year bookings growth.",
            ),
        ),
        search_suggestions=("<div>Searches related to Flowserve</div>",),
        provider="gemini-grounding-google-search",
    )
    _enable(monkeypatch, _Researcher(found))

    body = client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST).json()

    assert body["found_nothing"] is False
    assert body["evidence"][0]["url"] == "https://example.invalid/fls-q4"
    assert body["evidence"][0]["provenance"] == "web_grounded"
    # Rendered verbatim: Google requires the chips beside grounded results.
    assert body["search_suggestions"] == ["<div>Searches related to Flowserve</div>"]
    assert body["provider"] == "gemini-grounding-google-search"


def test_looked_and_found_nothing_is_not_the_same_as_could_not_look(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both are honest answers, and they send an analyst in opposite directions."""
    _enable(monkeypatch, _Researcher(MarketContext(query="q", provider="stub")))
    ran = client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST)
    assert ran.status_code == 200
    assert ran.json()["found_nothing"] is True

    _enable(monkeypatch, _Researcher(None))
    refused = client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST)
    assert refused.status_code == 422
    assert "not a finding that nothing was published" in refused.json()["detail"]


def test_the_query_carries_public_identity_and_not_the_facility(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What leaves the region is a name. The terms of the deal are the bank's business."""
    researcher = _Researcher(MarketContext(query="q", provider="stub"))
    _enable(monkeypatch, researcher)
    client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST)

    asked, purpose = researcher.calls[-1]
    assert "flowserve" in asked.lower()
    assert purpose, "an audit log needs to know why this service searched"


def test_a_stranger_cannot_research_another_tenants_analysis(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, _Researcher(MarketContext(query="q", provider="stub")))
    analysis_id = _open(client)
    denied = client.get(
        f"/v1/analyses/{analysis_id}/research", headers={"X-Dev-Persona": "other-tenant"}
    )
    assert denied.status_code == 404, "absent and forbidden must be the same answer"


def test_nothing_the_search_returns_carries_a_number(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fence, checked at the wire rather than only in the domain type.

    A shape with no numeric field cannot supply an operand to a ratio, a covenant test, a
    policy rule or a scorecard, however the response is later consumed.
    """
    _enable(
        monkeypatch,
        _Researcher(
            MarketContext(
                query="q",
                evidence=(WebEvidence(title="t", url="https://example.invalid/x", snippet="s"),),
                provider="stub",
            )
        ),
    )
    item = client.get(f"/v1/analyses/{_open(client)}/research", headers=ANALYST).json()["evidence"][
        0
    ]
    assert not [key for key, value in item.items() if isinstance(value, (int, float))]
