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
    """Source-document kinds the assistant extracts and reasons over."""

    FINANCIAL_STATEMENT = "financial_statement"
    FILING = "filing"
    LOAN_AGREEMENT = "loan_agreement"
    COVENANT_CERTIFICATE = "covenant_certificate"
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
class DocumentExtract:
    """Structured + raw text extracted from a filing (from Document AI)."""

    document_id: str
    fields: dict[str, str] = field(default_factory=dict)  # key/value form fields
    text: str = ""  # full extracted text
    pages: int = 0


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
class RiskFlag:
    """An identified credit risk with a category, severity and cited detail."""

    category: RiskCategory
    severity: Severity
    detail: str
    citations: tuple[Citation, ...] = ()


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
    #: The synthesis service's self-critique. Both were computed and then dropped on the
    #: floor before this field existed, so a reader could not see how sure the drafter
    #: was, nor what it said it could not support.
    confidence: float = 0.0
    caveats: tuple[str, ...] = ()
    #: What the analyst should go and ask the borrower. Experts rank this above another
    #: paragraph of narrative: it is the difference between a memo that reports a gap and
    #: one that closes it.
    questions_for_client: tuple[str, ...] = ()
