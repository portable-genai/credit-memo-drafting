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
