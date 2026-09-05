"""MemoSynthService — grounded memo prose + normalised metrics (SPEC §5).

Given the borrower and the case's retrieved evidence passages, the LLM drafts the memo
summary and recommendation rationale and normalises the key financial metrics, then a
self-critique groundedness pass adjusts the confidence and caveats. This is the LLM
half of the credit memo; the deterministic halves (covenant status, peer comps) live in
their own services and are never overridden by the model.

Pure domain code: talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import _grounded as g
from .models import (
    Borrower,
    Citation,
    CreditRequest,
    FinancialMetric,
    Ratio,
    RetrievedPassage,
)
from .prompts import (
    _CITATION_RULES,
    COMPUTED_BLOCK,
    MEMO_SYSTEM,
    MEMO_USER,
    REQUEST_BLOCK,
    SELF_CRITIQUE_SYSTEM,
    SELF_CRITIQUE_USER,
)

_MEMO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "financial_metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "period": {"type": "string"},
                    "currency": {"type": "string"},
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "value"],
            },
        },
        "recommendation_rationale": {"type": "string"},
        "confidence": {"type": "number"},
        "questions_for_client": {"type": "array", "items": {"type": "string"}},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "financial_metrics", "recommendation_rationale", "used_source_ids"],
}

_CRITIQUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grounded": {"type": "boolean"},
        "confidence": {"type": "number"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["grounded", "confidence", "caveats"],
}


@dataclass(frozen=True, slots=True)
class MemoDraft:
    """The LLM-synthesised half of the memo (prose + normalised metrics)."""

    summary: str
    financial_metrics: tuple[FinancialMetric, ...]
    recommendation_rationale: str
    citations: tuple[Citation, ...]
    confidence: float
    caveats: tuple[str, ...] = ()
    #: What the analyst should go and ask the borrower. A gap the drafter noticed is
    #: worth more as a question than as another hedged sentence in the narrative.
    questions_for_client: tuple[str, ...] = ()


class MemoSynthService:
    """Synthesise the memo summary, metrics and rationale. Signature fixed by SPEC §5."""

    def __init__(self, llm: Any, tracer: Any) -> None:
        self._llm = llm
        self._tracer = tracer

    def synthesise(
        self,
        borrower: Borrower,
        passages: list[RetrievedPassage],
        actor: str,
        request: CreditRequest | None = None,
        ratios: tuple[Ratio, ...] = (),
    ) -> MemoDraft:
        """Draft the memo prose and normalise metrics for ``borrower``.

        ``request`` is the ask the memo answers and ``ratios`` are the engine's own
        figures. Both are handed to the drafter as separate, authoritative blocks: the
        model narrates them and cites them, and never recomputes them.
        """
        passage_block = g.render_passages(list(passages))
        borrower_block = self._borrower_block(borrower)
        system = MEMO_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = MEMO_USER.format(
            borrower=borrower_block,
            request=self._request_block(request),
            computed=self._computed_block(ratios),
            passages=passage_block,
        )
        llm_request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,  # adapter default => reasoning model gemini-3.5-flash
            response_schema=_MEMO_SCHEMA,
        )
        response = self._llm.generate(llm_request)
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        summary = str(parsed.get("summary") or "").strip()
        rationale = str(parsed.get("recommendation_rationale") or "").strip()
        used_ids = g.as_str_list(parsed.get("used_source_ids"))
        confidence = g.clamp(parsed.get("confidence", 0.0))

        metrics = self._build_metrics(parsed.get("financial_metrics"))
        citations = g.citations_for_source_ids(used_ids, list(passages))
        questions = g.as_str_list(parsed.get("questions_for_client"))

        caveats: list[str] = []
        if summary and not citations:
            # The fallback that used to hide this attached every retrieved passage
            # instead, which made an uncited draft look like the best-evidenced section
            # of the memo. Saying it plainly is the honest replacement.
            caveats.append(
                "The draft cited no source. Treat every figure in it as unverified and "
                "check it against the evidence before relying on the memo."
            )
            confidence = min(confidence, 0.3)
        if not summary:
            summary = (
                "The available evidence does not support a confident credit memo for this "
                "borrower. Human review is required before any reliance."
            )
            confidence = min(confidence, 0.2)
            caveats.append("No grounded memo could be synthesised from the evidence.")

        confidence, critique_caveats = self._self_critique(
            borrower_block, f"{summary}\n{rationale}", passage_block, confidence
        )
        caveats.extend(critique_caveats)

        return MemoDraft(
            summary=summary,
            financial_metrics=metrics,
            recommendation_rationale=rationale,
            citations=citations,
            confidence=confidence,
            caveats=tuple(dict.fromkeys(caveats)),
            questions_for_client=tuple(dict.fromkeys(questions)),
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _borrower_block(borrower: Borrower) -> str:
        return (
            f"id={borrower.id}, name={borrower.name}, sector={borrower.sector or 'unknown'}, "
            f"jurisdiction={borrower.jurisdiction or 'unknown'}"
        )

    @staticmethod
    def _request_block(request: CreditRequest | None) -> str:
        if request is None:
            return ""
        lines = [
            f"kind={request.kind.value}, loan_type={request.loan_type.value}",
            f"purpose={request.purpose or 'not stated'}",
        ]
        for facility in request.facilities:
            lines.append(
                f"- facility {facility.id}: {facility.facility_type.value} "
                f"{facility.currency} {facility.amount:,.0f} over "
                f"{facility.tenor_months} months; purpose={facility.purpose or 'not stated'}; "
                f"repayment={facility.repayment_source or 'not stated'}; "
                f"security={facility.security or 'none stated'}"
            )
        sources_and_uses = request.sources_and_uses
        if sources_and_uses.sources or sources_and_uses.uses:
            lines.append(
                f"- sources {sources_and_uses.total_sources:,.0f} vs uses "
                f"{sources_and_uses.total_uses:,.0f} "
                f"(imbalance {sources_and_uses.imbalance:,.0f})"
            )
        if request.notes:
            lines.append(f"notes: {request.notes}")
        return REQUEST_BLOCK.format(request="\n".join(lines))

    @staticmethod
    def _computed_block(ratios: tuple[Ratio, ...]) -> str:
        """Render the engine's figures, including the ones it could not compute.

        A ratio the engine could not produce is stated as such rather than omitted, so
        the drafter says "the interest expense was not supplied" instead of quietly
        filling the gap from a passage.
        """
        if not ratios:
            return ""
        lines = []
        for ratio in ratios:
            if ratio.value is None:
                lines.append(
                    f"- {ratio.name} ({ratio.period}): not computable, {ratio.reason_missing}"
                )
                continue
            rendered = f"{ratio.value:,.2f}" + ("x" if ratio.unit == "x" else "")
            lines.append(
                f"- {ratio.name} ({ratio.period}) = {rendered} "
                f"[{ratio.formula_id}: {ratio.definition}]"
            )
        return COMPUTED_BLOCK.format(computed="\n".join(lines))

    @staticmethod
    def _build_metrics(raw_metrics: Any) -> tuple[FinancialMetric, ...]:
        if not isinstance(raw_metrics, list):
            return ()
        out: list[FinancialMetric] = []
        for raw in raw_metrics:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            value = g.as_float(raw.get("value"))
            if not name or value is None:
                continue
            out.append(
                FinancialMetric(
                    name=name,
                    value=value,
                    period=str(raw.get("period") or "").strip(),
                    currency=str(raw.get("currency") or "USD").strip() or "USD",
                )
            )
        return tuple(out)

    def _self_critique(
        self,
        borrower_block: str,
        memo_text: str,
        passage_block: str,
        prior_confidence: float,
    ) -> tuple[float, list[str]]:
        """Second LLM pass auditing groundedness; returns (confidence, caveats)."""
        request = g.build_llm_request(
            system_instruction=SELF_CRITIQUE_SYSTEM,
            user_content=SELF_CRITIQUE_USER.format(
                borrower=borrower_block, memo=memo_text, passages=passage_block
            ),
            model=None,
            response_schema=_CRITIQUE_SCHEMA,
            temperature=0.0,
        )
        try:
            response = self._llm.generate(request)
        except Exception:  # noqa: BLE001 - critique failure must not drop the memo
            return prior_confidence, []
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        if not parsed:
            return prior_confidence, []

        critic_conf = g.clamp(parsed.get("confidence", prior_confidence))
        grounded = bool(parsed.get("grounded", True))
        caveats = g.as_str_list(parsed.get("caveats"))

        confidence = min(prior_confidence, critic_conf)
        if not grounded:
            confidence = min(confidence, 0.4)
            if not caveats:
                caveats = ["Self-critique flagged unsupported claims; review required."]
        return confidence, caveats
