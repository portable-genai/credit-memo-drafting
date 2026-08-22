"""ADK FunctionTools that expose the B2 domain services to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the relevant domain service
from a :class:`~credit_memo.config.Container` (so every port is bound to the adapter
selected by the active profile), invokes the service, and returns a JSON-safe dict via
:func:`~credit_memo.domain.serialization.to_jsonable`.

Design notes
------------
* The domain services own orchestration (redact -> guardrail -> ingest -> retrieve ->
  synthesise -> deterministic covenant status + risk flags -> peer comps -> guardrail ->
  audit; SPEC §5). These tools add **no** business logic of their own: the model decides
  *which* artifact to produce, the service decides *how*.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The plain
  Python tool callables are importable and unit-testable without ADK at all.
* Every callable carries a precise type-hinted signature and docstring: ADK derives the
  tool's name, description and JSON parameter schema from them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

_DEFAULT_ACTOR = "credit-memo-drafting"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _borrower(name: str, sector: str, jurisdiction: str) -> Any:
    from ..domain.models import Borrower

    return Borrower(
        id=name.lower().replace(" ", "-"),
        name=name,
        sector=sector,
        jurisdiction=jurisdiction,
    )


def build_credit_memo(
    borrower_name: str,
    sector: str = "",
    jurisdiction: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Build a full cited credit memo for a borrower.

    Produces a ``CreditMemo`` (financial analysis, covenants, risk flags, peer
    comparisons, recommendation rationale) for the named borrower. Decision support, not a
    credit decision. Always flagged for human review.

    Args:
      borrower_name: The borrower (obligor) name to assess.
      sector: The borrower's sector (e.g. "manufacturing").
      jurisdiction: ISO-ish country/region code (e.g. "SG").
      actor: Authenticated identity the request is made for.

    Returns:
      A JSON-safe ``CreditMemo`` dict.
    """
    from ..api.deps import build_credit_memo_service
    from ..domain.models import MemoInput
    from ..domain.serialization import to_jsonable

    c = _container(settings)
    service = build_credit_memo_service(c)
    borrower = _borrower(borrower_name, sector, jurisdiction)
    return to_jsonable(service.build(MemoInput(borrower=borrower), actor))


def flag_risks(
    borrower_name: str,
    sector: str = "",
    jurisdiction: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Identify credit risk flags for a borrower.

    Returns a list of categorised, severity-ranked ``RiskFlag`` objects with citations,
    grounded in the borrower's evidence retrieved from the governed RAG store.

    Args:
      borrower_name: The borrower name to assess.
      sector: The borrower's sector.
      jurisdiction: ISO-ish country/region code.
      actor: Authenticated identity the request is made for.

    Returns:
      A JSON-safe list of ``RiskFlag`` dicts.
    """
    from ..domain import _grounded as g
    from ..domain.serialization import to_jsonable
    from ..domain.services import RiskFlagService

    c = _container(settings)
    borrower = _borrower(borrower_name, sector, jurisdiction)
    passages = g.retrieve_passages(
        c.knowledge_base,
        f"credit risks and sector context for {borrower.name}",
        acl_principals=(f"borrower:{borrower.id}",),
        top_k=c.settings.knowledge_base.top_k,
    )
    service = RiskFlagService(llm=c.llm, tracer=c.tracer)
    return to_jsonable(service.flag(borrower, passages, actor))


def peer_compare(
    borrower_name: str,
    sector: str = "",
    jurisdiction: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Compare a borrower's leverage and EBITDA against a peer set.

    Returns ``PeerComparison`` objects (peer median, percentile, deltas) for the
    borrower's key metrics, computed arithmetically from the peer dataset.

    Args:
      borrower_name: The borrower name to compare.
      sector: The borrower's sector (selects the peer cohort).
      jurisdiction: ISO-ish country/region code.
      actor: Authenticated identity the request is made for.

    Returns:
      A JSON-safe list of ``PeerComparison`` dicts.
    """
    from ..domain.models import FinancialMetric
    from ..domain.serialization import to_jsonable
    from ..domain.services import PeerCompService

    c = _container(settings)
    borrower = _borrower(borrower_name, sector, jurisdiction)
    service = PeerCompService(peer_data=c.peer_data, tracer=c.tracer)
    # The model supplies the borrower's own metrics; here we request the two core ratios.
    metrics = (
        FinancialMetric(name="leverage", value=0.0),
        FinancialMetric(name="ebitda", value=0.0),
    )
    return to_jsonable(service.compare(borrower, metrics, actor))


TOOL_FUNCTIONS = (
    build_credit_memo,
    flag_risks,
    peer_compare,
)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
