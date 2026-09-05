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


class CandidateLineItemModel(BaseModel):
    """One figure extraction proposed, with where it says it read it.

    Outbound only. A candidate is what a MODEL asserted, so there is no inbound shape for
    it: a caller who wants to assert a figure supplies a ``LineItemModel``, which lands as
    ``user_entered`` and is theirs.
    """

    code: str
    period: str
    value: float
    currency: str = "SGD"
    document_id: str = ""
    page: int | None = None
    quote: str = ""
    confidence: float = 0.0
    provenance: str = "extracted"

    @classmethod
    def from_domain(cls, item: m.CandidateLineItem) -> CandidateLineItemModel:
        return cls(
            code=item.code.value,
            period=item.period,
            value=item.value,
            currency=item.currency,
            document_id=item.document_id,
            page=item.page,
            quote=item.quote,
            confidence=item.confidence,
            provenance=item.provenance.value,
        )


class SpreadCandidateModel(BaseModel):
    """What extraction proposes, before a person has looked at it."""

    borrower_id: str = ""
    periods: list[PeriodModel] = Field(default_factory=list)
    items: list[CandidateLineItemModel] = Field(default_factory=list)
    currency: str = "SGD"
    unit: str = "thousands"
    extractor: str = ""
    extractor_version: str = ""
    extracted_at: str = ""

    @classmethod
    def from_domain(cls, candidate: m.SpreadCandidate) -> SpreadCandidateModel:
        return cls(
            borrower_id=candidate.borrower_id,
            periods=[PeriodModel.from_domain(p) for p in candidate.periods],
            items=[CandidateLineItemModel.from_domain(i) for i in candidate.items],
            currency=candidate.currency,
            unit=candidate.unit,
            extractor=candidate.extractor,
            extractor_version=candidate.extractor_version,
            extracted_at=candidate.extracted_at.isoformat(),
        )


class SpreadExtractRequest(BaseModel):
    """Which documents to read the figures off, and which periods were asked for."""

    #: Empty means every document in the bundle. Naming them narrows an expensive call to
    #: the statements, rather than sending the facility letter to the extractor too.
    document_ids: list[str] = Field(default_factory=list)
    periods: list[PeriodModel] = Field(default_factory=list)
    currency: str = "SGD"
    unit: str = "thousands"


class RejectedLineModel(BaseModel):
    """A (code, period) slot the analyst threw out."""

    code: str
    period: str


class AdjustmentModel(BaseModel):
    """An analyst's replacement for an extracted figure, and why.

    There is no ``actor`` field: the adjustment is attributed to the server-verified
    principal. An adjustment whose author is whatever the body claimed is not an audit
    trail, and this is precisely the record a committee asks about.
    """

    code: str
    period: str
    before: float | None = None
    after: float
    reason: str = Field(..., min_length=1)

    def to_domain(self, actor: str) -> m.Adjustment:
        return m.Adjustment(
            code=m.LineItemCode(self.code),
            period=self.period,
            before=self.before,
            after=self.after,
            reason=self.reason,
            actor=actor,
        )

    @classmethod
    def from_domain(cls, adjustment: m.Adjustment) -> AdjustmentModel:
        return cls(
            code=adjustment.code.value,
            period=adjustment.period,
            before=adjustment.before,
            after=adjustment.after,
            reason=adjustment.reason,
        )


class SpreadConfirmRequest(BaseModel):
    """The analyst's verdict on the candidate this analysis already holds.

    Deliberately NOT a spread the caller composes. Confirmation applies to the recorded
    proposal, so the confirmed figures are provably the ones that were reviewed — a
    caller who could post their own table could produce a "confirmed" spread nobody ever
    saw next to a document.
    """

    rejected: list[RejectedLineModel] = Field(default_factory=list)
    adjustments: list[AdjustmentModel] = Field(default_factory=list)
    #: Figures extraction never proposed. They land as ``user_entered``: the analyst typed
    #: them, so they are the analyst's.
    added: list[LineItemModel] = Field(default_factory=list)


class SpreadsResponse(BaseModel):
    """Both halves of the spread step, so a console can render the review grid."""

    candidate: SpreadCandidateModel | None = None
    confirmed: FinancialSpreadModel | None = None


class ExternalIdsModel(BaseModel):
    """Public registers only. A bank's own customer number identifies a relationship
    rather than a company, does not travel between institutions, and has no business in a
    record that may be exported."""

    uen: str = ""
    lei: str = ""
    cik: str = ""
    company_number: str = ""

    def to_domain(self) -> m.ExternalIds:
        return m.ExternalIds(
            uen=self.uen, lei=self.lei, cik=self.cik, company_number=self.company_number
        )

    @classmethod
    def from_domain(cls, ids: m.ExternalIds) -> ExternalIdsModel:
        return cls(uen=ids.uen, lei=ids.lei, cik=ids.cik, company_number=ids.company_number)


class RelatedEntityModel(BaseModel):
    """Another company or person in this borrower's group, as the analyst declared it."""

    id: str = Field(..., min_length=1)
    name: str = ""
    role: str = "affiliate"
    #: The stake the PARENT holds, where stated. Never inferred: a consolidated statement
    #: does not reveal a shareholding, and guessing one puts a control assertion in the
    #: memo that nobody made.
    ownership_pct: float | None = None
    jurisdiction: str = ""
    external_ids: ExternalIdsModel = Field(default_factory=ExternalIdsModel)
    provenance: str = "user_entered"

    def to_domain(self) -> m.RelatedEntity:
        return m.RelatedEntity(
            id=self.id,
            name=self.name or self.id,
            role=m.EntityRole(self.role),
            ownership_pct=self.ownership_pct,
            jurisdiction=self.jurisdiction,
            external_ids=self.external_ids.to_domain(),
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, entity: m.RelatedEntity) -> RelatedEntityModel:
        return cls(
            id=entity.id,
            name=entity.name,
            role=entity.role.value,
            ownership_pct=entity.ownership_pct,
            jurisdiction=entity.jurisdiction,
            external_ids=ExternalIdsModel.from_domain(entity.external_ids),
            provenance=entity.provenance.value,
        )


class GuarantorModel(BaseModel):
    """Someone standing behind the facility, and how far.

    ``reliance`` is prose rather than a number on purpose: a personal guarantee from
    someone whose only asset is shares in the borrower supports nothing, and no field can
    express that.
    """

    entity_id: str = Field(..., min_length=1)
    name: str = ""
    is_personal: bool = False
    support_amount: float | None = None
    currency: str = "SGD"
    limited: bool = True
    reliance: str = ""
    provenance: str = "user_entered"

    def to_domain(self) -> m.Guarantor:
        return m.Guarantor(
            entity_id=self.entity_id,
            name=self.name or self.entity_id,
            is_personal=self.is_personal,
            support_amount=self.support_amount,
            currency=self.currency,
            limited=self.limited,
            reliance=self.reliance,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, guarantor: m.Guarantor) -> GuarantorModel:
        return cls(
            entity_id=guarantor.entity_id,
            name=guarantor.name,
            is_personal=guarantor.is_personal,
            support_amount=guarantor.support_amount,
            currency=guarantor.currency,
            limited=guarantor.limited,
            reliance=guarantor.reliance,
            provenance=guarantor.provenance.value,
        )


class EliminationModel(BaseModel):
    """One intercompany amount removed on consolidation, and what it was."""

    code: str
    period: str
    amount: float
    between: str = ""
    reason: str = ""

    def to_domain(self) -> m.Elimination:
        return m.Elimination(
            code=m.LineItemCode(self.code),
            period=self.period,
            amount=self.amount,
            between=self.between,
            reason=self.reason,
        )

    @classmethod
    def from_domain(cls, elimination: m.Elimination) -> EliminationModel:
        return cls(
            code=elimination.code.value,
            period=elimination.period,
            amount=elimination.amount,
            between=elimination.between,
            reason=elimination.reason,
        )


class EntityGroupModel(BaseModel):
    """A public register's view of who else is in this group.

    A suggestion about who exists, never a figure. Every member is `vendor`-provenanced and
    a related entity holds no number, so an entity named here that nobody uploads statements
    for lands on the memo as one the consolidation could not include — which is exactly the
    outcome that keeps a global cash flow honest.
    """

    subject: RelatedEntityModel
    members: list[RelatedEntityModel] = Field(default_factory=list)
    source: str = ""
    as_of: str = ""
    quality: str = "ambiguous"
    #: Not the same as an empty ``members``: this is the register saying the company
    #: reported no parent, where empty can also mean it holds nothing for this company.
    register_reports_no_parent: bool = False
    coverage_note: str = ""
    candidates: list[str] = Field(default_factory=list)
    found_nothing: bool = True

    @classmethod
    def from_domain(cls, group: m.EntityGroup) -> EntityGroupModel:
        return cls(
            subject=RelatedEntityModel.from_domain(group.subject),
            members=[RelatedEntityModel.from_domain(e) for e in group.members],
            source=group.source,
            as_of=group.as_of.isoformat(),
            quality=group.quality.value,
            register_reports_no_parent=group.register_reports_no_parent,
            coverage_note=group.coverage_note,
            candidates=list(group.candidates),
            found_nothing=group.found_nothing,
        )


class AnalysisBuildRequest(BaseModel):
    """Build the memo for an analysis that already holds its uploaded evidence.

    The borrower and the documents are not repeated here: they are in the bundle. What
    the caller supplies is the ask, the confirmed spread and the group, which are the
    things a person decides rather than uploads.
    """

    request: CreditRequestModel | None = None
    spreads: list[FinancialSpreadModel] = Field(default_factory=list)
    #: The group, as the analyst declares it for THIS analysis. There is no standing
    #: ownership graph, so an entity named here with no confirmed figures below is
    #: reported on the memo as one the consolidation could not include — a weaker and
    #: truer claim than leaving it out, which reads as contributing nothing.
    related_entities: list[RelatedEntityModel] = Field(default_factory=list)
    guarantors: list[GuarantorModel] = Field(default_factory=list)
    #: Confirmed figures per entity id, for the entities whose statements were uploaded.
    entity_spreads: dict[str, FinancialSpreadModel] = Field(default_factory=dict)
    #: Intercompany amounts to remove, each saying what it is and between whom. Shown on
    #: the memo rather than netted away.
    eliminations: list[EliminationModel] = Field(default_factory=list)


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
    #: Display only. The id governs the ACL and every entitlement check.
    borrower_name: str = ""
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
            borrower_name=manifest.borrower_name,
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


class EntityContributionModel(BaseModel):
    """What one entity put into a consolidated line.

    Present because a consolidated EBITDA of 115 says nothing about whether that is one
    strong entity and two weak ones, which is the difference between a group that can
    support the facility and one where a single subsidiary can.
    """

    entity_id: str
    entity_name: str
    role: str
    value: float

    @classmethod
    def from_domain(cls, c: m.EntityContribution) -> EntityContributionModel:
        return cls(
            entity_id=c.entity_id, entity_name=c.entity_name, role=c.role.value, value=c.value
        )


class GlobalCashFlowLineModel(BaseModel):
    code: str
    period: str
    total: float
    contributions: list[EntityContributionModel] = Field(default_factory=list)
    eliminations: list[EliminationModel] = Field(default_factory=list)
    provenance: str = "computed"

    @classmethod
    def from_domain(cls, line: m.GlobalCashFlowLine) -> GlobalCashFlowLineModel:
        return cls(
            code=line.code.value,
            period=line.period,
            total=line.total,
            contributions=[EntityContributionModel.from_domain(c) for c in line.contributions],
            eliminations=[EliminationModel.from_domain(e) for e in line.eliminations],
            provenance=line.provenance.value,
        )


class GlobalCashFlowModel(BaseModel):
    """Whose cash actually services this debt.

    ``entities_without_figures`` is the field that keeps the whole calculation honest: a
    consolidation that silently omits the guarantor whose accounts nobody uploaded reads
    as though that guarantor contributes nothing, which is a stronger claim than "we did
    not look".
    """

    periods: list[str] = Field(default_factory=list)
    lines: list[GlobalCashFlowLineModel] = Field(default_factory=list)
    entities: list[RelatedEntityModel] = Field(default_factory=list)
    entities_without_figures: list[str] = Field(default_factory=list)
    currency: str = "SGD"
    complete: bool = True

    @classmethod
    def from_domain(cls, gcf: m.GlobalCashFlow) -> GlobalCashFlowModel:
        return cls(
            periods=list(gcf.periods),
            lines=[GlobalCashFlowLineModel.from_domain(line) for line in gcf.lines],
            entities=[RelatedEntityModel.from_domain(e) for e in gcf.entities],
            entities_without_figures=list(gcf.entities_without_figures),
            currency=gcf.currency,
            complete=gcf.complete,
        )


class ScenarioResultModel(BaseModel):
    """The shocked value, and the number underneath it.

    ``breaks_at`` is a severity multiple of the scenario: 2.0 means the borrower takes
    twice the shock. A committee cannot judge whether a 15% decline is the right test for
    this sector; they can judge "it survives twice that".
    """

    scenario_id: str
    scenario_name: str
    formula_id: str
    period: str
    base_value: float | None = None
    stressed_value: float | None = None
    threshold: float | None = None
    passes: bool | None = None
    breaks_at: float | None = None
    provenance: str = "computed"

    @classmethod
    def from_domain(cls, r: m.ScenarioResult) -> ScenarioResultModel:
        return cls(
            scenario_id=r.scenario_id,
            scenario_name=r.scenario_name,
            formula_id=r.formula_id,
            period=r.period,
            base_value=r.base_value,
            stressed_value=r.stressed_value,
            threshold=r.threshold,
            passes=r.passes,
            breaks_at=r.breaks_at,
            provenance=r.provenance.value,
        )


class TieOutFindingModel(BaseModel):
    """One reconciliation a credit file did not survive.

    Carried to the client and into the pack because a memo that quietly drops a failed
    balance-sheet check reads exactly like one that passed it.
    """

    check: str
    severity: str
    detail: str
    expected: float | None = None
    actual: float | None = None
    document_id: str = ""
    page: int | None = None
    period: str = ""

    def to_domain(self) -> m.TieOutFinding:
        return m.TieOutFinding(
            check=m.TieOutCheck(self.check),
            severity=m.Severity(self.severity),
            detail=self.detail,
            expected=self.expected,
            actual=self.actual,
            document_id=self.document_id,
            page=self.page,
            period=self.period,
        )

    @classmethod
    def from_domain(cls, f: m.TieOutFinding) -> TieOutFindingModel:
        return cls(
            check=f.check.value,
            severity=f.severity.value,
            detail=f.detail,
            expected=f.expected,
            actual=f.actual,
            document_id=f.document_id,
            page=f.page,
            period=f.period,
        )


class PolicyExceptionModel(BaseModel):
    """A breach of the bank's OWN uploaded limit, measured arithmetically."""

    rule_id: str
    description: str
    measured: float | None = None
    limit: float | None = None
    operator: str
    severity: str
    waiver_authority: str = ""
    period: str = ""
    provenance: str = "computed"
    detail: str = ""
    citation: str = ""

    def to_domain(self) -> m.PolicyException:
        return m.PolicyException(
            rule_id=self.rule_id,
            description=self.description,
            measured=self.measured,
            limit=self.limit,
            operator=m.PolicyOperator(self.operator),
            severity=m.Severity(self.severity),
            waiver_authority=self.waiver_authority,
            period=self.period,
            provenance=m.Provenance(self.provenance),
            detail=self.detail,
            citation=self.citation,
        )

    @classmethod
    def from_domain(cls, e: m.PolicyException) -> PolicyExceptionModel:
        return cls(
            rule_id=e.rule_id,
            description=e.description,
            measured=e.measured,
            limit=e.limit,
            operator=e.operator.value,
            severity=e.severity.value,
            waiver_authority=e.waiver_authority,
            period=e.period,
            provenance=e.provenance.value,
            detail=e.detail,
            citation=e.citation,
        )


class RatingDriverModel(BaseModel):
    name: str
    measured: float | None = None
    band: str = ""
    points: float = 0.0
    weight: float = 1.0
    detail: str = ""

    def to_domain(self) -> m.RatingDriver:
        return m.RatingDriver(
            name=self.name,
            measured=self.measured,
            band=self.band,
            points=self.points,
            weight=self.weight,
            detail=self.detail,
        )

    @classmethod
    def from_domain(cls, d: m.RatingDriver) -> RatingDriverModel:
        return cls(
            name=d.name,
            measured=d.measured,
            band=d.band,
            points=d.points,
            weight=d.weight,
            detail=d.detail,
        )


class RiskRatingProposalModel(BaseModel):
    """A grade this service PROPOSES from the bank's own scorecard. Never one of record."""

    obligor_grade: str
    score: float
    drivers: list[RatingDriverModel] = Field(default_factory=list)
    scorecard_version: str = ""
    definitions_url: str = ""
    rationale: str = ""
    facility_grade: str = ""
    provenance: str = "computed"

    def to_domain(self) -> m.RiskRatingProposal:
        return m.RiskRatingProposal(
            obligor_grade=self.obligor_grade,
            score=self.score,
            drivers=tuple(d.to_domain() for d in self.drivers),
            scorecard_version=self.scorecard_version,
            definitions_url=self.definitions_url,
            rationale=self.rationale,
            facility_grade=self.facility_grade,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, r: m.RiskRatingProposal) -> RiskRatingProposalModel:
        return cls(
            obligor_grade=r.obligor_grade,
            score=r.score,
            drivers=[RatingDriverModel.from_domain(d) for d in r.drivers],
            scorecard_version=r.scorecard_version,
            definitions_url=r.definitions_url,
            rationale=r.rationale,
            facility_grade=r.facility_grade,
            provenance=r.provenance.value,
        )


class SectionDeltaModel(BaseModel):
    """One line that moved between a prior memo and this one."""

    label: str
    before: float | None = None
    after: float | None = None
    unit: str = ""
    detail: str = ""

    def to_domain(self) -> m.SectionDelta:
        return m.SectionDelta(
            label=self.label,
            before=self.before,
            after=self.after,
            unit=self.unit,
            detail=self.detail,
        )

    @classmethod
    def from_domain(cls, d: m.SectionDelta) -> SectionDeltaModel:
        return cls(label=d.label, before=d.before, after=d.after, unit=d.unit, detail=d.detail)


class RenewalDeltaModel(BaseModel):
    """What moved since the memo before it."""

    prior_version: str = ""
    prior_at: str = ""
    ratios: list[SectionDeltaModel] = Field(default_factory=list)
    spread: list[SectionDeltaModel] = Field(default_factory=list)
    covenants: list[SectionDeltaModel] = Field(default_factory=list)
    rating_before: str = ""
    rating_after: str = ""
    new_exceptions: list[str] = Field(default_factory=list)
    cleared_exceptions: list[str] = Field(default_factory=list)
    unchanged_sections: list[str] = Field(default_factory=list)

    def to_domain(self) -> m.RenewalDelta:
        return m.RenewalDelta(
            prior_version=self.prior_version,
            prior_at=self.prior_at,
            ratios=tuple(d.to_domain() for d in self.ratios),
            spread=tuple(d.to_domain() for d in self.spread),
            covenants=tuple(d.to_domain() for d in self.covenants),
            rating_before=self.rating_before,
            rating_after=self.rating_after,
            new_exceptions=tuple(self.new_exceptions),
            cleared_exceptions=tuple(self.cleared_exceptions),
            unchanged_sections=tuple(self.unchanged_sections),
        )

    @classmethod
    def from_domain(cls, d: m.RenewalDelta) -> RenewalDeltaModel:
        return cls(
            prior_version=d.prior_version,
            prior_at=d.prior_at,
            ratios=[SectionDeltaModel.from_domain(x) for x in d.ratios],
            spread=[SectionDeltaModel.from_domain(x) for x in d.spread],
            covenants=[SectionDeltaModel.from_domain(x) for x in d.covenants],
            rating_before=d.rating_before,
            rating_after=d.rating_after,
            new_exceptions=list(d.new_exceptions),
            cleared_exceptions=list(d.cleared_exceptions),
            unchanged_sections=list(d.unchanged_sections),
        )


class ConditionModel(BaseModel):
    """A condition precedent or subsequent.

    Conditions are the memo's only output that outlives the decision, which is why they
    carry an owner and a due date rather than sitting in prose.
    """

    kind: str
    detail: str
    owner: str = ""
    due: str = ""
    provenance: str = "model_drafted"

    def to_domain(self) -> m.Condition:
        return m.Condition(
            kind=m.ConditionKind(self.kind),
            detail=self.detail,
            owner=self.owner,
            due=self.due,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, c: m.Condition) -> ConditionModel:
        return cls(
            kind=c.kind.value,
            detail=c.detail,
            owner=c.owner,
            due=c.due,
            provenance=c.provenance.value,
        )


class DeclineReasonModel(BaseModel):
    """Why the ask was not supported, in a form a decline notice can be written from.

    Structured rather than prose because ECOA / Regulation B 12 CFR 1002.9(a)(3) requires
    the specific principal reasons, and a paragraph is not a list of them.
    """

    detail: str
    rule_id: str = ""
    measured: float | None = None
    limit: float | None = None
    provenance: str = "computed"

    def to_domain(self) -> m.DeclineReason:
        return m.DeclineReason(
            detail=self.detail,
            rule_id=self.rule_id,
            measured=self.measured,
            limit=self.limit,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, d: m.DeclineReason) -> DeclineReasonModel:
        return cls(
            detail=d.detail,
            rule_id=d.rule_id,
            measured=d.measured,
            limit=d.limit,
            provenance=d.provenance.value,
        )


class RecommendationModel(BaseModel):
    """The ask, its conditions and the authority it needs — or why it was not supported."""

    action: str = ""
    conditions: list[ConditionModel] = Field(default_factory=list)
    decline_reasons: list[DeclineReasonModel] = Field(default_factory=list)
    required_authority: str = ""
    provenance: str = "model_drafted"

    def to_domain(self) -> m.Recommendation:
        return m.Recommendation(
            action=self.action,
            conditions=tuple(c.to_domain() for c in self.conditions),
            decline_reasons=tuple(d.to_domain() for d in self.decline_reasons),
            required_authority=self.required_authority,
            provenance=m.Provenance(self.provenance),
        )

    @classmethod
    def from_domain(cls, r: m.Recommendation) -> RecommendationModel:
        return cls(
            action=r.action,
            conditions=[ConditionModel.from_domain(c) for c in r.conditions],
            decline_reasons=[DeclineReasonModel.from_domain(d) for d in r.decline_reasons],
            required_authority=r.required_authority,
            provenance=r.provenance.value,
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
    #: Everything below was COMPUTED by the pipeline and dropped on the floor here: the
    #: response carried none of it, so no client ever saw a policy exception or a failed
    #: reconciliation, and the exported committee pack — rebuilt from this shape — read as
    #: though there had been none. `test_the_wire_shape_carries_every_memo_field` now
    #: fails if a future field is added to the memo and forgotten here.
    tie_out: list[TieOutFindingModel] = Field(default_factory=list)
    policy_exceptions: list[PolicyExceptionModel] = Field(default_factory=list)
    policy_version: str = ""
    rating: RiskRatingProposalModel | None = None
    recommendation: RecommendationModel | None = None
    renewal_delta: RenewalDeltaModel | None = None
    #: The group, and how far it can fall.
    related_entities: list[RelatedEntityModel] = Field(default_factory=list)
    guarantors: list[GuarantorModel] = Field(default_factory=list)
    global_cash_flow: GlobalCashFlowModel | None = None
    scenarios: list[ScenarioResultModel] = Field(default_factory=list)
    #: Which sections a person wrote or edited.
    authorship: dict[str, str] = Field(default_factory=dict)
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
            tie_out=[TieOutFindingModel.from_domain(f) for f in memo.tie_out],
            policy_exceptions=[PolicyExceptionModel.from_domain(e) for e in memo.policy_exceptions],
            policy_version=memo.policy_version,
            rating=(
                RiskRatingProposalModel.from_domain(memo.rating)
                if memo.rating is not None
                else None
            ),
            recommendation=(
                RecommendationModel.from_domain(memo.recommendation)
                if memo.recommendation is not None
                else None
            ),
            renewal_delta=(
                RenewalDeltaModel.from_domain(memo.renewal_delta)
                if memo.renewal_delta is not None
                else None
            ),
            related_entities=[RelatedEntityModel.from_domain(e) for e in memo.related_entities],
            guarantors=[GuarantorModel.from_domain(g) for g in memo.guarantors],
            global_cash_flow=(
                GlobalCashFlowModel.from_domain(memo.global_cash_flow)
                if memo.global_cash_flow is not None
                else None
            ),
            scenarios=[ScenarioResultModel.from_domain(r) for r in memo.scenarios],
            authorship=dict(memo.authorship),
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
        tie_out=tuple(f.to_domain() for f in response.tie_out),
        policy_exceptions=tuple(e.to_domain() for e in response.policy_exceptions),
        policy_version=response.policy_version,
        rating=response.rating.to_domain() if response.rating is not None else None,
        recommendation=(
            response.recommendation.to_domain() if response.recommendation is not None else None
        ),
        renewal_delta=(
            response.renewal_delta.to_domain() if response.renewal_delta is not None else None
        ),
        related_entities=tuple(e.to_domain() for e in response.related_entities),
        guarantors=tuple(g.to_domain() for g in response.guarantors),
        global_cash_flow=_global_cash_flow_to_domain(response.global_cash_flow),
        scenarios=tuple(_scenario_to_domain(r) for r in response.scenarios),
        authorship=dict(response.authorship),
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


def _global_cash_flow_to_domain(model: GlobalCashFlowModel | None) -> m.GlobalCashFlow | None:
    """The consolidation as the domain type, or None when there was no group.

    ``complete`` is not carried across: it is derived from
    ``entities_without_figures``, and a stored boolean that disagrees with the list it
    summarises is the kind of contradiction nobody notices until a committee does.
    """
    if model is None:
        return None
    return m.GlobalCashFlow(
        periods=tuple(model.periods),
        lines=tuple(
            m.GlobalCashFlowLine(
                code=m.LineItemCode(line.code),
                period=line.period,
                total=line.total,
                contributions=tuple(
                    m.EntityContribution(
                        entity_id=c.entity_id,
                        entity_name=c.entity_name,
                        role=m.EntityRole(c.role),
                        value=c.value,
                    )
                    for c in line.contributions
                ),
                eliminations=tuple(e.to_domain() for e in line.eliminations),
                provenance=m.Provenance(line.provenance),
            )
            for line in model.lines
        ),
        entities=tuple(e.to_domain() for e in model.entities),
        entities_without_figures=tuple(model.entities_without_figures),
        currency=model.currency,
    )


def _scenario_to_domain(model: ScenarioResultModel) -> m.ScenarioResult:
    return m.ScenarioResult(
        scenario_id=model.scenario_id,
        scenario_name=model.scenario_name,
        formula_id=model.formula_id,
        period=model.period,
        base_value=model.base_value,
        stressed_value=model.stressed_value,
        threshold=model.threshold,
        passes=model.passes,
        breaks_at=model.breaks_at,
        provenance=m.Provenance(model.provenance),
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
        borrower_name=model.borrower_name,
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


class SectionEditModel(BaseModel):
    """One analyst change to one section, with what it said before."""

    section: str
    before: str
    after: str
    actor: str
    at: str = ""
    reason: str = ""

    @classmethod
    def from_domain(cls, edit: m.SectionEdit) -> SectionEditModel:
        return cls(
            section=edit.section,
            before=edit.before,
            after=edit.after,
            actor=edit.actor,
            at=edit.at.isoformat(),
            reason=edit.reason,
        )


class MemoRevisionModel(BaseModel):
    """One saved version, chained to the one before it.

    ``memo_json`` is the whole memo as it stood, not a patch: a committee that approved
    revision 3 approved a document, and reconstructing it from deltas is a chance to
    reconstruct it wrongly.
    """

    revision: int
    memo_json: dict = Field(default_factory=dict)
    actor: str
    digest: str = ""
    parent_digest: str = ""
    edits: list[SectionEditModel] = Field(default_factory=list)
    authorship: dict[str, str] = Field(default_factory=dict)
    at: str = ""
    note: str = ""

    def to_domain(self) -> m.MemoRevision:
        return m.MemoRevision(
            revision=self.revision,
            memo_json=self.memo_json,
            actor=self.actor,
            digest=self.digest,
            parent_digest=self.parent_digest,
            edits=tuple(
                m.SectionEdit(
                    section=e.section,
                    before=e.before,
                    after=e.after,
                    actor=e.actor,
                    at=datetime.fromisoformat(e.at) if e.at else m.utcnow(),
                    reason=e.reason,
                )
                for e in self.edits
            ),
            authorship=dict(self.authorship),
            at=datetime.fromisoformat(self.at) if self.at else m.utcnow(),
            note=self.note,
        )

    @classmethod
    def from_domain(cls, revision: m.MemoRevision) -> MemoRevisionModel:
        return cls(
            revision=revision.revision,
            memo_json=revision.memo_json,
            actor=revision.actor,
            digest=revision.digest,
            parent_digest=revision.parent_digest,
            edits=[SectionEditModel.from_domain(e) for e in revision.edits],
            authorship=dict(revision.authorship),
            at=revision.at.isoformat(),
            note=revision.note,
        )


class MemoAmendRequest(BaseModel):
    """Rewrite one or more prose sections of the memo.

    Only the prose. The figures belong to the deterministic engines, and a memo whose
    leverage could be typed over by hand would put a number in front of a committee that
    no formula produced. An unknown section name is a 422 rather than a silent no-op.
    """

    sections: dict[str, str] = Field(..., min_length=1)
    reason: str = ""
    note: str = ""


class RevisionListResponse(BaseModel):
    """The chain, and whether it still holds.

    ``chain_intact`` is recomputed on read rather than stored. A stored flag says what
    was true when it was written, which is the one moment nobody is asking about.
    """

    revisions: list[MemoRevisionModel] = Field(default_factory=list)
    chain_intact: bool = True
    chain_detail: str = ""


class MemoCommentModel(BaseModel):
    """One reviewer's note, and whether the text it was written against has moved.

    ``stale`` is computed on read against the revision chain rather than stored. A stored
    flag says what was true when it was written, which for this field is the one moment
    nobody is asking about.
    """

    id: str
    section: str
    body: str
    author: str
    revision: int
    at: str = ""
    anchor_digest: str = ""
    resolved_by: str = ""
    resolved_at: str | None = None
    resolution: str = ""
    open: bool = True
    #: The section changed after this was written. Still open — nobody answered it — but a
    #: reader has to re-read it against the new text rather than assume it was addressed.
    stale: bool = False

    def to_domain(self) -> m.MemoComment:
        return m.MemoComment(
            id=self.id,
            section=self.section,
            body=self.body,
            author=self.author,
            revision=self.revision,
            at=datetime.fromisoformat(self.at) if self.at else m.utcnow(),
            anchor_digest=self.anchor_digest,
            resolved_by=self.resolved_by,
            resolved_at=datetime.fromisoformat(self.resolved_at) if self.resolved_at else None,
            resolution=self.resolution,
        )

    @classmethod
    def from_domain(cls, comment: m.MemoComment, stale: bool = False) -> MemoCommentModel:
        return cls(
            id=comment.id,
            section=comment.section,
            body=comment.body,
            author=comment.author,
            revision=comment.revision,
            at=comment.at.isoformat(),
            anchor_digest=comment.anchor_digest,
            resolved_by=comment.resolved_by,
            resolved_at=comment.resolved_at.isoformat() if comment.resolved_at else None,
            resolution=comment.resolution,
            open=comment.open,
            stale=stale,
        )


class CommentCreateRequest(BaseModel):
    """A note against one section. There is no author field: it is the verified principal."""

    section: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class CommentResolveRequest(BaseModel):
    """Closing a comment says what was done about it, not merely that it is closed."""

    resolution: str = ""


class CommentListResponse(BaseModel):
    comments: list[MemoCommentModel] = Field(default_factory=list)
    open_count: int = 0
    stale_count: int = 0


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
