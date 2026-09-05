"""WebResearchPort — sector and borrower context from the public web, for the analyst only.

This is the one place in the service that reaches outside the bank's own evidence, and
it is fenced on three sides. Each fence exists for a different reason and none of them is
optional.

**Licensing.** Google's Service Specific Terms section 20(k) permit Grounded Results to be
displayed only to the End User who submitted the prompt, forbid interspersing them with
other content, and survive termination of the agreement. A credit memo is read by a
checker, a committee and later an examiner — none of whom submitted the prompt. So
results reach the analyst who asked and go no further: they are never written into the
memo, never included in an export, and never persisted beyond a query log of
``(query, url, title, retrieved_at)``. An analyst who wants a fact in the memo types it
and cites the URL, which makes it USER_ENTERED and theirs.

**Residency.** Vertex serves web grounding from the global endpoint only, so the search
leg is processed outside the deploy region. That is a decision about where a QUERY goes,
recorded as a deviation in the deployment posture; the uploaded documents, the analysis
bundle, the memo and the audit trail all stay in region. It is also why queries carry
public identity only — a borrower's name, sector and jurisdiction — and never a guarantor
or director's name, a UEN, an account number or the terms of the facility.

**The deterministic-engine boundary.** :class:`WebEvidence` carries no numeric field, so
there is no number on it for a ratio, a covenant test, a policy rule or a scorecard to
reach for even by accident. The ``research_isolation`` gate metric proves it.

An adapter that cannot search returns ``None`` rather than an empty result. "We could not
look" and "we looked and found nothing" are different answers, and an analyst deciding
whether to go and check themselves needs to know which one they got.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import MarketContext


@runtime_checkable
class WebResearchPort(Protocol):
    def research(
        self,
        query: str,
        purpose: str = "",
        max_results: int = 8,
    ) -> MarketContext | None:
        """Search the public web and return what was found, or None if it could not.

        ``purpose`` is recorded in the audit log beside the redacted query: "why did this
        service search the web for this borrower" is a question a reviewer asks, and the
        query alone does not answer it.
        """
        ...
