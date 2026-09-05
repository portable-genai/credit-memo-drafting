"""Every response schema this service sends must be one the managed model can parse.

Vertex validates a `response_schema` into its own `types.Schema`, whose `type` is a SINGLE
enum member (`STRING`, `INTEGER`, ...). JSON Schema's `{"type": ["integer", "null"]}` union
is therefore refused outright, with a pydantic error naming the field.

Nothing caught that. The offline LLM stand-in reads a schema's property NAMES to decide what
shape to return and never validates its types, so a union passed the whole gate and failed
every single managed call: spread extraction returned 500 on the deployed service while 969
tests stayed green.

This walks the schemas the services actually send and asserts the property the managed API
enforces, without importing the cloud SDK -- the gate has no google-genai, and a check that
only runs where the SDK is installed is a check that does not run.
"""

from __future__ import annotations

from typing import Any

import pytest

# The one enum Vertex accepts, lower-cased as these schemas are written.
_VERTEX_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}


def _schemas() -> dict[str, dict[str, Any]]:
    """Every response schema the domain services and the managed adapters send."""
    from credit_memo.adapters.gcp.gemini_spread_extraction import SPREAD_SCHEMA
    from credit_memo.domain.covenant_service import CovenantService
    from credit_memo.domain.memo_synth_service import MemoSynthService
    from credit_memo.domain.risk_flag_service import RiskFlagService

    found: dict[str, dict[str, Any]] = {"gemini_spread_extraction.SPREAD_SCHEMA": SPREAD_SCHEMA}
    for module in (CovenantService, MemoSynthService, RiskFlagService):
        for name, value in vars(__import__(module.__module__, fromlist=["_"])).items():
            if name.endswith("_SCHEMA") and isinstance(value, dict):
                found[f"{module.__module__}.{name}"] = value
    return found


def _violations(node: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        declared = node.get("type")
        if isinstance(declared, list):
            out.append(
                f"{path or '<root>'}: type is a union {declared!r}; Vertex takes ONE type and "
                'expresses optionality as {"type": "<one>", "nullable": true}'
            )
        elif isinstance(declared, str) and declared.lower() not in _VERTEX_TYPES:
            out.append(f"{path or '<root>'}: type {declared!r} is not a Vertex schema type")
        for key, value in node.items():
            out.extend(_violations(value, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(_violations(value, f"{path}[{index}]"))
    return out


@pytest.mark.parametrize("name", sorted(_schemas()))
def test_the_schema_is_one_the_managed_model_can_parse(name: str) -> None:
    problems = _violations(_schemas()[name])
    assert not problems, f"{name} would be refused by Vertex:\n  " + "\n  ".join(problems)


def test_the_check_would_have_caught_the_shape_that_shipped() -> None:
    """The guard is only worth having if it fails on the exact schema that broke."""
    assert _violations({"properties": {"page": {"type": ["integer", "null"]}}})
