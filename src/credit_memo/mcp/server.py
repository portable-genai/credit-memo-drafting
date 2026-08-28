"""Serve the governed tool catalog Fin1 already declares, over MCP 2026-07-28.

The catalog declared four governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up.

**Three of the four tools are sections of one memo, and that is stated rather than hidden.**
`extract_covenants`, `flag_risks` and `peer_compare` are not cheaper paths than
`build_credit_memo`: the service produces all of them while building a memo, and these return
those sections of it. Inventing separate shortcut paths would create a second way to compute
figures the memo already owns, which for covenants and risk flags is exactly the kind of
duplication that ends with two answers to one question.

MCP stdio verifies no end user, so the caller is recorded as a SERVICE caller, no tenant is
asserted and no entitlement principals are supplied: retrieval stays on its fail-closed path.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve

from ..api import deps
from ..domain.models import Borrower, MemoInput

#: The tools this module answers, as data, so a test can hold it against the catalog.
HANDLER_NAMES: tuple[str, ...] = (
    "build_credit_memo",
    "extract_covenants",
    "flag_risks",
    "peer_compare",
)


def _memo(arguments: dict[str, Any], actor: str) -> Any:
    borrower = Borrower(
        id=f"mcp:{arguments.get('borrower_name', '')}",
        name=str(arguments.get("borrower_name", "") or ""),
        sector=str(arguments.get("sector", "") or ""),
        jurisdiction=str(arguments.get("jurisdiction", "") or ""),
    )
    return deps.get_credit_memo_service().build(MemoInput(borrower=borrower), actor=actor)


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the memo service that already performs it."""

    def build_credit_memo(**arguments: Any) -> Any:
        return _memo(arguments, actor)

    def extract_covenants(**arguments: Any) -> Any:
        return _memo(arguments, actor).covenants

    def flag_risks(**arguments: Any) -> Any:
        return _memo(arguments, actor).risk_flags

    def peer_compare(**arguments: Any) -> Any:
        return _memo(arguments, actor).peer_comparison

    return {
        "build_credit_memo": build_credit_memo,
        "extract_covenants": extract_covenants,
        "flag_risks": flag_risks,
        "peer_compare": peer_compare,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for Fin1's catalog, refusing on any catalog/handler mismatch."""
    container = deps.get_container()
    return mcpserve.build_server(
        name="credit-memo-drafting",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=getattr(container, "audit", None) if with_audit_tools else None,
    )
