"""Every console locator the demo uses, in one place.

The console carries almost no stable ``data-*`` hooks (unlike the presenter server on
:8094, which was built for exactly this). So the demo locates controls the way a person
does — by their visible label and their role — and keeps every one of those reads here, so
a UI rename is one edit rather than a hunt through fifteen acts.
"""

from __future__ import annotations

from typing import Any

# --- the borrower form -------------------------------------------------- #
BORROWER = "Borrower"
SECTOR = "Sector"
JURISDICTION = "Jurisdiction"
PERSONA = "Persona (local profile only)"
DOCUMENTS_INPUT = "Documents for this analysis"

# --- buttons ------------------------------------------------------------- #
EXTRACT = "Extract from the documents"
CONFIRM = "Confirm these figures"
DISCARD = "Discard and type them myself"
BUILD = "Build credit memo"
ADD_TO_GROUP = "Add to the group"
SUGGEST_FROM_REGISTER = "Suggest from the register"

#: How the spread review names each line, mirroring ``LABELS`` in
#: ``ui/components/SpreadReview.tsx``. The review's aria-labels are built from these, so a
#: demo that guessed "Capex" would look for a control the console never renders.
SPREAD_LINE_LABELS = {
    "revenue": "Revenue",
    "ebitda": "EBITDA",
    "interest_expense": "Interest expense",
    "tax_expense": "Tax expense",
    "capex": "Capital expenditure",
    "current_assets": "Current assets",
    "current_liabilities": "Current liabilities",
    "cash": "Cash",
    "total_debt": "Total debt",
    "scheduled_debt_service": "Scheduled debt service",
}

#: How the GROUP panel names its lines, mirroring ``LINES`` in
#: ``ui/components/GroupPanel.tsx``. Deliberately a second map: the group grid abbreviates
#: ("Capex", "Interest") where the review spells the line out, and one map pretending to
#: serve both would be wrong in whichever place it was not written for.
GROUP_LINE_LABELS = {
    "revenue": "Revenue",
    "ebitda": "EBITDA",
    "interest_expense": "Interest",
    "tax_expense": "Tax",
    "capex": "Capex",
    "scheduled_debt_service": "Debt service",
    "total_debt": "Total debt",
}

# --- memo section headings (MemoView renders each as an h3) -------------- #
SECTION_SUMMARY = "Summary"
SECTION_RATIOS = "Ratios"
SECTION_FINANCIAL = "Financial analysis"
SECTION_COVENANTS = "Covenants"
SECTION_RISK = "Risk assessment"
SECTION_PEERS = "Peer comparison"
SECTION_POLICY = "Policy exceptions"
SECTION_RATING = "Proposed risk rating"
SECTION_TIE_OUT = "Reconciliation findings"
SECTION_GROUP = "The group"
SECTION_GCF = "Global cash flow"
SECTION_STRESS = "Stress"
SECTION_RATIONALE = "Recommendation rationale"
SECTION_CITATIONS = "Citations"
SECTION_MANIFEST = "What this was assessed on"

#: The sections every memo must show, whatever the deal. The conditional ones (policy,
#: rating, reconciliation, group, cash flow, stress) are asserted by the acts that create
#: the conditions for them, not here.
ALWAYS_PRESENT = (
    SECTION_SUMMARY,
    SECTION_RATIOS,
    SECTION_FINANCIAL,
    SECTION_COVENANTS,
    SECTION_RISK,
    SECTION_PEERS,
    SECTION_RATIONALE,
    SECTION_CITATIONS,
)

#: The maker-checker banner, verbatim from ``ui/components/MemoView.tsx``. It is the one
#: sentence the product refuses to let a memo appear without, so the demo reads it off the
#: page rather than trusting that it is there.
REVIEW_BANNER = "HUMAN REVIEW REQUIRED"

#: What the console says when the guardrail refuses a request.
BLOCKED_BANNER = "Blocked by guardrail."


def choose(page: Any, label: str, option: str) -> None:
    """Pick ``option`` from the select whose field is called ``label``.

    Deliberately a NON-exact label match, and the reason is worth stating once here rather
    than being rediscovered per call site. The console wraps each select inside its
    ``<label>``, so the label's text content — and therefore the control's accessible name
    — is the field name followed by every option in the list ("Loan type C&I term /
    working capital SME ..."). An exact match against the field name finds nothing at all.
    Controls that carry their own ``aria-label`` are matched exactly, as normal.
    """
    page.get_by_label(label).select_option(label=option)


def section(page: Any, title: str) -> Any:
    """The panel whose heading is ``title``."""
    return page.get_by_role("heading", name=title, exact=True)


def button(page: Any, name: str) -> Any:
    return page.get_by_role("button", name=name, exact=True)
