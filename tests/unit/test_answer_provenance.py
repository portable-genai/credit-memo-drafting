"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool (owner decision, 2026-09-23). Both come
from response headers the kit emits (``install_answer_provenance`` in ``api/app.py``) for
whatever the model adapters NOTED as they called. Before a request is answered the pill shows
``generator_model`` from ``/healthz``, so that value must be the model the bound adapter calls,
never one a configuration flag names while the adapter calls another.

What is held here, offline:

* under ``local`` a model-backed route names the deterministic stub, under the same name
  ``generator_model`` gives it, and a route that called no model names nothing;
* the Gemini adapter notes the model it actually passed to the client, and nothing when the
  call failed;
* the one call that attaches Google Search notes the search, through the real route;
* the console, which calls this service cross-origin when standalone, may READ both headers;
* ``generator_model`` under ``gcp`` is the model the adapter calls, and the
  ``use_hard_reasoning`` flag that once moved it alone is gone.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.fixtures import fake_genai

from credit_memo.adapters.gcp.gemini_llm import GeminiLLMAdapter
from credit_memo.adapters.gcp.gemini_web_research import GeminiWebResearchAdapter
from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.config import ModelSettings, Settings
from credit_memo.domain.models import LlmMessage, LlmRequest

CONFIG_PATH = "config/settings.yaml"
ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"
ANALYST = {"X-Dev-Persona": "analyst"}
_LOOPBACK = ("127.0.0.1", 50000)
_BODY = {
    "borrower": {
        "id": "borr-acme-mfg",
        "name": "Acme Manufacturing Pte Ltd (FICTIONAL)",
        "sector": "manufacturing",
        "jurisdiction": "SG",
    },
    "documents": [],
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "local")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_ANALYSIS_ROOT", str(tmp_path))
    monkeypatch.delenv("CREDIT_MEMO_RESEARCH_ENABLED", raising=False)
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=_LOOPBACK) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


def _gcp_settings() -> Settings:
    return dataclasses.replace(Settings.load(CONFIG_PATH), profile="gcp")


def _request(model: str | None = None) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="Summarise."),), model=model)


# --------------------------------------------------------------------------- #
# Through the real app
# --------------------------------------------------------------------------- #
def test_a_model_backed_route_names_the_model_that_answered(client: TestClient) -> None:
    """Under ``local`` that is the stub, named exactly as the configured pill names it."""
    response = client.post("/v1/credit-memo", json=_BODY, headers=ANALYST)
    assert response.status_code == 200, response.text
    assert response.headers[ANSWERED_BY] == deps.get_settings().generator_model
    assert response.headers[ANSWERED_BY] == "deterministic-offline-stub"
    assert SEARCH_USED not in response.headers, "no search tool was attached to any call"


def test_a_route_that_called_no_model_names_none(client: TestClient) -> None:
    """Nothing noted, nothing sent: the pill never invents a model nobody called."""
    client.post("/v1/credit-memo", json=_BODY, headers=ANALYST)  # a record must not leak on
    response = client.get("/healthz")
    assert response.status_code == 200
    assert ANSWERED_BY not in response.headers
    assert SEARCH_USED not in response.headers


def test_the_console_may_read_both_headers_across_origins(client: TestClient) -> None:
    """Standalone, the console calls this service cross-origin, which hides unexposed headers.

    Without the expose list the pill would stay on the configured model forever, while every
    same-origin test here stayed green.
    """
    response = client.post(
        "/v1/credit-memo",
        json=_BODY,
        headers={**ANALYST, "Origin": "http://localhost:3000"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    exposed = {
        name.strip().lower()
        for value in response.headers.get_list("access-control-expose-headers")
        for name in value.split(",")
    }
    assert {ANSWERED_BY, SEARCH_USED} <= exposed


def test_the_search_call_names_its_model_and_the_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real Gemini research adapter on the real route, with only the SDK faked."""
    fake = fake_genai.install(monkeypatch)
    opened = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("spread.csv", b"code,period,value\nrevenue,FY2025,4729\n", "text/csv"))],
        data={"borrower_id": "flowserve-corp", "doc_types": "financial_statement"},
    )
    assert opened.status_code == 201, opened.text
    researcher = GeminiWebResearchAdapter(deps.get_settings())
    researcher._client = fake.client
    monkeypatch.setenv("CREDIT_MEMO_RESEARCH_ENABLED", "1")
    container = deps.get_container()
    monkeypatch.setattr(type(container), "web_research", property(lambda self: researcher))

    response = client.get(f"/v1/analyses/{opened.json()['analysis_id']}/research", headers=ANALYST)

    assert response.status_code == 200, response.text
    assert fake.calls, "the adapter never called the (fake) model"
    assert "tools" in fake.calls[0]["config"], "the search tool was not attached"
    assert response.headers[ANSWERED_BY] == fake.calls[0]["model"]
    assert response.headers[SEARCH_USED] == "true"


# --------------------------------------------------------------------------- #
# The Gemini adapter notes what it called
# --------------------------------------------------------------------------- #
def test_the_gemini_adapter_notes_the_model_it_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_genai.install(monkeypatch)
    adapter = GeminiLLMAdapter(_gcp_settings())
    adapter._client = fake.client
    with provenance.scope() as record:
        adapter.generate(_request(model="a-model-the-caller-named"))
        adapter.classify("text", ["ok", "not ok"])
    assert record.models == [fake.calls[0]["model"], fake.calls[1]["model"]]
    assert record.models == ["a-model-the-caller-named", adapter._models.triage]
    assert record.search_used is False, "no search tool rides on a drafting or triage call"


def test_a_failed_call_notes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_genai.install(monkeypatch)
    fake.fail = True
    adapter = GeminiLLMAdapter(_gcp_settings())
    adapter._client = fake.client
    with provenance.scope() as record, pytest.raises(RuntimeError):
        adapter.generate(_request())
    assert record.models == []


def test_generator_model_under_gcp_is_the_model_the_adapter_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured pill and the answered pill must name the same model for the same call."""
    fake = fake_genai.install(monkeypatch)
    settings = _gcp_settings()
    adapter = GeminiLLMAdapter(settings)
    adapter._client = fake.client
    adapter.generate(_request(model=None))
    assert fake.calls[0]["model"] == settings.generator_model


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    """The latent false banner: a flag that moved the configured model but not the call.

    ``generator_model`` once named ``models.hard_reasoning`` when ``use_hard_reasoning`` was
    set, while the Gemini adapter called ``request.model or models.reasoning`` and never read
    the flag. Flipping it would have put a model on screen that never answered.
    """
    fields = {f.name for f in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields and "hard_reasoning" not in fields
    assert "hard_reasoning" not in Path(CONFIG_PATH).read_text(encoding="utf-8")
    for source in sorted(Path("src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
