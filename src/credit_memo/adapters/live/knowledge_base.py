"""Live knowledge base (KnowledgeBaseClientPort): real SEC EDGAR grounding.

Same governed SQLite FTS5 store as the local adapter (uploaded borrower documents are
ingested into it with borrower+tenant ACL tags), with one live-only behaviour: when a
search for a borrower finds no evidence yet, the adapter resolves the borrower on SEC
EDGAR, synthesises page-cited passages from the registrant's real submissions and XBRL
company facts, ingests them under the borrower's ACL, and searches again. Typing any
US-listed company name into the demo therefore grounds the memo on that company's real
filings; a borrower EDGAR does not know stays evidence-less until documents are
uploaded (the pipeline then fails closed with its normal RetrievalEmptyError rather
than grounding on fiction: this adapter never seeds the built-in synthetic corpus).

Every passage cites the real public source URL (data.sec.gov endpoints and the EDGAR
filing index), so a reviewer can click from the memo straight to the SEC record.
"""

from __future__ import annotations

import logging

from ...config import Settings
from ...domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)
from ..local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from ._edgar import FACTS_URL, SUBMISSIONS_URL, EdgarClient, EdgarError

_LOG = logging.getLogger(__name__)

_BORROWER_TAG = "borrower:"

#: Every fictional built-in passage cites this host; nothing real ever does.
_FICTION_URL_PREFIX = "https://example.test/"

#: Human labels for the metric keys latest_annual_facts returns.
_METRIC_LABELS = {
    "revenue": "Revenue",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "cash": "Cash and cash equivalents",
    "long_term_debt": "Long-term debt",
    "equity": "Stockholders' equity",
}


def _usd(value: float) -> str:
    # Always millions: the memo's normalised metrics and the peer comparison share the
    # "USD millions" convention (the local seed uses it too), so stating figures in one
    # unit steers the LLM's metric normalisation onto the same scale the peer values use.
    return f"USD {value / 1e6:,.0f} million"


class LiveEdgarKnowledgeBaseAdapter(LocalFtsKnowledgeBaseAdapter):
    """Governed FTS store that lazily grounds a new borrower on real EDGAR data."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._edgar = EdgarClient(settings)
        self._purge_fiction()

    # Structural belt to the base class's profile-aware braces: live never seeds the
    # fictional corpus, whatever profile string this adapter is constructed under.
    def _maybe_seed(self) -> None:
        return

    def _purge_fiction(self) -> None:
        """Drop any fictional seed rows an earlier ``local`` run left in this index.

        Not seeding is not enough: the store is on disk and shared across profiles, so
        a local run's synthetic passages survive into a live one. They carry no ACL
        tags, which the governed search treats as readable by everyone, so a live memo
        could be grounded on invented borrower filings. Deleting them at construction
        makes "live cites only real evidence" true of the store, not just of this run.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM passages WHERE url LIKE ?", (f"{_FICTION_URL_PREFIX}%",)
            )
            self._conn.commit()

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        passages = super().search(query)
        if passages:
            return passages
        borrower_id = self._borrower_from(query)
        if not borrower_id:
            return passages
        try:
            ingested = self._ground_from_edgar(borrower_id, query.acl_principals)
        except EdgarError as exc:
            _LOG.warning("EDGAR grounding unavailable for %r: %s", borrower_id, exc)
            return passages
        if not ingested:
            return passages
        return super().search(query)

    # ------------------------------------------------------------------ #
    # EDGAR grounding
    # ------------------------------------------------------------------ #
    @staticmethod
    def _borrower_from(query: RetrievalQuery) -> str:
        for principal in query.acl_principals:
            if principal.startswith(_BORROWER_TAG):
                return principal[len(_BORROWER_TAG) :]
        return ""

    def _ground_from_edgar(self, borrower_id: str, principals: tuple[str, ...]) -> int:
        entry = self._edgar.resolve(borrower_id)
        if entry is None:
            _LOG.info("borrower %r not found on SEC EDGAR", borrower_id)
            return 0
        cik = entry["cik"]
        sub = self._edgar.submissions(cik)
        facts = self._edgar.latest_annual_facts(cik)

        # ACL: the borrower + tenant tags exactly as the memo pipeline stamps them, so
        # the subsequent governed search (subset match) can see these rows.
        acl_tags = tuple(p for p in principals if p.startswith((_BORROWER_TAG, "tenant:")))

        pages: list[tuple[str, str, str]] = []  # (text, source_kind, url)
        submissions_url = SUBMISSIONS_URL.format(cik=cik)
        facts_url = FACTS_URL.format(cik=cik)

        sic = str(sub.get("sic", ""))
        tickers = ", ".join(sub.get("tickers", [])[:3]) or "n/a"
        exchanges = ", ".join(x for x in sub.get("exchanges", []) if x) or "n/a"
        profile = (
            f"Registrant profile from SEC EDGAR: {entry['title']} (CIK {int(cik)}). "
            f"Listed as {tickers} on {exchanges}. "
            f"Industry (SIC {sic}): {sub.get('sicDescription', 'n/a')}. "
            f"State of incorporation: {sub.get('stateOfIncorporation', 'n/a')}. "
            f"Fiscal year end: {sub.get('fiscalYearEnd', 'n/a')}."
        )
        pages.append((profile, "edgar-profile", submissions_url))

        if facts:
            lines = [
                f"{_METRIC_LABELS.get(k, k)}: {_usd(v['value'])} "
                f"(FY{v.get('fy') or '?'}, period ended {v['end']}, us-gaap:{v['tag']})"
                for k, v in facts.items()
            ]
            financials = (
                f"Audited annual figures for {entry['title']} from the latest 10-K XBRL "
                "company facts filed with the SEC: " + "; ".join(lines) + "."
            )
            pages.append((financials, "edgar-financials", facts_url))

        recent = sub.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        try:
            idx = forms.index("10-K")
        except ValueError:
            idx = -1
        if idx >= 0:
            accession = str(recent.get("accessionNumber", [""])[idx])
            filed = str(recent.get("filingDate", [""])[idx])
            accession_path = accession.replace("-", "")
            index_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_path}/{accession}-index.htm"
            )
            filing = (
                f"Latest annual report (Form 10-K) for {entry['title']}: accession "
                f"{accession}, filed {filed}. Full filing available in the SEC EDGAR "
                "archive."
            )
            pages.append((filing, "edgar-filing", index_url))

        passages = [
            RetrievedPassage(
                text=text,
                citation=Citation(
                    source_id=f"{kind}-{borrower_id}",
                    source_type=SourceType.FILING,
                    title=f"SEC EDGAR: {entry['title']} ({kind.removeprefix('edgar-')})",
                    url=url,
                    page=1,
                    snippet=text[:120],
                    score=0.9,
                ),
                score=0.9,
                acl_tags=acl_tags,
            )
            for text, kind, url in pages
        ]
        count = self.add(passages)
        _LOG.info(
            "grounded borrower %r on SEC EDGAR: %s (CIK %s), %d passages",
            borrower_id,
            entry["title"],
            int(cik),
            count,
        )
        return count
