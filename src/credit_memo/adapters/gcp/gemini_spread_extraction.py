"""Gemini spread extraction (SpreadExtractionPort) — the PDF itself, not its text layer.

Sends the uploaded files to ``gemini-3.5-flash`` in ``asia-southeast1`` as document
parts and asks for a structured answer: one entry per line item per period, each naming
the page it came from and quoting the text it was read from.

Why the file rather than the extracted text. A financial statement is a table, and a
table flattened to a line of text loses the column that says which year a number belongs
to. It also loses the page, which is the difference between a citation a reviewer can
click and one they have to go looking for. Sending the PDF keeps both.

Why in-region and GA rather than a document processor. The Document AI path this
replaces ran in the `us` multi-region on the ``rc`` channel — which Google documents as
routing through the Vertex global endpoint and not compliant with data residency — and
needed a processor provisioned and a schema maintained per document kind. This is one
model call in the deploy region with no standing resource behind it.

The output is a :class:`SpreadCandidate`, which no engine will accept. A person confirms
it first, and that is deliberate rather than incidental: see
:mod:`credit_memo.domain.spread_service`.

All GenAI SDK imports are lazy so local, live, on-prem and test profiles import this
module without ``google-genai`` installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain import _grounded as g
from ...domain.models import (
    CandidateLineItem,
    LineItemCode,
    LlmDocument,
    Period,
    Provenance,
    SpreadCandidate,
)

#: The response contract. ``page`` and ``quote`` are required per item, not optional:
#: an extraction that cannot say where it read a number is an extraction a reviewer
#: cannot check, and this is the point in the pipeline where that becomes cheap to
#: insist on.
SPREAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "enum": [c.value for c in LineItemCode]},
                    "period": {"type": "string"},
                    "value": {"type": "number"},
                    "document_id": {"type": "string"},
                    "page": {"type": ["integer", "null"]},
                    "quote": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["code", "period", "value", "page", "quote"],
            },
        }
    },
    "required": ["items"],
}

SPREAD_SYSTEM = (
    "You are reading a borrower's financial documents to populate a credit spread. "
    "Return one entry per line item per reporting period.\n\n"
    "Rules, in order of importance:\n"
    "- Report ONLY figures that appear in the documents. If a line is not present for a "
    "period, omit it. Never derive, infer, interpolate or annualise a missing figure: an "
    "omission is a fact the analyst can act on, and a fabricated number is not.\n"
    "- For every entry give the page it appears on and a short verbatim quote containing "
    "it, copied exactly from that page. The quote is checked against the page.\n"
    "- Report figures in the stated unit and currency of the statements, unchanged. Do "
    "not rescale thousands to millions or convert currencies.\n"
    "- A figure shown in parentheses or with a minus sign is negative. Report it negative.\n"
    "- Use the period labels given below. If a document covers a period not in that list, "
    "omit it rather than relabelling it as one that is.\n"
    "- confidence is your own 0.0-1.0 estimate that this entry is correct and complete."
)

SPREAD_USER = (
    "BORROWER: {borrower}\n"
    "PERIODS WANTED: {periods}\n"
    "UNIT: figures are in {unit} of {currency}\n"
    "DOCUMENTS: {documents}\n\n"
    "Read the attached documents and return the spread line items you can support."
)


class GeminiSpreadExtractionAdapter:
    """Propose spread line items from uploaded documents, with a page and a quote each."""

    #: Bumped when the prompt or schema changes in a way that could move a figure. It is
    #: recorded on the candidate so a stored analysis says which extractor produced it.
    VERSION = "gemini-spread-v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._llm: Any | None = None

    def _generator(self) -> Any:
        if self._llm is None:
            from .gemini_llm import GeminiLLMAdapter

            self._llm = GeminiLLMAdapter(self.settings)
        return self._llm

    def extract_spread(
        self,
        borrower_id: str,
        documents: tuple[LlmDocument, ...],
        periods: tuple[Period, ...] = (),
        currency: str = "SGD",
        unit: str = "thousands",
    ) -> SpreadCandidate:
        wanted = tuple(p.label for p in periods)
        if not documents or not wanted:
            # Nothing to read, or nothing to read it into. An empty candidate is the
            # honest answer; inventing periods would put columns in the grid that no
            # document supports.
            return self._empty(borrower_id, periods, currency, unit)

        request = g.build_llm_request(
            system_instruction=SPREAD_SYSTEM,
            user_content=SPREAD_USER.format(
                borrower=borrower_id,
                periods=", ".join(wanted),
                unit=unit,
                currency=currency,
                documents=", ".join(d.document_id or "(unnamed)" for d in documents),
            ),
            model=None,
            response_schema=SPREAD_SCHEMA,
            documents=documents,
        )
        response = self._generator().generate(request)
        parsed = g.parse_structured(response)
        return SpreadCandidate(
            borrower_id=borrower_id,
            periods=periods,
            items=self._build_items(parsed.get("items"), wanted, currency, documents),
            currency=currency,
            unit=unit,
            extractor=f"{type(self).__name__}:{response.model or self.settings.models.reasoning}",
            extractor_version=self.VERSION,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _empty(
        borrower_id: str, periods: tuple[Period, ...], currency: str, unit: str
    ) -> SpreadCandidate:
        return SpreadCandidate(
            borrower_id=borrower_id,
            periods=periods,
            items=(),
            currency=currency,
            unit=unit,
            extractor=GeminiSpreadExtractionAdapter.__name__,
            extractor_version=GeminiSpreadExtractionAdapter.VERSION,
        )

    @staticmethod
    def _build_items(
        raw_items: Any,
        wanted_periods: tuple[str, ...],
        currency: str,
        documents: tuple[LlmDocument, ...],
    ) -> tuple[CandidateLineItem, ...]:
        if not isinstance(raw_items, list):
            return ()
        known_documents = {d.document_id for d in documents if d.document_id}
        out: list[CandidateLineItem] = []
        seen: set[tuple[LineItemCode, str]] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                code = LineItemCode(str(raw.get("code") or ""))
            except ValueError:
                continue  # a line the catalogue cannot use is a line no ratio needs
            period = str(raw.get("period") or "").strip()
            value = g.as_float(raw.get("value"))
            if value is None or period not in wanted_periods:
                # A period nobody asked for cannot be silently admitted: a reader
                # comparing two columns must be able to trust both labels.
                continue
            if (code, period) in seen:
                continue  # first answer wins; a second is the model contradicting itself
            seen.add((code, period))

            document_id = str(raw.get("document_id") or "").strip()
            if known_documents and document_id not in known_documents:
                # A citation to a file that was not supplied is dropped rather than
                # carried, the same rule the memo's citations follow.
                document_id = ""
            page_raw = raw.get("page")
            page = int(page_raw) if isinstance(page_raw, int | float) and page_raw else None
            out.append(
                CandidateLineItem(
                    code=code,
                    period=period,
                    value=value,
                    currency=currency,
                    document_id=document_id,
                    page=page,
                    quote=str(raw.get("quote") or "").strip()[:400],
                    confidence=g.clamp(raw.get("confidence", 0.0)),
                    provenance=Provenance.EXTRACTED,
                )
            )
        return tuple(out)
