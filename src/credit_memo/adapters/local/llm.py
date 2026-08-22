"""Local LLM adapter (LLMPort) — a deterministic, schema-driven generator.

The ``local`` profile's stand-in for **Gemini**: no model, no network, fully
reproducible. It reads ``request.response_schema`` (the JSON schema the calling service
asks for) and emits a deterministic JSON object whose keys match it: the memo-synthesis
schema is a flat object with a nested ``financial_metrics`` array, the covenant and
risk-flag schemas wrap an ``items`` array whose element shape differs, and the
self-critique schema is a flat object. Every item references the source ids actually
present in the rendered prompt via ``used_source_ids`` so the services map page-level
citations to real retrieved passages. There is no Google emulator for Gemini, so this
path is unconditional.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a test fixture, so
the in-memory implementation lives once under ``adapters/local`` and drives both the offline
tests and the CLI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import Settings
from ...domain.models import (
    LlmRequest,
    LlmResponse,
    TokenUsage,
)
from ._seed import PRIMARY_SOURCE_ID

# The rendered passage block keys each source with ``[source_id p.N]`` headers; recover
# the ids the service actually grounded on so the answer cites only retrieved sources.
_SOURCE_HEADER_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]*?)(?:\s+p\.[^\]]+)?\]")


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _item_props(schema: dict | None) -> set[str]:
    props = _schema_properties(schema)
    items_decl = props.get("items") if isinstance(props.get("items"), dict) else {}
    item_schema = items_decl.get("items", {}) if isinstance(items_decl, dict) else {}
    return set(_schema_properties(item_schema))


class LocalDeterministicLLMAdapter:
    """Deterministic LLM whose ``generate`` returns JSON matching the request schema."""

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.1-flash-lite"

    def __init__(self, settings: Settings, used_source_ids: list[str] | None = None) -> None:
        self.settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL
        # When set, used as the citation fallback; otherwise recovered from the prompt.
        self._used_source_ids = used_source_ids or [PRIMARY_SOURCE_ID]

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        self._used_source_ids = self._source_ids_from_request(request)
        body = self._body_for_schema(request.response_schema)
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=request.model or self._reasoning_model,
            web_citations=(),
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (the services only use this for routing).
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    def _source_ids_from_request(self, request: LlmRequest) -> list[str]:
        user = ""
        for message in reversed(request.messages):
            if message.role == "user":
                user = message.content
                break
        seen: list[str] = []
        for sid in _SOURCE_HEADER_RE.findall(user):
            if sid not in seen:
                seen.append(sid)
        return seen or list(self._used_source_ids)

    def _body_for_schema(self, schema: dict | None) -> dict[str, Any]:
        props = _schema_properties(schema)
        sid = list(self._used_source_ids)

        if "summary" in props:  # credit-memo synthesis
            return {
                "summary": (
                    "Acme is a profitable manufacturer with revenue of USD 120m and EBITDA "
                    "of USD 24m, operating at 2.5x net leverage with comfortable covenant "
                    "headroom."
                ),
                "financial_metrics": [
                    {
                        "name": "revenue",
                        "value": 120.0,
                        "period": "FY2025",
                        "currency": "USD",
                        "used_source_ids": sid,
                    },
                    {
                        "name": "ebitda",
                        "value": 24.0,
                        "period": "FY2025",
                        "currency": "USD",
                        "used_source_ids": sid,
                    },
                    {
                        "name": "leverage",
                        "value": 2.5,
                        "period": "FY2025",
                        "currency": "x",
                        "used_source_ids": sid,
                    },
                ],
                "recommendation_rationale": (
                    "The borrower's leverage and coverage are within covenant limits and "
                    "near the peer median; a credit officer should confirm concentration "
                    "exposure before relying on this memo."
                ),
                "confidence": 0.87,
                "used_source_ids": sid,
            }

        if "items" in props:
            item_props = _item_props(schema)
            if "threshold" in item_props:  # covenant extraction
                return {
                    "items": [
                        {
                            "type": "leverage",
                            "description": "Maximum net leverage covenant.",
                            "threshold": 3.0,
                            "operator": "<=",
                            "current_value": 2.5,
                            "period": "Q4",
                            "used_source_ids": sid,
                        },
                        {
                            "type": "dscr",
                            "description": "Minimum debt-service coverage ratio.",
                            "threshold": 1.25,
                            "operator": ">=",
                            "current_value": 1.40,
                            "period": "Q4",
                            "used_source_ids": sid,
                        },
                    ]
                }
            # risk-flag identification
            return {
                "items": [
                    {
                        "category": "concentration",
                        "severity": "medium",
                        "detail": "Sector policy flags single-customer concentration risk.",
                        "used_source_ids": sid,
                    }
                ]
            }

        # Flat object (self-critique).
        return {"grounded": True, "confidence": 0.86, "caveats": []}
