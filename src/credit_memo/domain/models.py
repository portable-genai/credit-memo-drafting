"""Domain models for the Credit-Memo / Underwriting Assistant (system B2).

This module is the **vertical** half of the hexagon's heart: the credit-underwriting
artifacts a fork is expected to rewrite (borrower, filings, covenants, risk flags,
peer comparisons, the memo itself). The vertical-neutral machinery it builds on
(citations, the LLM envelope, guardrail and redaction verdicts, the audit event, the
eval report, agent cards, the severity scale) lives in
:mod:`credit_memo.domain.kernel` and is imported from there. The dependency direction
is one way and enforced by ``tests/unit/test_kernel_boundary.py``: ``kernel`` never
imports ``models``.

It has **no dependency on Google Cloud, ADK, FastAPI, or any framework** (only the
Python standard library plus the shared commons). Every adapter (GCP, remote-platform,
or on-prem placeholder) speaks in terms of these types, which is what lets the managed-
service stack be swapped for an on-premise one without touching domain logic (General
Principle P-02, "no vendor lock-in / ports & adapters").

B2 handles borrower financial and PII data, so the safety models (guardrail +
redaction) are first-class: PII is redacted at the boundary before it ever reaches a
model, a trace span, or the audit sink (P-04, rule R1).

The kernel names below are re-exported unchanged, so every existing
``from credit_memo.domain.models import ...`` keeps working.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .kernel import (
    ENGINE_READABLE as ENGINE_READABLE,
)
from .kernel import (
    AgentCard as AgentCard,
)
from .kernel import (
    AgentSkill as AgentSkill,
)
from .kernel import (
    AuditEvent as AuditEvent,
)
from .kernel import (
    Citation as Citation,
)
from .kernel import (
    Decision as Decision,
)
from .kernel import (
    Direction as Direction,
)
from .kernel import (
    EvalMetricResult as EvalMetricResult,
)
from .kernel import (
    EvalReport as EvalReport,
)
from .kernel import (
    GuardrailCategory as GuardrailCategory,
)
from .kernel import (
    GuardrailFinding as GuardrailFinding,
)
from .kernel import (
    GuardrailVerdict as GuardrailVerdict,
)
from .kernel import (
    IngestResult as IngestResult,
)
from .kernel import (
    LlmDocument as LlmDocument,
)
from .kernel import (
    LlmMessage as LlmMessage,
)
from .kernel import (
    LlmRequest as LlmRequest,
)
from .kernel import (
    LlmResponse as LlmResponse,
)
from .kernel import (
    Provenance as Provenance,
)
from .kernel import (
    RedactionFinding as RedactionFinding,
)
from .kernel import (
    RedactionResult as RedactionResult,
)
from .kernel import (
    RetrievalQuery as RetrievalQuery,
)
from .kernel import (
    RetrievedPassage as RetrievedPassage,
)
from .kernel import (
    Severity as Severity,
)
from .kernel import (
    SourceType as SourceType,
)
from .kernel import (
    StrEnum as StrEnum,
)
from .kernel import (
    ThinkingLevel as ThinkingLevel,
)
from .kernel import (
    TokenUsage as TokenUsage,
)
from .kernel import (
    ToolSpec as ToolSpec,
)
from .kernel import (
    WebCitation as WebCitation,
)
from .kernel import (
    utcnow as utcnow,
)


# --------------------------------------------------------------------------- #
# Borrower & financial inputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Borrower:
    """The obligor the credit memo is being assembled for."""

    id: str  # stable borrower id, e.g. "borr-acme-mfg"
    name: str
    sector: str = ""  # e.g. "logistics", "manufacturing"
    jurisdiction: str = ""  # ISO-ish country/region code, e.g. "SG", "HK"


@dataclass(frozen=True, slots=True)
class FinancialMetric:
    """One normalised financial figure for a given period."""

    name: str  # e.g. "revenue", "ebitda", "leverage", "dscr"
    value: float
    period: str = ""  # reporting period, e.g. "FY2025"
    currency: str = "USD"


class DocType(StrEnum):
    """Source-document kinds the assistant extracts and reasons over.

    Five kinds covered a memo drafted from filings. A credit file is not filings: it is
    tax returns, bank statements, a debt schedule, an aging, a rent roll, a valuation,
    the bank's own policy pack and the prior memo. Each drives a different extraction and
    a different part of the analysis, so each is named rather than collapsed into OTHER.
    """

    FINANCIAL_STATEMENT = "financial_statement"
    MANAGEMENT_ACCOUNTS = "management_accounts"
    FILING = "filing"
    TAX_RETURN = "tax_return"
    BANK_STATEMENT = "bank_statement"
    DEBT_SCHEDULE = "debt_schedule"
    AR_AP_AGING = "ar_ap_aging"
    BORROWING_BASE_CERTIFICATE = "borrowing_base_certificate"
    RENT_ROLL = "rent_roll"
    OPERATING_STATEMENT = "operating_statement"  # T-12 for investor CRE
    LOAN_AGREEMENT = "loan_agreement"
    COVENANT_CERTIFICATE = "covenant_certificate"
    VALUATION = "valuation"
    POLICY_PACK = "policy_pack"  # the bank's own credit policy and scorecard
    PRIOR_MEMO = "prior_memo"
    RM_NOTE = "rm_note"  # call report, site-visit note
    EXPOSURE_SNAPSHOT = "exposure_snapshot"
    PROJECTIONS = "projections"
    REGISTRY_DOCUMENT = "registry_document"  # a purchased ACRA / INLIS / court search
    ANALYST_SPREAD = "analyst_spread"  # the analyst's own workbook; canonical if present
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Filing:
    """A source document supplied for a borrower (the raw input for extraction)."""

    id: str  # stable document id within the case
    doc_type: DocType = DocType.OTHER
    uri: str = ""  # where the bytes live (object store / data room)
    title: str = ""
    acl_tags: tuple[str, ...] = ()  # borrower-scoped access-control tags


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """A file the user uploaded for one analysis, and what is known about it.

    ``declared_as_of`` is the user's own statement of how current the document is, and it
    is deliberately not inferred: the system cannot tell a management account printed
    yesterday from one printed last year, and guessing would put a freshness claim in the
    memo that nobody made. The manifest prints exactly what was declared.
    """

    id: str
    filename: str
    doc_type: DocType = DocType.OTHER
    mime_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    pages: int = 0
    declared_as_of: str = ""  # ISO date the uploader states the document speaks to
    uploaded_at: datetime = field(default_factory=utcnow)
    uploaded_by: str = ""
    third_party_sourced: bool = False  # broker- or vendor-supplied, per APS 220 para 39


@dataclass(frozen=True, slots=True)
class AnalysisManifest:
    """Exactly which files this analysis used, and until when it can be reopened.

    The manifest is not bookkeeping; it is the answer to "what was this assessed on".
    It opens the memo and every export, because a reader who cannot see the inputs is
    being asked to trust the output. ``expires_at`` is printed beside it: this system
    keeps nothing beyond the analysis, and the person relying on it should know when the
    evidence behind it disappears.
    """

    analysis_id: str
    borrower_id: str
    #: The borrower's name as the person opening the analysis wrote it. Display only: the
    #: ID governs the ACL and every entitlement check, so this can never be used to point a
    #: build at a different borrower. It exists because a memo that names the borrower by
    #: its slug in its own group table is a memo that looks generated.
    borrower_name: str = ""
    documents: tuple[StoredDocument, ...] = ()
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    created_by: str = ""

    @property
    def document_count(self) -> int:
        return len(self.documents)

    def missing(self, required: tuple[DocType, ...]) -> tuple[DocType, ...]:
        """Required kinds this analysis was not given, in the order asked for."""
        present = {d.doc_type for d in self.documents}
        return tuple(kind for kind in required if kind not in present)


@dataclass(frozen=True, slots=True)
class DocumentExtract:
    """Structured + raw text extracted from a filing (from Document AI)."""

    document_id: str
    fields: dict[str, str] = field(default_factory=dict)  # key/value form fields
    text: str = ""  # full extracted text
    pages: int = 0
    #: The text of each page, in order. The extractor already knew where the pages ended
    #: and joined them anyway, so every citation from an uploaded file said "p.1" and no
    #: click could open the right page. Empty when the source has no page structure.
    pages_text: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# 0. The credit request (the ask the memo answers)
# --------------------------------------------------------------------------- #
class MemoKind(StrEnum):
    """Why this memo is being written.

    A credit memo is not one document. A renewal re-underwrites an existing facility
    and leads with what changed; an annual review confirms a grade against unchanged
    terms; a pre-screen answers "is this bankable" from a thin package. Each kind
    selects a section template, a required-input checklist and an approval path, so
    the kind is part of the request rather than something a reader infers from prose.
    """

    NEW_FACILITY = "new_facility"
    RENEWAL = "renewal"
    ANNUAL_REVIEW = "annual_review"
    INTERIM_REVIEW = "interim_review"
    RATING_ACTION = "rating_action"
    PRE_SCREEN = "pre_screen"
    DECLINE = "decline"


class LoanType(StrEnum):
    """What is being lent, which decides the ratio set and the document checklist."""

    CI_TERM = "ci_term"  # C&I term loan / working-capital line
    SME = "sme"  # small business, bank-statement led
    CRE_INVESTOR = "cre_investor"  # investor commercial real estate
    SPONSOR_BACKED = "sponsor_backed"  # sponsor-backed / leveraged
    OTHER = "other"


class FacilityType(StrEnum):
    TERM_LOAN = "term_loan"
    REVOLVING_CREDIT = "revolving_credit"
    OVERDRAFT = "overdraft"
    TRADE_LINE = "trade_line"
    GUARANTEE = "guarantee"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Facility:
    """One proposed or existing facility within the request.

    ``pricing_note`` is free text the relationship manager records; nothing in the
    domain reads it. Pricing and limit setting are out of scope (SPEC §1), so the
    field exists to carry what the RM was told, never to be assessed or recomputed.
    """

    id: str
    facility_type: FacilityType = FacilityType.TERM_LOAN
    amount: float = 0.0
    currency: str = "SGD"
    tenor_months: int = 0
    purpose: str = ""
    repayment_source: str = ""
    security: str = ""
    pricing_note: str = ""  # RM-recorded, never read by a service
    provenance: Provenance = Provenance.USER_ENTERED


@dataclass(frozen=True, slots=True)
class FundingLine:
    """One row of the sources-and-uses table."""

    label: str
    amount: float
    currency: str = "SGD"


@dataclass(frozen=True, slots=True)
class SourcesAndUses:
    """Where the money comes from and where it goes; the two sides must agree."""

    sources: tuple[FundingLine, ...] = ()
    uses: tuple[FundingLine, ...] = ()

    @property
    def total_sources(self) -> float:
        return sum(line.amount for line in self.sources)

    @property
    def total_uses(self) -> float:
        return sum(line.amount for line in self.uses)

    @property
    def imbalance(self) -> float:
        """Signed gap between sources and uses; zero when the table ties out."""
        return self.total_sources - self.total_uses


@dataclass(frozen=True, slots=True)
class CreditRequest:
    """The ask: what kind of memo, what is being lent, and on what terms.

    Without this the pipeline reasons about a borrower and its documents but never
    about a credit request, and a memo cannot carry a DSCR against *proposed* debt
    service, an approval condition or a policy exception. Every field is
    analyst-declared until an exposure feed exists, which is why the whole object
    carries ``Provenance.USER_ENTERED``.
    """

    kind: MemoKind = MemoKind.NEW_FACILITY
    loan_type: LoanType = LoanType.CI_TERM
    facilities: tuple[Facility, ...] = ()
    sources_and_uses: SourcesAndUses = field(default_factory=SourcesAndUses)
    purpose: str = ""
    notes: str = ""
    provenance: Provenance = Provenance.USER_ENTERED

    @property
    def total_amount(self) -> float:
        return sum(f.amount for f in self.facilities)


# --------------------------------------------------------------------------- #
# 0b. The financial spread and the ratio engine
# --------------------------------------------------------------------------- #
class LineItemCode(StrEnum):
    """The spread lines the ratio catalogue is allowed to reference.

    A closed vocabulary, not free text: every formula in
    :mod:`credit_memo.domain.ratio_catalogue` names codes from this enum, so a formula
    can never silently reference a line nobody supplies, and a spread can be checked
    for the inputs a given ratio needs *before* it is computed.
    """

    REVENUE = "revenue"
    EBITDA = "ebitda"
    EBIT = "ebit"
    NET_INCOME = "net_income"
    DEPRECIATION_AMORTISATION = "depreciation_amortisation"
    INTEREST_EXPENSE = "interest_expense"
    TAX_EXPENSE = "tax_expense"
    CAPEX = "capex"
    LEASE_EXPENSE = "lease_expense"
    CURRENT_ASSETS = "current_assets"
    CURRENT_LIABILITIES = "current_liabilities"
    INVENTORY = "inventory"
    CASH = "cash"
    TOTAL_ASSETS = "total_assets"
    TOTAL_DEBT = "total_debt"
    TOTAL_EQUITY = "total_equity"
    INTANGIBLE_ASSETS = "intangible_assets"
    SCHEDULED_DEBT_SERVICE = "scheduled_debt_service"


@dataclass(frozen=True, slots=True)
class Period:
    """One reporting period: a column of the spread."""

    label: str  # "FY2025", "9M2026"
    ends_on: str = ""  # ISO date where known, for ordering and staleness
    months: int = 12
    audited: bool = False


def _undeclared_periods(
    periods: tuple[Period, ...], item_periods: Iterable[str]
) -> tuple[str, ...]:
    """Period labels the items use that the columns do not declare.

    An empty declaration with figures in it is the worst case rather than a lenient one:
    everything downstream iterates the declared periods, so those figures are unreachable
    and nothing says so.
    """
    declared = {p.label for p in periods}
    return tuple(sorted({label for label in item_periods if label not in declared}))


@dataclass(frozen=True, slots=True)
class LineItem:
    """One figure of the spread, for one line and one period.

    ``provenance`` is not decoration: :class:`FinancialSpread` refuses to hold an item
    an engine may not read, which is what stops an unreviewed extraction reaching the
    ratio engine.
    """

    code: LineItemCode
    period: str  # matches Period.label
    value: float
    currency: str = "SGD"
    provenance: Provenance = Provenance.USER_ENTERED
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class FinancialSpread:
    """A borrower's normalised financials: line items across ordered periods.

    Every item must carry a provenance a deterministic engine may read
    (:data:`~credit_memo.domain.kernel.ENGINE_READABLE`). An ``EXTRACTED`` item —
    something a model read off a page that no person has yet confirmed — raises here
    rather than being quietly averaged into a covenant test. That refusal is the
    "confirm before drafting" stop, enforced by the type rather than by a code review.
    """

    borrower_id: str
    periods: tuple[Period, ...] = ()
    items: tuple[LineItem, ...] = ()
    currency: str = "SGD"
    unit: str = "thousands"
    confirmed_by: str = ""
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        offending = sorted(
            {
                f"{item.code.value}/{item.period}={item.provenance.value}"
                for item in self.items
                if item.provenance not in ENGINE_READABLE
            }
        )
        if offending:
            raise ValueError(
                "a financial spread may only hold line items an engine may read "
                f"({', '.join(sorted(p.value for p in ENGINE_READABLE))}); "
                f"refused: {', '.join(offending)}"
            )
        undeclared = _undeclared_periods(self.periods, (i.period for i in self.items))
        if undeclared:
            raise ValueError(
                "a financial spread cannot hold a figure for a period it does not "
                f"declare: {', '.join(undeclared)}. The ratio engine iterates the declared "
                "periods, so such a figure is not merely mislabelled — it is invisible, and "
                "the memo comes out with no ratios and no reason given."
            )

    def value(self, code: LineItemCode, period: str) -> float | None:
        """The figure for one line in one period, or None when it was not supplied."""
        for item in self.items:
            if item.code is code and item.period == period:
                return item.value
        return None

    @property
    def period_labels(self) -> tuple[str, ...]:
        return tuple(p.label for p in self.periods)


@dataclass(frozen=True, slots=True)
class CandidateLineItem:
    """One figure a model read off a document, with where it read it.

    ``quote`` is the verbatim text the model says it took the number from, and it is not
    decoration: the tie-out service checks that the quote actually appears on the page
    the model named. A model that invents a figure rarely invents a quote that survives
    that check, which is the cheapest hallucination detector available here.
    """

    code: LineItemCode
    period: str
    value: float
    currency: str = "SGD"
    document_id: str = ""
    page: int | None = None
    quote: str = ""
    confidence: float = 0.0
    provenance: Provenance = Provenance.EXTRACTED


@dataclass(frozen=True, slots=True)
class SpreadCandidate:
    """What extraction proposes, before a person has looked at it.

    Deliberately NOT a :class:`FinancialSpread`. The spread refuses to hold an
    unconfirmed figure, so there is no way to hand this to the ratio engine by accident;
    turning one into the other is :meth:`SpreadService.confirm`, and it takes an actor.
    That gap is the "confirm before drafting" stop, and it exists because the alternative
    is a memo whose numbers nobody ever looked at.
    """

    borrower_id: str
    periods: tuple[Period, ...] = ()
    items: tuple[CandidateLineItem, ...] = ()
    currency: str = "SGD"
    unit: str = "thousands"
    extractor: str = ""  # which adapter and model produced this
    extractor_version: str = ""
    extracted_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        undeclared = _undeclared_periods(self.periods, (i.period for i in self.items))
        if undeclared:
            raise ValueError(
                "an extractor proposed figures for a period it did not declare: "
                f"{', '.join(undeclared)}. Caught here rather than at the confirm gate "
                "because the confirmed spread inherits these periods, and a spread that "
                "declares none computes no ratios while looking perfectly well-formed."
            )

    def value(self, code: LineItemCode, period: str) -> float | None:
        for item in self.items:
            if item.code is code and item.period == period:
                return item.value
        return None


@dataclass(frozen=True, slots=True)
class Adjustment:
    """One analyst change to an extracted figure, kept forever beside the original.

    A normalising add-back is a judgement, and a committee is entitled to see who made
    it and why. ``before`` is retained even when it was wrong: "the statements said 18
    and we normalised to 24 for the disposal" is the sentence this record exists to
    support, and it cannot be written from the after-value alone.
    """

    code: LineItemCode
    period: str
    before: float | None
    after: float
    reason: str
    actor: str
    at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                "an adjustment must say why. A changed figure with no reason is "
                "indistinguishable from a typo when the committee asks about it."
            )
        if not self.actor.strip():
            raise ValueError("an adjustment must name who made it")


class TieOutCheck(StrEnum):
    """The reconciliations a credit file is expected to survive."""

    BALANCE_SHEET_BALANCES = "balance_sheet_balances"
    QUOTE_ON_PAGE = "quote_on_page"  # the model's quote is really on the page it named
    CERTIFICATE_AGREES = "certificate_agrees"  # covenant certificate vs computed
    NARRATIVE_AGREES = "narrative_agrees"  # a figure in the prose vs the spread
    SOURCES_EQUAL_USES = "sources_equal_uses"
    PERIOD_CONTINUITY = "period_continuity"  # no period silently missing from a series


@dataclass(frozen=True, slots=True)
class TieOutFinding:
    """One reconciliation that did not hold, stated as a reader would check it."""

    check: TieOutCheck
    severity: Severity
    detail: str
    expected: float | None = None
    actual: float | None = None
    document_id: str = ""
    page: int | None = None
    period: str = ""


@dataclass(frozen=True, slots=True)
class FormulaTerm:
    """One ``coefficient x line`` term of a formula's numerator or denominator."""

    code: LineItemCode
    coefficient: float = 1.0


@dataclass(frozen=True, slots=True)
class RatioFormula:
    """A versioned, declarative credit ratio.

    Declarative rather than a Python lambda so the formula can be shown to the reader,
    versioned in its id, and replayed byte-identically. ``denominator`` empty means the
    numerator is the whole answer (tangible net worth is a subtraction, not a ratio).
    """

    id: str  # "leverage.v1" — the version is part of the identity
    name: str
    numerator: tuple[FormulaTerm, ...]
    denominator: tuple[FormulaTerm, ...] = ()
    higher_is_better: bool = True
    unit: str = "x"
    definition: str = ""  # the formula as a reader would write it


@dataclass(frozen=True, slots=True)
class RatioInput:
    """One operand that went into a computed ratio, for the drill-down."""

    code: LineItemCode
    period: str
    value: float
    coefficient: float = 1.0
    side: str = "numerator"  # "numerator" | "denominator"


@dataclass(frozen=True, slots=True)
class Ratio:
    """A ratio a deterministic engine computed from a confirmed spread.

    Constructible **only** with ``Provenance.COMPUTED``. That is the whole point: a
    ``Ratio`` in the memo is a claim that this number was calculated here, from named
    operands, by a named formula version — never that a model said so. A ratio whose
    inputs were missing carries ``value=None`` and says which line was absent, rather
    than guessing.
    """

    formula_id: str
    name: str
    period: str
    value: float | None
    unit: str = "x"
    higher_is_better: bool = True
    inputs: tuple[RatioInput, ...] = ()
    definition: str = ""
    reason_missing: str = ""
    provenance: Provenance = Provenance.COMPUTED

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.COMPUTED:
            raise ValueError(
                "a Ratio is by definition computed; refusing provenance "
                f"{self.provenance.value!r}. A figure from any other source belongs in "
                "the spread as a LineItem, or in the prose as a model-drafted claim."
            )
        if self.value is None and not self.reason_missing:
            raise ValueError("a ratio with no value must say which input was missing")


# --------------------------------------------------------------------------- #
# 0c. The bank's own credit policy, and what it says about this request
# --------------------------------------------------------------------------- #
class PolicyOperator(StrEnum):
    """How a policy rule compares the measured value against its limit."""

    LE = "<="
    LT = "<"
    GE = ">="
    GT = ">"
    EQ = "=="
    IN = "in"  # the value must be one of the listed options
    NOT_IN = "not_in"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """One line of the bank's credit policy, in a form an engine can test.

    The policy is the bank's, not this service's. It arrives as an uploaded, versioned
    pack and is evaluated here; nothing in this repo decides what a prudent leverage cap
    is, and the shipped example pack is explicitly an example. That separation is the
    whole reason exceptions are credible: an exception means "your policy says X and this
    deal is Y", not "our software disapproves".

    ``waiver_authority`` names who can approve a breach of THIS rule. It is the field
    that turns a flag into an action: an exception nobody is named to waive is an
    observation, and observations do not get memos approved.
    """

    id: str  # "LEV-01", stable across pack versions so an exception can be tracked
    description: str
    metric: str  # a LineItemCode value, a RatioFormula id, or a request attribute
    operator: PolicyOperator
    limit: float | None = None
    options: tuple[str, ...] = ()  # for IN / NOT_IN
    severity: Severity = Severity.MEDIUM
    waiver_authority: str = ""
    #: Which memo kinds and loan types this rule applies to. Empty means all: a policy
    #: that only bites on CRE should say so rather than firing on every C&I memo.
    applies_to_kinds: tuple[MemoKind, ...] = ()
    applies_to_loan_types: tuple[LoanType, ...] = ()
    #: A knockout stops a pre-screen dead rather than being logged as an exception. Banks
    #: reserve these for the handful of rules no amount of committee appetite overrides.
    knockout: bool = False
    citation: str = ""  # where in the policy document this rule lives


@dataclass(frozen=True, slots=True)
class PolicyPack:
    """A versioned set of policy rules, as the bank uploaded them.

    ``version`` and ``digest`` are printed at the point of use. A memo that says "within
    policy" without saying which policy is a claim nobody can check a year later, when
    the pack has moved on twice.
    """

    version: str
    rules: tuple[PolicyRule, ...] = ()
    source_document_id: str = ""
    digest: str = ""
    effective_from: str = ""

    def applicable(self, kind: MemoKind, loan_type: LoanType) -> tuple[PolicyRule, ...]:
        return tuple(
            rule
            for rule in self.rules
            if (not rule.applies_to_kinds or kind in rule.applies_to_kinds)
            and (not rule.applies_to_loan_types or loan_type in rule.applies_to_loan_types)
        )


@dataclass(frozen=True, slots=True)
class PolicyException:
    """A policy rule this request does not meet, and who can waive it.

    Not a refusal. A bank lends outside its own guidelines constantly and on purpose;
    what supervisors ask is that it knows when it is doing so, at what level that was
    approved, and how many such exceptions are outstanding. So this carries the measured
    value, the limit, and the authority — everything a committee needs to decide, and
    everything a reviewer needs to count.
    """

    rule_id: str
    description: str
    measured: float | None
    limit: float | None
    operator: PolicyOperator
    severity: Severity
    waiver_authority: str = ""
    period: str = ""
    provenance: Provenance = Provenance.COMPUTED
    detail: str = ""
    citation: str = ""

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.COMPUTED:
            raise ValueError(
                "a policy exception is the result of testing a rule, not an opinion about "
                f"one; refusing provenance {self.provenance.value!r}"
            )


# --------------------------------------------------------------------------- #
# 0d. The risk rating, proposed and never assigned
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RatingDriver:
    """One scorecard factor and what it contributed."""

    name: str
    measured: float | None
    band: str  # the band label the measured value fell into
    points: float
    weight: float = 1.0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RatingScorecard:
    """The bank's own rating scorecard, uploaded like the policy pack.

    Bands are (upper_bound, points) pairs per factor. The grade map turns a total score
    into a grade label. Both are the bank's; this service arithmetic-only applies them.
    """

    version: str
    factors: tuple[tuple[str, str, float, tuple[tuple[float, float], ...]], ...] = ()
    grade_bands: tuple[tuple[float, str], ...] = ()  # (max score, grade)
    source_document_id: str = ""
    digest: str = ""
    definitions_url: str = ""


@dataclass(frozen=True, slots=True)
class RiskRatingProposal:
    """A grade this service PROPOSES. It never assigns one.

    The distinction is the whole design. Supervisors expect a rating to be the bank's
    judgement, arrived at by its own methodology, owned by a named officer and justified
    in the memo. What this produces is arithmetic over the bank's own scorecard plus a
    drafted rationale, offered to that officer. The grade of record lives in the bank's
    rating system and is read-only from here.

    ``rationale`` is the one part a model writes, and it explains drivers that were
    computed before it saw them. It cannot move the grade.
    """

    obligor_grade: str
    score: float
    drivers: tuple[RatingDriver, ...] = ()
    scorecard_version: str = ""
    definitions_url: str = ""
    rationale: str = ""
    facility_grade: str = ""
    provenance: Provenance = Provenance.COMPUTED
    #: Set when an officer overrides the proposed grade. Both halves are required: a
    #: silent override is the failure supervisors name explicitly.
    override_grade: str = ""
    override_reason: str = ""
    override_by: str = ""

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.COMPUTED:
            raise ValueError(
                "a rating proposal is scorecard arithmetic, not a model's opinion; "
                f"refusing provenance {self.provenance.value!r}"
            )
        if self.override_grade and not (self.override_reason.strip() and self.override_by.strip()):
            raise ValueError(
                "an override must name the officer and the reason. A grade changed with "
                "neither is the exact finding supervisors write up: a scorecard overridden "
                "silently is a scorecard that was never really used."
            )

    @property
    def grade(self) -> str:
        """The grade a reader should act on: the override where one was made."""
        return self.override_grade or self.obligor_grade


# --------------------------------------------------------------------------- #
# 0e. The group: who else stands behind this, and whose cash actually services it
# --------------------------------------------------------------------------- #
class EntityRole(StrEnum):
    """Why an entity is in this analysis at all."""

    BORROWER = "borrower"
    PARENT = "parent"
    SUBSIDIARY = "subsidiary"
    AFFILIATE = "affiliate"  # common ownership, no control either way
    GUARANTOR_CORPORATE = "guarantor_corporate"
    GUARANTOR_PERSONAL = "guarantor_personal"


@dataclass(frozen=True, slots=True)
class ExternalIds:
    """Public identifiers, so the same company is the same company across sources.

    All four are public registers. Nothing here is the bank's own customer number: those
    identify a relationship rather than a company, do not travel between institutions,
    and have no business in a record that may be exported.
    """

    uen: str = ""  # Singapore
    lei: str = ""  # Legal Entity Identifier, GLEIF, CC0
    cik: str = ""  # SEC EDGAR
    company_number: str = ""  # Companies House and equivalents


@dataclass(frozen=True, slots=True)
class RelatedEntity:
    """Another company or person in this borrower's group.

    Assembled from what the user uploaded into THIS analysis, not from a standing
    ownership graph: this service holds nothing between analyses, so the group is
    whatever the analyst brought. That is visible rather than hidden — the manifest
    lists the files, so a reader can see which entities were actually covered and infer
    which were not.

    ``ownership_pct`` is the stake the PARENT holds in this entity, where stated. It is
    not inferred from anything: a consolidated statement does not reveal a shareholding,
    and guessing one would put a control assertion in the memo that nobody made.
    """

    id: str
    name: str
    role: EntityRole = EntityRole.AFFILIATE
    ownership_pct: float | None = None
    jurisdiction: str = ""
    external_ids: ExternalIds = field(default_factory=ExternalIds)
    provenance: Provenance = Provenance.USER_ENTERED


class MatchQuality(StrEnum):
    """How sure a public register's answer is.

    An enum rather than a score, deliberately. A float here is a number, and the rule this
    whole path is built around is that nothing arriving from outside the bank's own evidence
    supplies a number. It is also more honest: "one candidate after normalising the legal
    form" is a statement a reader can act on, and 0.82 is not.
    """

    EXACT = "exact"  # the register's own legal name matched exactly
    STRONG = "strong"  # one candidate after normalising the legal form
    AMBIGUOUS = "ambiguous"  # several candidates; the analyst chooses, not this service


@dataclass(frozen=True, slots=True)
class EntityGroup:
    """A public register's view of who else is in this borrower's group.

    A SUGGESTION about who exists, never a figure. Every member carries
    ``Provenance.VENDOR``, and a ``RelatedEntity`` holds no figure at all, so an entity
    named here with no uploaded statements behind it lands in
    ``GlobalCashFlow.entities_without_figures`` exactly like one the analyst typed. That is
    the point: the register supplies the denominator of completeness and the analyst still
    supplies every number.

    ``register_reports_no_parent`` is not the same as an empty ``members``. The first is the
    register saying this company reported that it has no parent; the second can also mean it
    holds no relationship data for this company at all, and the two lead an analyst to do
    different things next.
    """

    subject: RelatedEntity
    members: tuple[RelatedEntity, ...] = ()
    source: str = ""  # which register, so a reader can go and check it
    as_of: datetime = field(default_factory=utcnow)
    quality: MatchQuality = MatchQuality.AMBIGUOUS
    register_reports_no_parent: bool = False
    #: What this register cannot see. GLEIF holds relationships only for entities that have
    #: an LEI, which most private SME borrowers do not, so an empty answer is frequently a
    #: statement about the register rather than about the group.
    coverage_note: str = ""
    candidates: tuple[str, ...] = ()  # when AMBIGUOUS, the names that matched

    def __post_init__(self) -> None:
        offending = sorted(
            {
                e.name or e.id
                for e in (self.subject, *self.members)
                if e.provenance is not Provenance.VENDOR
            }
        )
        if offending:
            raise ValueError(
                "a register's answer is vendor-supplied by definition; refusing to record "
                f"{', '.join(offending)} under another provenance. An entity the analyst "
                "declared belongs on the memo directly, not inside a register's answer."
            )

    @property
    def found_nothing(self) -> bool:
        """The register answered and knows of no related entity."""
        return not self.members


@dataclass(frozen=True, slots=True)
class Guarantor:
    """Someone who has agreed to stand behind the facility, and how far.

    ``support_amount`` is what the guarantee is worth on paper. Whether it is worth that
    in practice is the analyst's judgement and belongs in the risk section, which is why
    ``reliance`` is prose rather than a number: a personal guarantee from someone whose
    only asset is shares in the borrower supports nothing, and no field can express that
    as a figure.

    ``limited`` matters more than it looks. An unlimited guarantee and a capped one are
    different instruments, and a memo that shows only an amount cannot tell them apart.
    """

    entity_id: str
    name: str
    is_personal: bool = False
    support_amount: float | None = None
    currency: str = "SGD"
    limited: bool = True
    reliance: str = ""  # the analyst's view of what it is actually worth
    provenance: Provenance = Provenance.USER_ENTERED


@dataclass(frozen=True, slots=True)
class Elimination:
    """One intercompany amount removed when consolidating.

    Shown rather than netted silently. A group whose revenue halves on consolidation is
    telling the reader something important about how it trades with itself, and a
    consolidation that hides the eliminations hides that.
    """

    code: LineItemCode
    period: str
    amount: float
    between: str = ""  # "opco -> holdco", as the analyst described it
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EntityContribution:
    """What one entity brought to the consolidated figure for one line."""

    entity_id: str
    entity_name: str
    role: EntityRole
    value: float


@dataclass(frozen=True, slots=True)
class GlobalCashFlowLine:
    """One consolidated line, with every entity that contributed to it."""

    code: LineItemCode
    period: str
    total: float
    contributions: tuple[EntityContribution, ...] = ()
    eliminations: tuple[Elimination, ...] = ()
    provenance: Provenance = Provenance.COMPUTED

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.COMPUTED:
            raise ValueError(
                "a consolidated line is the sum of confirmed figures, not an assertion "
                f"about them; refusing provenance {self.provenance.value!r}"
            )

    @property
    def eliminated(self) -> float:
        return sum(e.amount for e in self.eliminations)


@dataclass(frozen=True, slots=True)
class GlobalCashFlow:
    """The group's combined position, and what it is missing.

    ``entities_without_figures`` is the field that keeps this honest. A global cash flow
    is only as complete as the statements behind it, and one that silently omits the
    guarantor whose accounts nobody uploaded reads as though that guarantor contributes
    nothing — which is a stronger claim than "we did not look".
    """

    periods: tuple[str, ...] = ()
    lines: tuple[GlobalCashFlowLine, ...] = ()
    entities: tuple[RelatedEntity, ...] = ()
    entities_without_figures: tuple[str, ...] = ()
    currency: str = "SGD"

    def value(self, code: LineItemCode, period: str) -> float | None:
        for line in self.lines:
            if line.code is code and line.period == period:
                return line.total
        return None

    @property
    def complete(self) -> bool:
        """Whether every entity in the group contributed figures."""
        return not self.entities_without_figures


# --------------------------------------------------------------------------- #
# 0f. Stress: what happens if it goes wrong
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Scenario:
    """One shock, expressed as multipliers on the lines it moves.

    The scenario set is the bank's, uploaded with the policy pack. Nothing here decides
    that a 200 basis point rate rise is the right test, because that is a risk-appetite
    question and this service does not have an appetite.
    """

    id: str
    name: str
    description: str = ""
    #: line code -> multiplier. 0.85 on EBITDA is a 15% decline.
    shocks: tuple[tuple[LineItemCode, float], ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """What a ratio becomes under a shock, and whether it still passes.

    ``breaks_at`` answers the question a committee actually asks, which is not "what is
    the DSCR under a 15% decline" but "how far can this fall before it breaches". A
    number they can hold against their own view of the sector is worth more than a
    scenario somebody else chose.
    """

    scenario_id: str
    scenario_name: str
    formula_id: str
    period: str
    base_value: float | None
    stressed_value: float | None
    threshold: float | None = None
    passes: bool | None = None
    breaks_at: float | None = None  # the multiplier at which it first fails
    provenance: Provenance = Provenance.COMPUTED


# --------------------------------------------------------------------------- #
# 1. Covenants
# --------------------------------------------------------------------------- #
class CovenantType(StrEnum):
    """The financial-covenant kinds the assistant extracts and tests."""

    LEVERAGE = "leverage"  # e.g. net debt / EBITDA
    DSCR = "dscr"  # debt-service coverage ratio
    INTEREST_COVER = "interest_cover"  # EBITDA / interest
    CURRENT_RATIO = "current_ratio"  # current assets / current liabilities
    MIN_EBITDA = "min_ebitda"
    MAX_CAPEX = "max_capex"
    TANGIBLE_NET_WORTH = "tangible_net_worth"
    OTHER = "other"


class CovenantOperator(StrEnum):
    """How ``current_value`` is compared against ``threshold`` to set status."""

    LE = "<="  # current must be at or below threshold (e.g. max leverage)
    LT = "<"
    GE = ">="  # current must be at or above threshold (e.g. min DSCR)
    GT = ">"
    EQ = "=="


class CovenantStatus(StrEnum):
    COMPLIANT = "compliant"
    AT_RISK = "at_risk"  # within the headroom band of the threshold
    BREACH = "breach"


@dataclass(frozen=True, slots=True)
class Covenant:
    """A financial covenant extracted from a filing/agreement, with a tested status.

    ``status`` is computed deterministically (``CovenantService``) by comparing
    ``current_value`` against ``threshold`` via ``operator``: the LLM drafts prose but
    never overrides a breach computation (SPEC §5).

    That was only ever half the guarantee. The *comparison* was deterministic while both
    of its operands were model output, so a confidently wrong extracted figure produced a
    confidently wrong COMPLIANT. ``measured`` closes it: where the spread supports the
    covenant's type, the engine computes the value and ``current_value`` is that number,
    with ``reported_value`` keeping whatever the extraction claimed so the two can be
    shown side by side when they disagree. ``value_provenance`` is what the reader sees.
    """

    type: CovenantType
    description: str
    threshold: float
    operator: CovenantOperator
    current_value: float | None = None
    status: CovenantStatus = CovenantStatus.AT_RISK
    period: str = ""
    citations: tuple[Citation, ...] = ()
    #: The engine's own measurement, when the confirmed spread supports this covenant.
    measured: Ratio | None = None
    #: What the extraction said the current value was, kept even when it was not used.
    reported_value: float | None = None
    #: Where ``current_value`` came from: COMPUTED when ``measured`` set it, otherwise
    #: EXTRACTED. The covenant table prints this beside the figure.
    value_provenance: Provenance = Provenance.EXTRACTED


# --------------------------------------------------------------------------- #
# 2. Risk flags
# --------------------------------------------------------------------------- #
class RiskCategory(StrEnum):
    LEVERAGE = "leverage"
    LIQUIDITY = "liquidity"
    PROFITABILITY = "profitability"
    GOVERNANCE = "governance"
    SECTOR = "sector"
    CONCENTRATION = "concentration"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Mitigant:
    """What answers a risk, and whether anybody has confirmed it does.

    A risk with no mitigant is a reason to decline; a risk with an unconfirmed mitigant is
    a question for the borrower. Those are different memos, so ``confirmed_by`` is a field
    rather than an assumption: an LLM may propose "the sponsor has covered shortfalls
    before", and until an analyst says that is true it stays a proposal.
    """

    detail: str
    confirmed_by: str = ""
    citations: tuple[Citation, ...] = ()
    provenance: Provenance = Provenance.MODEL_DRAFTED


@dataclass(frozen=True, slots=True)
class RiskFlag:
    """An identified credit risk with a category, severity, cited detail and mitigants.

    The memo raised risks it could not pair with a support until ``mitigants`` existed,
    which is half a risk section: every credit memo template in the industry puts the two
    in the same row, because a committee reads them together or not at all.
    """

    category: RiskCategory
    severity: Severity
    detail: str
    citations: tuple[Citation, ...] = ()
    mitigants: tuple[Mitigant, ...] = ()


# --------------------------------------------------------------------------- #
# 2b. What the memo asks the approver to agree to
# --------------------------------------------------------------------------- #
class ConditionKind(StrEnum):
    """When a condition has to be satisfied, which is what makes it trackable."""

    PRECEDENT = "precedent"  # before drawdown
    SUBSEQUENT = "subsequent"  # after drawdown, by a date
    ONGOING = "ongoing"  # for the life of the facility
    COVENANT = "covenant"  # to be written into the agreement


@dataclass(frozen=True, slots=True)
class Condition:
    """One thing that must be true for this credit to proceed.

    Free prose could say all of this, and did. The reason it is a record is what happens
    afterwards: conditions are the memo's only output that outlives the decision, and a
    condition nobody can list is a condition nobody tracks. ``owner`` and ``due`` are what
    a monitoring system needs; ``kind`` is what tells it when to start asking.
    """

    kind: ConditionKind
    detail: str
    owner: str = ""
    due: str = ""  # ISO date or a relative phrase the bank uses ("at each quarter end")
    provenance: Provenance = Provenance.MODEL_DRAFTED


@dataclass(frozen=True, slots=True)
class DeclineReason:
    """Why a request was not supported, tied to the rule it failed.

    Structured first and prose second, deliberately. Where a decline has to be explained
    to an applicant, the explanation must be specific and accurate about the actual
    reason (ECOA and Regulation B, which reach business credit at 12 CFR 1002.9(a)(3)),
    and "the model recommended against it" is neither. A reason that names the policy rule
    and the measured value is both.
    """

    detail: str
    rule_id: str = ""
    measured: float | None = None
    limit: float | None = None
    provenance: Provenance = Provenance.COMPUTED


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The memo's ask, its conditions, and the authority it needs.

    ``action`` is deliberately not an approval. SPEC section 1 excludes making or
    communicating a credit decision, so this states what is being put to the approver
    ("support, subject to the conditions below") rather than deciding it.
    """

    action: str = ""
    conditions: tuple[Condition, ...] = ()
    decline_reasons: tuple[DeclineReason, ...] = ()
    required_authority: str = ""
    provenance: Provenance = Provenance.MODEL_DRAFTED


# --------------------------------------------------------------------------- #
# 2c. Revisions: who wrote which sentence, and what changed since
# --------------------------------------------------------------------------- #
class Authorship(StrEnum):
    """Who wrote a section, which a reader is entitled to know before relying on it."""

    MODEL = "model"  # drafted from the evidence, unedited
    ANALYST = "analyst"  # written or rewritten by a person
    EDITED = "edited"  # model draft a person changed


@dataclass(frozen=True, slots=True)
class SectionEdit:
    """One analyst change to one section of the memo.

    ``before`` survives for the same reason an Adjustment keeps its before-value: a
    committee asking "what did the machine actually say" is asking a fair question, and
    the answer cannot be reconstructed from the after-text.
    """

    section: str
    before: str
    after: str
    actor: str
    at: datetime = field(default_factory=utcnow)
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MemoComment:
    """One reviewer's note against one section of one revision.

    Anchored to a REVISION as well as a section, which is the whole point. A checker who
    writes "this overstates the headroom" is objecting to a paragraph as it stood when they
    read it. Attaching that note to whatever the section says three edits later puts an
    objection next to text its author never saw, and quietly changes what the reviewer said.
    So the anchor records which version was in front of them, and a comment whose section
    has since changed is reported as raised against an earlier version rather than silently
    re-pointed.

    ``resolved_by`` is a person, never a state the system reaches on its own. A comment that
    closed because the text changed underneath it was not answered; it was lost, and the two
    look identical in a list afterwards.
    """

    id: str
    section: str
    body: str
    author: str
    revision: int
    at: datetime = field(default_factory=utcnow)
    #: The digest of the revision this was written against. Cheap and decisive: it survives
    #: a renumbering, and it is what makes "the text has moved on" checkable rather than
    #: inferred from a revision number.
    anchor_digest: str = ""
    resolved_by: str = ""
    resolved_at: datetime | None = None
    resolution: str = ""

    def __post_init__(self) -> None:
        if not self.body.strip():
            raise ValueError(
                "a comment with no body is not a comment. An empty note in a review thread "
                "reads as an objection nobody can answer."
            )
        if not self.author.strip():
            raise ValueError(
                "a comment requires a named author. An unattributed objection cannot be "
                "answered, and a committee asks who raised it."
            )
        if bool(self.resolved_by.strip()) != (self.resolved_at is not None):
            raise ValueError(
                "a resolution needs both who closed it and when, or neither. Half a "
                "resolution reads as closed to one query and open to another."
            )

    @property
    def open(self) -> bool:
        return not self.resolved_by.strip()


@dataclass(frozen=True, slots=True)
class MemoRevision:
    """One saved version of a memo, chained to the one before it.

    The chain is the point. A memo is decision-support that a committee relied on, and
    "which version did they read" has to be answerable months later. ``parent_digest`` and
    ``digest`` make the sequence tamper-evident: changing any earlier revision's content
    breaks every digest after it, so a quiet edit to what the committee saw is detectable
    rather than merely discouraged.

    This is NOT a durable archive. The revision lives in the analysis bundle and dies with
    it after the retention window, like everything else here. What the chain protects is
    integrity within that window, not permanence beyond it.
    """

    revision: int
    memo_json: dict
    actor: str
    digest: str = ""
    parent_digest: str = ""
    edits: tuple[SectionEdit, ...] = ()
    authorship: dict[str, str] = field(default_factory=dict)  # section -> Authorship value
    at: datetime = field(default_factory=utcnow)
    note: str = ""


@dataclass(frozen=True, slots=True)
class SectionDelta:
    """How one part of a renewal differs from the memo before it."""

    label: str
    before: float | None
    after: float | None
    unit: str = ""
    detail: str = ""

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def direction(self) -> str:
        """ "up", "down", "unchanged", or "new" — what a reader scans for first."""
        change = self.change
        if self.before is None:
            return "new"
        if self.after is None:
            return "gone"
        if change is None or abs(change) < 1e-9:
            return "unchanged"
        return "up" if change > 0 else "down"


@dataclass(frozen=True, slots=True)
class RenewalDelta:
    """What changed since the last memo, which is the whole point of a renewal.

    A renewal re-underwrites a facility the bank already holds. Its reader knows the
    borrower and does not need the history again; what they need is the difference, and a
    renewal that buries it under a repeated borrower overview has buried its own point.
    """

    prior_version: str = ""
    prior_at: str = ""
    ratios: tuple[SectionDelta, ...] = ()
    spread: tuple[SectionDelta, ...] = ()
    covenants: tuple[SectionDelta, ...] = ()
    rating_before: str = ""
    rating_after: str = ""
    new_exceptions: tuple[str, ...] = ()
    cleared_exceptions: tuple[str, ...] = ()
    unchanged_sections: tuple[str, ...] = ()

    @property
    def rating_moved(self) -> bool:
        return bool(self.rating_before) and self.rating_before != self.rating_after


# --------------------------------------------------------------------------- #
# 2d. Public-web context: analyst-only, ephemeral, and numerically inert
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class WebEvidence:
    """One thing found on the public web, with where and when it was found.

    **This type carries no numeric field, deliberately.** Not an oversight and not a
    simplification: it is the mechanism. A ratio, a covenant test, a policy rule and a
    scorecard all read numbers, and a type with no number on it cannot supply one to any
    of them even by accident. An analyst who wants a figure from the web in the memo
    types it, which makes it USER_ENTERED and theirs to stand behind.

    ``retrieved_at`` is on every item because web context goes stale in a way a filed
    statement does not, and a reader six weeks later needs to know how old this is.
    """

    title: str
    url: str
    snippet: str = ""
    retrieved_at: datetime = field(default_factory=utcnow)
    provenance: Provenance = Provenance.WEB_GROUNDED

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.WEB_GROUNDED:
            raise ValueError(
                "web evidence is web-grounded by definition; refusing provenance "
                f"{self.provenance.value!r}. A figure an analyst took from the web and "
                "typed into the memo is USER_ENTERED and belongs in the spread."
            )


@dataclass(frozen=True, slots=True)
class MarketContext:
    """What a search found, for the analyst who ran it and nobody else.

    Never written into a memo, never exported, never persisted beyond the query log.
    Google's Service Specific Terms section 20(k) permit Grounded Results to be shown
    only to the End User who submitted the prompt, and a credit memo is read by a
    checker, a committee and an examiner — none of whom did.

    ``search_suggestions`` are the chips Google requires be rendered verbatim alongside
    grounded results. Dropping them is a licence breach that looks like a tidy UI.
    """

    query: str
    purpose: str = ""
    evidence: tuple[WebEvidence, ...] = ()
    search_suggestions: tuple[str, ...] = ()
    retrieved_at: datetime = field(default_factory=utcnow)
    provider: str = ""

    @property
    def found_nothing(self) -> bool:
        """True when the search ran and returned nothing.

        Distinct from the port returning None, which means the search could not run at
        all. An analyst deciding whether to go and check themselves needs to know which
        of the two they got.
        """
        return not self.evidence


# --------------------------------------------------------------------------- #
# 3. Peer comparison
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PeerMetric:
    """One peer's value for a given metric (from the peer dataset)."""

    peer_name: str
    metric: str
    value: float


@dataclass(frozen=True, slots=True)
class PeerComparison:
    """The borrower's metric versus a peer set, with the median and percentile."""

    metric: str
    borrower_value: float
    peer_median: float
    percentile: float  # the borrower's percentile within the peer set, 0.0-1.0
    peers: tuple[PeerMetric, ...] = ()

    @property
    def delta_to_median(self) -> float:
        """How far the borrower sits from the peer median (signed)."""
        return self.borrower_value - self.peer_median


# --------------------------------------------------------------------------- #
# The credit memo (the bundled top-level artifact)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MemoInput:
    """The inbound request to build a memo: a borrower, its evidence, and the ask.

    ``request`` and ``spreads`` are optional so every existing caller keeps working, but
    a memo built without them is a commentary on a borrower rather than an assessment of
    a credit: there is no proposed debt service to test a DSCR against, and no confirmed
    figure for an engine to compute from.
    """

    borrower: Borrower
    documents: tuple[Filing, ...] = ()
    request: CreditRequest | None = None
    spreads: tuple[FinancialSpread, ...] = ()
    #: The bundle this memo is built from. When set, the pipeline reads the uploaded
    #: bytes out of it rather than extracting from nothing, and the manifest of what it
    #: actually used is carried onto the memo.
    analysis_id: str = ""
    #: The group, as the analyst declared it for THIS analysis. There is no standing
    #: ownership graph to consult, which is why an entity here with no spread below is
    #: named on the memo as one the consolidation could not include rather than quietly
    #: contributing nothing.
    related_entities: tuple[RelatedEntity, ...] = ()
    guarantors: tuple[Guarantor, ...] = ()
    #: Confirmed figures per entity id, for the entities whose statements were uploaded.
    entity_spreads: dict[str, FinancialSpread] = field(default_factory=dict)
    #: Intercompany amounts to remove on consolidation, each saying what it is and
    #: between whom. Shown rather than netted: a group whose revenue halves on
    #: consolidation is telling the reader something about how it trades with itself.
    eliminations: tuple[Elimination, ...] = ()


@dataclass(frozen=True, slots=True)
class CreditMemo:
    """A single credit memo bundling all four cited, audited artifacts.

    A credit memo is consequential decision-support (never a credit decision), so it
    **always** requires human review (maker-checker, P-06): a maker (the assistant)
    proposes and a checker (a qualified credit officer) disposes before it is relied
    upon.
    """

    borrower: Borrower
    summary: str
    financial_metrics: tuple[FinancialMetric, ...] = ()
    covenants: tuple[Covenant, ...] = ()
    risk_flags: tuple[RiskFlag, ...] = ()
    peer_comparison: tuple[PeerComparison, ...] = ()
    recommendation_rationale: str = ""
    citations: tuple[Citation, ...] = ()
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)
    #: The ask and the confirmed figures the engines computed from, carried on the memo
    #: so a reader sees what was assessed rather than inferring it from prose.
    request: CreditRequest | None = None
    spreads: tuple[FinancialSpread, ...] = ()
    ratios: tuple[Ratio, ...] = ()
    #: Reconciliations that did not hold. Not failures: sentences in the reviewer's
    #: gutter saying "these two numbers should agree and they do not", with both numbers.
    tie_out: tuple[TieOutFinding, ...] = ()
    #: Where this request sits against the bank's own uploaded policy, and who can waive
    #: what. An exception is not a refusal: banks lend outside their guidelines on purpose,
    #: and what supervisors ask is that they know when, at what level it was approved, and
    #: how many are outstanding.
    policy_exceptions: tuple[PolicyException, ...] = ()
    policy_version: str = ""
    #: A grade this service PROPOSES from the bank's scorecard. It never assigns one.
    rating: RiskRatingProposal | None = None
    #: The ask, its conditions and the authority it needs; or the structured reasons it
    #: was not supported.
    recommendation: Recommendation | None = None
    #: Which sections a person wrote or edited. A reader is entitled to know before they
    #: rely on a paragraph whether a person stood behind it.
    authorship: dict[str, str] = field(default_factory=dict)
    #: For a renewal: what moved since the memo before it.
    renewal_delta: RenewalDelta | None = None
    #: The group, when the analyst uploaded more than one entity's figures.
    related_entities: tuple[RelatedEntity, ...] = ()
    guarantors: tuple[Guarantor, ...] = ()
    global_cash_flow: GlobalCashFlow | None = None
    #: What the ratios become under the bank's own scenario set.
    scenarios: tuple[ScenarioResult, ...] = ()
    #: Exactly which uploaded files this memo was assessed on, and when they expire.
    manifest: AnalysisManifest | None = None
    #: The synthesis service's self-critique. Both were computed and then dropped on the
    #: floor before this field existed, so a reader could not see how sure the drafter
    #: was, nor what it said it could not support.
    confidence: float = 0.0
    caveats: tuple[str, ...] = ()
    #: What the analyst should go and ask the borrower. Experts rank this above another
    #: paragraph of narrative: it is the difference between a memo that reports a gap and
    #: one that closes it.
    questions_for_client: tuple[str, ...] = ()
