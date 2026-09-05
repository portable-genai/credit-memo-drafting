"""Pytest fixtures: the ``local`` adapters (seeded) + the assembled CreditMemoService.

The unit suite is driven by the **real** ``local`` adapter family
(``src/credit_memo/adapters/local``) rather than bespoke in-memory fakes, so the offline
implementation lives in exactly one place and the tests exercise the same code the
offline CLI runs. Every adapter constructs with a single ``Settings`` (the adapter
convention) pointed at ``:memory:`` SQLite, and the knowledge-base index is seeded with
the synthetic ``tests/fixtures/sample_cases`` corpus for determinism.

A few fixtures wrap the local adapter in a thin **recording** subclass that captures call
arguments for assertions (``.calls`` / ``.requests`` / ``.queries`` / ``.ingested`` /
``.spans`` / ``.events``). These add no behaviour: every method delegates to the real
local adapter, so the in-memory implementation is still the one under ``adapters/local``.
The recorders are the test instrumentation the previous bespoke fakes used to bundle.

The classic ``Fake*`` names (``FakeLLM``, ``FakePeerData``, ``FakeTracer``,
``BlockingGuardrail``) are retained as thin aliases over the recording local adapters so
the existing unit tests import and subclass them unchanged. ``BlockingGuardrail`` keeps
its ``block_input`` / ``block_output`` knobs (the OUTPUT-blocking path cannot be triggered
by input text alone), reproducing the one fake whose behaviour is hard to express as a
seedable adapter, per the build brief.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Any

import pytest

from credit_memo.adapters.local.analysis_bundle import LocalAnalysisBundleAdapter
from credit_memo.adapters.local.audit import LocalAppendOnlyAuditAdapter
from credit_memo.adapters.local.evaluation import LocalOfflineEvalAdapter
from credit_memo.adapters.local.extraction import LocalDocumentExtractionAdapter
from credit_memo.adapters.local.guardrail import LocalHeuristicGuardrailAdapter
from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from credit_memo.adapters.local.llm import LocalDeterministicLLMAdapter, _schema_properties
from credit_memo.adapters.local.peer_data import LocalPeerDataAdapter
from credit_memo.adapters.local.policy_pack import LocalYamlPolicyPackAdapter
from credit_memo.adapters.local.redaction import LocalRegexRedactionAdapter
from credit_memo.adapters.local.registry import LocalAgentRegistryAdapter
from credit_memo.adapters.local.tool_catalog import LocalToolCatalogAdapter
from credit_memo.adapters.local.tracer import LocalNoopTracerAdapter
from credit_memo.config import AnalysisBundleSettings, LocalSettings, Settings
from credit_memo.domain.models import (
    AuditEvent,
    Borrower,
    Direction,
    Filing,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
    IngestResult,
    LlmRequest,
    LlmResponse,
    PeerMetric,
    RetrievalQuery,
    RetrievedPassage,
)
from tests.fixtures import sample_cases

# Re-exported so unit tests can build the same body-shaping helper the local LLM uses.
__all__ = ["Direction", "_schema_properties"]


#: One temporary root for the whole test session, cleaned up by the OS. Module scope so
#: a container built twice in one test still sees the bundle the first one wrote.
_BUNDLE_ROOT = Path(tempfile.mkdtemp(prefix="credit-memo-test-analyses-"))


def _settings() -> Settings:
    """Settings whose local stores are ephemeral (deterministic, and never ``~``).

    The analysis bundle needs a real directory (it holds uploaded bytes), so it gets a
    per-process temporary one. Without an explicit root the local adapter would write
    into ``~/.credit_memo/analyses`` and a test run would leave a developer's home
    directory holding fixture documents.
    """
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        analysis_bundle=AnalysisBundleSettings(root=str(_BUNDLE_ROOT)),
    )


# --------------------------------------------------------------------------- #
# Recording wrappers — thin subclasses of the local adapters that capture call
# arguments for assertions. Every method delegates to the real local adapter.
# --------------------------------------------------------------------------- #
class RecordingExtraction(LocalDocumentExtractionAdapter):
    """Local document extraction that records the filings it was asked to extract."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[Filing] = []

    def extract(self, document: Filing, content: bytes, mime_type: str):  # type: ignore[no-untyped-def]
        self.calls.append(document)
        return super().extract(document, content, mime_type)


class RecordingKnowledgeBase(LocalFtsKnowledgeBaseAdapter):
    """Local FTS5 knowledge base that records ingest + search calls.

    Seeded with the sample corpus (or an explicit ``passages`` list, empty for the
    empty-store case) so retrieval is deterministic.
    """

    def __init__(self, settings: Settings, passages: list[RetrievedPassage] | None = None) -> None:
        super().__init__(settings)
        seed = list(sample_cases.SAMPLE_PASSAGES) if passages is None else list(passages)
        self.seed(seed)
        self.ingested: list[tuple[Filing, tuple[str, ...]]] = []
        self.queries: list[RetrievalQuery] = []

    def ingest(self, document: Filing, content: bytes, acl_tags: tuple[str, ...]) -> IngestResult:
        self.ingested.append((document, acl_tags))
        # Record the ACL-tagged ingest, but do not mutate the seeded corpus the asserts
        # rely on: the empty-store case must stay empty, the normal case stays seeded.
        return IngestResult(document_id=document.id, chunks=3, status="indexed", ok=True)

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        self.queries.append(query)
        # Honour the seeded corpus without ACL-filtering the synthetic fixtures away:
        # the sample passages carry borrower tags that the test queries also pass, but
        # the empty-store fixture must still return nothing.
        match = self._build_match(query.text)
        if match:
            cur = self._conn.execute(
                "SELECT * FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
                (match, max(query.top_k, 1)),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM passages ORDER BY score DESC LIMIT ?", (max(query.top_k, 1),)
            )
        return [self._row_to_passage(row) for row in cur.fetchall()]


class RecordingLLM(LocalDeterministicLLMAdapter):
    """Local deterministic LLM that records the requests it received (alias: FakeLLM)."""

    def __init__(self, settings: Settings | None = None, used_source_ids: list[str] | None = None):
        super().__init__(settings or _settings(), used_source_ids=used_source_ids)
        self.requests: list[LlmRequest] = []
        self.classify_calls: list[tuple[str, list[str]]] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return super().generate(request)

    def classify(self, text: str, labels: list[str]) -> str:
        self.classify_calls.append((text, labels))
        return super().classify(text, labels)


class RecordingPeerData(LocalPeerDataAdapter):
    """Local peer data that records lookups (alias: FakePeerData).

    Accepts a ``by_metric`` override so tests can simulate a missing-peer cohort.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        by_metric: dict[str, tuple[PeerMetric, ...]] | None = None,
    ) -> None:
        super().__init__(settings or _settings())
        if by_metric is not None:
            self.seed(by_metric)
        self.calls: list[tuple[str, str]] = []

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        self.calls.append((borrower.id, metric))
        return super().peers_for(borrower, metric)


class RecordingRedaction(LocalRegexRedactionAdapter):
    """Local regex redaction that records the raw text it was asked to redact."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []

    def redact(self, text: str):  # type: ignore[no-untyped-def]
        self.calls.append(text)
        return super().redact(text)


class RecordingTracer(LocalNoopTracerAdapter):
    """Local no-op tracer that records the span names it opened (alias: FakeTracer)."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or _settings())
        self.spans: list[str] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return super().span(name, **attributes)


class RecordingGuardrail(LocalHeuristicGuardrailAdapter):
    """Local heuristic guardrail that records (text, direction) screen calls.

    Behaviour is the real heuristic: benign text passes, malicious text (e.g.
    ``sample_cases.MALICIOUS_MEMO_INPUT``) is blocked. Only the recording is added.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction):  # type: ignore[no-untyped-def]
        self.calls.append((text, direction))
        return super().screen(text, direction)


class RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        super().record(event)


class RecordingEval(LocalOfflineEvalAdapter):
    """Local offline eval gate (alias: FakeEval); constructs without a Settings arg."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or _settings())


class RecordingAgentRegistry(LocalAgentRegistryAdapter):
    """Local in-process agent registry; constructs without a Settings arg in tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or _settings())


class RecordingToolCatalog(LocalToolCatalogAdapter):
    """Local in-process tool catalog; constructs without a Settings arg in tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or _settings())


class BlockingGuardrail(LocalHeuristicGuardrailAdapter):
    """Guardrail that force-blocks a chosen direction, for the blocked-path tests.

    The default local heuristic only blocks malicious *input* text, so the OUTPUT-blocking
    path (clean input, blocked output) cannot be exercised by text alone. This thin local
    adapter reproduces that one deterministic behaviour with explicit knobs, keeping the
    suite green without re-introducing a bespoke fake.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        block_input: bool = True,
        block_output: bool = False,
    ) -> None:
        super().__init__(settings or _settings())
        self.block_input = block_input
        self.block_output = block_output
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        self.calls.append((text, direction))
        blocked = (direction is Direction.INPUT and self.block_input) or (
            direction is Direction.OUTPUT and self.block_output
        )
        if not blocked:
            return GuardrailVerdict(
                allowed=True, direction=direction, findings=(), sanitized_text=text, reason="ok"
            )
        return GuardrailVerdict(
            allowed=False,
            direction=direction,
            findings=(
                GuardrailFinding(
                    category=GuardrailCategory.PROMPT_INJECTION,
                    confidence="high",
                    detail="prompt injection detected",
                ),
            ),
            sanitized_text=None,
            reason="blocked by guardrail",
        )


# Backward-compatible aliases: the classic ``Fake*`` names now resolve to the recording
# local adapters, so existing unit tests import / subclass them unchanged.
FakeLLM = RecordingLLM
FakePeerData = RecordingPeerData
FakeTracer = RecordingTracer
FakeEval = RecordingEval


# --------------------------------------------------------------------------- #
# Service / policy resolution — locate the domain classes wherever they live.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "credit_memo.domain.memo_service",
    "credit_memo.domain.memo_synth_service",
    "credit_memo.domain.covenant_service",
    "credit_memo.domain.risk_flag_service",
    "credit_memo.domain.peer_comp_service",
    "credit_memo.domain.services",
)
_POLICY_MODULE_CANDIDATES = (
    "credit_memo.domain.review_policy",
    "credit_memo.domain.policies",
    "credit_memo.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


def load_policy(name: str) -> Any:
    return _resolve(name, _POLICY_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures — construct the (seeded) local adapters.
# --------------------------------------------------------------------------- #
@pytest.fixture
def extraction() -> RecordingExtraction:
    return RecordingExtraction(_settings())


@pytest.fixture
def knowledge_base() -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings())


@pytest.fixture
def empty_knowledge_base() -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings(), passages=[])


@pytest.fixture
def peer_data() -> RecordingPeerData:
    return RecordingPeerData(_settings())


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM(_settings())


@pytest.fixture
def guardrail() -> RecordingGuardrail:
    return RecordingGuardrail(_settings())


@pytest.fixture
def blocking_guardrail() -> BlockingGuardrail:
    return BlockingGuardrail(_settings())


@pytest.fixture
def redaction() -> RecordingRedaction:
    return RecordingRedaction(_settings())


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer(_settings())


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit(_settings())


@pytest.fixture
def evaluation() -> RecordingEval:
    return RecordingEval(_settings())


@pytest.fixture
def agent_registry() -> RecordingAgentRegistry:
    return RecordingAgentRegistry(_settings())


@pytest.fixture
def tool_catalog() -> RecordingToolCatalog:
    return RecordingToolCatalog(_settings())


@pytest.fixture
def credit_memo_service(
    extraction,
    knowledge_base,
    peer_data,
    llm,
    guardrail,
    redaction,
    tracer,
    audit,
    analysis_bundle,
    policy_pack,
):
    """CreditMemoService(extraction, knowledge_base, peer_data, llm, guardrail, redaction,
    tracer, audit, analysis_bundle)."""
    cls = load_service("CreditMemoService")
    return cls(
        extraction,
        knowledge_base,
        peer_data,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        analysis_bundle=analysis_bundle,
        policy_pack=policy_pack,
    )


@pytest.fixture
def policy_pack() -> LocalYamlPolicyPackAdapter:
    """The shipped EXAMPLE pack, whose limits are made up and say so."""
    return LocalYamlPolicyPackAdapter(_settings())


@pytest.fixture
def analysis_bundle() -> LocalAnalysisBundleAdapter:
    """Custody for one test's analyses, on the session's temporary root."""
    return LocalAnalysisBundleAdapter(_settings())
