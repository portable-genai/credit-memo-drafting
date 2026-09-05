"""The versioned catalogue of credit ratios the engine may compute.

Every ratio a memo states is defined here, once, declaratively, with a version in its
id. Three things follow from that, and all three are the reason this is a data table
rather than a handful of functions:

* **A reader can see the formula.** ``definition`` is the line the ratio panel prints
  under the number, so "leverage 2.5x" is never asserted without "total debt / EBITDA"
  beside it and the two operands it used.
* **A change of definition is a change of id.** Banks disagree about DSCR. When an
  adopter redefines it, they add ``dscr.v2`` rather than editing ``dscr.v1``, so an old
  memo keeps replaying to the number it originally showed.
* **The model cannot pick the formula.** :data:`COVENANT_FORMULA` maps a covenant type
  to the ratio that measures it as a policy table. The LLM extracts a covenant's
  *terms*; which arithmetic tests them is decided here.

Pure standard library, no ports, no I/O.
"""

from __future__ import annotations

from .models import (
    CovenantType,
    FormulaTerm,
    LineItemCode,
    RatioFormula,
)

_C = LineItemCode


def _t(code: LineItemCode, coefficient: float = 1.0) -> FormulaTerm:
    return FormulaTerm(code=code, coefficient=coefficient)


#: The shipped formulas. ``higher_is_better`` is what lets the UI colour a delta without
#: each component re-deciding whether more leverage is good news (it is not).
FORMULAS: tuple[RatioFormula, ...] = (
    RatioFormula(
        id="leverage.v1",
        name="Leverage",
        numerator=(_t(_C.TOTAL_DEBT),),
        denominator=(_t(_C.EBITDA),),
        higher_is_better=False,
        unit="x",
        definition="total debt / EBITDA",
    ),
    RatioFormula(
        id="dscr.v1",
        name="Debt-service coverage",
        numerator=(_t(_C.EBITDA), _t(_C.CAPEX, -1.0), _t(_C.TAX_EXPENSE, -1.0)),
        denominator=(_t(_C.SCHEDULED_DEBT_SERVICE),),
        higher_is_better=True,
        unit="x",
        definition="(EBITDA - capex - tax) / scheduled debt service",
    ),
    RatioFormula(
        id="interest_cover.v1",
        name="Interest cover",
        numerator=(_t(_C.EBITDA),),
        denominator=(_t(_C.INTEREST_EXPENSE),),
        higher_is_better=True,
        unit="x",
        definition="EBITDA / interest expense",
    ),
    RatioFormula(
        id="current_ratio.v1",
        name="Current ratio",
        numerator=(_t(_C.CURRENT_ASSETS),),
        denominator=(_t(_C.CURRENT_LIABILITIES),),
        higher_is_better=True,
        unit="x",
        definition="current assets / current liabilities",
    ),
    RatioFormula(
        id="quick_ratio.v1",
        name="Quick ratio",
        numerator=(_t(_C.CURRENT_ASSETS), _t(_C.INVENTORY, -1.0)),
        denominator=(_t(_C.CURRENT_LIABILITIES),),
        higher_is_better=True,
        unit="x",
        definition="(current assets - inventory) / current liabilities",
    ),
    RatioFormula(
        id="tangible_net_worth.v1",
        name="Tangible net worth",
        numerator=(_t(_C.TOTAL_EQUITY), _t(_C.INTANGIBLE_ASSETS, -1.0)),
        denominator=(),
        higher_is_better=True,
        unit="currency",
        definition="total equity - intangible assets",
    ),
    RatioFormula(
        id="fccr.v1",
        name="Fixed-charge coverage",
        numerator=(_t(_C.EBITDA), _t(_C.LEASE_EXPENSE, -1.0)),
        denominator=(
            _t(_C.INTEREST_EXPENSE),
            _t(_C.SCHEDULED_DEBT_SERVICE),
            _t(_C.LEASE_EXPENSE),
        ),
        higher_is_better=True,
        unit="x",
        definition="(EBITDA - lease expense) / (interest + scheduled debt service + lease expense)",
    ),
    RatioFormula(
        id="gearing.v1",
        name="Gearing",
        numerator=(_t(_C.TOTAL_DEBT),),
        denominator=(_t(_C.TOTAL_EQUITY),),
        higher_is_better=False,
        unit="x",
        definition="total debt / total equity",
    ),
    RatioFormula(
        id="ebitda_margin.v1",
        name="EBITDA margin",
        numerator=(_t(_C.EBITDA),),
        denominator=(_t(_C.REVENUE),),
        higher_is_better=True,
        unit="ratio",
        definition="EBITDA / revenue",
    ),
)

_BY_ID: dict[str, RatioFormula] = {f.id: f for f in FORMULAS}

#: Which formula measures which covenant. A policy table, deliberately separate from the
#: formulas themselves: an adopter who redefines DSCR points this at ``dscr.v2`` without
#: touching the catalogue, and a covenant type absent here is simply not measured by the
#: engine (its LLM-extracted value is shown, unmeasured, rather than silently trusted).
COVENANT_FORMULA: dict[CovenantType, str] = {
    CovenantType.LEVERAGE: "leverage.v1",
    CovenantType.DSCR: "dscr.v1",
    CovenantType.INTEREST_COVER: "interest_cover.v1",
    CovenantType.CURRENT_RATIO: "current_ratio.v1",
    CovenantType.TANGIBLE_NET_WORTH: "tangible_net_worth.v1",
}


def formula(formula_id: str) -> RatioFormula | None:
    """The formula with this id, or None. Ids are versioned, so a miss is a real miss."""
    return _BY_ID.get(formula_id)


def formula_for_covenant(covenant_type: CovenantType) -> RatioFormula | None:
    """The formula that measures this covenant type, per the policy table above."""
    formula_id = COVENANT_FORMULA.get(covenant_type)
    return _BY_ID.get(formula_id) if formula_id else None


def catalogue_version() -> str:
    """A stable digest of the shipped catalogue, for the memo's lineage line.

    Sorted ids and definitions rather than a hash of this file, so reordering the tuple
    or editing a docstring does not invalidate every stored memo's lineage, while a
    changed definition does.
    """
    import hashlib

    payload = "\n".join(f"{f.id}={f.definition}" for f in sorted(FORMULAS, key=lambda f: f.id))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
