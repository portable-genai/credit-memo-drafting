"""Built-in synthetic corpus for the ``local`` profile (offline grounding + peer data).

A tiny, clearly-fictional set of borrower-filing and credit-policy passages (with
page-level citations) so the local knowledge-base adapter has something to ground a memo
on out of the box, plus a small peer-financials table for the peer-comparison artifact.
This lets the end-to-end CLI smoke run return a real cited memo with no external corpus.

All text, ids and peer rows are invented and must never be treated as real borrower data.
This lives under ``src`` (not ``tests``) so the shipped package can self-seed without
importing the test tree; it mirrors the shape of ``tests/fixtures/sample_cases`` for
determinism.

**This corpus stays fictional on purpose, and the reason grew stronger, not weaker, when
the demo moved onto a real borrower's filings.** Everything here is the fallback served
when a borrower supplied no evidence at all — so whatever is written below is what a memo
about SOME OTHER company will cite and report as that company's figures. Filling it with a
real registrant's filed numbers would mean a memo for an unknown borrower quoting a real
company's revenue and leverage as its own, which is a worse failure than the one the move
to real data was meant to fix. The obviously-invented names and the ``(FICTIONAL)`` on
every title are what make that fallback visible to a reader the moment it happens.

The demo does not rely on this. It uploads Flowserve Corporation's real filed documents
(``demo/documents/``), which retrieve on their own and shut the fallback out entirely.
"""

from __future__ import annotations

from ...domain.models import (
    Citation,
    PeerMetric,
    RetrievedPassage,
    SourceType,
)

#: The ACL tag every built-in passage carries. A query holds it only via the fallback in
#: ``LocalFtsKnowledgeBaseAdapter.search``, which admits this corpus when the borrower's own
#: evidence retrieved NOTHING -- so the out-of-the-box CLI smoke run is still grounded, and a
#: borrower that supplied filings is grounded in those filings and only those.
DEMO_CORPUS_TAG = "demo:seed-corpus"


def _passage(
    *,
    source_id: str,
    source_type: SourceType,
    title: str,
    page: int,
    text: str,
    score: float,
) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        citation=Citation(
            source_id=source_id,
            source_type=source_type,
            title=title,
            url=f"https://example.test/{source_id}",
            page=page,
            snippet=text[:120],
            score=score,
        ),
        score=score,
        # Tagged, and deliberately NOT untagged. Untagged means public under the ACL
        # contract, so this fictional corpus was visible to every borrower: it competed
        # with a borrower's own ingested filings on relevance, outranked them, and --
        # because retrieval is capped at top_k -- displaced them. Memos for a real
        # borrower were grounded in invented filings and cited them, and the covenant
        # extractor read leverage and DSCR straight out of a made-up certificate.
        acl_tags=(DEMO_CORPUS_TAG,),
    )


# A small, deterministic corpus. Page numbers are required for credit-memo provenance.
SEED_PASSAGES: tuple[RetrievedPassage, ...] = (
    _passage(
        source_id="doc-financials",
        source_type=SourceType.FILING,
        title="Acme 2025 Audited Financial Statements (FICTIONAL)",
        page=4,
        text=(
            "The audited 2025 financial statements report revenue of USD 120m, EBITDA of "
            "USD 24m, and net debt of USD 60m, giving net leverage of 2.5x."
        ),
        score=0.94,
    ),
    _passage(
        source_id="doc-loan-agreement",
        source_type=SourceType.FILING,
        title="Acme Senior Facility Agreement (FICTIONAL)",
        page=18,
        text=(
            "The senior facility agreement sets a maximum net-leverage covenant of 3.0x "
            "and a minimum debt-service coverage ratio (DSCR) of 1.25x, tested quarterly."
        ),
        score=0.90,
    ),
    _passage(
        source_id="doc-covenant-cert",
        source_type=SourceType.FILING,
        title="Acme Q4 Covenant Compliance Certificate (FICTIONAL)",
        page=2,
        text=(
            "The Q4 covenant certificate reports current net leverage of 2.5x and a "
            "current DSCR of 1.40x for the borrower."
        ),
        score=0.88,
    ),
    _passage(
        source_id="policy-mfg-concentration",
        source_type=SourceType.POLICY,
        title="Manufacturing Sector Credit Policy (FICTIONAL)",
        page=7,
        text=(
            "Credit policy guidance for the manufacturing sector flags concentration risk "
            "when a single customer accounts for more than 25 percent of revenue."
        ),
        score=0.80,
    ),
)

# Peer financials, keyed by metric: the offline stand-in for the SEC EDGAR peer adapter.
#
# REAL companies and REAL filed figures, unlike the passages above, and the difference is
# deliberate. A peer table names other companies as comparators; it never speaks for the
# borrower, so there is no misattribution to guard against — and inventing it does active
# harm. When the demo moved onto a real borrower, three fictional peers with revenue
# around USD 125m put Flowserve's USD 4.7bn at the hundredth percentile of its own sector,
# which is a confident, precise and meaningless number.
#
# All three are flow-control manufacturers, all figures from each company's own FY2025
# Form 10-K via the XBRL company facts at data.sec.gov, in USD millions. EBITDA is
# operating income plus depreciation and amortisation, the same statutory definition the
# borrower's spread uses, so the comparison is like for like.
SEED_PEERS: dict[str, tuple[PeerMetric, ...]] = {
    "leverage": (
        PeerMetric(peer_name="Watts Water Technologies, Inc.", metric="leverage", value=0.39),
        PeerMetric(peer_name="ITT Inc.", metric="leverage", value=0.63),
        PeerMetric(peer_name="Xylem Inc.", metric="leverage", value=0.78),
    ),
    "ebitda": (
        PeerMetric(peer_name="Watts Water Technologies, Inc.", metric="ebitda", value=504.9),
        PeerMetric(peer_name="ITT Inc.", metric="ebitda", value=827.7),
        PeerMetric(peer_name="Xylem Inc.", metric="ebitda", value=1798.0),
    ),
    "revenue": (
        PeerMetric(peer_name="Watts Water Technologies, Inc.", metric="revenue", value=2438.5),
        PeerMetric(peer_name="ITT Inc.", metric="revenue", value=3938.5),
        PeerMetric(peer_name="Xylem Inc.", metric="revenue", value=9035.0),
    ),
}

#: Source id the deterministic LLM falls back to when a prompt carries no passage headers.
PRIMARY_SOURCE_ID = SEED_PASSAGES[0].citation.source_id

#: What each built-in document actually SAYS, keyed by the filing id that carries it.
#:
#: The memo pipeline can ingest a filing by reference, with no bytes: the CLI and the
#: presenter demo both do. The extraction stand-in then had nothing to extract and
#: synthesised a placeholder sentence with no figures in it, so the offline demo's
#: evidence said nothing while its memo reported revenue, EBITDA and two covenants. Those
#: numbers came from the LLM stand-in's own hardcoded body, which is exactly the failure
#: a grounded assistant exists to prevent. Handing back the corpus's own text makes the
#: demo report what its documents say.
SEED_DOCUMENT_TEXT: dict[str, str] = {
    passage.citation.source_id: passage.text for passage in SEED_PASSAGES
}
