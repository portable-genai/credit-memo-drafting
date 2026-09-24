"""FastAPI dependency wiring for the B2 Credit-Memo / Underwriting Assistant.

This module builds a single, process-wide :class:`~credit_memo.config.Container` (the
ports-and-adapters registry) and assembles the orchestration services from the
Container's port instances. The Container is created lazily on first access so importing
this module (and therefore the FastAPI app) never touches Google Cloud: a unit test or
the on-prem profile can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. Services take *explicit port
instances* in their constructors (SPEC §5), so the wiring here is the single place that
knows which ports each service needs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from ..adapters.controls import DisclosingRedaction, RecordingReviewRouter
from ..config import Container, Settings, build_container
from ..domain.services import (
    CovenantService,
    CreditMemoService,
    PeerCompService,
    RiskFlagService,
)


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use."""
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, models...)."""
    return get_container().settings


# --------------------------------------------------------------------------- #
# Service factories — assemble each service from the Container's ports.
# --------------------------------------------------------------------------- #


def get_request_redaction() -> DisclosingRedaction:
    """The redaction adapter for ONE request, wrapped so the response can disclose a change.

    FastAPI resolves a dependency once per request, so the route and the service it builds
    receive the same wrapper and the route reads what the service's redaction did.
    """
    return DisclosingRedaction(get_container().redaction)


def get_request_review_router() -> RecordingReviewRouter:
    """The review router for ONE request, wrapped so the response reports the hand-off."""
    return RecordingReviewRouter(get_container().review_router)


#: Injected by FastAPI; ``None`` when a getter is called directly (the MCP server does), which
#: binds the container's adapters unwrapped.
RequestRedaction = Annotated[DisclosingRedaction | None, Depends(get_request_redaction)]
RequestReviewRouter = Annotated[RecordingReviewRouter | None, Depends(get_request_review_router)]


def get_credit_memo_service(
    redaction: RequestRedaction = None, review_router: RequestReviewRouter = None
) -> CreditMemoService:
    """CreditMemoService(extraction, knowledge_base, peer_data, llm, guardrail,
    redaction, tracer, audit)."""
    return build_credit_memo_service(
        get_container(), redaction=redaction, review_router=review_router
    )


def build_credit_memo_service(
    container: Container, *, redaction: Any = None, review_router: Any = None
) -> CreditMemoService:
    """Assemble a :class:`CreditMemoService` from an explicit Container."""
    return CreditMemoService(
        extraction=container.extraction,
        knowledge_base=container.knowledge_base,
        peer_data=container.peer_data,
        llm=container.llm,
        guardrail=container.guardrail,
        redaction=redaction or container.redaction,
        tracer=container.tracer,
        audit=container.audit,
        review_router=review_router or container.review_router,
        covenant_at_risk_band=container.settings.policy.covenant_at_risk_band,
        analysis_bundle=container.analysis_bundle,
        policy_pack=container.policy_pack,
    )


def build_covenant_service(container: Container) -> CovenantService:
    """Assemble a :class:`CovenantService` from an explicit Container."""
    return CovenantService(
        llm=container.llm,
        tracer=container.tracer,
        at_risk_band=container.settings.policy.covenant_at_risk_band,
    )


def build_risk_flag_service(container: Container) -> RiskFlagService:
    """Assemble a :class:`RiskFlagService` from an explicit Container."""
    return RiskFlagService(llm=container.llm, tracer=container.tracer)


def build_peer_comp_service(container: Container) -> PeerCompService:
    """Assemble a :class:`PeerCompService` from an explicit Container."""
    return PeerCompService(peer_data=container.peer_data, tracer=container.tracer)


def create_app():  # -> fastapi.FastAPI
    """Application factory used by uvicorn (``--factory``) and the CLI ``serve`` command."""
    from .app import app

    return app
