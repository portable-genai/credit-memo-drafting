"""Built-in synthetic corpus for the ``local`` profile (offline grounding + peer data).

A tiny, clearly-fictional set of borrower-filing and credit-policy passages (with
page-level citations) so the local knowledge-base adapter has something to ground a memo
on out of the box, plus a small peer-financials table for the peer-comparison artifact.
This lets the end-to-end CLI smoke run return a real cited memo with no external corpus.

All text, ids and peer rows are invented and must never be treated as real borrower data.
This lives under ``src`` (not ``tests``) so the shipped package can self-seed without
importing the test tree; it mirrors the shape of ``tests/fixtures/sample_cases`` for
determinism.
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

# Synthetic peer-financials table, keyed by metric (the offline stand-in for SEC EDGAR).
SEED_PEERS: dict[str, tuple[PeerMetric, ...]] = {
    "leverage": (
        PeerMetric(peer_name="Peer Alpha (FICTIONAL)", metric="leverage", value=2.0),
        PeerMetric(peer_name="Peer Beta (FICTIONAL)", metric="leverage", value=3.2),
        PeerMetric(peer_name="Peer Gamma (FICTIONAL)", metric="leverage", value=2.8),
    ),
    "ebitda": (
        PeerMetric(peer_name="Peer Alpha (FICTIONAL)", metric="ebitda", value=20.0),
        PeerMetric(peer_name="Peer Beta (FICTIONAL)", metric="ebitda", value=30.0),
        PeerMetric(peer_name="Peer Gamma (FICTIONAL)", metric="ebitda", value=26.0),
    ),
    "revenue": (
        PeerMetric(peer_name="Peer Alpha (FICTIONAL)", metric="revenue", value=110.0),
        PeerMetric(peer_name="Peer Beta (FICTIONAL)", metric="revenue", value=140.0),
        PeerMetric(peer_name="Peer Gamma (FICTIONAL)", metric="revenue", value=125.0),
    ),
}

#: Source id the deterministic LLM falls back to when a prompt carries no passage headers.
PRIMARY_SOURCE_ID = SEED_PASSAGES[0].citation.source_id
