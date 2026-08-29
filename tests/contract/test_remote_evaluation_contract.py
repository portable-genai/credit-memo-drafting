"""Hrz4 wire-contract test for the platform ``RemoteEvaluationAdapter``.

This adapter is the ``platform``-profile implementation of :class:`EvaluationGatePort`: a
thin httpx client to the shared **Hrz4 AI Quality / model-risk** service
(``model-quality-gate``). The service's contract was hardened, and this suite pins
the client to the corrected wire shape so a regression to the old (silently-broken) shape
fails CI:

* ``POST /v1/evaluations`` sends a structured ``target`` object plus a top-level
  ``dataset_id`` that MUST equal ``target.dataset_id`` and a registered ``bundle`` name;
  it must NOT send an explicit ``metrics`` list (Hrz4 now 422s on unknown metrics).
* the response is parsed from ``results[]`` (not the old, always-empty ``metrics[]``), and
  only when it also carries the evidence that lets somebody re-derive the scores later.
* ``gate`` is a ``POST /v1/gate`` (not a ``GET``) carrying the same body, and returns a
  verdict RE-DERIVED from a complete promotion decision rather than the aggregate boolean
  the service reports.

The response fixtures are deliberately full. The hardened ``agent-eval-kit`` client recomputes
every verdict from the evidence and raises on any contradiction, so a body cannot simply
assert a promotion passed: each metric row's ``passed`` has to equal ``score >= threshold``,
the red-team aggregate has to equal the AND of its rows, and the top-level verdict has to
equal (quality AND attested AND red team). The refusal tests at the bottom are as much the
contract as the happy path, because the shape they reject, ``{"passed": true}`` with nothing
behind it, is a promotion certified by nothing.

Runs fully offline: the Hrz4 endpoint is mocked with respx and never actually served. The
localhost default below MUST match ``QUALITY_GATE_URL``'s default in the adapter.
"""

from __future__ import annotations

import json

import pytest
import respx

from credit_memo.adapters.platform.remote_evaluation import (
    RemoteEvaluationAdapter,
    RemoteEvaluationError,
)
from credit_memo.config import Settings, instantiate
from credit_memo.domain.models import EvalReport

CONFIG_PATH = "config/settings.yaml"

# The platform client's localhost default (SPEC contract): mocked, never actually served.
# This MUST match the QUALITY_GATE_URL default hard-coded in remote_evaluation.py.
QUALITY_GATE = "http://localhost:8084"

# A dataset *path*; the adapter derives dataset_id = basename without the ``.jsonl`` suffix.
DATASET_PATH = "eval/datasets/golden_cases.jsonl"
DATASET_ID = "golden_cases"

# The registered bundle Hrz4 resolves the metric set from.
BUNDLE = "doc2-credit-memo"

#: Obviously fictional durable identifiers. Every one is REQUIRED by the hardened parse: a
#: score naming no run, no dataset state and no evaluator cannot be reproduced by anyone
#: reading the promotion record later, so it is a number rather than evidence.
_DIGEST = "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
_EVALUATOR = "hrz4-ai-quality (FICTIONAL)"
_DATASET_VERSION = "golden_cases@2026-08-01"
_MODEL_CARD_REF = "gs://fictional-hrz4-evidence/model-cards/doc2-credit-memo.md"
_MRM_REF = "gs://fictional-hrz4-evidence/mrm/doc2-credit-memo-2026-08.json"

#: Every row is internally CONSISTENT: ``passed`` equals ``score >= threshold``.
MIXED_ROWS = [
    {"metric": "groundedness", "score": 0.94, "threshold": 0.80, "passed": True},
    {"metric": "covenant_accuracy", "score": 0.88, "threshold": 0.90, "passed": False},
]

PASSING_ROWS = [
    {"metric": "groundedness", "score": 0.94, "threshold": 0.80, "passed": True},
    {"metric": "covenant_accuracy", "score": 0.93, "threshold": 0.90, "passed": True},
    {"metric": "citation_accuracy", "score": 0.96, "threshold": 0.90, "passed": True},
    {"metric": "pii_safety", "score": 1.0, "threshold": 0.99, "passed": True},
]

#: Red-team rows: ``passed`` and ``blocked`` must AGREE (an attack that was not blocked did
#: not pass), and the aggregate must equal the AND of the rows.
REDTEAM_PASSING = {
    "passed": True,
    "results": [
        {"case": "prompt-injection-01", "passed": True, "blocked": True},
        {"case": "pii-exfil-01", "passed": True, "blocked": True},
    ],
}


def _eval_body(*, run_id: str, results: list[dict], attested: bool = True) -> dict:
    """A complete evaluation response in the hardened shape.

    ``passed`` is deliberately absent: the client derives the aggregate from the rows, and a
    value that disagrees with them is a hard error rather than an override.
    """
    return {
        "results": results,
        "n_examples": 24,
        "run_id": run_id,
        "dataset_version": _DATASET_VERSION,
        "dataset_digest": _DIGEST,
        "evaluator": _EVALUATOR,
        "schema_version": "v1",
        "artifact_refs": [f"gs://fictional-hrz4-evidence/{run_id}/report.json"],
        "attested": attested,
    }


def _gate_body(*, passed: bool, rows: list[dict], attested: bool = True) -> dict:
    """The full promotion decision, at every layer the client re-derives."""
    return {
        "passed": passed,
        "eval_report": _eval_body(run_id="run-fictional-0001", results=rows, attested=attested),
        "redteam_report": REDTEAM_PASSING,
        "model_card_ref": _MODEL_CARD_REF,
        "mrm_evidence_ref": _MRM_REF,
    }


def _adapter() -> RemoteEvaluationAdapter:
    """Build the adapter through its real settings binding, as the container would."""
    settings = Settings.load(CONFIG_PATH)
    adapter = instantiate(settings.adapters["evaluation"]["platform"], settings)
    assert isinstance(adapter, RemoteEvaluationAdapter)
    return adapter


def test_evaluate_sends_structured_target_and_matching_dataset_id():
    adapter = _adapter()
    expected_model = Settings.load(CONFIG_PATH).models.reasoning

    with respx.mock:
        route = respx.post(f"{QUALITY_GATE}/v1/evaluations").respond(
            json=_eval_body(run_id="run-fictional-0002", results=MIXED_ROWS),
        )
        report = adapter.evaluate(DATASET_PATH)
        body = json.loads(route.calls.last.request.content)

    # A structured target object (not a bare string) is sent.
    target = body["target"]
    assert isinstance(target, dict)
    assert target["model"] == expected_model
    assert target["dataset_id"] == DATASET_ID
    assert set(target) == {"model", "prompt_version", "dataset_id", "system"}

    # Top-level dataset_id equals target.dataset_id (Hrz4 422s on divergence).
    assert body["dataset_id"] == DATASET_ID == target["dataset_id"]

    # The registered bundle name is sent...
    assert body["bundle"] == BUNDLE
    # ...and NO explicit metrics list (would risk sending an unregistered metric name).
    assert "metrics" not in body

    # The response's results[] land in the EvalReport (the old code read the wrong key).
    assert isinstance(report, EvalReport)
    assert report.dataset == DATASET_PATH
    scored = {r.metric: r for r in report.results}
    assert scored["groundedness"].score == 0.94
    assert scored["groundedness"].passed is True
    assert scored["covenant_accuracy"].threshold == 0.90
    assert scored["covenant_accuracy"].passed is False
    assert report.n_examples == 24
    assert report.passed is False  # one metric failed


def test_evaluate_carries_the_attested_evidence_through_the_adapter():
    """The evidence the client validated must SURVIVE the adapter, not be re-typed away.

    An adapter rebuilding a local ``EvalReport`` from three fields of the client's report,
    which silently discarded the run id, dataset version and digest, evaluator, schema version,
    artifact refs and the ``attested`` flag: the promotion record kept the number and threw away
    everything that made it reproducible. The rebuild is gone and the domain re-exports the
    commons type, so the client's report is returned unaltered. These assertions are what would
    go red if anyone reintroduced the mapper.
    """
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/evaluations").respond(
            json=_eval_body(run_id="run-fictional-0004", results=PASSING_ROWS),
        )
        report = adapter.evaluate(DATASET_PATH)

    assert report.run_id == "run-fictional-0004"
    assert report.dataset_version == _DATASET_VERSION
    assert report.dataset_digest == _DIGEST
    assert report.evaluator == _EVALUATOR
    assert report.schema_version == "v1"
    assert report.artifact_refs == ("gs://fictional-hrz4-evidence/run-fictional-0004/report.json",)
    assert report.attested is True
    assert report.dataset == DATASET_PATH
    assert report.passed is True


def test_evaluate_REFUSES_scores_with_no_durable_run_identity():
    """Metric rows on their own are numbers, not promotion evidence.

    The client enforces the durable identifiers on the plain evaluations path too, not
    only inside ``gate()``. Without a run id, a dataset digest, an evaluator and an artifact
    ref, nobody can later reproduce the score or say which corpus produced it.
    """
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/evaluations").respond(
            json={"results": PASSING_ROWS, "n_examples": 24}
        )
        with pytest.raises(RemoteEvaluationError):
            adapter.evaluate(DATASET_PATH)


def test_evaluate_REFUSES_a_row_whose_verdict_contradicts_its_score():
    """A row claiming PASS below its own bar is the failure a trusted flag always hides."""
    adapter = _adapter()
    rows = [{"metric": "covenant_accuracy", "score": 0.41, "threshold": 0.90, "passed": True}]
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/evaluations").respond(
            json=_eval_body(run_id="run-fictional-0003", results=rows)
        )
        with pytest.raises(RemoteEvaluationError):
            adapter.evaluate(DATASET_PATH)


def test_gate_posts_to_v1_gate_and_returns_true_on_a_full_decision():
    adapter = _adapter()

    with respx.mock:
        route = respx.post(f"{QUALITY_GATE}/v1/gate").respond(
            json=_gate_body(passed=True, rows=PASSING_ROWS)
        )
        result = adapter.gate(DATASET_PATH)
        request = route.calls.last.request
        body = json.loads(request.content)

    assert request.method == "POST"
    assert result is True
    # The gate carries the same structured-target + matching-dataset_id + bundle body.
    assert body["target"]["dataset_id"] == body["dataset_id"] == DATASET_ID
    assert body["bundle"] == BUNDLE
    assert "metrics" not in body


def test_gate_returns_false_through_evidence_that_actually_failed():
    """A FAIL has to be reached the honest way: a metric that genuinely missed its bar.

    A body claiming ``passed: false`` over evidence where everything passed is a
    contradiction and raises, so this fixture fails the covenant-accuracy row instead.
    """
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/gate").respond(
            json=_gate_body(passed=False, rows=MIXED_ROWS)
        )
        assert adapter.gate(DATASET_PATH) is False


def test_gate_REFUSES_a_naked_boolean_with_no_evidence():
    """The shape this file used to accept: a verdict with nothing behind it.

    An upstream that answers ``{"passed": true}`` for every target is indistinguishable from
    one that evaluated nothing at all, so the refusal is the contract, not an inconvenience.
    """
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/gate").respond(json={"passed": True})
        with pytest.raises(RemoteEvaluationError):
            adapter.gate(DATASET_PATH)


def test_gate_REFUSES_an_unattested_report_even_when_every_metric_passes():
    """Unattested scores are a draft run, not sign-off, however good the numbers look."""
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/gate").respond(
            json=_gate_body(passed=True, rows=PASSING_ROWS, attested=False)
        )
        with pytest.raises(RemoteEvaluationError):
            adapter.gate(DATASET_PATH)


def test_gate_REFUSES_a_redteam_aggregate_that_contradicts_its_rows():
    """A red-team summary reporting PASS over a case that was not blocked is a rubber stamp."""
    adapter = _adapter()
    body = _gate_body(passed=True, rows=PASSING_ROWS)
    body["redteam_report"] = {
        "passed": True,
        "results": [
            {"case": "prompt-injection-01", "passed": True, "blocked": True},
            {"case": "pii-exfil-01", "passed": False, "blocked": False},
        ],
    }
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/gate").respond(json=body)
        with pytest.raises(RemoteEvaluationError):
            adapter.gate(DATASET_PATH)


def test_gate_REFUSES_a_decision_with_no_mrm_evidence_reference():
    """Model-risk sign-off has to point at something durable, or it points at nothing."""
    adapter = _adapter()
    body = _gate_body(passed=True, rows=PASSING_ROWS)
    body["mrm_evidence_ref"] = ""
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/gate").respond(json=body)
        with pytest.raises(RemoteEvaluationError):
            adapter.gate(DATASET_PATH)


def test_non_2xx_raises_remote_evaluation_error():
    adapter = _adapter()
    with respx.mock:
        respx.post(f"{QUALITY_GATE}/v1/evaluations").respond(422, json={"detail": "dataset_id"})
        with pytest.raises(RemoteEvaluationError):
            adapter.evaluate(DATASET_PATH)
