"""What each kind of memo is made of, and what it needs before it can be written.

A credit memo is not one document. A renewal re-underwrites an existing facility and
leads with what changed; an annual review confirms a grade against unchanged terms; a
pre-screen answers "is this bankable" from a thin package in under a minute; a decline
has to give specific reasons rather than a narrative. Writing all four from one template
produces a document that is slightly wrong for each.

Two things live here, and both are data rather than logic:

* **The section order.** What a reader of THIS kind expects to find, in the order they
  expect it. A renewal that opens with a borrower history the reader already knows has
  buried its own point.
* **The required inputs.** Which document kinds this memo cannot honestly be written
  without. That list is what produces the missing-documents checklist at intake, which is
  the difference between finding out at the start and finding out at the committee.

Loan type layers on top: an investor-CRE memo needs a rent roll whatever kind it is, and
a C&I working-capital line needs an aging. The two lists are merged rather than one
overriding the other.

Pure standard library. No ports, no I/O, no model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DocType, LoanType, MemoKind

_D = DocType


@dataclass(frozen=True, slots=True)
class MemoTemplate:
    """The shape of one kind of memo."""

    kind: MemoKind
    title: str
    #: What a reader of this kind expects, in the order they expect it.
    sections: tuple[str, ...]
    #: Documents this memo cannot honestly be written without.
    required: tuple[DocType, ...] = ()
    #: Documents that materially improve it. Their absence is worth saying, not blocking.
    recommended: tuple[DocType, ...] = ()
    #: One line telling the analyst what this kind is for, shown beside the picker.
    purpose: str = ""
    #: Whether this kind proposes a rating. A pre-screen deliberately does not: grading a
    #: borrower from a two-document package would put a number in front of a committee
    #: that the package cannot support.
    proposes_rating: bool = True


_TEMPLATES: dict[MemoKind, MemoTemplate] = {
    MemoKind.NEW_FACILITY: MemoTemplate(
        kind=MemoKind.NEW_FACILITY,
        title="New facility",
        purpose="New money: the full assessment, leading with the ask.",
        sections=(
            "The request",
            "Borrower and ownership",
            "Transaction structure and sources and uses",
            "Financial analysis",
            "Repayment capacity",
            "Collateral and support",
            "Risks and mitigants",
            "Policy exceptions",
            "Risk rating",
            "Recommendation and conditions",
        ),
        required=(_D.FINANCIAL_STATEMENT, _D.DEBT_SCHEDULE),
        recommended=(_D.LOAN_AGREEMENT, _D.TAX_RETURN, _D.POLICY_PACK, _D.VALUATION),
    ),
    MemoKind.RENEWAL: MemoTemplate(
        kind=MemoKind.RENEWAL,
        title="Renewal",
        purpose="Re-underwrite a maturing facility, leading with what changed.",
        sections=(
            "What changed since the last review",
            "The request",
            "Financial analysis",
            "Covenant compliance history",
            "Risks and mitigants",
            "Policy exceptions",
            "Risk rating",
            "Recommendation and conditions",
        ),
        # The prior memo is required, not recommended: without it this is a new-facility
        # memo wearing a renewal's title, and "what changed" is unanswerable.
        required=(_D.FINANCIAL_STATEMENT, _D.PRIOR_MEMO),
        recommended=(_D.COVENANT_CERTIFICATE, _D.DEBT_SCHEDULE, _D.POLICY_PACK),
    ),
    MemoKind.ANNUAL_REVIEW: MemoTemplate(
        kind=MemoKind.ANNUAL_REVIEW,
        title="Annual review",
        purpose="Confirm the grade and the terms against a year of performance.",
        sections=(
            "Summary and rating recommendation",
            "Performance against the last review",
            "Financial analysis",
            "Covenant compliance",
            "Risks and mitigants",
            "Policy exceptions outstanding",
            "Risk rating",
            "Actions",
        ),
        required=(_D.FINANCIAL_STATEMENT, _D.COVENANT_CERTIFICATE),
        recommended=(_D.PRIOR_MEMO, _D.RM_NOTE, _D.POLICY_PACK),
    ),
    MemoKind.INTERIM_REVIEW: MemoTemplate(
        kind=MemoKind.INTERIM_REVIEW,
        title="Interim review",
        purpose="Event-driven: a breach, a late certificate, an adverse development.",
        sections=(
            "The trigger",
            "What it means for repayment",
            "Financial position",
            "Covenant status",
            "Risks and mitigants",
            "Recommended action",
        ),
        # Deliberately light. An interim review is written because something happened, and
        # demanding a full pack before it can be written is how a bank learns about a
        # problem late.
        required=(),
        recommended=(_D.MANAGEMENT_ACCOUNTS, _D.COVENANT_CERTIFICATE, _D.RM_NOTE),
    ),
    MemoKind.RATING_ACTION: MemoTemplate(
        kind=MemoKind.RATING_ACTION,
        title="Rating action",
        purpose="Upgrade, downgrade or watchlist, with the drivers that moved.",
        sections=(
            "Proposed action",
            "Drivers",
            "Financial analysis",
            "What would reverse this",
            "Risk rating",
        ),
        required=(_D.FINANCIAL_STATEMENT,),
        recommended=(_D.PRIOR_MEMO, _D.POLICY_PACK, _D.COVENANT_CERTIFICATE),
    ),
    MemoKind.PRE_SCREEN: MemoTemplate(
        kind=MemoKind.PRE_SCREEN,
        title="Pre-screen",
        purpose="Is this bankable? Policy knockouts from a thin package, in under a minute.",
        sections=(
            "Bankability",
            "Policy knockouts",
            "What is missing before this can be worked up",
        ),
        # Nothing is required. The whole point is to answer from what the RM has in hand,
        # and a pre-screen that demands a full credit file is a pre-screen nobody runs.
        required=(),
        recommended=(_D.FINANCIAL_STATEMENT, _D.POLICY_PACK),
        # A grade from a two-document package would put a number in front of a committee
        # that the package cannot support.
        proposes_rating=False,
    ),
    MemoKind.DECLINE: MemoTemplate(
        kind=MemoKind.DECLINE,
        title="Decline",
        purpose="Structured reasons tied to the rules the request failed, not a narrative.",
        sections=(
            "The request",
            "Reasons",
            "Policy exceptions",
            "What would change the answer",
        ),
        required=(_D.FINANCIAL_STATEMENT,),
        recommended=(_D.POLICY_PACK,),
        proposes_rating=False,
    ),
}

#: Documents a loan type needs whatever kind of memo is being written. Merged with the
#: kind's own list rather than replacing it.
_BY_LOAN_TYPE: dict[LoanType, tuple[DocType, ...]] = {
    LoanType.CI_TERM: (_D.DEBT_SCHEDULE,),
    LoanType.SME: (_D.BANK_STATEMENT, _D.TAX_RETURN),
    LoanType.CRE_INVESTOR: (_D.RENT_ROLL, _D.OPERATING_STATEMENT),
    LoanType.SPONSOR_BACKED: (_D.PROJECTIONS, _D.DEBT_SCHEDULE),
}

_RECOMMENDED_BY_LOAN_TYPE: dict[LoanType, tuple[DocType, ...]] = {
    LoanType.CI_TERM: (_D.AR_AP_AGING, _D.BORROWING_BASE_CERTIFICATE),
    LoanType.SME: (_D.MANAGEMENT_ACCOUNTS,),
    LoanType.CRE_INVESTOR: (_D.VALUATION,),
    LoanType.SPONSOR_BACKED: (_D.PRIOR_MEMO,),
}


def template_for(kind: MemoKind) -> MemoTemplate:
    """The template for this kind, falling back to a new-facility memo."""
    return _TEMPLATES.get(kind, _TEMPLATES[MemoKind.NEW_FACILITY])


def required_documents(kind: MemoKind, loan_type: LoanType) -> tuple[DocType, ...]:
    """What this memo cannot honestly be written without, kind and loan type together."""
    template = template_for(kind)
    return tuple(dict.fromkeys((*template.required, *_BY_LOAN_TYPE.get(loan_type, ()))))


def recommended_documents(kind: MemoKind, loan_type: LoanType) -> tuple[DocType, ...]:
    """What would materially improve it. Absent is worth saying, not blocking."""
    template = template_for(kind)
    required = set(required_documents(kind, loan_type))
    return tuple(
        doc
        for doc in dict.fromkeys(
            (*template.recommended, *_RECOMMENDED_BY_LOAN_TYPE.get(loan_type, ()))
        )
        if doc not in required
    )


def all_templates() -> tuple[MemoTemplate, ...]:
    """Every kind, in the order the picker should offer them."""
    return tuple(_TEMPLATES[kind] for kind in MemoKind)
