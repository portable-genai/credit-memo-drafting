"""Span ATTRIBUTES carry structure, never borrower content, and this is the test that sees it.

The conftest ``RecordingTracer`` records span NAMES (``self.spans.append(name)``), which is
the right shape for the tests asserting that the pipeline opened its span, and structurally
blind to the one defect that matters here: it discards ``**attributes``, so a span that
started carrying the borrower's name, the memo narrative or a covenant figure would keep
every existing test green.

A trace backend is not the WORM audit trail. It has no redaction stage, a far wider read
audience and no retention rule written against a regulator's requirement, so a span
attribute is OUTSIDE the boundary that redact-before-everything (R1 / P-04) holds. The
recorder below keeps ``dict(attributes)`` and the content case drives the pipeline with
``PII_MEMO_INPUT``, whose borrower name embeds a planted NRIC and email, so a leak fails on
a planted literal rather than on a subtlety.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from tests.fixtures import sample_cases

_ACTOR = "credit-officer@bank.example"

#: The complete attribute key set a credit-memo span may carry, per span name. Widening one
#: of these is a decision about what leaves the trust boundary, so it is made here
#: deliberately rather than by adding a keyword argument at a call site.
_ALLOWED: dict[str, set[str]] = {
    "credit_memo.build": {"action", "actor"},
}

#: Planted in ``PII_BORROWER``'s name. A content-shaped attribute would carry one of these.
_PLANTED = ("S1234567A", "casey.lim@example.com", "Casey Lim")


class _AttributeRecordingTracer:
    """Keeps (name, attributes) per span, unlike the name-only conftest recorder."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage, model):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture
def tracer() -> _AttributeRecordingTracer:  # type: ignore[override]
    """Override the conftest tracer so ``credit_memo_service`` assembles with THIS recorder."""
    return _AttributeRecordingTracer()


def test_a_memo_build_opens_its_named_span_with_allowlisted_keys_only(
    credit_memo_service, tracer
) -> None:
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=_ACTOR)
    assert [name for name, _ in tracer.spans], "the pipeline opened no span at all"
    for name, attributes in tracer.spans:
        assert name in _ALLOWED, f"unexpected span {name!r}; add it here deliberately"
        assert set(attributes) == _ALLOWED[name], (
            f"span {name!r} attribute keys changed; widening the set is a trust-boundary "
            "decision, so update _ALLOWED here deliberately"
        )


def test_no_span_attribute_carries_the_planted_identifiers(credit_memo_service, tracer) -> None:
    """PII_MEMO_INPUT's borrower embeds an NRIC and an email; neither may reach a span."""
    credit_memo_service.build(sample_cases.PII_MEMO_INPUT, actor=_ACTOR)
    emitted = " ".join(
        str(value) for _, attributes in tracer.spans for value in attributes.values()
    )
    for planted in _PLANTED:
        assert planted not in emitted, f"{planted!r} reached a span attribute"
        assert planted.lower() not in emitted.lower()


def test_every_attribute_value_is_a_string(credit_memo_service, tracer) -> None:
    """The port declares str values; a structured object smuggles content past a grep."""
    credit_memo_service.build(sample_cases.SAMPLE_MEMO_INPUT, actor=_ACTOR)
    for name, attributes in tracer.spans:
        for key, value in attributes.items():
            assert isinstance(value, str), f"span {name!r} attribute {key!r} is not a str"
