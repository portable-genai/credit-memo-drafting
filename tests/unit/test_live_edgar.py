"""The live profile's real-data behaviours, with EDGAR mocked at the client seam.

Pinned here:

* the live knowledge base never seeds the fictional corpus, lazily grounds an unknown
  borrower on EDGAR facts under the caller's ACL, and leaves a borrower EDGAR does not
  know evidence-less (fail closed downstream, never fiction);
* the live peer adapter converts filed values to the memo's USD-millions convention,
  skips dead registrants and stale figures, and degrades to [] on EDGAR failure;
* the borrower-document upload endpoint ingests audience evidence with the same
  server-side authorization as the memo build, and the upload template is downloadable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from credit_memo.adapters.live import _edgar
from credit_memo.adapters.live.knowledge_base import LiveEdgarKnowledgeBaseAdapter
from credit_memo.adapters.live.peer_data import LiveEdgarPeerDataAdapter
from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.config import LocalSettings, Settings
from credit_memo.domain.models import Borrower, RetrievalQuery

_ACL = ("group:credit-analyst", "tenant:demo-bank", "borrower:apple-inc")


def _settings(profile: str = "live") -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        profile=profile,
        adapters=base.adapters,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        live=base.live,
    )


class _FakeEdgar:
    """Answers like EdgarClient for one known company; unknown names resolve to None."""

    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve(self, name_or_slug: str):
        self.resolved.append(name_or_slug)
        if "apple" not in name_or_slug:
            return None
        return {"cik": "0000320193", "title": "Apple Inc.", "ticker": "AAPL"}

    def submissions(self, cik: str) -> dict:
        return {
            "sic": "3571",
            "sicDescription": "Electronic Computers",
            "tickers": ["AAPL"],
            "exchanges": ["Nasdaq"],
            "stateOfIncorporation": "CA",
            "fiscalYearEnd": "0927",
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K"],
                    "accessionNumber": ["0000320193-25-000079", "x"],
                    "filingDate": ["2025-10-31", "2025-10-01"],
                }
            },
        }

    def latest_annual_facts(self, cik: str) -> dict:
        return {
            "revenue": {
                "value": 391_035_000_000.0,
                "end": "2024-09-28",
                "fy": 2024,
                "tag": "Revenues",
            }
        }


def test_live_kb_never_seeds_fiction_and_grounds_from_edgar(monkeypatch) -> None:
    adapter = LiveEdgarKnowledgeBaseAdapter(_settings())
    adapter._edgar = _FakeEdgar()  # type: ignore[assignment]

    # No fiction: with no EDGAR call yet, the index is empty (the local profile would
    # have self-seeded example.test passages here).
    bare = adapter.search(RetrievalQuery(text="credit context", top_k=5))
    assert bare == [] or all(not p.citation.url.startswith("https://example.test/") for p in bare)

    hits = adapter.search(
        RetrievalQuery(
            text="financial statements and credit context for Apple Inc",
            top_k=8,
            acl_principals=_ACL,
        )
    )
    assert hits, "EDGAR grounding must produce passages for a resolvable borrower"
    urls = {h.citation.url for h in hits}
    assert any("data.sec.gov" in u for u in urls)
    assert all(not u.startswith("https://example.test/") for u in urls)
    # The figures carry the USD-millions convention the peer comparison relies on.
    financials = next(h for h in hits if "edgar-financials" in h.citation.source_id)
    assert "USD 391,035 million" in financials.text


def test_live_kb_leaves_unknown_borrowers_evidence_less() -> None:
    adapter = LiveEdgarKnowledgeBaseAdapter(_settings())
    adapter._edgar = _FakeEdgar()  # type: ignore[assignment]
    hits = adapter.search(
        RetrievalQuery(
            text="context for Meridian Robotics",
            top_k=5,
            acl_principals=("borrower:meridian-robotics",),
        )
    )
    assert hits == []


class _FakePeerEdgar(_FakeEdgar):
    def peer_ciks(self, sic: str, exclude_cik: str, limit: int) -> list[str]:
        return ["0000000009", "0000000001", "0000000002", "0000000003"]

    def latest_annual_facts(self, cik: str) -> dict:
        if cik.endswith("9"):
            raise _edgar.EdgarError("no facts (dead registrant)")
        if cik.endswith("3"):
            return {"revenue": {"value": 1e9, "end": "2013-12-31", "fy": 2013, "tag": "Revenues"}}
        return {
            "revenue": {
                "value": 95_567_000_000.0,
                "end": "2025-01-31",
                "fy": 2025,
                "tag": "Revenues",
            }
        }

    def entity_name(self, cik: str) -> str:
        return f"Peer {cik[-1]}"


def test_live_peer_adapter_converts_to_millions_and_skips_dead_or_stale() -> None:
    adapter = LiveEdgarPeerDataAdapter(_settings())
    adapter._edgar = _FakePeerEdgar()  # type: ignore[assignment]
    peers = adapter.peers_for(Borrower(id="apple-inc", name="Apple Inc"), "Revenue")
    names = [p.peer_name for p in peers]
    assert "Peer 9" not in names, "a dead registrant must be skipped, not fatal"
    assert "Peer 3" not in names, "a 2013 figure is stale, not a comparable"
    assert peers and all(p.value == pytest.approx(95_567.0) for p in peers)


def test_live_peer_adapter_returns_empty_for_unsupported_metric() -> None:
    adapter = LiveEdgarPeerDataAdapter(_settings())
    adapter._edgar = _FakePeerEdgar()  # type: ignore[assignment]
    assert adapter.peers_for(Borrower(id="apple-inc", name="Apple Inc"), "dscr") == []


# --------------------------------------------------------------------------- #
# Peer ratios: the same catalogue formula, over the peer's own filed figures
# --------------------------------------------------------------------------- #
_END = "2025-01-31"


def _fact(value: float, end: str = _END, tag: str = "Tag") -> dict:
    return {"value": value, "end": end, "fy": 2025, "tag": tag}


#: One peer's 10-K, in whole USD as EDGAR reports them. EBITDA (25,000m) is derived from
#: operating income plus D&A, and total debt (100,000m) from the non-current balance plus
#: the current portion, so a formula reading either exercises the derivations.
_RICH_FACTS: dict[str, dict] = {
    "revenue": _fact(125e9),
    "operating_income": _fact(20e9),
    "depreciation_amortisation": _fact(5e9),
    "interest_expense": _fact(5e9),
    "long_term_debt": _fact(80e9, tag="LongTermDebtNoncurrent"),
    "current_debt": _fact(20e9, tag="LongTermDebtCurrent"),
    "current_assets": _fact(60e9),
    "current_liabilities": _fact(30e9),
    "inventory": _fact(6e9),
    "equity": _fact(50e9),
    "intangible_assets": _fact(4e9),
    "goodwill": _fact(10e9),
}


class _FakeRatioEdgar(_FakeEdgar):
    """One peer, with whatever fact set a test hands it."""

    def __init__(self, facts: dict[str, dict]) -> None:
        super().__init__()
        self._facts = facts

    def peer_ciks(self, sic: str, exclude_cik: str, limit: int) -> list[str]:
        return ["0000000001"]

    def latest_annual_facts(self, cik: str) -> dict:
        return self._facts

    def entity_name(self, cik: str) -> str:
        return "Peer One"


def _peer_value(metric: str, facts: dict[str, dict] | None = None) -> float | None:
    adapter = LiveEdgarPeerDataAdapter(_settings())
    adapter._edgar = _FakeRatioEdgar(facts if facts is not None else _RICH_FACTS)  # type: ignore[assignment]
    peers = adapter.peers_for(Borrower(id="apple-inc", name="Apple Inc"), metric)
    return peers[0].value if peers else None


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        pytest.param("leverage", 4.0, id="leverage: 100,000 debt / 25,000 derived EBITDA"),
        pytest.param("Interest cover", 5.0, id="interest cover, named as the memo labels it"),
        pytest.param("current_ratio", 2.0, id="current ratio"),
        pytest.param("quick_ratio", 1.8, id="quick ratio nets inventory off"),
        pytest.param("gearing", 2.0, id="gearing"),
        pytest.param("ebitda_margin", 0.2, id="EBITDA margin"),
    ],
)
def test_a_peer_ratio_is_computed_by_the_catalogue_formula(metric: str, expected: float) -> None:
    """The only way the comparison means anything.

    A peer median assembled from a vendor's definition of leverage and a borrower figure
    from the bank's own compares two different quantities that share a name. Here both
    come from the same versioned formula id.
    """
    assert _peer_value(metric) == pytest.approx(expected)


def test_tangible_net_worth_treats_goodwill_as_an_intangible() -> None:
    """Goodwill is tagged apart from other intangibles and is usually the larger.

    Ignoring it overstates tangible net worth by the size of the peer's acquisitions.
    """
    assert _peer_value("tangible_net_worth") == pytest.approx(50_000 - 4_000 - 10_000)


def test_debt_that_already_includes_the_current_portion_is_not_counted_twice() -> None:
    """``LongTermDebt`` is the inclusive tag; adding the current portion double-counts."""
    facts = {**_RICH_FACTS, "long_term_debt": _fact(100e9, tag="LongTermDebt")}
    assert _peer_value("gearing", facts) == pytest.approx(2.0)  # 100,000 / 50,000, not 120,000


def test_only_facts_from_one_fiscal_year_end_reach_a_spread() -> None:
    """A ratio whose numerator and denominator are from different years is wrong quietly.

    The peer is skipped rather than reported on a mixed-period basis, so the peer set
    shrinks instead of silently gaining a wrong member.
    """
    facts = {**_RICH_FACTS, "current_liabilities": _fact(30e9, end="2024-01-31")}
    assert _peer_value("current_ratio", facts) is None


def test_a_peer_missing_an_operand_contributes_nothing_rather_than_a_guess() -> None:
    facts = {k: v for k, v in _RICH_FACTS.items() if k != "interest_expense"}
    assert _peer_value("interest_cover", facts) is None


@pytest.mark.parametrize("metric", ["dscr", "fccr", "fixed-charge coverage"])
def test_coverage_ratios_needing_debt_service_are_not_offered_at_all(metric: str) -> None:
    """No filer tags scheduled debt service, and EDGAR carries no substitute for it.

    A coverage ratio built on a guessed denominator would look exactly like one built on
    a filed figure, so these metrics are absent from the map rather than approximated.
    """
    assert _peer_value(metric) is None


# --------------------------------------------------------------------------- #
# Borrower document upload (audience data)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "local")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


def test_upload_template_is_downloadable_csv(client: TestClient) -> None:
    response = client.get("/v1/documents/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "field,required,example,notes"


def test_upload_ingests_borrower_evidence(client: TestClient) -> None:
    response = client.post(
        "/v1/documents",
        headers={"X-Dev-Persona": "analyst"},
        files={"file": ("fin.txt", b"Revenue: USD 85 million. EBITDA: USD 17m.", "text/plain")},
        data={
            "borrower_id": "meridian-robotics-pte-ltd",
            "title": "Meridian FY2025 Audited Financial Statements",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["chunks"] == 1
    assert body["borrower_id"] == "meridian-robotics-pte-ltd"


def test_upload_rejects_unknown_doc_type_and_empty_file(client: TestClient) -> None:
    bad_type = client.post(
        "/v1/documents",
        headers={"X-Dev-Persona": "analyst"},
        files={"file": ("fin.txt", b"text", "text/plain")},
        data={"borrower_id": "b1", "title": "Some Title", "doc_type": "nope"},
    )
    assert bad_type.status_code == 422
    empty = client.post(
        "/v1/documents",
        headers={"X-Dev-Persona": "analyst"},
        files={"file": ("fin.txt", b"", "text/plain")},
        data={"borrower_id": "b1", "title": "Some Title"},
    )
    assert empty.status_code == 422


def test_live_kb_purges_fiction_left_by_an_earlier_local_run(tmp_path) -> None:
    """The store outlives the profile, so not-seeding is not enough.

    A prior local run writes synthetic passages to the shared on-disk index. They carry
    no ACL tags, which the governed search treats as readable by everyone, so a live
    memo could be grounded on invented borrower filings while claiming to be real.
    """
    from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter

    db = str(tmp_path / "kb.db")
    base = Settings.load("config/settings.yaml")
    local = LocalFtsKnowledgeBaseAdapter(
        Settings(
            profile="local",
            adapters=base.adapters,
            local=LocalSettings(db_path=db, audit_path=":memory:"),
        )
    )
    seeded = local.search(RetrievalQuery(text="credit policy manufacturing", top_k=5))
    assert any(p.citation.url.startswith("https://example.test/") for p in seeded)

    live = LiveEdgarKnowledgeBaseAdapter(
        Settings(
            profile="live",
            adapters=base.adapters,
            local=LocalSettings(db_path=db, audit_path=":memory:"),
        )
    )
    live._edgar = _FakeEdgar()  # type: ignore[assignment]
    after = live.search(RetrievalQuery(text="credit policy manufacturing", top_k=5))
    assert all(not p.citation.url.startswith("https://example.test/") for p in after)


# --------------------------------------------------------------------------- #
# Fact selection: one period, and the tag that carries the figure
# --------------------------------------------------------------------------- #
def _usd(**kw: object) -> dict:
    """One companyfacts row, in the shape data.sec.gov actually returns."""
    row = {"form": "10-K", "fy": 2025, "fp": "FY", "accn": "0000030625-26-000003"}
    row.update(kw)
    return row


def _client() -> _edgar.EdgarClient:
    return _edgar.EdgarClient(Settings(profile="live"))


def _facts(gaap: dict) -> dict:
    """``{tag: [rows]}`` in the units/USD nesting data.sec.gov wraps every tag in."""
    return {"facts": {"us-gaap": {tag: {"units": {"USD": rows}} for tag, rows in gaap.items()}}}


def test_every_figure_comes_from_one_reporting_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """A spread mixing two years reconciles against nothing and misstates every ratio.

    This is the shape the real filings had: the balance sheet had rolled forward to the
    new year end while an income-statement tag the company had stopped using still held
    the prior year, and reading each tag's own latest fact silently combined them.
    """
    gaap = {
        # Income statement: reported for both years.
        "Revenues": [
            _usd(start="2024-01-01", end="2024-12-31", val=4_000e6),
            _usd(start="2025-01-01", end="2025-12-31", val=4_729e6),
        ],
        # Balance sheet: same two year ends.
        "Assets": [_usd(end="2024-12-31", val=5_000e6), _usd(end="2025-12-31", val=5_708e6)],
        # A line the company stopped tagging after 2024. It must be ABSENT, not carried
        # forward into a 2025 spread as though it were this year's figure.
        "Liabilities": [_usd(end="2024-12-31", val=3_100e6)],
    }
    client = _client()
    monkeypatch.setattr(client, "companyfacts", lambda cik: _facts(gaap))
    facts = client.latest_annual_facts("0000030625")

    assert {f["end"] for f in facts.values()} == {"2025-12-31"}
    assert facts["revenue"]["value"] == 4_729e6
    assert facts["total_assets"]["value"] == 5_708e6
    assert "total_liabilities" not in facts


def test_a_tag_reporting_zero_loses_to_one_reporting_the_figure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flowserve's real filing: ``Revenues`` is tagged 0 and the revenue is elsewhere.

    Preferring the first tag that exists grounded the memo on revenue of zero. A total of
    zero beside a non-zero tag for the same concept is an artifact of how the filer split
    the line, not a claim that the company earned nothing.
    """
    gaap = {
        "Revenues": [_usd(start="2025-01-01", end="2025-12-31", val=0)],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            _usd(start="2025-01-01", end="2025-12-31", val=4_729.3e6)
        ],
        "Assets": [_usd(end="2025-12-31", val=5_708.2e6)],
    }
    client = _client()
    monkeypatch.setattr(client, "companyfacts", lambda cik: _facts(gaap))
    facts = client.latest_annual_facts("0000030625")

    assert facts["revenue"]["value"] == 4_729.3e6
    assert facts["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_a_genuine_zero_still_comes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuine zero is a fact about the borrower, not a tagging artifact.

    Zero only loses to a non-zero alternative for the SAME concept; with no alternative
    it is the answer, and must not be dropped into "not supplied".
    """
    gaap = {
        "Revenues": [_usd(start="2025-01-01", end="2025-12-31", val=1_000e6)],
        "Assets": [_usd(end="2025-12-31", val=2_000e6)],
        "LongTermDebtCurrent": [_usd(end="2025-12-31", val=0)],
    }
    client = _client()
    monkeypatch.setattr(client, "companyfacts", lambda cik: _facts(gaap))
    facts = client.latest_annual_facts("0000030625")

    assert facts["current_debt"]["value"] == 0.0


def test_a_restated_period_takes_the_later_filing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two filings report the same period; the restatement is the one that stands."""
    gaap = {
        "Revenues": [
            _usd(start="2025-01-01", end="2025-12-31", val=900e6, accn="0000030625-26-000003"),
            _usd(start="2025-01-01", end="2025-12-31", val=950e6, accn="0000030625-27-000010"),
        ],
        "Assets": [_usd(end="2025-12-31", val=2_000e6)],
    }
    client = _client()
    monkeypatch.setattr(client, "companyfacts", lambda cik: _facts(gaap))

    assert client.latest_annual_facts("0000030625")["revenue"]["value"] == 950e6


def test_capex_is_read_from_either_tag_filers_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filers split between two capex tags; reading one left half the peers uncomparable."""
    gaap = {
        "Revenues": [_usd(start="2025-01-01", end="2025-12-31", val=1_000e6)],
        "Assets": [_usd(end="2025-12-31", val=2_000e6)],
        "PaymentsToAcquireProductiveAssets": [
            _usd(start="2025-01-01", end="2025-12-31", val=70.9e6)
        ],
    }
    client = _client()
    monkeypatch.setattr(client, "companyfacts", lambda cik: _facts(gaap))

    assert client.latest_annual_facts("0000030625")["capex"]["value"] == 70.9e6
