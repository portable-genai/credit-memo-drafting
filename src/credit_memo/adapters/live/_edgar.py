"""SEC EDGAR client for the ``live`` profile: real listed-company facts, cached on disk.

Three public, no-key endpoints (US-government public-domain works):

* ``company_tickers.json`` — the full registrant list, used to resolve a typed
  borrower name to a CIK;
* ``submissions/CIK##########.json`` — registrant profile (SIC, tickers, exchanges,
  latest filings);
* ``api/xbrl/companyfacts/CIK##########.json`` — the XBRL facts every figure in the
  memo grounding is read from.

The SEC's fair-access policy requires an identifying User-Agent and dislikes repeated
bulk downloads, so every successful response is cached on disk (default TTL 24 h,
``live.edgar_cache_ttl_seconds: 0`` disables) and a demo re-run never re-downloads the
same company. Failures are never cached.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from ...config import Settings
from ...envread import setting_or_default

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

#: us-gaap tags read for the memo grounding, in "first tag that exists wins" order.
_METRIC_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "equity": ("StockholdersEquity",),
}

_DEFAULT_CACHE_DIR = Path.home() / ".credit_memo" / "edgar-cache"


class EdgarError(RuntimeError):
    """EDGAR was unreachable or did not know the company."""


def _slug_to_words(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().lower()


class EdgarClient:
    """Fetch + cache the three EDGAR endpoints and derive memo-ready summaries."""

    def __init__(self, settings: Settings) -> None:
        live = settings.live
        # SEC fair-access policy: traffic must be declared with contact information,
        # or www.sec.gov answers with an "Undeclared Automated Tool" page.
        contact = setting_or_default("SEC_EDGAR_CONTACT", "unset")
        self._ua = f"{live.edgar_user_agent} (contact: {contact})"
        self._ttl = live.edgar_cache_ttl_seconds
        self._cache_dir = Path(live.edgar_cache_dir or _DEFAULT_CACHE_DIR)

    # ------------------------------------------------------------------ #
    # Cached fetch
    # ------------------------------------------------------------------ #
    def _get_text(self, url: str) -> str:
        cache_path = self._cache_path(url)
        if self._ttl > 0 and cache_path.is_file():
            age = time.time() - cache_path.stat().st_mtime
            if age <= self._ttl:
                return cache_path.read_text(encoding="utf-8")
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": self._ua},
                timeout=60.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            text = response.text
        except httpx.HTTPError as exc:
            raise EdgarError(f"SEC EDGAR request failed for {url}: {exc}") from exc
        if self._ttl > 0:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(cache_path)
        return text

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            return json.loads(self._get_text(url))
        except json.JSONDecodeError as exc:
            raise EdgarError(f"SEC EDGAR returned non-JSON for {url}: {exc}") from exc

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        hint = re.sub(r"[^A-Za-z0-9]+", "-", url.rsplit("/", 1)[-1])[:40].strip("-")
        return self._cache_dir / f"{digest}-{hint}.json"

    # ------------------------------------------------------------------ #
    # Company resolution
    # ------------------------------------------------------------------ #
    def resolve(self, name_or_slug: str) -> dict[str, Any] | None:
        """Resolve a borrower name (or UI slug) to ``{cik, title, ticker}``.

        Matching is deliberately conservative: exact ticker, exact title, then a
        titles-containing-every-word match. Returns None when nothing matches so the
        caller can fall back to uploaded documents rather than grounding on the wrong
        company.
        """
        wanted = _slug_to_words(name_or_slug)
        if not wanted:
            return None
        table = self._get_json(TICKERS_URL)
        rows = [row for row in table.values() if isinstance(row, dict)]
        by_ticker = next((r for r in rows if str(r.get("ticker", "")).lower() == wanted), None)
        if by_ticker is not None:
            return self._entry(by_ticker)
        exact = next((r for r in rows if str(r.get("title", "")).strip().lower() == wanted), None)
        if exact is not None:
            return self._entry(exact)
        words = [w for w in wanted.split() if w not in {"inc", "corp", "co", "ltd", "plc"}]
        if not words:
            return None
        contains = [r for r in rows if all(w in str(r.get("title", "")).lower() for w in words)]
        if len(contains) == 1:
            return self._entry(contains[0])
        if contains:
            # Prefer the shortest title: "apple" should be Apple Inc., not
            # "Apple Hospitality REIT". Ambiguity beyond that is a non-match.
            contains.sort(key=lambda r: len(str(r.get("title", ""))))
            best, runner_up = contains[0], contains[1] if len(contains) > 1 else None
            if runner_up is None or len(str(best["title"])) < len(str(runner_up["title"])):
                return self._entry(best)
        return None

    @staticmethod
    def _entry(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "cik": str(row.get("cik_str", "")).zfill(10),
            "title": str(row.get("title", "")).strip(),
            "ticker": str(row.get("ticker", "")).strip(),
        }

    # ------------------------------------------------------------------ #
    # Summaries
    # ------------------------------------------------------------------ #
    def submissions(self, cik: str) -> dict[str, Any]:
        return self._get_json(SUBMISSIONS_URL.format(cik=cik.zfill(10)))

    def companyfacts(self, cik: str) -> dict[str, Any]:
        return self._get_json(FACTS_URL.format(cik=cik.zfill(10)))

    def latest_annual_facts(self, cik: str) -> dict[str, dict[str, Any]]:
        """The most recent annual (10-K) USD value per metric, with provenance.

        Returns ``{metric: {value, end, fy, tag}}`` for every metric a tag exists
        for; a company that does not report a tag simply omits that metric.
        """
        facts = self.companyfacts(cik)
        out: dict[str, dict[str, Any]] = {}
        for metric, tags in _METRIC_TAGS.items():
            for tag in tags:
                latest = self._latest_annual(facts, tag)
                if latest is not None:
                    out[metric] = {**latest, "tag": tag}
                    break
        return out

    @staticmethod
    def _latest_annual(facts: dict[str, Any], tag: str) -> dict[str, Any] | None:
        node = facts.get("facts", {}).get("us-gaap", {}).get(tag, {})
        rows = node.get("units", {}).get("USD", [])
        annual = [r for r in rows if r.get("form") == "10-K" and "frame" not in r]
        if not annual:
            return None
        # Later filings restate earlier periods; keep the latest value per period end,
        # then take the most recent period.
        by_end: dict[str, Any] = {}
        for row in annual:
            end = str(row.get("end", ""))
            if end:
                by_end[end] = row
        end, row = sorted(by_end.items())[-1]
        try:
            value = float(row.get("val", 0.0))
        except (TypeError, ValueError):
            return None
        return {"value": value, "end": end, "fy": row.get("fy"), "accn": row.get("accn")}

    def peer_ciks(self, sic: str, exclude_cik: str, limit: int) -> list[str]:
        """CIKs of registrants sharing a SIC code (browse-edgar atom feed).

        Newest CIKs first: the SIC cohort is full of pre-XBRL registrants long since
        dead (their companyfacts 404), and registration order is the best available
        liveness proxy in this feed. The feed's name fields are currently broken
        server-side (Perl ``ARRAY(...)`` stringifications), so only the CIKs are read
        here; a peer's display name comes from its own companyfacts ``entityName``.
        """
        url = (
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&SIC={sic}&type=10-K&owner=include&count=100&output=atom"
        )
        text = self._get_text(url)
        exclude = exclude_cik.lstrip("0")
        ciks = sorted(
            {
                m.group(1).zfill(10)
                for m in re.finditer(r"<cik>(\d+)</cik>", text)
                if m.group(1).lstrip("0") != exclude
            },
            reverse=True,
        )
        return ciks[:limit]

    def entity_name(self, cik: str) -> str:
        """The registrant's display name, from companyfacts (cached)."""
        facts = self.companyfacts(cik)
        return str(facts.get("entityName") or f"CIK {cik.lstrip('0')}")
