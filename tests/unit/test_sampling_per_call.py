"""Sampling is chosen per call: pinned where the output is compared, free where it is prose.

**History.** This file began as "the grounded request must not sample by default". The
organization front page claims that the consequential math is deterministic and replayable and
that the model "never produces the number". That sentence was measured in one tree,
`cdd-sow-research`, and there it was FALSE: on 2026-08-26 two runs of one identical case
against the deployment returned `score` 0.5 then 0.0, because the shared request builder
defaulted to `temperature=0.2` and every grounded call sampled. The answer then was a 0.0
default on the type and on the builder.

**What changed (owner decision, 2026-09-23).** A blanket 0.0 also pinned calls whose output is
prose nobody compares, and some models (Opus 5, Fable 5) reject the parameter outright, so a
default that sends one is a default that fails there. Sampling is now a decision each call
site makes and says:

* PINNED at 0.0 where the output is extracted, classified, scored or fed to a deterministic
  check: covenant terms, risk flags, spread line items, triage labels, and the memo draft,
  whose normalised financial metrics feed the peer comparison and the tie-out reconciliation;
* FREE (no temperature sent at all, never 1.0) for drafting, narration and judging: the
  self-critique that judges the draft, and the web-research summary of what a search found.

The type's default is therefore "free", and the builder has NO default, so a new grounded call
site cannot inherit either answer without saying which it is. The cdd-sow-research finding is
still why the pinned rows exist. **Temperature 0 is not a promise of determinism**: a hosted
model can still vary across batching and model revisions. It is the strongest thing a caller
controls, and it is what makes a comparison between two profiles a measurement.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from hex_service_kit.localmodel import LocalModelClient, LocalModelSettings
from tests.conftest import FakeLLM, FakeTracer, _settings
from tests.fixtures import fake_genai, sample_cases

from credit_memo.adapters.gcp.gemini_llm import GeminiLLMAdapter
from credit_memo.adapters.gcp.gemini_spread_extraction import GeminiSpreadExtractionAdapter
from credit_memo.adapters.gcp.gemini_web_research import GeminiWebResearchAdapter
from credit_memo.adapters.live.llm import LocalModelLLMAdapter
from credit_memo.domain import _grounded as g
from credit_memo.domain import memo_synth_service
from credit_memo.domain.covenant_service import CovenantService
from credit_memo.domain.kernel import LlmRequest
from credit_memo.domain.memo_synth_service import MemoSynthService
from credit_memo.domain.models import LlmDocument, LlmMessage, Period
from credit_memo.domain.risk_flag_service import RiskFlagService

ACTOR = "officer@bank.test"
BORROWER = sample_cases.ENTITY_BORROWER
PASSAGES = list(sample_cases.SAMPLE_PASSAGES)


def test_the_request_type_leaves_sampling_free_by_default() -> None:
    """Free means absent: ``None`` is sent as no temperature at all."""
    assert LlmRequest.__dataclass_fields__["temperature"].default is None


def test_the_grounded_builder_makes_every_call_site_choose() -> None:
    parameter = inspect.signature(g.build_llm_request).parameters["temperature"]
    assert parameter.default is inspect.Parameter.empty, "a default would be chosen for them"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------- #
# Each call site, driven for real against a recording model
# --------------------------------------------------------------------------- #
def test_covenant_extraction_is_pinned() -> None:
    llm = FakeLLM()
    CovenantService(llm=llm, tracer=FakeTracer()).extract(BORROWER, PASSAGES, ACTOR)
    assert [r.temperature for r in llm.requests] == [0.0]


def test_risk_flag_classification_is_pinned() -> None:
    llm = FakeLLM()
    RiskFlagService(llm=llm, tracer=FakeTracer()).flag(BORROWER, PASSAGES, ACTOR)
    assert [r.temperature for r in llm.requests] == [0.0]


def test_the_memo_draft_is_pinned_and_its_judge_is_free() -> None:
    """The draft carries metrics a deterministic check reads; the critique only judges it."""
    llm = FakeLLM()
    MemoSynthService(llm=llm, tracer=FakeTracer()).synthesise(BORROWER, PASSAGES, ACTOR)
    by_schema = {id(r.response_schema): r.temperature for r in llm.requests}
    assert by_schema[id(memo_synth_service._MEMO_SCHEMA)] == 0.0
    assert by_schema[id(memo_synth_service._CRITIQUE_SCHEMA)] is None


def test_spread_extraction_is_pinned() -> None:
    llm = FakeLLM()
    adapter = GeminiSpreadExtractionAdapter(_settings())
    adapter._llm = llm
    adapter.extract_spread(
        "borr-acme-mfg",
        (LlmDocument(content=b"%PDF-1.7", document_id="fs-2025"),),
        periods=(Period(label="FY2025"),),
    )
    assert [r.temperature for r in llm.requests] == [0.0]


# --------------------------------------------------------------------------- #
# What the adapters actually send
# --------------------------------------------------------------------------- #
def _gemini(monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiLLMAdapter, fake_genai.FakeGenai]:
    fake = fake_genai.install(monkeypatch)
    adapter = GeminiLLMAdapter(_settings())
    adapter._client = fake.client
    return adapter, fake


def _request(temperature: float | None) -> LlmRequest:
    return LlmRequest(
        messages=(LlmMessage(role="user", content="Draft."),), temperature=temperature
    )


def test_gemini_omits_a_free_temperature_and_sends_a_pinned_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, fake = _gemini(monkeypatch)
    adapter.generate(_request(None))
    adapter.generate(_request(0.0))
    adapter.classify("text", ["a", "b"])
    free, pinned, label = (call["config"] for call in fake.calls)
    assert "temperature" not in free, "free must mean absent, never a value the model rejects"
    assert pinned["temperature"] == 0.0
    assert label["temperature"] == 0.0, "a triage label is a classification"


def test_the_web_research_summary_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_genai.install(monkeypatch)
    adapter = GeminiWebResearchAdapter(_settings())
    adapter._client = fake.client
    assert adapter.research("Acme Manufacturing sector outlook") is not None
    assert "temperature" not in fake.calls[0]["config"]


class _Transport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        self.sent.append(json.loads(body))
        return json.dumps(
            {"model": "served-model", "choices": [{"message": {"content": "prose"}}]}
        ).encode()


def test_the_live_adapter_passes_free_through_as_absent() -> None:
    transport = _Transport()
    client = LocalModelClient(LocalModelSettings(), transport=transport)
    adapter = LocalModelLLMAdapter(_settings(), client=client)
    adapter.generate(_request(None))
    adapter.generate(_request(0.0))
    assert "temperature" not in transport.sent[0]
    assert transport.sent[1]["temperature"] == 0.0
