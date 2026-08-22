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
    """

    type: CovenantType
    description: str
    threshold: float
    operator: CovenantOperator
    current_value: float | None = None
    status: CovenantStatus = CovenantStatus.AT_RISK
    period: str = ""
    citations: tuple[Citation, ...] = ()


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
    """The inbound request to build a memo: a borrower plus its source documents."""

    borrower: Borrower
    documents: tuple[Filing, ...] = ()


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
