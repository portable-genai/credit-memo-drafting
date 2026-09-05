"""A reviewer's objection stays attached to the text they actually read.

A checker writes "this overstates the headroom" against a paragraph. Three edits later that
paragraph says something else. A comment system that silently re-points the note has changed
what the reviewer said and put an objection next to text its author never saw.

Four properties hold that, and each fails silently if it breaks:

* **The anchor is a revision, not just a section.** Every comment records the revision and
  its digest, so "the text has moved on" is checkable rather than inferred.
* **A moved section flags the comment, it does not close it.** A comment that lapsed because
  the text changed underneath it was not answered — it was lost — and the two are
  indistinguishable in a list afterwards.
* **Only a person resolves.** With their name on it, and re-resolving is refused, because a
  second write would destroy the record of who answered.
* **Staleness is computed on read.** A stored flag says what was true when it was written,
  which for this field is the one moment nobody is asking about.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.domain.comment_service import CommentService
from credit_memo.domain.models import MemoComment
from credit_memo.domain.revision_service import RevisionService

ANALYST = {"X-Dev-Persona": "analyst"}
SPREAD_CSV = b"code,period,value\nrevenue,FY2025,4200\nebitda,FY2025,760\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[TestClient]:
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "local")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_ANALYSIS_ROOT", str(tmp_path))
    deps.get_container.cache_clear()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
            yield test_client
    finally:
        deps.get_container.cache_clear()


def _built(client: TestClient) -> str:
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("spread.csv", SPREAD_CSV, "text/csv"))],
        data={"borrower_id": "acme-manufacturing", "doc_types": "financial_statement"},
    )
    analysis_id = response.json()["analysis_id"]
    assert client.post(f"/v1/analyses/{analysis_id}/build", headers=ANALYST, json={}).status_code
    return analysis_id


def _comment(client: TestClient, analysis_id: str, section: str, body: str) -> dict:
    response = client.post(
        f"/v1/analyses/{analysis_id}/comments",
        headers=ANALYST,
        json={"section": section, "body": body},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


# --------------------------------------------------------------------------- #
# The type refuses what a review thread cannot use
# --------------------------------------------------------------------------- #
def test_a_comment_needs_a_body_and_an_author() -> None:
    with pytest.raises(ValueError, match="not a comment"):
        MemoComment(id="c1", section="summary", body="   ", author="a@b.example", revision=1)
    with pytest.raises(ValueError, match="named author"):
        MemoComment(id="c1", section="summary", body="text", author="", revision=1)


def test_half_a_resolution_is_refused() -> None:
    """Closed to one query and open to another is the worst of both."""
    with pytest.raises(ValueError, match="who closed it and when"):
        MemoComment(
            id="c1",
            section="summary",
            body="text",
            author="a@b.example",
            revision=1,
            resolved_by="checker@bank.example",
        )


# --------------------------------------------------------------------------- #
# The anchor
# --------------------------------------------------------------------------- #
def test_a_comment_records_the_revision_the_author_read(client: TestClient) -> None:
    analysis_id = _built(client)
    comment = _comment(client, analysis_id, "summary", "This overstates the headroom.")
    assert comment["revision"] == 1
    assert comment["anchor_digest"], "the digest is what survives a renumbering"
    assert comment["author"] == "demo.analyst@bank.example"
    assert comment["open"] is True and comment["stale"] is False


def test_editing_the_section_flags_the_comment_and_leaves_it_open(client: TestClient) -> None:
    """The property the whole design exists for.

    Closing it would record that somebody answered the objection. Nobody did: the text
    moved, and the reviewer has to look again.
    """
    analysis_id = _built(client)
    _comment(client, analysis_id, "summary", "This overstates the headroom.")
    client.patch(
        f"/v1/analyses/{analysis_id}/memo",
        headers=ANALYST,
        json={"sections": {"summary": "A rewritten summary that says something else."}},
    )
    listing = client.get(f"/v1/analyses/{analysis_id}/comments", headers=ANALYST).json()
    assert listing["open_count"] == 1
    assert listing["stale_count"] == 1
    assert listing["comments"][0]["open"] is True


def test_editing_a_different_section_does_not_flag_the_comment(client: TestClient) -> None:
    """Otherwise every edit flags every comment until reviewers stop reading the flag."""
    analysis_id = _built(client)
    _comment(client, analysis_id, "summary", "This overstates the headroom.")
    client.patch(
        f"/v1/analyses/{analysis_id}/memo",
        headers=ANALYST,
        json={"sections": {"recommendation_rationale": "A different section, rewritten."}},
    )
    listing = client.get(f"/v1/analyses/{analysis_id}/comments", headers=ANALYST).json()
    assert listing["stale_count"] == 0


def test_a_comment_on_a_section_the_memo_does_not_have_is_refused(client: TestClient) -> None:
    """An unanswerable comment makes a thread that can never be cleared."""
    analysis_id = _built(client)
    response = client.post(
        f"/v1/analyses/{analysis_id}/comments",
        headers=ANALYST,
        json={"section": "not_a_section", "body": "?"},
    )
    assert response.status_code == 422
    assert "could never be answered" in response.text


def test_there_is_nothing_to_comment_on_before_a_memo_exists(client: TestClient) -> None:
    response = client.post(
        "/v1/analyses",
        headers=ANALYST,
        files=[("files", ("spread.csv", SPREAD_CSV, "text/csv"))],
        data={"borrower_id": "acme-manufacturing", "doc_types": "financial_statement"},
    )
    analysis_id = response.json()["analysis_id"]
    refused = client.post(
        f"/v1/analyses/{analysis_id}/comments",
        headers=ANALYST,
        json={"section": "summary", "body": "early"},
    )
    assert refused.status_code == 422
    assert "build one before reviewing it" in refused.text


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def test_resolving_names_the_person_and_what_they_did(client: TestClient) -> None:
    analysis_id = _built(client)
    comment = _comment(client, analysis_id, "summary", "This overstates the headroom.")
    response = client.post(
        f"/v1/analyses/{analysis_id}/comments/{comment['id']}/resolve",
        headers=ANALYST,
        json={"resolution": "Rewrote the paragraph against the computed ratio."},
    )
    assert response.status_code == 200, response.text
    resolved = response.json()
    assert resolved["open"] is False
    assert resolved["resolved_by"] == "demo.analyst@bank.example"
    assert resolved["resolved_at"]
    assert "computed ratio" in resolved["resolution"]


def test_a_resolved_comment_cannot_be_resolved_again(client: TestClient) -> None:
    """A second write destroys the record of who answered the objection."""
    analysis_id = _built(client)
    comment = _comment(client, analysis_id, "summary", "Objection.")
    client.post(
        f"/v1/analyses/{analysis_id}/comments/{comment['id']}/resolve",
        headers=ANALYST,
        json={},
    )
    again = client.post(
        f"/v1/analyses/{analysis_id}/comments/{comment['id']}/resolve",
        headers=ANALYST,
        json={},
    )
    assert again.status_code == 422
    assert "already resolved" in again.text


def test_resolving_an_unknown_comment_says_so(client: TestClient) -> None:
    analysis_id = _built(client)
    response = client.post(
        f"/v1/analyses/{analysis_id}/comments/c99/resolve", headers=ANALYST, json={}
    )
    assert response.status_code == 422
    assert "no comment" in response.text


def test_a_resolved_comment_is_never_reported_stale(client: TestClient) -> None:
    """Staleness is a prompt to re-read an OPEN objection. A closed one is finished."""
    analysis_id = _built(client)
    comment = _comment(client, analysis_id, "summary", "Objection.")
    client.post(
        f"/v1/analyses/{analysis_id}/comments/{comment['id']}/resolve", headers=ANALYST, json={}
    )
    client.patch(
        f"/v1/analyses/{analysis_id}/memo",
        headers=ANALYST,
        json={"sections": {"summary": "Rewritten after the objection was answered."}},
    )
    listing = client.get(f"/v1/analyses/{analysis_id}/comments", headers=ANALYST).json()
    assert listing["stale_count"] == 0 and listing["open_count"] == 0


# --------------------------------------------------------------------------- #
# The anchor survives a chain that no longer holds the revision
# --------------------------------------------------------------------------- #
def test_a_comment_whose_revision_is_gone_is_stale_rather_than_current() -> None:
    """A reader who cannot see what was commented on must not be told it still applies."""
    service = RevisionService()
    first = service.first({"summary": "original"}, actor="a@b.example")
    orphan = MemoComment(
        id="c1",
        section="summary",
        body="objection",
        author="checker@bank.example",
        revision=99,
        anchor_digest="a digest from a chain this memo does not have",
    )
    assert CommentService.stale(orphan, (first,)) is True
