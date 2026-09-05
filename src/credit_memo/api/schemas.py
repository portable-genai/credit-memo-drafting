"""Pydantic v2 request/response models for the B2 Credit-Memo API.

These schemas mirror the frozen domain dataclasses in :mod:`credit_memo.domain.models`
one-for-one, so the HTTP boundary is a thin, typed projection of the domain: the
React/Next.js UI and the CLI consume exactly these shapes. Each response model exposes a
``from_domain`` classmethod that builds itself from the corresponding domain object
(enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration services, never on a concrete adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain import models as m
from ..domain.serialization import to_jsonable

# --------------------------------------------------------------------------- #
# Citation
# --------------------------------------------------------------------------- #


class CitationModel(BaseModel):
    """Source-grade provenance attached to a generated claim (mirror of Citation)."""

    source_id: str
    source_type: str
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None

    @classmethod
    def from_domain(cls, citation: m.Citation) -> CitationModel:
        return cls(**to_jsonable(citation))


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class BorrowerModel(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    sector: str = ""
    jurisdiction: str = ""

    def to_domain(self) -> m.Borrower:
        return m.Borrower(
            id=self.id, name=self.name, sector=self.sector, jurisdiction=self.jurisdiction
        )


class DocumentModel(BaseModel):
    id: str = Field(..., min_length=1)
    doc_type: str = "other"
    uri: str = ""
    title: str = ""
    acl_tags: list[str] = Field(default_factory=list)

    def to_domain(self) -> m.Filing:
        return m.Filing(
            id=self.id,
            doc_type=m.DocType(self.doc_type),
            uri=self.uri,
            title=self.title,
            acl_tags=tuple(self.acl_tags),
        )


class FacilityModel(BaseModel):
    id: str = Field(..., min_length=1)
    facility_type: str = "term_loan"
    amount: float = 0.0
    currency: str = "SGD"
    tenor_months: int = 0
    purpose: str = ""
    repayment_source: str = ""
    security: str = ""
    #: Recorded from the relationship manager and never assessed: pricing is out of
    #: scope (SPEC §1), so no service reads this.
    pricing_note: str = ""

    def to_domain(self) -> m.Facility:
        return m.Facility(
            id=self.id,
            facility_type=m.FacilityType(self.facility_type),
            amount=self.amount,
            currency=self.currency,
            tenor_months=self.tenor_months,
            purpose=self.purpose,
            repayment_source=self.repayment_source,
            security=self.security,
            pricing_note=self.pricing_note,
        )

    @classmethod
    def from_domain(cls, facility: m.Facility) -> FacilityModel:
        return cls(
            id=facility.id,
            facility_type=facility.facility_type.value,
            amount=facility.amount,
            currency=facility.currency,
            tenor_months=facility.tenor_months,
            purpose=facility.purpose,
            repayment_source=facility.repayment_source,
            security=facility.security,
            pricing_note=facility.pricing_note,
        )


class FundingLineModel(BaseModel):
    label: str
    amount: float
    currency: str = "SGD"

    def to_domain(self) -> m.FundingLine:
        return m.FundingLine(label=self.label, amount=self.amount, currency=self.currency)

    @classmethod
    def from_domain(cls, line: m.FundingLine) -> FundingLineModel:
        return cls(label=line.label, amount=line.amount, currency=line.currency)


class SourcesAndUsesModel(BaseModel):
    sources: list[FundingLineModel] = Field(default_factory=list)
    uses: list[FundingLineModel] = Field(default_factory=list)
    total_sources: float = 0.0
    total_uses: float = 0.0
    imbalance: float = 0.0

    def to_domain(self) -> m.SourcesAndUses:
        return m.SourcesAndUses(
            sources=tuple(x.to_domain() for x in self.sources),
            uses=tuple(x.to_domain() for x in self.uses),
        )

    @classmethod
    def from_domain(cls, table: m.SourcesAndUses) -> SourcesAndUsesModel:
        return cls(
            sources=[FundingLineModel.from_domain(x) for x in table.sources],
            uses=[FundingLineModel.from_domain(x) for x in table.uses],
            total_sources=table.total_sources,
            total_uses=table.total_uses,
            imbalance=table.imbalance,
        )


class CreditRequestModel(BaseModel):
    """The ask the memo answers: kind of memo, loan type, and the facilities."""

    kind: str = "new_facility"
    loan_type: str = "ci_term"
    facilities: list[FacilityModel] = Field(default_factory=list)
    sources_and_uses: SourcesAndUsesModel = Field(default_factory=SourcesAndUsesModel)
    purpose: str = ""
    notes: str = ""
    total_amount: float = 0.0

    def to_domain(self) -> m.CreditRequest:
        return m.CreditRequest(
            kind=m.MemoKind(self.kind),
            loan_type=m.LoanType(self.loan_type),
            facilities=tuple(f.to_domain() for f in self.facilities),
            sources_and_uses=self.sources_and_uses.to_domain(),
            purpose=self.purpose,
            notes=self.notes,
        )

    @classmethod
    def from_domain(cls, request: m.CreditRequest) -> CreditRequestModel:
        return cls(
            kind=request.kind.value,
            loan_type=request.loan_type.value,
            facilities=[FacilityModel.from_domain(f) for f in request.facilities],
            sources_and_uses=SourcesAndUsesModel.from_domain(request.sources_and_uses),
            purpose=request.purpose,
            notes=request.notes,
            total_amount=request.total_amount,
        )


class PeriodModel(BaseModel):
    label: str = Field(..., min_length=1)
    ends_on: str = ""
    months: int = 12
    audited: bool = False

    def to_domain(self) -> m.Period:
        return m.Period(
            label=self.label, ends_on=self.ends_on, months=self.months, audited=self.audited
        )

    @classmethod
    def from_domain(cls, period: m.Period) -> PeriodModel:
        return cls(
            label=period.label,
            ends_on=period.ends_on,
            months=period.months,
            audited=period.audited,
        )


class LineItemModel(BaseModel):
    code: str
    period: str
    value: float
    currency: str = "SGD"
    #: Inbound spreads are what the analyst typed, so the default is ``user_entered``.
    #: The domain refuses anything an engine may not read, and that refusal is a 422
    #: rather than something the API silently upgrades.
    provenance: str = "user_entered"
    citations: list[CitationModel] = Field(default_factory=list)

    def to_domain(self) -> m.LineItem:
        return m.LineItem(
            code=m.LineItemCode(self.code),
            period=self.period,
            value=self.value,
            currency=self.currency,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, item: m.LineItem) -> LineItemModel:
        return cls(
            code=item.code.value,
            period=item.period,
            value=item.value,
            currency=item.currency,
            provenance=item.provenance.value,
            citations=[CitationModel.from_domain(c) for c in item.citations],
        )


class FinancialSpreadModel(BaseModel):
    borrower_id: str = ""
    periods: list[PeriodModel] = Field(default_factory=list)
    items: list[LineItemModel] = Field(default_factory=list)
    currency: str = "SGD"
    unit: str = "thousands"
    confirmed_by: str = ""

    def to_domain(self, borrower_id: str = "") -> m.FinancialSpread:
        return m.FinancialSpread(
            borrower_id=self.borrower_id or borrower_id,
            periods=tuple(p.to_domain() for p in self.periods),
            items=tuple(i.to_domain() for i in self.items),
            currency=self.currency,
            unit=self.unit,
            confirmed_by=self.confirmed_by,
        )

    @classmethod
    def from_domain(cls, spread: m.FinancialSpread) -> FinancialSpreadModel:
        return cls(
            borrower_id=spread.borrower_id,
            periods=[PeriodModel.from_domain(p) for p in spread.periods],
            items=[LineItemModel.from_domain(i) for i in spread.items],
            currency=spread.currency,
            unit=spread.unit,
            confirmed_by=spread.confirmed_by,
        )


class CreditMemoRequest(BaseModel):
    """Inbound request to build a full credit memo.

    There is no ``actor`` field: the audit actor is the server-verified ``Principal``
    (``api/security.py``), never a client-asserted identity.
    """

    borrower: BorrowerModel
    documents: list[DocumentModel] = Field(default_factory=list)
    #: The ask, and the confirmed figures the engines compute from. Optional so every
    #: existing caller keeps working; supplying them is what turns a commentary on a
    #: borrower into an assessment of a credit.
    request: CreditRequestModel | None = None
    spreads: list[FinancialSpreadModel] = Field(default_factory=list)

    def to_memo_input(self) -> m.MemoInput:
        return m.MemoInput(
            borrower=self.borrower.to_domain(),
            documents=tuple(d.to_domain() for d in self.documents),
            request=self.request.to_domain() if self.request is not None else None,
            spreads=tuple(s.to_domain(self.borrower.id) for s in self.spreads),
        )


class DocumentUploadResponse(BaseModel):
    """Outcome of ingesting one uploaded borrower document into the evidence store."""

    document_id: str
    borrower_id: str
    chunks: int = 0
    detail: str = ""


class CovenantRequest(BaseModel):
    """Inbound request to extract covenants for a borrower from its documents.

    No ``actor`` field: the audit actor is the server-verified ``Principal``.
    """

    borrower: BorrowerModel
    documents: list[DocumentModel] = Field(default_factory=list)

    def to_memo_input(self) -> m.MemoInput:
        return m.MemoInput(
            borrower=self.borrower.to_domain(),
            documents=tuple(d.to_domain() for d in self.documents),
        )


class RiskFlagRequest(BaseModel):
    """Inbound request to identify risk flags for a borrower.

    No ``actor`` field: the audit actor is the server-verified ``Principal``.
    """

    borrower: BorrowerModel
    documents: list[DocumentModel] = Field(default_factory=list)

    def to_memo_input(self) -> m.MemoInput:
        return m.MemoInput(
            borrower=self.borrower.to_domain(),
            documents=tuple(d.to_domain() for d in self.documents),
        )


# --------------------------------------------------------------------------- #
# Artifact responses
# --------------------------------------------------------------------------- #


class FinancialMetricModel(BaseModel):
    name: str
    value: float
    period: str = ""
    currency: str = "USD"

    @classmethod
    def from_domain(cls, metric: m.FinancialMetric) -> FinancialMetricModel:
        return cls(
            name=metric.name, value=metric.value, period=metric.period, currency=metric.currency
        )


class RatioInputModel(BaseModel):
    code: str
    period: str
    value: float
    coefficient: float = 1.0
    side: str = "numerator"

    @classmethod
    def from_domain(cls, item: m.RatioInput) -> RatioInputModel:
        return cls(
            code=item.code.value,
            period=item.period,
            value=item.value,
            coefficient=item.coefficient,
            side=item.side,
        )


class RatioModel(BaseModel):
    """A figure the engine calculated, with the formula and operands that produced it."""

    formula_id: str
    name: str
    period: str
    value: float | None = None
    unit: str = "x"
    higher_is_better: bool = True
    inputs: list[RatioInputModel] = Field(default_factory=list)
    definition: str = ""
    reason_missing: str = ""
    provenance: str = "computed"

    @classmethod
    def from_domain(cls, ratio: m.Ratio) -> RatioModel:
        return cls(
            formula_id=ratio.formula_id,
            name=ratio.name,
            period=ratio.period,
            value=ratio.value,
            unit=ratio.unit,
            higher_is_better=ratio.higher_is_better,
            inputs=[RatioInputModel.from_domain(i) for i in ratio.inputs],
            definition=ratio.definition,
            reason_missing=ratio.reason_missing,
            provenance=ratio.provenance.value,
        )


class CovenantModel(BaseModel):
    type: str
    description: str
    threshold: float
    operator: str
    current_value: float | None = None
    status: str
    period: str = ""
    citations: list[CitationModel] = Field(default_factory=list)
    #: The engine's own measurement, where the confirmed spread supported one. When it
    #: is set, ``current_value`` is its value and the test ran on arithmetic rather than
    #: on what a model read off a page.
    measured: RatioModel | None = None
    reported_value: float | None = None
    value_provenance: str = "extracted"

    @classmethod
    def from_domain(cls, covenant: m.Covenant) -> CovenantModel:
        return cls(
            type=covenant.type.value,
            description=covenant.description,
            threshold=covenant.threshold,
            operator=covenant.operator.value,
            current_value=covenant.current_value,
            status=covenant.status.value,
            period=covenant.period,
            citations=[CitationModel.from_domain(c) for c in covenant.citations],
            measured=(
                RatioModel.from_domain(covenant.measured) if covenant.measured is not None else None
            ),
            reported_value=covenant.reported_value,
            value_provenance=covenant.value_provenance.value,
        )


class RiskFlagModel(BaseModel):
    category: str
    severity: str
    detail: str
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, flag: m.RiskFlag) -> RiskFlagModel:
        return cls(
            category=flag.category.value,
            severity=flag.severity.value,
            detail=flag.detail,
            citations=[CitationModel.from_domain(c) for c in flag.citations],
        )


class PeerMetricModel(BaseModel):
    peer_name: str
    metric: str
    value: float

    @classmethod
    def from_domain(cls, peer: m.PeerMetric) -> PeerMetricModel:
        return cls(peer_name=peer.peer_name, metric=peer.metric, value=peer.value)


class PeerComparisonModel(BaseModel):
    metric: str
    borrower_value: float
    peer_median: float
    percentile: float
    delta_to_median: float = 0.0
    peers: list[PeerMetricModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, comparison: m.PeerComparison) -> PeerComparisonModel:
        return cls(
            metric=comparison.metric,
            borrower_value=comparison.borrower_value,
            peer_median=comparison.peer_median,
            percentile=comparison.percentile,
            delta_to_median=comparison.delta_to_median,
            peers=[PeerMetricModel.from_domain(p) for p in comparison.peers],
        )


class CreditMemoResponse(BaseModel):
    """The full credit memo (mirror of CreditMemo)."""

    borrower: BorrowerModel
    summary: str
    financial_metrics: list[FinancialMetricModel] = Field(default_factory=list)
    covenants: list[CovenantModel] = Field(default_factory=list)
    risk_flags: list[RiskFlagModel] = Field(default_factory=list)
    peer_comparison: list[PeerComparisonModel] = Field(default_factory=list)
    recommendation_rationale: str = ""
    citations: list[CitationModel] = Field(default_factory=list)
    requires_human_review: bool = True
    generated_at: str = ""
    request: CreditRequestModel | None = None
    spreads: list[FinancialSpreadModel] = Field(default_factory=list)
    ratios: list[RatioModel] = Field(default_factory=list)
    #: How fully the drafter believed the evidence supported the memo, and what it said
    #: it could not support. Both were computed and discarded before Wave 0.
    confidence: float = 0.0
    caveats: list[str] = Field(default_factory=list)
    questions_for_client: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, memo: m.CreditMemo) -> CreditMemoResponse:
        return cls(
            borrower=BorrowerModel(
                id=memo.borrower.id,
                name=memo.borrower.name,
                sector=memo.borrower.sector,
                jurisdiction=memo.borrower.jurisdiction,
            ),
            summary=memo.summary,
            financial_metrics=[FinancialMetricModel.from_domain(x) for x in memo.financial_metrics],
            covenants=[CovenantModel.from_domain(c) for c in memo.covenants],
            risk_flags=[RiskFlagModel.from_domain(f) for f in memo.risk_flags],
            peer_comparison=[PeerComparisonModel.from_domain(p) for p in memo.peer_comparison],
            recommendation_rationale=memo.recommendation_rationale,
            citations=[CitationModel.from_domain(c) for c in memo.citations],
            requires_human_review=memo.requires_human_review,
            generated_at=memo.generated_at.isoformat(),
            request=(
                CreditRequestModel.from_domain(memo.request) if memo.request is not None else None
            ),
            spreads=[FinancialSpreadModel.from_domain(s) for s in memo.spreads],
            ratios=[RatioModel.from_domain(r) for r in memo.ratios],
            confidence=memo.confidence,
            caveats=list(memo.caveats),
            questions_for_client=list(memo.questions_for_client),
        )


class CovenantListResponse(BaseModel):
    borrower_id: str
    covenants: list[CovenantModel] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls, borrower_id: str, covenants: tuple[m.Covenant, ...]
    ) -> CovenantListResponse:
        return cls(
            borrower_id=borrower_id,
            covenants=[CovenantModel.from_domain(c) for c in covenants],
        )


class RiskFlagListResponse(BaseModel):
    borrower_id: str
    risk_flags: list[RiskFlagModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, borrower_id: str, flags: tuple[m.RiskFlag, ...]) -> RiskFlagListResponse:
        return cls(
            borrower_id=borrower_id,
            risk_flags=[RiskFlagModel.from_domain(f) for f in flags],
        )


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    status: str = "ok"
    profile: str = "local"
    #: Provenance the UI banner states on every page: where the runtime sits and which
    #: model answers. Derived server-side so the console never guesses (org decision,
    #: 2026-08-30).
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
    region: str = "asia-southeast1"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "credit-memo-drafting"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        return cls(**to_jsonable(card))
