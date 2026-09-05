"""Gemini web research (WebResearchPort) — Grounding with Google Search, fenced.

Sector outlook, a listed borrower's recent filings, a regulatory action, a public
property transaction: things an analyst would otherwise open a browser for. This runs
that search from inside the console and hands back what it found, to the analyst who
asked and to nobody else.

Every constraint below is load-bearing, and each has a different source.

**Service Specific Terms section 20(k).** Grounded Results may be displayed only to the
End User who submitted the prompt (i)(1); may not be interspersed with other content
(4.1); may not be cached, analysed or indexed (i)(2); and the restrictions survive
termination (iv). A credit memo is read by a checker, a committee and later an examiner —
none of whom submitted the prompt. So results never enter the memo, the export or the
review payload. Search Suggestion chips come back verbatim because Google requires them
rendered, and dropping them is a licence breach that looks like a tidy UI.

**Residency.** Vertex serves grounding from the global endpoint only, so the search leg
is processed outside asia-southeast1. That is a recorded deviation about where a QUERY
goes; the documents, the bundle, the memo and the audit trail stay in region. It is also
why the query is redacted and carries public identity only — a borrower's name, sector
and jurisdiction — never a guarantor or director's name, a UEN, an account number, or the
terms of the facility.

**Cost.** Grounding is billed per query with no free headroom on this account (the
5,000/month pool is shared across the portfolio and already consumed by siblings), and
one prompt can fan out into several billable queries. Hence a hard per-analysis cap.

**The engine boundary.** :class:`WebEvidence` carries no numeric field, so nothing here
can supply an operand to a ratio, a covenant test, a policy rule or a scorecard. That is
the type's job; this adapter simply cannot construct anything else.

All GenAI SDK imports are lazy so local, live, on-prem and test profiles import this
module without ``google-genai``.
"""

from __future__ import annotations

import re
from typing import Any

from ...config import Settings
from ...domain.models import (
    LlmMessage,
    LlmRequest,
    MarketContext,
    ThinkingLevel,
    WebEvidence,
)

RESEARCH_SYSTEM = (
    "You are helping a credit analyst gather public context on a borrower or its sector. "
    "Search the public web and report what you find.\n\n"
    "Rules:\n"
    "- Report only what the search returned. Never supply a figure, a date or a fact from "
    "your own knowledge: the analyst is using this to decide whether to go and check, and "
    "a confident answer they cannot trace wastes the trip.\n"
    "- Give the source for everything. A claim with no URL is not usable here.\n"
    "- Prefer primary sources: the company's own filings and announcements, a regulator, a "
    "statistics agency. A news summary of a filing is worth less than the filing.\n"
    "- Say plainly when the search found little. 'Nothing recent was published' is a "
    "useful answer; padding it with general industry commentary is not."
)


class GeminiWebResearchAdapter:
    """Search the public web via Gemini grounding, for the analyst who asked."""

    #: Ceiling per analysis. One prompt can fan out into several billable grounding
    #: queries, and there is no free allowance on this billing account.
    MAX_QUERIES_PER_ANALYSIS = 12

    #: Patterns that must never reach a query. Public identity is fine — a borrower's
    #: registered name is public — but an account number, an identifier or the terms of a
    #: facility are the bank's business and would leave the region in a search string.
    _FORBIDDEN = (
        re.compile(r"\b\d{6,}\b"),  # account numbers, long identifiers
        re.compile(r"\b[0-9]{8,9}[A-Z]\b", re.I),  # SG UEN / NRIC shapes
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),  # IBAN
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),  # anything addressed to a person
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._queries_run = 0
        self._client: Any | None = None

    def _get_client(self) -> Any:
        from google import genai  # lazy: GCP SDK only on this path

        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self.settings.project_id,
                # `global`, not the deploy region: Vertex serves grounding from the global
                # endpoint only. This is the residency deviation, in one line, deliberately
                # not hidden behind a settings lookup that would make it look incidental.
                location="global",
            )
        return self._client

    def research(
        self,
        query: str,
        purpose: str = "",
        max_results: int = 8,
    ) -> MarketContext | None:
        """Search, or return None if this adapter will not or cannot.

        None rather than an empty result on refusal, because "we did not look" and "we
        looked and found nothing" lead an analyst to do different things next.
        """
        if self._queries_run >= self.MAX_QUERIES_PER_ANALYSIS:
            return None
        safe = self._safe_query(query)
        if not safe:
            return None

        try:
            from google.genai import types

            client = self._get_client()
            self._queries_run += 1
            response = client.models.generate_content(
                model=self.settings.models.reasoning,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=safe)],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=RESEARCH_SYSTEM,
                    temperature=0.0,
                    # The search tool cannot be combined with a response schema on Vertex,
                    # which is why this adapter parses prose rather than asking for JSON,
                    # and why it is a separate agent from the memo drafter.
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
                ),
            )
        except Exception:  # noqa: BLE001 - a failed search must never fail a memo
            return None

        return MarketContext(
            query=safe,
            purpose=purpose,
            evidence=self._evidence(response, max_results),
            search_suggestions=self._suggestions(response),
            provider="gemini-grounding-google-search",
        )

    # ------------------------------------------------------------------ #
    # Query hygiene
    # ------------------------------------------------------------------ #
    def _safe_query(self, query: str) -> str:
        """The query with anything that must not leave the region removed.

        Refuses rather than redacts when a forbidden pattern is present. A query with an
        account number scrubbed out of the middle is a query whose meaning changed, and
        the analyst should see that it was rejected rather than receive results for a
        question they did not ask.
        """
        cleaned = " ".join(query.split())[:400]
        if not cleaned:
            return ""
        for pattern in self._FORBIDDEN:
            if pattern.search(cleaned):
                return ""
        return cleaned

    # ------------------------------------------------------------------ #
    # Reading the response
    # ------------------------------------------------------------------ #
    @staticmethod
    def _evidence(response: Any, max_results: int) -> tuple[WebEvidence, ...]:
        """The grounding chunks, as evidence with a URL each.

        Read from ``grounding_metadata`` rather than from the model's prose: the metadata
        is what Google actually retrieved, and the prose is the model's account of it. A
        URL the model wrote into a sentence may not be one the search returned.
        """
        out: list[WebEvidence] = []
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", "") if web else ""
                if not uri:
                    continue
                out.append(
                    WebEvidence(
                        title=getattr(web, "title", "") or uri,
                        url=uri,
                        snippet=(getattr(web, "domain", "") or "")[:200],
                    )
                )
                if len(out) >= max_results:
                    return tuple(out)
        return tuple(out)

    @staticmethod
    def _suggestions(response: Any) -> tuple[str, ...]:
        """The Search Suggestion chips, verbatim.

        Google requires these rendered alongside grounded results. Dropping them is a
        licence breach that looks like a tidy interface, which is exactly the kind of
        breach that survives review.
        """
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            entry = getattr(metadata, "search_entry_point", None)
            rendered = getattr(entry, "rendered_content", "") if entry else ""
            if rendered:
                return (rendered,)
        return ()


def build_query(borrower_name: str, sector: str, jurisdiction: str, topic: str) -> str:
    """A query carrying public identity only.

    Assembled here rather than by a caller so there is one place that decides what may go
    into a search string. A borrower's registered name, its sector and its jurisdiction
    are public; everything else the bank knows about it is not.
    """
    parts = [borrower_name.strip(), sector.strip(), jurisdiction.strip(), topic.strip()]
    return " ".join(part for part in parts if part)


def research_request(query: str) -> LlmRequest:
    """The request shape, exposed so a test can assert on it without a client."""
    return LlmRequest(
        messages=(LlmMessage(role="user", content=query),),
        system_instruction=RESEARCH_SYSTEM,
        thinking=ThinkingLevel.LOW,
        temperature=0.0,
    )
