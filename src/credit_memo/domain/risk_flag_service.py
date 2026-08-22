"""RiskFlagService — grounded credit risk-flag identification (SPEC §5).

Given the borrower and the case's retrieved evidence passages, the LLM identifies a
set of cited :class:`RiskFlag` entries, each with a category, severity and a short
detail tied to the evidence. The flags feed the memo's risk assessment and the review
policy (HIGH/CRITICAL flags escalate the memo).

Pure domain code: talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from . import _grounded as g
from .models import (
    Borrower,
    RetrievedPassage,
    RiskFlag,
)
from .prompts import _CITATION_RULES, RISK_FLAG_SYSTEM, RISK_FLAG_USER

_RISK_FLAG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "leverage",
                            "liquidity",
                            "profitability",
                            "governance",
                            "sector",
                            "concentration",
                            "other",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "detail": {"type": "string"},
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "severity", "detail"],
            },
        }
    },
    "required": ["items"],
}


class RiskFlagService:
    """Identify cited credit risk flags. Signature fixed by SPEC §5."""

    def __init__(self, llm: Any, tracer: Any) -> None:
        self._llm = llm
        self._tracer = tracer

    def flag(
        self,
        borrower: Borrower,
        passages: list[RetrievedPassage],
        actor: str,
    ) -> tuple[RiskFlag, ...]:
        """Identify risk flags for ``borrower`` grounded in the evidence."""
        passage_block = g.render_passages(list(passages))
        borrower_block = (
            f"id={borrower.id}, name={borrower.name}, sector={borrower.sector or 'unknown'}, "
            f"jurisdiction={borrower.jurisdiction or 'unknown'}"
        )
        system = RISK_FLAG_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = RISK_FLAG_USER.format(borrower=borrower_block, passages=passage_block)
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,
            response_schema=_RISK_FLAG_SCHEMA,
        )
        response = self._llm.generate(request)
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        return self._build_flags(parsed.get("items"), list(passages))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _build_flags(
        self, raw_items: Any, passages: list[RetrievedPassage]
    ) -> tuple[RiskFlag, ...]:
        if not isinstance(raw_items, list):
            return ()
        out: list[RiskFlag] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            detail = str(raw.get("detail") or "").strip()
            if not detail:
                continue
            out.append(
                RiskFlag(
                    category=g.coerce_risk_category(raw.get("category")),
                    severity=g.coerce_severity(raw.get("severity")),
                    detail=detail,
                    citations=g.citations_for_source_ids(
                        g.as_str_list(raw.get("used_source_ids")), passages
                    ),
                )
            )
        return tuple(out)
