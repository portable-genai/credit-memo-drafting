"""A2A AgentCard for the B2 Credit-Memo Assistant (A3 Registry & Governance).

This builds the agent's discovery card (the same minimal A2A shape the
``agent-registry`` service stores and serves, SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises the four credit-memo skills B2 produces (build_credit_memo,
extract_covenants, flag_risks, peer_compare), mirroring the ADK FunctionTools so a peer
agent or the registry sees one consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="build_credit_memo",
        name="Credit-memo assembly",
        description=(
            "Build a full cited credit memo for a borrower and its filings: a financial "
            "analysis, a covenant section with a deterministic compliance status, a risk "
            "assessment, peer comparisons, and a recommendation rationale. Decision "
            "support, never a credit decision. Always flagged for human review (P-06)."
        ),
    ),
    AgentSkill(
        id="extract_covenants",
        name="Covenant extraction",
        description=(
            "Extract financial covenants from filings and agreements (type, threshold, "
            "operator, current value) and compute each covenant's compliance status "
            "(COMPLIANT, AT_RISK, BREACH) deterministically, with citations."
        ),
    ),
    AgentSkill(
        id="flag_risks",
        name="Risk-flag identification",
        description=(
            "Identify categorised, severity-ranked credit risk flags (leverage, liquidity, "
            "profitability, governance, sector, concentration) grounded in the borrower's "
            "evidence, with citations."
        ),
    ),
    AgentSkill(
        id="peer_compare",
        name="Peer comparison",
        description=(
            "Compare a borrower's financial metrics against a peer set, returning the peer "
            "median, the borrower's percentile, and deltas."
        ),
    ),
)

_DESCRIPTION = (
    "Grounded underwriting assistant for a commercial bank's credit team. Turns a "
    "borrower's financial statements and filings into a cited credit memo (financial "
    "analysis, covenants with a deterministic compliance status, risk flags, peer "
    "comparisons), with a full audit trail. Decision support, not a credit decision. "
    "Built ports-and-adapters on the Gemini Enterprise Agent Platform; the governed RAG "
    "store is the A2 Enterprise KB."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this agent."""
    return AgentCard(
        name="credit-memo-drafting",
        description=_DESCRIPTION,
        url=_resolve_url(settings),
        version="0.1.0",
        skills=SKILLS,
        provider="credit-memo-drafting",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to asia-southeast1."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://credit-memo-drafting.doc.internal/a2a"
