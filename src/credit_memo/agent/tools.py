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
* **Three of the four tools are sections of one memo**, exactly as the MCP surface serves
  them. ``extract_covenants``, ``flag_risks`` and ``peer_compare`` are not cheaper paths
  than ``build_credit_memo``; each builds the memo and returns its section. A shortcut path
  is a second way to compute figures the memo already owns, and the peer shortcut this
  replaced compared the borrower against the peer median at an assumed value of zero — a
  fabricated position that was indistinguishable in the output from a real one.
* The four tools are the governed tool catalog, and a test holds them to it. A tool the
  catalog declares and the agent cannot call is a promise the fleet made and this repo
  does not keep.
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


def _memo(
    borrower_name: str,
    sector: str,
    jurisdiction: str,
    actor: str,
    settings: Settings | None,
) -> Any:
    """One memo, from which the section tools return their section.

    The three section tools are not cheaper paths than ``build_credit_memo``: the service
    produces covenants, risk flags and peer comparisons while building a memo, and each
    tool returns that part of it. A shortcut path would be a second way to compute figures
    the memo already owns, which ends with two answers to one question — and for peer
    comparison it ended with a borrower percentile measured against an assumed value of
    zero, which reads exactly like a real position.
    """
    from ..api.deps import build_credit_memo_service
    from ..domain.models import MemoInput

    c = _container(settings)
    service = build_credit_memo_service(c)
    borrower = _borrower(borrower_name, sector, jurisdiction)
    return service.build(MemoInput(borrower=borrower), actor)


def extract_covenants(
    borrower_name: str,
    sector: str = "",
    jurisdiction: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Extract a borrower's financial covenants with a deterministic compliance status.

    Returns the ``Covenant`` objects from the borrower's memo, each carrying its threshold,
    its tested status (COMPLIANT, AT_RISK, BREACH) and citations. The status is computed
    arithmetically, never asserted by the model.

    Args:
      borrower_name: The borrower name to assess.
      sector: The borrower's sector.
      jurisdiction: ISO-ish country/region code.
      actor: Authenticated identity the request is made for.

    Returns:
      A JSON-safe list of ``Covenant`` dicts.
    """
    from ..domain.serialization import to_jsonable

    return to_jsonable(_memo(borrower_name, sector, jurisdiction, actor, settings).covenants)


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
    from ..domain.serialization import to_jsonable

    return to_jsonable(_memo(borrower_name, sector, jurisdiction, actor, settings).risk_flags)


def peer_compare(
    borrower_name: str,
    sector: str = "",
    jurisdiction: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Compare a borrower's financial metrics against a peer set.

    Returns ``PeerComparison`` objects (peer median, the borrower's percentile, deltas)
    for the borrower's own normalised metrics, computed arithmetically from the peer
    dataset. A metric the peer source cannot answer is skipped rather than estimated.

    Args:
      borrower_name: The borrower name to compare.
      sector: The borrower's sector (selects the peer cohort).
      jurisdiction: ISO-ish country/region code.
      actor: Authenticated identity the request is made for.

    Returns:
      A JSON-safe list of ``PeerComparison`` dicts.
    """
    from ..domain.serialization import to_jsonable

    return to_jsonable(_memo(borrower_name, sector, jurisdiction, actor, settings).peer_comparison)


#: The ADK surface, which is the governed tool catalog and nothing else. Held to the
#: catalog by a test: a tool the catalog declares and the agent cannot call is a promise
#: the fleet made and this repo does not keep, and it fails silently in both directions.
TOOL_FUNCTIONS = (
    build_credit_memo,
    extract_covenants,
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
