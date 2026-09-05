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

# The borrower block the synthesis service renders: "id=..., name=..., sector=...".
_NAME_RE = re.compile(r"\bname=([^,\n]+)")
_SECTOR_RE = re.compile(r"\bsector=([^,\n]+)")

# Figures as the evidence states them. This adapter READS its prompt rather than
# asserting a fixed answer: it stood in for the model, and a stand-in that replies
# "Acme ... revenue of USD 120m" whatever borrower it was handed is not a quiet
# simplification. It is the one failure a grounded assistant must never show, wired in
# by default, and it hid behind a demo whose borrower really was Acme.
_MONEY_RE = re.compile(
    r"\b(revenue|EBITDA|net debt|total debt|interest expense)\b[^.\n]{0,40}?"
    r"\bUSD\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*m\b",
    re.I,
)
_COMPUTED_RE = re.compile(r"^- ([a-z][a-z /_-]*?) \(([^)]*)\) = ([0-9,.]+)(x?) \[", re.I | re.M)
_MAX_LEVERAGE_RE = re.compile(
    r"maximum\s+(?:net[- ])?leverage[^0-9\n]{0,40}([0-9]+(?:\.[0-9]+)?)\s*x", re.I
)
_MIN_DSCR_RE = re.compile(
    r"minimum\s+debt[- ]service\s+coverage[^0-9\n]{0,60}([0-9]+(?:\.[0-9]+)?)\s*x", re.I
)
_CURRENT_LEVERAGE_RE = re.compile(
    r"current\s+(?:net\s+)?leverage[^0-9\n]{0,30}([0-9]+(?:\.[0-9]+)?)\s*x", re.I
)
_CURRENT_DSCR_RE = re.compile(r"current\s+DSCR[^0-9\n]{0,30}([0-9]+(?:\.[0-9]+)?)\s*x", re.I)
_MIN_CURRENT_RATIO_RE = re.compile(
    r"minimum\s+current\s+ratio[^0-9\n]{0,40}([0-9]+(?:\.[0-9]+)?)\s*x", re.I
)
_CONCENTRATION_RE = re.compile(r"concentration", re.I)


def _first_group(pattern: re.Pattern[str], text: str, default: str) -> str:
    """The pattern's first capture, stripped, or ``default`` when it does not match."""
    found = pattern.search(text)
    return found.group(1).strip() if found else default


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
    TRIAGE_MODEL = "gemini-3.5-flash"

    def __init__(self, settings: Settings, used_source_ids: list[str] | None = None) -> None:
        self.settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL
        # When set, used as the citation fallback; otherwise recovered from the prompt.
        self._used_source_ids = used_source_ids or [PRIMARY_SOURCE_ID]
        #: The user content of the request being answered. Held on the instance rather
        #: than threaded through ``_body_for_schema`` so subclasses that override it with
        #: the documented one-argument signature keep working.
        self._prompt = ""

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        self._used_source_ids = self._source_ids_from_request(request)
        self._prompt = self._user_content(request)
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
        prompt = self._prompt

        if "summary" in props:  # credit-memo synthesis
            return self._memo_body(prompt, sid)

        if "items" in props:
            item_props = _item_props(schema)
            if "threshold" in item_props:  # covenant extraction
                return {"items": self._covenant_items(prompt, sid)}
            return {"items": self._risk_items(prompt, sid)}

        # Flat object (self-critique).
        return {"grounded": True, "confidence": 0.86, "caveats": []}

    # ------------------------------------------------------------------ #
    # Reading the prompt
    # ------------------------------------------------------------------ #
    @staticmethod
    def _user_content(request: LlmRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content or ""
        return ""

    @staticmethod
    def _number(text: str) -> float:
        return float(text.replace(",", ""))

    @classmethod
    def _figures(cls, prompt: str) -> dict[str, float]:
        """USD-million figures the evidence states, keyed by the line they belong to."""
        out: dict[str, float] = {}
        for line, amount in _MONEY_RE.findall(prompt):
            out.setdefault(line.strip().lower(), cls._number(amount))
        return out

    @classmethod
    def _computed(cls, prompt: str) -> dict[str, tuple[float, str, str]]:
        """The engine's own ratios, as the COMPUTED block renders them.

        The bank calculated these before a word was drafted, so where one exists it is
        what the drafter should repeat. Repeating the engine is the whole discipline:
        a stand-in that states its own leverage is the thing the memo must never do.
        """
        out: dict[str, tuple[float, str, str]] = {}
        for name, period, value, unit in _COMPUTED_RE.findall(prompt):
            out.setdefault(name.strip().lower(), (cls._number(value), period.strip(), unit))
        return out

    def _memo_body(self, prompt: str, sid: list[str]) -> dict[str, Any]:
        name = _first_group(_NAME_RE, prompt, "the borrower")
        sector = _first_group(_SECTOR_RE, prompt, "")
        figures = self._figures(prompt)
        computed = self._computed(prompt)
        period = next((p for _, p, _ in computed.values() if p), "")

        metrics: list[dict[str, Any]] = [
            {
                "name": line,
                "value": value,
                "period": period,
                "currency": "USD",
                "used_source_ids": sid,
            }
            for line, value in figures.items()
        ]
        leverage = computed.get("leverage")
        if leverage is not None:
            metrics.append(
                {
                    "name": "leverage",
                    "value": leverage[0],
                    "period": leverage[1] or period,
                    "currency": "x",
                    "used_source_ids": sid,
                }
            )

        stated = ", ".join(f"{line} of USD {value:,.1f}m" for line, value in figures.items())
        descriptor = f"a {sector} borrower" if sector and sector != "unknown" else "the borrower"
        if stated:
            summary = f"{name}, {descriptor}, reports {stated} in the evidence supplied"
            summary += f" for {period}." if period else "."
        else:
            summary = (
                f"{name}, {descriptor}. The evidence supplied states no headline figures, "
                "so this draft asserts none."
            )
        if leverage is not None:
            summary += (
                f" On those figures the bank's own arithmetic puts leverage at {leverage[0]:,.2f}x."
            )

        return {
            "summary": summary,
            "financial_metrics": metrics,
            # Deliberately no verdict on covenant compliance. ``covenant_status()`` is the
            # single auditable place that is decided, and a drafter that volunteered
            # "comfortable covenant headroom" — as this one used to, for every borrower —
            # puts a second, unearned answer in front of the reader beside the real one.
            "recommendation_rationale": (
                "The figures above are the evidence's and the ratios are the bank's own "
                "arithmetic on the confirmed spread. A credit officer should confirm the "
                "covenant definitions and the concentration exposure before relying on "
                "this memo."
            ),
            "confidence": 0.87 if metrics else 0.3,
            "used_source_ids": sid,
        }

    def _covenant_items(self, prompt: str, sid: list[str]) -> list[dict[str, Any]]:
        """Covenant terms as the evidence states them — never invented.

        ``current_value`` is what the EVIDENCE reports, which is exactly the figure the
        engine then disagrees with when the borrower measures on a different definition.
        Fabricating it would fabricate the disagreement the reconciliation exists to
        report.
        """
        items: list[dict[str, Any]] = []
        max_leverage = _MAX_LEVERAGE_RE.search(prompt)
        if max_leverage is not None:
            reported = _CURRENT_LEVERAGE_RE.search(prompt)
            items.append(
                {
                    "type": "leverage",
                    "description": "Maximum net leverage covenant.",
                    "threshold": self._number(max_leverage.group(1)),
                    "operator": "<=",
                    "current_value": self._number(reported.group(1)) if reported else None,
                    "period": "Q4",
                    "used_source_ids": sid,
                }
            )
        min_current_ratio = _MIN_CURRENT_RATIO_RE.search(prompt)
        if min_current_ratio is not None:
            items.append(
                {
                    "type": "current_ratio",
                    "description": "Minimum current ratio.",
                    "threshold": self._number(min_current_ratio.group(1)),
                    "operator": ">=",
                    # The evidence states the limit, not a current reading: a liquidity
                    # covenant is tested from the spread, and there is nothing to report.
                    "current_value": None,
                    "period": "Q4",
                    "used_source_ids": sid,
                }
            )
        min_dscr = _MIN_DSCR_RE.search(prompt)
        if min_dscr is not None:
            reported = _CURRENT_DSCR_RE.search(prompt)
            items.append(
                {
                    "type": "dscr",
                    "description": "Minimum debt-service coverage ratio.",
                    "threshold": self._number(min_dscr.group(1)),
                    "operator": ">=",
                    "current_value": self._number(reported.group(1)) if reported else None,
                    "period": "Q4",
                    "used_source_ids": sid,
                }
            )
        return items

    @staticmethod
    def _risk_items(prompt: str, sid: list[str]) -> list[dict[str, Any]]:
        """A flag only where the evidence supports one. No evidence, no flag."""
        if _CONCENTRATION_RE.search(prompt) is None:
            return []
        return [
            {
                "category": "concentration",
                "severity": "medium",
                "detail": "The retrieved policy and filing evidence raises concentration risk.",
                "used_source_ids": sid,
            }
        ]
