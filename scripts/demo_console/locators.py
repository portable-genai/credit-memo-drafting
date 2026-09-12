"""Every console locator the demo uses, in one place, and each one a ``data-*`` hook.

The console used to carry almost no stable hooks, so the demo found controls the way a person
does, by visible label and role. That tied every act to wording: rewording a button, or
wrapping a select inside its label so its accessible name became the field name followed by
every option, broke an act that proved nothing about wording. The controls and panels the acts
drive or read now carry ``data-*`` attributes that say what they ARE, and this module is the
one place that spells them. ``tests/unit/test_console_data_hooks.py`` fails the offline gate
when a hook named here is missing from ``ui/``, and when an act goes back to locating a control
by its label, its role or its visible text.

Five kinds, one per job:

* ``data-panel``: a region an act waits for or reads (``spread-candidate``, ``manifest``)
* ``data-field``: an input an act fills or picks from (``borrower``, ``memo-kind``)
* ``data-action``: a button an act presses (``extract``, ``build-memo``)
* ``data-section``: one section of the rendered memo (``summary``, ``tie-out``)
* identifying attributes on repeated rows, so an act names the row it means rather than
  counting to it: ``data-line`` and ``data-period``, ``data-covenant`` and ``data-status``,
  ``data-rule``, ``data-filename``, ``data-verdict``

Nothing here changes what the demo narrates, or what it asserts a reader can see. It changes
only how an act finds the thing it presses.
"""

from __future__ import annotations

# --- who is asking, and the credit file ------------------------------------ #
PERSONA = '[data-field="persona"]'
BORROWER = '[data-field="borrower"]'
SECTOR = '[data-field="sector"]'
JURISDICTION = '[data-field="jurisdiction"]'
DOCUMENTS_INPUT = '[data-field="documents"]'
#: Rendered twice once a memo exists (beside the upload, and at the foot of the memo), so
#: acts read ``.first``. It carries ``data-analysis-id``.
MANIFEST = '[data-panel="manifest"]'
RETENTION = '[data-manifest="retention"]'


def document_kind(filename: str) -> str:
    """The kind picker on the queued row for ``filename``."""
    return f'[data-field="document-kind"][data-filename="{filename}"]'


def document_as_of(filename: str) -> str:
    """The as-of date on the queued row for ``filename``."""
    return f'[data-field="document-as-of"][data-filename="{filename}"]'


# --- the ask ----------------------------------------------------------------- #
MEMO_KIND = '[data-field="memo-kind"]'
LOAN_TYPE = '[data-field="loan-type"]'
FACILITY_TYPE = '[data-field="facility-type"]'
AMOUNT = '[data-field="amount"]'
TENOR = '[data-field="tenor"]'
REPAYMENT_SOURCE = '[data-field="repayment-source"]'
PURPOSE = '[data-field="purpose"]'
SECURITY = '[data-field="security"]'

# --- the spread: propose, review, confirm ------------------------------------ #
EXTRACT = '[data-action="extract"]'
SPREAD_CANDIDATE = '[data-panel="spread-candidate"]'
SHOW_QUOTE = '[data-action="show-quote"]'
OPEN_SOURCE = '[data-action="open-source"]'
ADJUSTED_VALUE = '[data-field="adjusted-value"]'
ADJUSTMENT_REASON = '[data-field="adjustment-reason"]'
CONFIRM = '[data-action="confirm-spread"]'
DISCARD = '[data-action="discard-candidate"]'
#: Carries ``data-confirmed-by``, the confirmer the service recorded.
SPREAD_CONFIRMED = '[data-panel="spread-confirmed"]'


def spread_row(code: str, period: str) -> str:
    """One proposed figure, by what it is rather than by where it happens to render."""
    return f'[data-line="{code}"][data-period="{period}"]'


def verdict(choice: str) -> str:
    """The keep / adjust / reject control inside a review row."""
    return f'[data-verdict="{choice}"]'


# --- the group, and public context ------------------------------------------ #
GROUP_ENTITY = '[data-field="group-entity"]'
GROUP_ROLE = '[data-field="group-role"]'
ADD_TO_GROUP = '[data-action="add-to-group"]'
SUGGEST_FROM_REGISTER = '[data-action="suggest-group"]'
RESEARCH_QUERY = '[data-field="research-query"]'
RESEARCH = '[data-action="research"]'
#: The line saying none of the results is in the memo.
RESEARCH_FENCE = '[data-research="not-in-memo"]'

# --- building, and what comes back ------------------------------------------ #
BUILD = '[data-action="build-memo"]'
#: Carries ``data-outcomes``: how many build attempts have settled, answered or refused.
OUTCOME = '[data-panel="outcome"]'
ERROR = '[data-panel="error"]'
GUARDRAIL_BLOCKED = '[data-panel="guardrail-blocked"]'
MEMO = '[data-panel="memo"]'
#: The consolidation's "Incomplete" notice, naming the entities nobody filed for.
GCF_INCOMPLETE = '[data-gcf="incomplete"]'


def covenant(kind: str) -> str:
    """Every covenant card of ``kind``; each carries ``data-status``."""
    return f'[data-covenant="{kind}"]'


def policy_rule(rule_id: str) -> str:
    """The policy exception raised under ``rule_id``."""
    return f'[data-rule="{rule_id}"]'


# --- after the memo: the edit, the objection, the pack, the delete ----------- #
AMEND_SECTION = '[data-field="amend-section"]'
AMEND_TEXT = '[data-field="amend-text"]'
AMEND_REASON = '[data-field="amend-reason"]'
AMEND_NOTE = '[data-field="amend-note"]'
AMEND = '[data-action="amend-memo"]'
#: Carries ``data-revisions`` and ``data-chain-intact``.
REVISIONS = '[data-panel="revisions"]'
#: Carries ``data-open-count`` and ``data-stale-count``.
COMMENTS = '[data-panel="comments"]'
COMMENT_SECTION = '[data-field="comment-section"]'
COMMENT_BODY = '[data-field="comment-body"]'
ADD_COMMENT = '[data-action="add-comment"]'
RESOLUTION = '[data-field="resolution"]'
RESOLVE = '[data-action="resolve-comment"]'
EXPORT_FORMAT = '[data-field="export-format"]'
EXPORT = '[data-action="export-memo"]'
DELETE_ANALYSIS = '[data-action="delete-analysis"]'
CONFIRM_DELETE = '[data-action="confirm-delete"]'
DELETED = '[data-panel="deleted"]'
REVIEW_ERROR = '[data-panel="review-error"]'


def revisions_numbering(count: int) -> str:
    """The chain once it holds ``count`` versions, so an act waits for the saved edit."""
    return f'[data-panel="revisions"][data-revisions="{count}"]'


def comment_row(comment_id: str) -> str:
    """One comment, by the id the service gave it; carries ``data-open`` and ``data-stale``."""
    return f'[data-comment-id="{comment_id}"]'


# --- the memo's sections ------------------------------------------------------ #
SECTION_SUMMARY = '[data-section="summary"]'
SECTION_RATIOS = '[data-section="ratios"]'
SECTION_FINANCIAL = '[data-section="financial-analysis"]'
SECTION_COVENANTS = '[data-section="covenants"]'
SECTION_RISK = '[data-section="risk-assessment"]'
SECTION_PEERS = '[data-section="peer-comparison"]'
SECTION_POLICY = '[data-section="policy-exceptions"]'
SECTION_RATING = '[data-section="rating"]'
SECTION_TIE_OUT = '[data-section="tie-out"]'
SECTION_GROUP = '[data-section="group"]'
SECTION_GCF = '[data-section="global-cash-flow"]'
SECTION_STRESS = '[data-section="stress"]'
SECTION_RATIONALE = '[data-section="recommendation-rationale"]'
SECTION_CITATIONS = '[data-section="citations"]'
SECTION_MANIFEST = '[data-section="manifest"]'

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

#: The maker-checker banner, verbatim from ``ui/components/MemoView.tsx``. Read as TEXT on
#: purpose, not located by a hook: it is the one sentence the product refuses to let a memo
#: appear without, so the demo asserts the words a reader sees rather than that an element
#: exists.
REVIEW_BANNER = "HUMAN REVIEW REQUIRED"
