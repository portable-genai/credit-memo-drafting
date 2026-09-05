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

from datetime import datetime

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


class AnalysisBuildRequest(BaseModel):
    """Build the memo for an analysis that already holds its uploaded evidence.

    The borrower and the documents are not repeated here: they are in the bundle. What
    the caller supplies is the ask and the confirmed spread, which are the two things a
    person decides rather than uploads.
    """

    request: CreditRequestModel | None = None
    spreads: list[FinancialSpreadModel] = Field(default_factory=list)


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


class StoredDocumentModel(BaseModel):
    """One file this analysis was given, as the manifest states it."""

    id: str
    filename: str
    doc_type: str
    mime_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    pages: int = 0
    declared_as_of: str = ""
    uploaded_at: str = ""
    uploaded_by: str = ""
    third_party_sourced: bool = False

    @classmethod
    def from_domain(cls, document: m.StoredDocument) -> StoredDocumentModel:
        return cls(
            id=document.id,
            filename=document.filename,
            doc_type=document.doc_type.value,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
            pages=document.pages,
            declared_as_of=document.declared_as_of,
            uploaded_at=document.uploaded_at.isoformat(),
            uploaded_by=document.uploaded_by,
            third_party_sourced=document.third_party_sourced,
        )


class AnalysisManifestModel(BaseModel):
    """Exactly which files fed this analysis, and until when it can be reopened."""

    analysis_id: str
    borrower_id: str
    documents: list[StoredDocumentModel] = Field(default_factory=list)
    created_at: str = ""
    expires_at: str | None = None
    created_by: str = ""
    #: Said in words as well as as a date, because "available until 20 September" is what
    #: a reader needs and an ISO timestamp is what a machine needs.
    retention_note: str = ""

    @classmethod
    def from_domain(cls, manifest: m.AnalysisManifest) -> AnalysisManifestModel:
        expires = manifest.expires_at
        note = (
            f"This analysis and the {len(manifest.documents)} file(s) it used are "
            f"available until {expires.date().isoformat()}, then deleted."
            if expires
            else "No retention window is configured for this analysis."
        )
        return cls(
            analysis_id=manifest.analysis_id,
            borrower_id=manifest.borrower_id,
            documents=[StoredDocumentModel.from_domain(d) for d in manifest.documents],
            created_at=manifest.created_at.isoformat(),
            expires_at=expires.isoformat() if expires else None,
            created_by=manifest.created_by,
            retention_note=note,
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
    manifest: AnalysisManifestModel | None = None

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
            manifest=(
                AnalysisManifestModel.from_domain(memo.manifest)
                if memo.manifest is not None
                else None
            ),
        )


def to_domain_memo(response: CreditMemoResponse) -> m.CreditMemo:
    """Rebuild the domain memo from its wire form.

    The honest inverse of ``from_domain``, needed wherever a stored memo has to become a
    domain object again: exporting the pack a committee reviewed, diffing a renewal
    against it, replaying it. A partial reconstruction would be worse than none — an
    exporter silently missing the policy exceptions produces a pack that reads as though
    there were none.

    Enums are re-parsed rather than trusted, so a stored memo from a version that has
    since renamed a value fails here rather than three layers down.
    """
    return m.CreditMemo(
        borrower=response.borrower.to_domain(),
        summary=response.summary,
        financial_metrics=tuple(
            m.FinancialMetric(name=x.name, value=x.value, period=x.period, currency=x.currency)
            for x in response.financial_metrics
        ),
        covenants=tuple(_covenant_to_domain(c) for c in response.covenants),
        risk_flags=tuple(
            m.RiskFlag(
                category=m.RiskCategory(f.category),
                severity=m.Severity(f.severity),
                detail=f.detail,
                citations=tuple(_citation_to_domain(c) for c in f.citations),
            )
            for f in response.risk_flags
        ),
        peer_comparison=tuple(
            m.PeerComparison(
                metric=p.metric,
                borrower_value=p.borrower_value,
                peer_median=p.peer_median,
                percentile=p.percentile,
                peers=tuple(
                    m.PeerMetric(peer_name=q.peer_name, metric=q.metric, value=q.value)
                    for q in p.peers
                ),
            )
            for p in response.peer_comparison
        ),
        recommendation_rationale=response.recommendation_rationale,
        citations=tuple(_citation_to_domain(c) for c in response.citations),
        requires_human_review=response.requires_human_review,
        generated_at=(
            datetime.fromisoformat(response.generated_at) if response.generated_at else m.utcnow()
        ),
        request=response.request.to_domain() if response.request else None,
        spreads=tuple(x.to_domain() for x in response.spreads),
        ratios=tuple(_ratio_to_domain(r) for r in response.ratios),
        confidence=response.confidence,
        caveats=tuple(response.caveats),
        questions_for_client=tuple(response.questions_for_client),
        manifest=_manifest_to_domain(response.manifest) if response.manifest else None,
    )


def _citation_to_domain(model: CitationModel) -> m.Citation:
    return m.Citation(
        source_id=model.source_id,
        source_type=m.SourceType(model.source_type),
        title=model.title,
        url=model.url,
        page=model.page,
        snippet=model.snippet,
        score=model.score,
    )


def _ratio_to_domain(model: RatioModel) -> m.Ratio:
    return m.Ratio(
        formula_id=model.formula_id,
        name=model.name,
        period=model.period,
        value=model.value,
        unit=model.unit,
        higher_is_better=model.higher_is_better,
        inputs=tuple(
            m.RatioInput(
                code=m.LineItemCode(i.code),
                period=i.period,
                value=i.value,
                coefficient=i.coefficient,
                side=i.side,
            )
            for i in model.inputs
        ),
        definition=model.definition,
        reason_missing=model.reason_missing,
    )


def _covenant_to_domain(model: CovenantModel) -> m.Covenant:
    return m.Covenant(
        type=m.CovenantType(model.type),
        description=model.description,
        threshold=model.threshold,
        operator=m.CovenantOperator(model.operator),
        current_value=model.current_value,
        status=m.CovenantStatus(model.status),
        period=model.period,
        citations=tuple(_citation_to_domain(c) for c in model.citations),
        measured=_ratio_to_domain(model.measured) if model.measured else None,
        reported_value=model.reported_value,
        value_provenance=m.Provenance(model.value_provenance),
    )


def _manifest_to_domain(model: AnalysisManifestModel) -> m.AnalysisManifest:
    return m.AnalysisManifest(
        analysis_id=model.analysis_id,
        borrower_id=model.borrower_id,
        documents=tuple(
            m.StoredDocument(
                id=d.id,
                filename=d.filename,
                doc_type=m.DocType(d.doc_type),
                mime_type=d.mime_type,
                size_bytes=d.size_bytes,
                sha256=d.sha256,
                pages=d.pages,
                declared_as_of=d.declared_as_of,
                uploaded_at=datetime.fromisoformat(d.uploaded_at) if d.uploaded_at else m.utcnow(),
                uploaded_by=d.uploaded_by,
                third_party_sourced=d.third_party_sourced,
            )
            for d in model.documents
        ),
        created_at=datetime.fromisoformat(model.created_at) if model.created_at else m.utcnow(),
        expires_at=datetime.fromisoformat(model.expires_at) if model.expires_at else None,
        created_by=model.created_by,
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
