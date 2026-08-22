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
    THRESHOLDS,
    _build_adapters,
    _make_service,
    _memo_input,
    load_golden,
    score_citation_accuracy,
    score_covenant_accuracy,
    score_groundedness,
    score_pii_safety,
)

from credit_memo.domain.models import CreditMemo, RetrievalQuery

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
    memo, retrieved = memo_and_sources
    assert_can_go_red(
        lambda ids: score_citation_accuracy(memo, ids),
        green=retrieved,
        red=set(),  # nothing the memo cites was ever actually retrieved
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
