"""Prove every eval metric can go RED: a degraded memo must score below its threshold.

A metric that cannot fail proves nothing. Each scorer in ``eval/run_eval.py`` is fed the SAME
credit memo twice: once as the assistant produced it (green) and once carrying exactly the
defect the metric exists to catch (red). The scorers are imported rather than re-implemented,
so a scorer that silently became a constant 1.0 breaks this build.

The covenant proof uses a case with expected covenants, because an empty expectation scores a
vacuous 1.0; the pii_safety proof uses a case carrying a planted identifier.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    DEFAULT_DATASET,
    _build_adapters,
    _make_service,
    _memo_input,
    load_golden,
    load_thresholds_from_rubrics,
    score_citation_accuracy,
    score_covenant_accuracy,
    score_groundedness,
    score_pii_safety,
)

from credit_memo.domain.models import CreditMemo, RetrievalQuery

#: The reviewed bars, read from `eval/rubrics/*.yaml` exactly as the gate reads them. The
#: module-level dict this used to import is gone: a threshold written as a Python literal
#: carries no argument, and having both was two homes for one number.
THRESHOLDS = load_thresholds_from_rubrics()

_GOLDEN = load_golden(DEFAULT_DATASET)
#: A case with covenants to get right, so covenant_accuracy scores something real.
_WITH_COVENANTS = next(e for e in _GOLDEN if e.expected_covenants)
#: A case carrying a planted identifier, so pii_safety has a target to miss.
_WITH_PII = next(e for e in _GOLDEN if e.pii_in_inputs)


def _build(example):  # type: ignore[no-untyped-def]
    """Drive the real assistant over one golden case; return the memo and its adapters."""
    adapters = _build_adapters(_GOLDEN)
    memo = _make_service(adapters).build(_memo_input(example), actor="eval-bot")
    return memo, adapters


@pytest.fixture(scope="module")
def memo_and_sources() -> tuple[CreditMemo, set[str]]:
    memo, adapters = _build(_WITH_COVENANTS)
    retrieved = {
        p.citation.source_id
        for p in adapters.knowledge_base.search(
            RetrievalQuery(
                text=f"... {_WITH_COVENANTS.borrower_name} ...",
                acl_principals=(f"borrower:{_WITH_COVENANTS.id}",),
            )
        )
    }
    assert memo.citations, "the proof needs a memo that actually cites something"
    return memo, retrieved


def test_groundedness_can_go_red(memo_and_sources: tuple[CreditMemo, set[str]]) -> None:
    memo, _ = memo_and_sources
    assert_can_go_red(
        score_groundedness,
        green=memo,
        red=replace(memo, citations=()),  # claims made with nothing behind them
        threshold=THRESHOLDS["groundedness"],
        metric="groundedness",
    )


def test_citation_accuracy_can_go_red(memo_and_sources: tuple[CreditMemo, set[str]]) -> None:
    """The red case is a model CITING something that was never retrieved.

    It used to be an empty retrieved-set, which scored the citations that survived
    ``citations_for_source_ids``. Those are correct by construction: unknown ids are
    dropped on the way through, so the metric was measuring the filter and could not fall
    for the defect it exists to catch. The metric now takes what the model ASSERTED, and
    the red case is a fabricated id among real ones.
    """
    memo, retrieved = memo_and_sources
    assert_can_go_red(
        lambda asserted: score_citation_accuracy(memo, retrieved, asserted),
        green=retrieved,
        red={*retrieved, "src-fabricated-annual-report", "src-invented-filing"},
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_covenant_accuracy_can_go_red(memo_and_sources: tuple[CreditMemo, set[str]]) -> None:
    memo, _ = memo_and_sources
    flipped = tuple(
        {**c, "status": "breached" if c["status"] != "breached" else "compliant"}
        for c in _WITH_COVENANTS.expected_covenants
    )
    assert_can_go_red(
        lambda expected: score_covenant_accuracy(memo, expected),
        green=_WITH_COVENANTS.expected_covenants,
        red=flipped,  # every covenant status is now the opposite of what was computed
        threshold=THRESHOLDS["covenant_accuracy"],
        metric="covenant_accuracy",
    )


def test_pii_safety_can_go_red() -> None:
    """The red case re-introduces a raw identifier into the memo AFTER redaction ran."""
    memo, adapters = _build(_WITH_PII)
    assert_can_go_red(
        lambda m: score_pii_safety(m, _WITH_PII, adapters.audit.events),
        green=memo,
        red=replace(memo, summary=f"{memo.summary} Director NRIC S1234567D on file."),
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )


# --------------------------------------------------------------------------- #
# The five metrics that had no red case anywhere, and the ordering that guards them
# --------------------------------------------------------------------------- #
def test_the_five_strictest_metrics_can_go_red() -> None:
    """Run the SHIPPED proof, the same one the scored run executes before it scores.

    ``ratio_reproducibility``, ``spread_accuracy``, ``tie_out_precision``,
    ``revision_integrity`` and ``research_isolation`` had never been shown able to fail
    anywhere. Four of the five sit at exactly 1.00, which is also the shape a scorer that
    silently became a constant produces, so a green report told a reader nothing about them.
    """
    from eval.run_eval import load_thresholds_from_rubrics, prove_every_metric_can_go_red

    prove_every_metric_can_go_red(load_thresholds_from_rubrics())


def test_the_scored_run_refuses_a_metric_that_became_a_constant() -> None:
    """The ordering IS the guarantee: falsification runs before a single golden score.

    Run only here, a proof says the metric could have gone red in this process. Run as the
    first statement of ``run_offline``, it says the metric about to score this corpus can go
    red, against the thresholds that run just loaded from the rubrics. This test breaks a
    scorer into the constant 1.0 the proof exists to catch and asserts the scored run refuses
    rather than reporting a confident green.
    """
    from agent_eval_kit.harness import NotFalselyGreenError
    from eval import run_eval

    original = run_eval.score_tie_out_precision
    run_eval.score_tie_out_precision = lambda memo, expected: 1.0  # type: ignore[assignment]
    try:
        with pytest.raises(NotFalselyGreenError, match="tie_out_precision: FALSELY GREEN"):
            run_eval.run_offline(DEFAULT_DATASET, run_eval.load_thresholds_from_rubrics())
    finally:
        run_eval.score_tie_out_precision = original  # type: ignore[assignment]


def test_the_scored_run_refuses_a_bar_the_corpus_cannot_express() -> None:
    """The denominator rule, and the same ordering argument.

    Three bars in this repository were arithmetically identical to 1.0 while reading as though
    they had headroom. They now say 1.0; this is what stops the next one being introduced.
    """
    from agent_eval_kit.denominators import DenominatorError
    from eval import run_eval

    thresholds = dict(run_eval.load_thresholds_from_rubrics())
    thresholds["spread_accuracy"] = 0.99  # a bar the twelve line items cannot express
    with pytest.raises(DenominatorError, match="identical to 1.0"):
        run_eval.run_offline(DEFAULT_DATASET, thresholds)


def test_every_scored_metric_has_a_reviewed_bar_and_every_bar_is_scored() -> None:
    """Both directions. The second is the one nobody writes by hand, and the one that rots."""
    from agent_eval_kit import load_rubrics
    from agent_eval_kit.rubrics import RubricError
    from eval.run_eval import RUBRICS, SCORED

    load_rubrics(RUBRICS).assert_covers(SCORED)
    with pytest.raises(RubricError, match="reads as governance"):
        load_rubrics(RUBRICS).assert_covers(SCORED[:-1])
