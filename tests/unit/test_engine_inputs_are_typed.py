"""The deterministic-engine boundary, enforced by type and by AST rather than by review.

The repo's covenant test was deterministic while both of its operands were model
output, which is a comparison you can replay and a conclusion you cannot trust. Wave 0
made provenance a type so that the refusal happens at construction; these tests are what
stop the refusal being quietly widened later.

Three independent guards, because each catches a different way of losing the boundary:

1. **Construction.** A spread cannot hold an unconfirmed extraction; a ``Ratio`` cannot
   be anything but computed. Someone would have to edit the model to break this.
2. **Signature.** No deterministic service may take an LLM- or web-sourced type as an
   argument. Someone would have to edit this list to break it, which is the point.
3. **Shape.** ``WebEvidence``-style context types carry no numeric field, so there is no
   number on them for an engine to reach for even by accident.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from credit_memo.domain import ratio_catalogue as catalogue
from credit_memo.domain.covenant_service import CovenantService
from credit_memo.domain.models import (
    ENGINE_READABLE,
    CovenantType,
    FinancialSpread,
    LineItem,
    LineItemCode,
    Period,
    Provenance,
    Ratio,
)
from credit_memo.domain.ratio_service import RatioService

DOMAIN = Path(__file__).resolve().parents[2] / "src" / "credit_memo" / "domain"

#: Types whose values originate outside the bank's own arithmetic. A deterministic
#: service that names one of these in its signature has, by definition, opened a route
#: for a model-asserted number to reach a calculation.
UNTRUSTED_TYPES = frozenset(
    {
        "LlmResponse",
        "LlmRequest",
        "MemoDraft",
        "SpreadCandidate",
        "MarketContext",
        "WebEvidence",
        "WebCitation",
    }
)

#: The services that must compute rather than narrate. Adding a module here is how a new
#: engine joins the guarantee; removing one needs a reason in the commit message.
DETERMINISTIC_SERVICES = (
    "ratio_service.py",
    "peer_comp_service.py",
    "review_policy.py",
    "entitlements.py",
)


def _spread(provenance: Provenance) -> FinancialSpread:
    return FinancialSpread(
        borrower_id="borr-test",
        periods=(Period(label="FY2025"),),
        items=(
            LineItem(
                code=LineItemCode.TOTAL_DEBT,
                period="FY2025",
                value=250.0,
                provenance=provenance,
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# 1. Construction refuses what an engine may not read
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "provenance",
    [Provenance.EXTRACTED, Provenance.MODEL_DRAFTED, Provenance.WEB_GROUNDED, Provenance.VENDOR],
)
def test_spread_refuses_a_line_item_no_person_confirmed(provenance: Provenance) -> None:
    """An extraction nobody reviewed must not reach the ratio engine as an operand."""
    with pytest.raises(ValueError, match="engine may read"):
        _spread(provenance)


@pytest.mark.parametrize("provenance", sorted(ENGINE_READABLE, key=lambda p: p.value))
def test_spread_accepts_every_engine_readable_provenance(provenance: Provenance) -> None:
    assert _spread(provenance).value(LineItemCode.TOTAL_DEBT, "FY2025") == 250.0


@pytest.mark.parametrize(
    "provenance",
    [
        Provenance.EXTRACTED,
        Provenance.USER_ENTERED,
        Provenance.CONFIRMED,
        Provenance.MODEL_DRAFTED,
        Provenance.WEB_GROUNDED,
    ],
)
def test_a_ratio_is_constructible_only_as_computed(provenance: Provenance) -> None:
    """The memo's ratios are a claim that the bank calculated them. Nothing else."""
    with pytest.raises(ValueError, match="by definition computed"):
        Ratio(
            formula_id="leverage.v1",
            name="Leverage",
            period="FY2025",
            value=2.5,
            provenance=provenance,
        )


def test_a_missing_ratio_must_say_which_input_was_absent() -> None:
    """ "Not computable" without a reason is indistinguishable from "we forgot"."""
    with pytest.raises(ValueError, match="which input was missing"):
        Ratio(formula_id="leverage.v1", name="Leverage", period="FY2025", value=None)


# --------------------------------------------------------------------------- #
# 2. No deterministic service takes an untrusted type
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("filename", DETERMINISTIC_SERVICES)
def test_no_deterministic_service_signature_names_an_untrusted_type(filename: str) -> None:
    module = ast.parse((DOMAIN / filename).read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        annotations = [a.annotation for a in node.args.args if a.annotation is not None]
        annotations += [a.annotation for a in node.args.kwonlyargs if a.annotation is not None]
        if node.returns is not None:
            annotations.append(node.returns)
        for annotation in annotations:
            rendered = ast.unparse(annotation)
            offences += [
                f"{filename}:{node.name} -> {rendered}"
                for name in UNTRUSTED_TYPES
                if name in rendered
            ]
    assert not offences, (
        "a deterministic service must not accept or return a model- or web-sourced "
        f"type: {offences}"
    )


def test_the_ratio_engine_holds_no_ports() -> None:
    """No ports means no I/O means the same spread replays to the same number.

    The engine declares no constructor of its own, so there is nowhere to put a
    collaborator. A future ``__init__`` that took one would fail here.
    """
    own_init = RatioService.__dict__.get("__init__")
    if own_init is not None:
        assert list(inspect.signature(own_init).parameters) == ["self"], (
            "RatioService must take no collaborators: a ratio engine that can call "
            "something is a ratio engine whose output depends on when you ran it"
        )


# --------------------------------------------------------------------------- #
# 3. The covenant test runs on the computed value, and says so
# --------------------------------------------------------------------------- #
def test_covenant_prefers_the_computed_value_over_the_extracted_one() -> None:
    """The regression this whole wave exists to prevent.

    The model reports leverage of 1.0 (comfortably inside a 3.0 cap). The confirmed
    spread says debt is 400 against EBITDA of 100, which is 4.0 and a breach. The test
    must run on the engine's number.
    """
    spread = FinancialSpread(
        borrower_id="borr-test",
        periods=(Period(label="FY2025"),),
        items=(
            LineItem(code=LineItemCode.TOTAL_DEBT, period="FY2025", value=400.0),
            LineItem(code=LineItemCode.EBITDA, period="FY2025", value=100.0),
        ),
    )
    service = CovenantService(llm=None, tracer=None)
    covenants = service._build_covenants(
        [
            {
                "type": "leverage",
                "description": "Net debt / EBITDA not to exceed 3.0x",
                "threshold": 3.0,
                "operator": "<=",
                "current_value": 1.0,  # the model's figure, and it is wrong
                "period": "FY2025",
            }
        ],
        passages=[],
        spread=spread,
    )

    (covenant,) = covenants
    assert covenant.current_value == pytest.approx(4.0)
    assert covenant.reported_value == pytest.approx(1.0)
    assert covenant.value_provenance is Provenance.COMPUTED
    assert covenant.status.value == "breach"
    assert covenant.measured is not None
    assert covenant.measured.formula_id == "leverage.v1"


def test_covenant_falls_back_to_the_extracted_value_and_labels_it() -> None:
    """With no spread the old behaviour stands, but the reader is told which it is."""
    service = CovenantService(llm=None, tracer=None)
    (covenant,) = service._build_covenants(
        [
            {
                "type": "leverage",
                "description": "Net debt / EBITDA not to exceed 3.0x",
                "threshold": 3.0,
                "operator": "<=",
                "current_value": 1.0,
                "period": "FY2025",
            }
        ],
        passages=[],
        spread=None,
    )
    assert covenant.current_value == pytest.approx(1.0)
    assert covenant.value_provenance is Provenance.EXTRACTED
    assert covenant.measured is None


def test_every_covenant_type_the_policy_table_maps_resolves_to_a_real_formula() -> None:
    """A policy table pointing at a formula id that does not exist measures nothing."""
    for covenant_type, formula_id in catalogue.COVENANT_FORMULA.items():
        assert isinstance(covenant_type, CovenantType)
        assert catalogue.formula(formula_id) is not None, formula_id
