"""CovenantService — covenant extraction + deterministic status (SPEC §5).

Given the borrower and the case's retrieved evidence passages (from the A2 governed
RAG store), the LLM extracts the covenant *terms* (type, threshold, operator, current
value), and the domain then computes each covenant's compliance ``status``
deterministically by comparing ``current_value`` against ``threshold`` via the
operator (``_grounded.covenant_status``). The LLM drafts prose but never overrides a
breach computation: covenant status is a single, auditable calculation.

Pure domain code: talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from . import _grounded as g
from .models import (
    Borrower,
    Covenant,
    RetrievedPassage,
)
from .prompts import _CITATION_RULES, COVENANT_SYSTEM, COVENANT_USER

_COVENANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "leverage",
                            "dscr",
                            "interest_cover",
                            "current_ratio",
                            "min_ebitda",
                            "max_capex",
                            "tangible_net_worth",
                            "other",
                        ],
                    },
                    "description": {"type": "string"},
                    "threshold": {"type": "number"},
                    "operator": {"type": "string", "enum": ["<=", "<", ">=", ">", "=="]},
                    "current_value": {"type": ["number", "null"]},
                    "period": {"type": "string"},
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "description", "threshold", "operator"],
            },
        }
    },
    "required": ["items"],
}


class CovenantService:
    """Extract covenants and compute their status. Signature fixed by SPEC §5."""

    def __init__(self, llm: Any, tracer: Any, at_risk_band: float = 0.05) -> None:
        self._llm = llm
        self._tracer = tracer
        self._at_risk_band = at_risk_band

    def extract(
        self,
        borrower: Borrower,
        passages: list[RetrievedPassage],
        actor: str,
    ) -> tuple[Covenant, ...]:
        """Extract covenants for ``borrower`` from the evidence, with tested status."""
        passage_block = g.render_passages(list(passages))
        borrower_block = _borrower_block(borrower)
        system = COVENANT_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = COVENANT_USER.format(borrower=borrower_block, passages=passage_block)
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,  # adapter default => reasoning model gemini-3.5-flash
            response_schema=_COVENANT_SCHEMA,
        )
        response = self._llm.generate(request)
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        return self._build_covenants(parsed.get("items"), list(passages))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _build_covenants(
        self, raw_items: Any, passages: list[RetrievedPassage]
    ) -> tuple[Covenant, ...]:
        if not isinstance(raw_items, list):
            return ()
        out: list[Covenant] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            description = str(raw.get("description") or "").strip()
            threshold = g.as_float(raw.get("threshold"))
            if not description or threshold is None:
                continue
            operator = g.coerce_operator(raw.get("operator"))
            current_value = g.as_float(raw.get("current_value"))
            status = g.covenant_status(
                current_value, threshold, operator, at_risk_band=self._at_risk_band
            )
            out.append(
                Covenant(
                    type=g.coerce_covenant_type(raw.get("type")),
                    description=description,
                    threshold=threshold,
                    operator=operator,
                    current_value=current_value,
                    status=status,
                    period=str(raw.get("period") or "").strip(),
                    citations=g.citations_for_source_ids(
                        g.as_str_list(raw.get("used_source_ids")), passages
                    ),
                )
            )
        return tuple(out)


def _borrower_block(borrower: Borrower) -> str:
    return (
        f"id={borrower.id}, name={borrower.name}, sector={borrower.sector or 'unknown'}, "
        f"jurisdiction={borrower.jurisdiction or 'unknown'}"
    )
