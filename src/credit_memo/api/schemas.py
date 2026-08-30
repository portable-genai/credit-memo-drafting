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


class CreditMemoRequest(BaseModel):
    """Inbound request to build a full credit memo.

    There is no ``actor`` field: the audit actor is the server-verified ``Principal``
    (``api/security.py``), never a client-asserted identity.
    """

    borrower: BorrowerModel
    documents: list[DocumentModel] = Field(default_factory=list)

    def to_memo_input(self) -> m.MemoInput:
        return m.MemoInput(
            borrower=self.borrower.to_domain(),
            documents=tuple(d.to_domain() for d in self.documents),
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


class CovenantModel(BaseModel):
    type: str
    description: str
    threshold: float
    operator: str
    current_value: float | None = None
    status: str
    period: str = ""
    citations: list[CitationModel] = Field(default_factory=list)

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
