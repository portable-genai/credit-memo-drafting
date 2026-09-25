"""The ``live`` laptop lane: the core on the local model, Gemini only for optional research.

Owner decision 2026-09-23: this assistant runs its CORE on the fleet's local open-weight
model and uses Gemini only while its optional public-web research is on. These tests pin the
things that decision rests on, offline, against a fake transport:

* the live LLM adapter maps the domain request onto the shared kit client and back, including
  a fenced, then invalid, first answer that the kit feeds back and retries;
* ``live`` binds and builds every port with no cloud SDK and no credentials;
* research is off under ``live`` unless ``CREDIT_MEMO_RESEARCH_ENABLED`` is set, and switched
  on without credentials it reports itself unavailable instead of crashing the core.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelSettings,
    LocalModelUnavailable,
)

from credit_memo.adapters.live import web_research as live_research
from credit_memo.adapters.live.llm import LocalModelLLMAdapter
from credit_memo.adapters.live.web_research import LiveWebResearchAdapter
from credit_memo.config import AnalysisBundleSettings, Container, LocalSettings, Settings
from credit_memo.domain.models import (
    LlmDocument,
    LlmMessage,
    LlmRequest,
    MarketContext,
    TokenUsage,
)

CONFIG_PATH = "config/settings.yaml"
_BUNDLE_ROOT = Path(tempfile.mkdtemp(prefix="credit-memo-live-test-"))

_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["answer", "confidence"],
}


class FakeTransport:
    """Answers each POST with the next scripted body; records what was sent."""

    def __init__(self, *answers: str, model: str = "served-model", usage: Any = None) -> None:
        self._answers = list(answers)
        self._model = model
        self._usage = usage
        self.sent: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        self.sent.append(json.loads(body))
        reply: dict[str, Any] = {
            "model": self._model,
            "choices": [{"message": {"role": "assistant", "content": self._answers.pop(0)}}],
        }
        if self._usage is not None:
            reply["usage"] = self._usage
        return json.dumps(reply).encode()


def _live_settings(**overrides: Any) -> Settings:
    base = Settings.load(CONFIG_PATH)
    return dataclasses.replace(
        base,
        profile="live",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        analysis_bundle=AnalysisBundleSettings(root=str(_BUNDLE_ROOT)),
        **overrides,
    )


def _adapter(transport: FakeTransport) -> LocalModelLLMAdapter:
    client = LocalModelClient(LocalModelSettings(), transport=transport)
    return LocalModelLLMAdapter(_live_settings(), client=client)


def _request(**kwargs: Any) -> LlmRequest:
    return LlmRequest(
        messages=(LlmMessage(role="user", content="Summarise the leverage trend."),),
        system_instruction="Answer only from the passages.",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# The live LLM adapter
# --------------------------------------------------------------------------- #
def test_structured_call_retries_a_fenced_invalid_answer_and_returns_clean_json() -> None:
    transport = FakeTransport(
        '```json\n{"answer": "Leverage fell."}\n```',  # fenced AND missing confidence
        '{"answer": "Leverage fell.", "confidence": 0.8}',
        usage={"prompt_tokens": 40, "completion_tokens": 9},
    )
    response = _adapter(transport).generate(
        _request(response_schema=_SCHEMA, temperature=0.0, max_output_tokens=512)
    )

    assert len(transport.sent) == 2, "the invalid first answer must be fed back and retried"
    retry = transport.sent[1]["messages"]
    assert "confidence" in retry[-1]["content"], "the retry names the missing field"
    assert json.loads(response.text) == {"answer": "Leverage fell.", "confidence": 0.8}
    assert response.raw == {"answer": "Leverage fell.", "confidence": 0.8}
    assert response.model == "served-model", "model is the id that answered"
    assert response.usage == TokenUsage(input_tokens=80, output_tokens=18)


def test_the_request_maps_onto_messages_temperature_and_budget() -> None:
    transport = FakeTransport("plain text")
    request = LlmRequest(
        messages=(
            LlmMessage(role="user", content="q1"),
            LlmMessage(role="model", content="a1"),
            LlmMessage(role="user", content="q2"),
        ),
        system_instruction="sys",
        temperature=0.3,
        max_output_tokens=100_000,
    )
    response = _adapter(transport).generate(request)

    sent = transport.sent[0]
    assert [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "user"]
    assert sent["messages"][0]["content"] == "sys"
    assert sent["temperature"] == 0.3, "the request's temperature passes through unchanged"
    assert sent["max_tokens"] == Settings().live.max_output_tokens, "the live budget caps it"
    assert response.text == "plain text"
    assert response.usage == TokenUsage(), "no usage reported is zeros, the type's default"


def test_an_answer_that_never_validates_degrades_to_the_last_text() -> None:
    transport = FakeTransport("not json", "still not", "nope")
    response = _adapter(transport).generate(_request(response_schema=_SCHEMA))

    assert len(transport.sent) == 3
    assert response.text == "nope", "the domain parses this defensively, as a bad Gemini answer"


def test_an_unreachable_server_raises_with_the_start_recipe() -> None:
    def down(url: str, body: bytes | None, timeout: float) -> bytes:
        raise OSError("connection refused")

    adapter = LocalModelLLMAdapter(
        _live_settings(), client=LocalModelClient(LocalModelSettings(), transport=down)
    )
    with pytest.raises(LocalModelUnavailable, match="mlx_vlm.server"):
        adapter.generate(_request())


def test_classify_coerces_the_reply_to_a_label() -> None:
    transport = FakeTransport("Label: Manufacturing.")
    label = _adapter(transport).classify("text", ["retail", "manufacturing"])

    assert label == "manufacturing"
    assert transport.sent[0]["temperature"] == 0.0


def test_attached_documents_are_refused_rather_than_silently_dropped() -> None:
    transport = FakeTransport("never sent")
    request = _request(documents=(LlmDocument(content=b"%PDF-1.7", document_id="fs-2025"),))
    with pytest.raises(NotImplementedError, match="text only"):
        _adapter(transport).generate(request)
    assert transport.sent == []


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #
def test_live_binds_the_local_model_for_the_core_and_the_optional_leg_for_search() -> None:
    adapters = Settings.load(CONFIG_PATH).adapters
    assert adapters["llm"]["live"].endswith("adapters.live.llm:LocalModelLLMAdapter")
    assert adapters["web_research"]["live"].endswith(
        "adapters.live.web_research:LiveWebResearchAdapter"
    )


def test_the_container_builds_every_port_under_live_with_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("CREDIT_MEMO_RESEARCH_ENABLED", raising=False)
    monkeypatch.delenv("CREDIT_MEMO_ENTITY_RESOLUTION_ENABLED", raising=False)
    container = Container(_live_settings())
    optional = {"web_research", "entity_resolution"}  # None while switched off
    for port in Settings.load(CONFIG_PATH).adapters:
        built = getattr(container, port)
        assert (built is None) if port in optional else (built is not None), port
    assert isinstance(container.llm, LocalModelLLMAdapter)


def test_the_banner_names_the_local_model_under_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_MODEL", "some-org/some-local-model")
    assert _live_settings().generator_model == "some-org/some-local-model"


# --------------------------------------------------------------------------- #
# The optional research leg
# --------------------------------------------------------------------------- #
def test_research_switched_on_without_credentials_is_unavailable_not_fatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CREDIT_MEMO_RESEARCH_ENABLED", "true")
    container = Container(_live_settings(project_id="your-gcp-project"))
    leg = container.web_research

    assert isinstance(leg, LiveWebResearchAdapter)
    assert leg.available is False
    assert "GOOGLE_CLOUD_PROJECT" in leg.reason
    assert "unavailable" in caplog.text
    with pytest.raises(NotImplementedError, match="unavailable on this machine"):
        leg.research("Acme Holdings sector outlook")
    assert isinstance(container.llm, LocalModelLLMAdapter), "the core still builds"


def test_research_switched_on_with_credentials_delegates_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = MarketContext(query="q", provider="gemini-grounding-google-search")

    class Gemini:
        def research(self, query: str, purpose: str = "", max_results: int = 8) -> MarketContext:
            return found

    monkeypatch.setattr(live_research, "_gemini_or_reason", lambda settings: (Gemini(), ""))
    leg = LiveWebResearchAdapter(_live_settings())

    assert (leg.available, leg.reason) == (True, "")
    assert leg.research("q") is found
