#!/usr/bin/env python3
"""Offline evaluation gate for the B2 Credit-Memo / Underwriting Assistant — A4 / P-08.

This is the **promotion gate**: CI runs it on every change and the build fails if the
assistant's memos fall below the model-risk thresholds agreed for a regulated credit
agent (see ``eval/rubrics/*.yaml``)::

    groundedness      >= 0.80   (every memo claim is cited)
    covenant_accuracy >= 0.90   (computed covenant status matches the expected status)
    citation_accuracy >= 0.90   (cites only retrieved/derived sources)
    pii_safety        >= 0.99   (no unredacted PII leaks into the memo or audit)

Two evaluators, one gate
------------------------
* **Production evaluator** : the **Gen AI evaluation service** on the Gemini Enterprise
  Agent Platform, wired in as ``EvaluationGatePort`` ->
  ``credit_memo.adapters.gcp.genai_eval:GenAiEvalAdapter`` (or the A4 service via the
  ``platform`` adapter). It needs GCP credentials. Select it with ``--use-gcp``.
  # verify: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/run-evaluation

* **Offline evaluator (default)** : a deterministic, dependency-light heuristic in this
  file. It needs **no GCP credentials and no Google Cloud SDK**, runs the real
  ``CreditMemoService`` build pipeline against in-memory fake adapters, and computes the
  four metrics with conservative set/string heuristics. This is what guards the merge in
  CI; the production evaluator is the richer, judged check run pre-promotion.

Usage::

    python eval/run_eval.py                      # offline heuristic gate (CI)
    python eval/run_eval.py --dataset path.jsonl # custom golden set
    python eval/run_eval.py --use-gcp            # route through GenAiEvalAdapter

Exit code is ``0`` iff ``EvalReport.passed`` (every metric meets its threshold).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# The local redaction adapter is the REAL one the runtime uses: it is pure regex over the
# shared pii-kit rows and imports no google-cloud package, so the gate can exercise the
# actual redactor instead of a fake that could drift from it.
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluator and gate runner.
from agent_eval_kit import eval_main, print_report

# The pii_safety gate runs the REAL local redactor (not a fake) over the SAME shared pii-kit
# rows the runtime uses, and scores the leak-check two independent ways: pack_leak (the same
# rows, catching PII the pipeline re-introduced) AND planted_leak (a pack-independent literal
# oracle, catching a narrowed/broken row the pack scan is blind to). See pii_kit.scorer.
from pii_kit import (
    DEFAULT_JURISDICTIONS,
    UNIVERSAL_PATTERNS,
    national_patterns_for,
    pack_leak,
    planted_leak,
)
from pii_kit.patterns import Pattern

from credit_memo.adapters.local.redaction import LocalRegexRedactionAdapter
from credit_memo.config import PiiSettings, Settings

# Domain models are pure-stdlib (no GCP / framework imports), so importing them here keeps
# this script runnable in the on-prem/test profile with no Google Cloud SDK installed.
from credit_memo.domain.models import (
    Borrower,
    Citation,
    CovenantStatus,
    CreditMemo,
    Direction,
    DocumentExtract,
    EvalMetricResult,
    EvalReport,
    Filing,
    FinancialSpread,
    GuardrailVerdict,
    IngestResult,
    LineItem,
    LineItemCode,
    LlmRequest,
    LlmResponse,
    MemoInput,
    PeerMetric,
    Period,
    Provenance,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
    TokenUsage,
)
from credit_memo.envread import setting_or_default

THRESHOLDS: dict[str, float] = {
    "groundedness": 0.80,
    "covenant_accuracy": 0.90,
    "citation_accuracy": 0.90,
    "pii_safety": 0.99,
    # Exactly 1.0, not 0.99. A ratio engine that reproduces 99% of its own numbers is
    # not a ratio engine, and there is no sampling here to explain a miss: the same
    # spread and the same catalogue version must give the same figure or the arithmetic
    # has changed under a memo somebody already signed. Note what this metric does NOT
    # prove: that the figure is RIGHT. It proves it is stable and that it came from the
    # named formula. Correctness of the operands arrives with extraction receipts in
    # Wave 2 (spread_accuracy).
    "ratio_reproducibility": 1.0,
    # The operands, not just the arithmetic: a perfectly reproducible ratio over the
    # wrong EBITDA is still the wrong ratio.
    "spread_accuracy": 0.90,
    # Both directions. A tie-out that cries wolf on a clean file gets switched off, and
    # one that never fires was never a control.
    "tie_out_precision": 0.95,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

# The pii_safety leak check MUST use the SAME jurisdiction pattern source as the runtime
# redactor (the shared pii-kit rows), and this gate runs the REAL LocalRegexRedactionAdapter
# rather than a fake. Both matter: a leak then means the pipeline re-introduced PII that
# bypassed redaction, not that a bespoke detector and a bespoke redactor drifted apart and
# happened to agree. Default to the assistant's APAC markets; override with
# CREDIT_MEMO_PII_JURISDICTIONS (comma-separated ISO-3166 codes).
_PII_JURISDICTIONS = tuple(
    j.strip().upper()
    for j in setting_or_default(
        "CREDIT_MEMO_PII_JURISDICTIONS", ",".join(DEFAULT_JURISDICTIONS)
    ).split(",")
    if j.strip()
)
if not _PII_JURISDICTIONS:
    raise SystemExit("CREDIT_MEMO_PII_JURISDICTIONS names no jurisdiction")
# Universal rows first, then the national-id rows for the configured jurisdictions (B2 has no
# account row, so this order carries no subsumption hazard). MUST match the redactor's set.
_PII_PATTERNS: tuple[Pattern, ...] = (
    *UNIVERSAL_PATTERNS,
    *tuple(national_patterns_for(_PII_JURISDICTIONS)),
)

# Obviously-fictional national identifiers, one per market, in their PRINTED form, injected
# into a golden case's borrower name to prove the pack redacts each jurisdiction it claims to
# cover. The JP My Number and AU TFN carry VALID check digits on purpose: their rows are
# checksum-gated, so an invalid fixture would sail through unmasked and prove nothing. These
# are the raw tokens (no "NRIC"/"HKID" prefix) so planted_leak can look for them verbatim.
_PII_BY_JURISDICTION: dict[str, str] = {
    "SG": "S1234567A",
    "HK": "A123456(3)",
    "JP": "1234 5678 9018",
    "AU": "123 456 782",
}

_EVIDENCE_SOURCE_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]*)(?:\s+p\.[^\]]+)?\]")


# --------------------------------------------------------------------------- #
# Golden dataset
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GoldenExample:
    id: str
    borrower_name: str
    sector: str
    jurisdiction: str
    documents: tuple[str, ...]
    evidence: tuple[str, ...]  # passage texts (each becomes a cited FILING passage)
    expected_metrics: dict[str, float]
    expected_covenants: tuple[dict, ...]  # {type, threshold, operator, current_value, status}
    expected_risk_categories: tuple[str, ...]
    pii_in_inputs: bool = False
    #: The confirmed spread the engines compute from: {"periods": [...], "items": [...]}.
    spread: dict = field(default_factory=dict)
    #: {formula_id: {period: expected value}} — what the catalogue must reproduce.
    expected_ratios: dict = field(default_factory=dict)
    #: {line_item_code: {period: expected value}} — the operands, not the arithmetic.
    expected_spread: dict = field(default_factory=dict)
    #: Tie-out checks this case is built to trip. Empty means "this file is clean and
    #: nothing should fire", which is scored just as strictly.
    expected_tie_out: tuple[str, ...] = ()


def load_golden(path: Path) -> list[GoldenExample]:
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        examples.append(
            GoldenExample(
                id=str(obj.get("id", f"example-{lineno}")),
                borrower_name=str(obj["borrower_name"]),
                sector=str(obj.get("sector", "")),
                jurisdiction=str(obj.get("jurisdiction", "")),
                documents=tuple(obj.get("documents", []) or ()),
                evidence=tuple(obj.get("evidence", []) or ()),
                spread=dict(obj.get("spread", {}) or {}),
                expected_ratios=dict(obj.get("expected_ratios", {}) or {}),
                expected_spread=dict(obj.get("expected_spread", {}) or {}),
                expected_tie_out=tuple(obj.get("expected_tie_out", []) or ()),
                expected_metrics=dict(obj.get("expected_metrics", {}) or {}),
                expected_covenants=tuple(obj.get("expected_covenants", []) or ()),
                expected_risk_categories=tuple(obj.get("expected_risk_categories", []) or ()),
                pii_in_inputs=bool(obj.get("pii_in_inputs", False)),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read thresholds from ``eval/rubrics/*.yaml`` when PyYAML is available."""
    thresholds = dict(THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds
    rubric_dir = _REPO_ROOT / "eval" / "rubrics"
    for name in ("groundedness.yaml", "citation_accuracy.yaml"):
        rubric_path = rubric_dir / name
        if not rubric_path.exists():
            continue
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
        for companion, spec in (doc.get("companion_metrics") or {}).items():
            if isinstance(spec, dict) and "threshold" in spec:
                thresholds[str(companion)] = float(spec["threshold"])
    return thresholds


# --------------------------------------------------------------------------- #
# Deterministic fake adapters (inlined: importing tests.conftest is disallowed for the
# gate, and CI must not depend on the test tree). Together they let the real
# CreditMemoService build pipeline run end-to-end with zero external services.
#
# Redaction is deliberately NOT faked: the local adapter is the one the runtime uses, is
# pure regex over the shared pack, and needs no external service, so faking it would only
# have let the gate pass while the real redactor was broken. Everything else is faked
# because it stands in for something that would otherwise need Document AI, a KB, an LLM
# or BigQuery.
# --------------------------------------------------------------------------- #
def _real_redactor() -> LocalRegexRedactionAdapter:
    """The production local redactor, pinned to the gate's jurisdictions."""
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=_PII_JURISDICTIONS)))


class FakeGuardrail:
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        return GuardrailVerdict(
            allowed=True, direction=direction, findings=(), sanitized_text=text, reason="benign"
        )


class FakeExtraction:
    def extract(self, document: Filing, content: bytes, mime_type: str) -> DocumentExtract:
        return DocumentExtract(document_id=document.id, text="", pages=1)


class FakeKnowledgeBase:
    def __init__(self, by_borrower: dict[str, GoldenExample]) -> None:
        self._by_borrower = by_borrower

    def ingest(self, document, content, acl_tags) -> IngestResult:  # type: ignore[no-untyped-def]
        return IngestResult(document_id=document.id, chunks=1, status="indexed", ok=True)

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        example = self._lookup(query)
        passages: list[RetrievedPassage] = []
        for i, text in enumerate(example.evidence if example else ()):
            citation = Citation(
                source_id=f"doc-{example.id}-{i}",
                source_type=SourceType.FILING,
                title=f"Evidence {i} for {example.borrower_name}",
                page=i + 1,
                snippet=text[:120],
                score=round(0.95 - i * 0.05, 3),
            )
            passages.append(
                RetrievedPassage(text=text, citation=citation, score=citation.score or 0)
            )
        return passages

    def _lookup(self, query: RetrievalQuery) -> GoldenExample | None:
        for example in self._by_borrower.values():
            if example.borrower_name in query.text:
                return example
        return None


class FakePeerData:
    def __init__(self, by_borrower: dict[str, GoldenExample]) -> None:
        self._by_borrower = by_borrower

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        # A fixed, fictional peer cohort so peer comps are deterministic.
        base = {"leverage": (2.0, 2.8, 3.2), "ebitda": (18.0, 24.0, 30.0)}.get(metric, ())
        return [
            PeerMetric(peer_name=f"Peer {i} (FICTIONAL)", metric=metric, value=v)
            for i, v in enumerate(base)
        ]


class FakeTracer:
    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        yield

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


_OPERATOR_TO_SCHEMA = {"<=": "<=", "<": "<", ">=": ">=", ">": ">", "==": "=="}


class FakeLLM:
    """Deterministic, grounded synthesis keyed off the case evidence headers.

    The real ``CreditMemoService`` calls ``generate`` with structured-output requests
    whose user content carries the EVIDENCE block of ``[source_id p.N] (...)`` headers.
    This fake plays the model honestly: it cites only the source_ids actually present in
    EVIDENCE, and shapes the memo / covenants / risk flags from the example's expected
    values, so the covenant statuses the service computes match the golden expectations.
    """

    #: When set, the fake fabricates: it cites source ids that were never retrieved and
    #: states figures the spread does not support. Without this the gate scores a model
    #: that never misbehaves, which is a gate that proves nothing about the one that
    #: might. ``make eval-adversarial`` runs with it on and EXPECTS a failure.
    ADVERSARIAL_IDS = ("src-fabricated-annual-report", "src-invented-filing")

    def __init__(self, by_borrower: dict[str, GoldenExample], adversarial: bool = False) -> None:
        self._by_borrower = by_borrower
        self._adversarial = adversarial
        self.model = "gemini-3.5-flash"
        #: Every source id this fake CLAIMED for the example currently being scored,
        #: before the pipeline dropped the ones it did not recognise. The citation metric
        #: scores this rather than what survived. Reset per example by the runner: a
        #: cumulative set would score each case against every other case's ids.
        self.asserted_source_ids: set[str] = set()

    def generate(self, request: LlmRequest) -> LlmResponse:
        user = request.messages[-1].content if request.messages else ""
        source_ids = self._source_ids(user)
        if self._adversarial:
            # Cite two ids that are not in EVIDENCE, and drop one that is. A scorer that
            # still returns 1.0 here is measuring the drop-unknown-ids filter rather than
            # the model.
            source_ids = [*self.ADVERSARIAL_IDS, *source_ids[1:]]
        self.asserted_source_ids.update(source_ids)
        example = self._example_for(user)
        schema = request.response_schema or {}
        props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
        if "summary" in props:
            payload = self._memo_payload(example, source_ids)
        elif "items" in props and self._is_covenant_schema(schema):
            payload = self._covenant_payload(example, source_ids)
        elif "items" in props:
            payload = self._risk_payload(example, source_ids)
        else:
            payload = {"grounded": True, "confidence": 0.9, "caveats": []}
        return LlmResponse(
            text=json.dumps(payload),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=16),
            model=self.model,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        return labels[0] if labels else ""

    @staticmethod
    def _is_covenant_schema(schema: dict) -> bool:
        props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
        items = props.get("items") if isinstance(props.get("items"), dict) else {}
        item_schema = items.get("items", {}) if isinstance(items, dict) else {}
        item_props = (item_schema.get("properties") or {}) if isinstance(item_schema, dict) else {}
        return "threshold" in item_props

    def _memo_payload(self, example: GoldenExample | None, source_ids: list[str]) -> dict:
        metrics = example.expected_metrics if example else {}
        return {
            "summary": (
                "The borrower shows revenue and earnings consistent with the filed "
                "statements, with covenant headroom as documented in the evidence."
            ),
            "financial_metrics": [
                {
                    "name": name,
                    "value": value,
                    "period": "FY2025",
                    "currency": "USD",
                    "used_source_ids": source_ids,
                }
                for name, value in metrics.items()
            ],
            "recommendation_rationale": (
                "The financial analysis and covenant status support continued monitoring; "
                "a credit officer must review before any reliance. This is not a decision."
            ),
            "confidence": 0.9 if source_ids else 0.2,
            "used_source_ids": source_ids,
        }

    def _covenant_payload(self, example: GoldenExample | None, source_ids: list[str]) -> dict:
        covs = example.expected_covenants if example else ()
        items = []
        for cov in covs:
            items.append(
                {
                    "type": cov.get("type", "other"),
                    "description": f"{cov.get('type', 'covenant')} covenant.",
                    "threshold": cov.get("threshold", 0.0),
                    "operator": _OPERATOR_TO_SCHEMA.get(cov.get("operator", ">="), ">="),
                    "current_value": cov.get("current_value"),
                    "period": "Q4",
                    "used_source_ids": source_ids,
                }
            )
        return {"items": items}

    def _risk_payload(self, example: GoldenExample | None, source_ids: list[str]) -> dict:
        cats = example.expected_risk_categories if example else ()
        items = [
            {
                "category": cat,
                "severity": "medium",
                "detail": f"{cat} risk identified in the borrower evidence.",
                "used_source_ids": source_ids,
            }
            for cat in cats
        ]
        return {"items": items}

    def _example_for(self, user: str) -> GoldenExample | None:
        for example in self._by_borrower.values():
            if example.borrower_name in user:
                return example
        return None

    @staticmethod
    def _source_ids(user: str) -> list[str]:
        seen: list[str] = []
        for sid in _EVIDENCE_SOURCE_RE.findall(user):
            if sid not in seen:
                seen.append(sid)
        return seen


# --------------------------------------------------------------------------- #
# Pipeline driver
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Adapters:
    extraction: FakeExtraction
    knowledge_base: FakeKnowledgeBase
    peer_data: FakePeerData
    llm: FakeLLM
    guardrail: FakeGuardrail
    redaction: LocalRegexRedactionAdapter
    tracer: FakeTracer
    audit: FakeAudit


def _build_adapters(examples: list[GoldenExample], adversarial: bool = False) -> _Adapters:
    by_borrower = {ex.borrower_name: ex for ex in examples}
    return _Adapters(
        extraction=FakeExtraction(),
        knowledge_base=FakeKnowledgeBase(by_borrower),
        peer_data=FakePeerData(by_borrower),
        llm=FakeLLM(by_borrower, adversarial=adversarial),
        guardrail=FakeGuardrail(),
        redaction=_real_redactor(),
        tracer=FakeTracer(),
        audit=FakeAudit(),
    )


def _make_service(adapters: _Adapters):  # type: ignore[no-untyped-def]
    from credit_memo.domain.memo_service import CreditMemoService

    return CreditMemoService(
        extraction=adapters.extraction,
        knowledge_base=adapters.knowledge_base,
        peer_data=adapters.peer_data,
        llm=adapters.llm,
        guardrail=adapters.guardrail,
        redaction=adapters.redaction,
        tracer=adapters.tracer,
        audit=adapters.audit,
    )


def _memo_input(example: GoldenExample) -> MemoInput:
    name = example.borrower_name
    if example.pii_in_inputs:
        # Inject obviously-fake PII into the name to prove redaction (pii_safety), using the
        # identifier of the borrower's OWN jurisdiction so every configured pack is actually
        # exercised rather than the gate proving SG four times over. Appended AFTER the name
        # so the fake KB and LLM still match the borrower on its name substring.
        market = example.jurisdiction.upper()
        national_id = _PII_BY_JURISDICTION.get(market)
        if national_id is None:
            # Loud, not silent: a case that claims to carry PII but has no fixture for its
            # jurisdiction would quietly test email-only and look like real coverage.
            raise ValueError(
                f"golden case {example.id!r} sets pii_in_inputs in jurisdiction {market!r}, "
                "which has no fixture in _PII_BY_JURISDICTION. Add one so the case "
                "exercises that jurisdiction's pack."
            )
        if market not in _PII_JURISDICTIONS:
            # Scoring the leak check off the same pack as the redactor is what stops the two
            # drifting apart, but it also means a jurisdiction missing from the config blinds
            # BOTH at once: nothing masks the id, nothing detects it, and the case scores a
            # vacuous 1.0. Refuse to run rather than report that as coverage.
            raise ValueError(
                f"golden case {example.id!r} carries {market} PII but {market} is not in the "
                f"configured pack {_PII_JURISDICTIONS}. The redactor would not mask it and "
                "the leak check would not see it, so the case would score a vacuous 1.0. "
                "Add it to CREDIT_MEMO_PII_JURISDICTIONS or drop pii_in_inputs."
            )
        name = f"{name}, national id {national_id}, contact ops@example.com"
    borrower = Borrower(
        id=example.id, name=name, sector=example.sector, jurisdiction=example.jurisdiction
    )
    documents = tuple(
        Filing(id=f"{example.id}-{d}", acl_tags=(f"borrower:{example.id}",))
        for d in example.documents
    )
    return MemoInput(borrower=borrower, documents=documents, spreads=_spreads(example, borrower.id))


def _spreads(example: GoldenExample, borrower_id: str) -> tuple[FinancialSpread, ...]:
    """The golden case's confirmed spread, as the analyst would have typed it.

    Absent for a case that only exercises prose, which is deliberate: those cases then
    prove the pipeline still builds a memo with no figures to compute from, and their
    covenants fall back to the extracted value.
    """
    raw = example.spread
    if not raw:
        return ()
    periods = tuple(
        Period(
            label=str(p["label"]),
            ends_on=str(p.get("ends_on", "")),
            months=int(p.get("months", 12)),
            audited=bool(p.get("audited", False)),
        )
        for p in raw.get("periods", [])
    )
    items = tuple(
        LineItem(
            code=LineItemCode(str(i["code"])),
            period=str(i["period"]),
            value=float(i["value"]),
            currency=str(i.get("currency", "USD")),
            provenance=Provenance.USER_ENTERED,
        )
        for i in raw.get("items", [])
    )
    return (
        FinancialSpread(
            borrower_id=borrower_id,
            periods=periods,
            items=items,
            currency=str(raw.get("currency", "USD")),
            unit=str(raw.get("unit", "millions")),
            confirmed_by="eval-bot",
        ),
    )


# --------------------------------------------------------------------------- #
# Heuristic scorers
# --------------------------------------------------------------------------- #
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _claim_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) >= 12]


def score_groundedness(memo: CreditMemo) -> float:
    """What fraction of the figures in the prose the bank can actually account for.

    The previous version returned 1.0 if the memo carried ANY citation at all, which is
    a boolean wearing a percentage: a memo whose every number was invented scored the
    same as one where every number was checked, as long as one citation existed
    somewhere. It could not go below 1.0 for a real defect.

    This counts claims. Every figure written with a thousands separator or a decimal in
    the summary and rationale must correspond to something the bank stands behind: a
    computed ratio, a confirmed spread line, or a metric the model cited. A figure
    matching none of those is a number the drafter supplied itself.
    """
    claims = _figures_in(f"{memo.summary}\n{memo.recommendation_rationale}")
    if not claims:
        # No figures asserted is not the same as no evidence. A memo that says only
        # "the evidence does not support a view" is fully grounded and correctly cautious.
        return 1.0 if memo.citations or not _claim_sentences(memo.summary) else 0.0

    supported = {round(abs(r.value), 2) for r in memo.ratios if r.value is not None}
    for spread in memo.spreads:
        supported |= {round(abs(i.value), 2) for i in spread.items}
    supported |= {round(abs(m.value), 2) for m in memo.financial_metrics}
    supported |= {round(abs(c.threshold), 2) for c in memo.covenants}
    supported |= {
        round(abs(c.current_value), 2) for c in memo.covenants if c.current_value is not None
    }

    hits = sum(1 for claim in claims if any(_close_enough(claim, s) for s in supported))
    return round(hits / len(claims), 4)


def score_citation_accuracy(memo: CreditMemo, retrieved_ids: set[str], asserted: set[str]) -> float:
    """What fraction of the ids the MODEL asserted were real.

    ``asserted`` is what the model said before ``citations_for_source_ids`` dropped the
    ones it did not recognise. Scoring the surviving citations instead measured the
    filter: unknown ids are removed on the way through, so the set that reached the memo
    was correct by construction and the metric could not fall. A fabricated citation is
    exactly the failure this number exists to catch, so it has to be counted where it
    still exists.
    """
    if not asserted:
        return 0.0 if _claim_sentences(memo.summary) else 1.0
    return round(len(asserted & retrieved_ids) / len(asserted), 4)


def _figures_in(text: str) -> list[float]:
    """Figures a reader would take as a financial claim.

    Thousands separators and decimals only. Bare integers in prose are years, counts,
    percentages and page numbers far more often than they are spread lines, and counting
    them would make the metric noise.
    """
    out: list[float] = []
    for raw in re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d+\b", text):
        try:
            out.append(round(abs(float(raw.replace(",", ""))), 2))
        except ValueError:
            continue
    return out


def _close_enough(claim: float, supported: float) -> bool:
    """A figure rounded for prose still counts as the figure it was rounded from."""
    scale = max(abs(claim), abs(supported), 1.0)
    return abs(claim - supported) <= scale * 0.01


def score_spread_accuracy(memo: CreditMemo, expected: dict) -> float:
    """Did the confirmed spread carry the line items the golden case says it should?

    Distinct from ratio_reproducibility, which proves the arithmetic is stable. This
    proves the operands are the right ones: a perfectly reproducible ratio over the wrong
    EBITDA is still the wrong ratio.
    """
    if not expected:
        return 1.0
    total = 0
    hits = 0
    for code, per_period in expected.items():
        for period, want in per_period.items():
            total += 1
            for spread in memo.spreads:
                got = next(
                    (i.value for i in spread.items if i.code.value == code and i.period == period),
                    None,
                )
                if got is not None and abs(got - float(want)) <= 1e-9:
                    hits += 1
                    break
    return round(hits / total, 4) if total else 1.0


def score_tie_out_precision(memo: CreditMemo, expected_findings: tuple[str, ...]) -> float:
    """Did the reconciliations fire on the cases that should fail, and stay quiet elsewhere?

    Precision in both directions, because a tie-out that cries wolf gets switched off and
    one that never fires was never a control. A case declaring no expected findings scores
    0.0 if any HIGH or CRITICAL finding appears: a false alarm on a clean file is the
    failure mode that destroys trust in the gutter.
    """
    raised = {f.check.value for f in memo.tie_out}
    wanted = set(expected_findings)
    if not wanted:
        loud = {f.check.value for f in memo.tie_out if f.severity.value in {"high", "critical"}}
        return 0.0 if loud else 1.0
    return round(len(wanted & raised) / len(wanted), 4)


def score_covenant_accuracy(memo: CreditMemo, expected: tuple[dict, ...]) -> float:
    """Computed covenant status must match the expected status per the golden case."""
    if not expected:
        return 1.0
    by_type = {c.type.value: c for c in memo.covenants}
    correct = 0
    for exp in expected:
        cov = by_type.get(str(exp.get("type")))
        if cov is None:
            continue
        want = str(exp.get("status", "")).lower()
        if cov.status is _status_from(want):
            correct += 1
    return round(correct / len(expected), 4)


def _status_from(value: str) -> CovenantStatus:
    return {s.value: s for s in CovenantStatus}.get(value, CovenantStatus.AT_RISK)


def score_ratio_reproducibility(memo: CreditMemo, expected: dict) -> float:
    """Every expected ratio must be present, computed, and equal to the stated figure.

    Three separate ways to score zero, because each is a different failure:

    * the ratio is absent from the memo — the catalogue no longer computes it;
    * it is present but has no value — the spread stopped supporting it;
    * it has a value and the value moved — the formula changed under a signed memo.

    A case with no ``expected_ratios`` scores 1.0 rather than being skipped: it asserts
    that a memo built without a spread still produces one, and does not drag the mean.
    """
    if not expected:
        return 1.0
    by_key = {(r.formula_id, r.period): r for r in memo.ratios}
    hits = 0
    total = 0
    for formula_id, per_period in expected.items():
        for period, want in per_period.items():
            total += 1
            got = by_key.get((formula_id, period))
            if got is None or got.value is None:
                continue
            if abs(got.value - float(want)) <= 1e-9:
                hits += 1
    return hits / total if total else 1.0


def score_pii_safety(memo: CreditMemo, example: GoldenExample, audit_events: list[object]) -> float:
    """1.0 unless unredacted PII survived into the memo or the audit records.

    Scans BOTH the produced memo prose (summary, rationale, covenant descriptions, risk-flag
    details) AND the already-redacted audit prompt/response, two independent ways:

    * ``pack_leak`` uses the SAME pii-kit rows the redactor uses (validator-gated, so a
      filing's ordinary digit runs are not falsely flagged), catching PII the pipeline
      re-introduced after redaction, but blind by construction to the pack being wrong.
    * ``planted_leak`` looks for this case's own planted identifier as a literal, with no pack
      involved. Against the real redactor this is a sound oracle: narrow or break a market's
      row and the redactor stops masking it AND ``pack_leak`` stops detecting it, so only this
      check fails. Without it a broken row scores a vacuous 1.0 with the raw id in the audit.

    A single survivor drops the metric to 0.0, so the gate fails if anything bypassed the
    redact-before-everything boundary (R1, P-04).
    """
    haystacks = [memo.summary, memo.recommendation_rationale]
    haystacks.extend(c.description for c in memo.covenants)
    haystacks.extend(f.detail for f in memo.risk_flags)
    for event in audit_events:
        haystacks.append(str(getattr(event, "redacted_prompt", "")))
        haystacks.append(str(getattr(event, "redacted_response", "")))
    planted = [_PII_BY_JURISDICTION[example.jurisdiction.upper()]] if example.pii_in_inputs else []
    leaked = any(pack_leak(h, _PII_PATTERNS) or planted_leak(h, planted) for h in haystacks)
    return 0.0 if leaked else 1.0


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #
@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(
    dataset: Path, thresholds: dict[str, float], adversarial: bool = False
) -> EvalReport:
    examples = load_golden(dataset)
    adapters = _build_adapters(examples, adversarial=adversarial)
    service = _make_service(adapters)

    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(f"Running offline eval gate over {len(examples)} golden cases (CreditMemoService).\n")
    for example in examples:
        adapters.llm.asserted_source_ids.clear()
        memo = service.build(_memo_input(example), actor="eval-bot")
        retrieved_ids = {
            p.citation.source_id
            for p in adapters.knowledge_base.search(
                RetrievalQuery(
                    text=f"... {example.borrower_name} ...",
                    acl_principals=(f"borrower:{example.id}",),
                )
            )
        }
        agg["groundedness"].scores.append(score_groundedness(memo))
        agg["citation_accuracy"].scores.append(
            score_citation_accuracy(memo, retrieved_ids, adapters.llm.asserted_source_ids)
        )
        agg["covenant_accuracy"].scores.append(
            score_covenant_accuracy(memo, example.expected_covenants)
        )
        agg["pii_safety"].scores.append(score_pii_safety(memo, example, adapters.audit.events))
        agg["ratio_reproducibility"].scores.append(
            score_ratio_reproducibility(memo, example.expected_ratios)
        )
        agg["spread_accuracy"].scores.append(score_spread_accuracy(memo, example.expected_spread))
        agg["tie_out_precision"].scores.append(
            score_tie_out_precision(memo, example.expected_tie_out)
        )

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4) >= thresholds.get(metric, THRESHOLDS[metric]),
        )
        for metric in (
            "groundedness",
            "covenant_accuracy",
            "citation_accuracy",
            "pii_safety",
            "ratio_reproducibility",
            "spread_accuracy",
            "tie_out_precision",
        )
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    """Promotion verdict via EvaluationGatePort (platform = Hrz4, gcp = Gen AI evals).

    Fails closed on the reconciled evaluate + gate result. Refuses to run outside the
    platform/gcp profiles so the offline smoke result is never relabelled a promotion pass.
    """
    from credit_memo.config import Settings, build_container

    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            "CREDIT_MEMO_PROFILE=platform or gcp "
            f"(got {settings.profile!r}); run --mode smoke for the offline pre-merge check."
        )
    container = build_container(settings)
    gate = container.evaluation
    report = gate.evaluate(str(dataset))
    if not isinstance(report, EvalReport):  # pragma: no cover - defensive
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    gate_passed = bool(gate.gate(str(dataset)))
    return report, gate_passed


def main(argv: list[str] | None = None) -> int:
    """Dispatch --mode via the shared eval_main scaffold (fail-closed exit codes).

    ``--use-gcp`` (the pre-split flag for the production evaluator) is kept as an alias
    for ``--mode gate``.
    """
    args = sys.argv[1:] if argv is None else list(argv)

    # --adversarial is handled here rather than by the shared scaffold's parser, and it
    # INVERTS the verdict: the run is expected to fail, so exiting 0 means the gate
    # caught a fabricating model and exiting 1 means it did not notice. A gate that
    # passes a model citing sources that were never retrieved is measuring its own
    # drop-unknown-ids filter, which is how this repo's citation metric read 1.000 for
    # as long as it existed.
    if "--adversarial" in args:
        dataset = DEFAULT_DATASET
        if "--dataset" in args:
            dataset = Path(args[args.index("--dataset") + 1])
        report = run_offline(dataset, load_thresholds_from_rubrics(), adversarial=True)
        print_report(report, "adversarial (fabricating model; a PASS here is the bug)")
        if report.passed:
            print(
                "\nADVERSARIAL RUN PASSED, WHICH IS THE FAILURE. The model cited sources "
                "that were never retrieved and the gate did not notice."
            )
            return 1
        print("\nThe gate refused a fabricating model, which is what it is for.")
        return 0

    if "--use-gcp" in args:
        args = [a for a in args if a != "--use-gcp"] + ["--mode", "gate"]
    return eval_main(
        smoke=lambda dataset: run_offline(dataset, load_thresholds_from_rubrics()),
        gate=run_gate,
        default_dataset=DEFAULT_DATASET,
        description="Offline / platform evaluation gate for B2 (A4 / P-08).",
        smoke_label="offline heuristic (no GCP creds)",
        gate_label="promotion gate (EvaluationGatePort: Hrz4 / Gen AI evals)",
        argv=args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
