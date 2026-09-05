"""The declared tool catalog is now SERVED, and the plugin is rendered from the declarations.

This repo declared its capability surface twice over, as an A2A agent card and as a governed
tool catalog of JSON Schemas, and served neither. There was no MCP server process anywhere in
the fleet, so a surface described in two places could be read by a human and reached by nobody.

These guards are about the seam rather than the transport. What goes wrong here is not that MCP
breaks; it is that the served surface and the declared surface drift apart, so the catalog says
one thing and the process does another. ``bind`` refuses that in both directions.

The MCP SDK is in the ``[gcp]`` extra and the offline gate does not install it, so everything
below uses ``bind``, which is pure.

**What these do NOT prove, stated because the green would otherwise read stronger than it is:**
no handler is EXECUTED here. ``bind`` pairs names with callables and checks nothing about what a
callable does when called, so a handler that reaches for a field its domain object does not have
still binds cleanly. One did, during adoption: a handler filtered a value object as though it
were a list and only reading the domain type caught it. Executing the handlers needs live
services and belongs in the managed suite, not in an offline gate.
"""

from __future__ import annotations

import json
import pathlib
import sys

import jsonschema
import pytest
from hex_service_kit.mcpserve import ToolDispatchError, bind
from hex_service_kit.plugin import load_schema

from credit_memo.adapters.gcp.mcp_tool_catalog import McpToolCatalogAdapter
from credit_memo.config import Settings
from credit_memo.mcp import server as mcp_server


@pytest.fixture
def catalog() -> McpToolCatalogAdapter:
    return McpToolCatalogAdapter(Settings.load())


def test_every_declared_tool_has_a_handler_and_no_handler_is_undeclared(
    catalog: McpToolCatalogAdapter,
) -> None:
    """The whole point of binding at start-up rather than on the first call."""
    bound = bind(catalog, mcp_server.build_handlers(actor="svc:test"))

    assert set(bound) == {spec.name for spec in catalog.list_tools()}


def test_a_declared_tool_with_no_handler_refuses_to_start(
    catalog: McpToolCatalogAdapter,
) -> None:
    """A capability the service advertises and cannot perform must not be served."""
    handlers = mcp_server.build_handlers(actor="svc:test")
    handlers.pop(next(iter(handlers)))

    with pytest.raises(ToolDispatchError, match="no handler"):
        bind(catalog, handlers)


def test_a_handler_for_an_undeclared_tool_refuses_to_start(
    catalog: McpToolCatalogAdapter,
) -> None:
    """An ungoverned entry point is the more dangerous direction of the same mismatch."""
    handlers = mcp_server.build_handlers(actor="svc:test")
    handlers["exfiltrate_everything"] = lambda **_: None

    with pytest.raises(ToolDispatchError, match="does not declare"):
        bind(catalog, handlers)


def test_the_handler_roster_matches_the_catalog_exactly(
    catalog: McpToolCatalogAdapter,
) -> None:
    """``HANDLER_NAMES`` is documentation, so it is held to the catalog rather than trusted."""
    assert set(mcp_server.HANDLER_NAMES) == {spec.name for spec in catalog.list_tools()}


def test_the_adk_agent_can_call_every_tool_the_catalog_declares(
    catalog: McpToolCatalogAdapter,
) -> None:
    """The two surfaces answer the same roster, or one of them is lying.

    MCP is already held to the catalog above. The ADK agent was not, and drifted: the
    catalog declared ``extract_covenants`` while the agent had no such tool, so a promise
    the fleet published was one this repo did not keep — and nothing failed, in either
    direction.
    """
    from credit_memo.agent import tools as adk_tools

    assert {fn.__name__ for fn in adk_tools.TOOL_FUNCTIONS} == {
        spec.name for spec in catalog.list_tools()
    }


def test_no_adk_tool_invents_a_borrower_figure() -> None:
    """The section tools return sections of a memo; they do not assemble their own inputs.

    ``peer_compare`` used to construct ``FinancialMetric(name="leverage", value=0.0)`` and
    compare that against the peer median, reporting the borrower at the bottom percentile
    of every cohort. It was indistinguishable in the output from a real position, which is
    what makes a fabricated input worse than a missing one.
    """
    import inspect

    from credit_memo.agent import tools as adk_tools

    source = inspect.getsource(adk_tools)
    assert "FinancialMetric(" not in source, (
        "an ADK tool is building a borrower metric of its own. The memo owns the "
        "borrower's normalised metrics; a tool that assembles its own is a second answer "
        "to one question."
    )


def _render(tmp_path: pathlib.Path) -> pathlib.Path:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
    import render_plugin

    render_plugin.main(["--dest", str(tmp_path / "plugin")])
    return tmp_path / "plugin"


def test_the_manifest_validates_against_the_vendored_specification_schema(
    tmp_path: pathlib.Path,
) -> None:
    """``jsonschema`` is a hard dev dependency so this can never quietly skip into green."""
    manifest = json.loads((_render(tmp_path) / "plugin.json").read_text())

    jsonschema.validate(manifest, load_schema("plugin"))


def test_the_manifest_advertises_exactly_the_declared_tools(
    tmp_path: pathlib.Path, catalog: McpToolCatalogAdapter
) -> None:
    """Rendered from the declarations, so it is not a second description to maintain."""
    manifest = json.loads((_render(tmp_path) / "plugin.json").read_text())
    declared = {spec.name.replace("_", "-") for spec in catalog.list_tools()}

    assert set(manifest["keywords"]) == declared
