"""Local tool-catalog adapter (ToolCatalogPort) — in-process MCP tool catalog.

The ``local`` profile's stand-in for the governed **MCP** tool catalog: a small,
deterministic in-process set of least-privilege tool specs exposed to the agent. SDK-free
and unconditional (there is no emulator for the tool catalog).
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec


class LocalToolCatalogAdapter:
    """In-process catalog of the governed tools exposed to the credit-memo agent."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tools: dict[str, ToolSpec] = {
            "build_credit_memo": ToolSpec(
                name="build_credit_memo",
                description="Build a cited credit memo for a borrower.",
                input_schema={
                    "type": "object",
                    "properties": {"borrower_name": {"type": "string"}},
                },
            )
        }

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)
