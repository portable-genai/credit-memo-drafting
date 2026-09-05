"""The stateless intake path: upload per analysis, nothing standing, nothing hidden.

This service keeps no document library. Evidence is brought to each analysis, used, and
deleted on a schedule the console prints. These tests hold the four promises that posture
makes to a user:

1. **What you upload is what is used.** The manifest is complete by construction, and the
   memo carries it, so "what was this assessed on" has an answer on the page.
2. **The bytes actually reach extraction.** Before Wave 1 the pipeline passed ``b""`` to
   the extraction port, so no citation could open a page and no figure could be read off
   one. That regression is the easiest to reintroduce and the hardest to notice.
3. **A citation opens the page it names.** Page-true chunking, end to end.
4. **It expires, and it is not readable by anyone else.** Fail-closed subset ACL, one
   error for absent / expired / forbidden so ids cannot be probed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from credit_memo.adapters.local.analysis_bundle import LocalAnalysisBundleAdapter
from credit_memo.config import AnalysisBundleSettings, Settings
from credit_memo.domain.errors import AnalysisExpiredError, AnalysisNotFoundError
from credit_memo.domain.models import DocType

TENANT = ("borrower:acme", "tenant:demo-bank")


@pytest.fixture
def bundle(tmp_path) -> LocalAnalysisBundleAdapter:
    return LocalAnalysisBundleAdapter(
        Settings(
            profile="local",
            analysis_bundle=AnalysisBundleSettings(root=str(tmp_path), retention_days=15),
        )
    )


def _open(bundle: LocalAnalysisBundleAdapter, analysis_id: str = "an-1"):
    return bundle.create(analysis_id, "acme", TENANT, created_by="analyst@bank.example")


# --------------------------------------------------------------------------- #
# 1. The manifest is the answer to "what was this assessed on"
# --------------------------------------------------------------------------- #
def test_the_manifest_names_every_file_and_nothing_else(bundle) -> None:
    _open(bundle)
    bundle.put_document(
        "an-1",
        b"audited statements",
        "fs-2025.pdf",
        DocType.FINANCIAL_STATEMENT,
        TENANT,
        mime_type="application/pdf",
        declared_as_of="2025-12-31",
    )
    bundle.put_document(
        "an-1",
        b"debt schedule rows",
        "debt.csv",
        DocType.DEBT_SCHEDULE,
        TENANT,
        mime_type="text/csv",
    )
    manifest = bundle.manifest("an-1", TENANT)

    assert manifest.document_count == 2
    assert {d.filename for d in manifest.documents} == {"fs-2025.pdf", "debt.csv"}
    # The freshness claim is the uploader's, never inferred.
    statements = next(d for d in manifest.documents if d.doc_type is DocType.FINANCIAL_STATEMENT)
    assert statements.declared_as_of == "2025-12-31"
    assert statements.sha256


def test_the_manifest_keeps_the_name_the_analyst_wrote(bundle) -> None:
    """Display only, and it earns its place.

    Without it the memo names the borrower by its slug in its own group table — a small
    thing that makes the whole document read as generated. The ID still governs the ACL
    and every entitlement check, so a display name can never point a build at a different
    borrower.
    """
    manifest = bundle.create(
        "an-name",
        "acme",
        TENANT,
        created_by="analyst@bank.example",
        borrower_name="Acme Manufacturing Pte Ltd (FICTIONAL)",
    )
    assert manifest.borrower_name == "Acme Manufacturing Pte Ltd (FICTIONAL)"
    assert bundle.manifest("an-name", TENANT).borrower_name == manifest.borrower_name
    # Absent is the honest default for an analysis opened without one.
    assert bundle.create("an-plain", "acme", TENANT).borrower_name == ""


def test_the_same_file_twice_is_one_document(bundle) -> None:
    """Re-uploading the pack after adding one statement must not duplicate the rest."""
    _open(bundle)
    first = bundle.put_document("an-1", b"same bytes", "fs.pdf", DocType.FILING, TENANT)
    again = bundle.put_document("an-1", b"same bytes", "fs-copy.pdf", DocType.FILING, TENANT)
    assert first.id == again.id
    assert bundle.manifest("an-1", TENANT).document_count == 1


def test_missing_names_the_kinds_this_analysis_was_not_given(bundle) -> None:
    _open(bundle)
    bundle.put_document("an-1", b"fs", "fs.pdf", DocType.FINANCIAL_STATEMENT, TENANT)
    manifest = bundle.manifest("an-1", TENANT)
    assert manifest.missing(
        (DocType.FINANCIAL_STATEMENT, DocType.DEBT_SCHEDULE, DocType.BANK_STATEMENT)
    ) == (DocType.DEBT_SCHEDULE, DocType.BANK_STATEMENT)


# --------------------------------------------------------------------------- #
# 2 and 3. The bytes reach extraction, and a citation opens the page it names
# --------------------------------------------------------------------------- #
def test_uploaded_bytes_reach_the_extraction_port(
    credit_memo_service, analysis_bundle, extraction
) -> None:
    """The regression guard. ``extract`` was called with b"" at every site before Wave 1."""
    from credit_memo.domain.models import Borrower, MemoInput

    analysis_bundle.create("an-bytes", "acme", ("borrower:acme",), created_by="analyst")
    analysis_bundle.put_document(
        "an-bytes",
        b"Revenue was USD 120m and EBITDA USD 24m in FY2025.",
        "fs.txt",
        DocType.FINANCIAL_STATEMENT,
        ("borrower:acme",),
        mime_type="text/plain",
    )

    seen: list[bytes] = []
    original = extraction.extract

    def _record(document, content, mime_type):  # type: ignore[no-untyped-def]
        seen.append(content)
        return original(document, content, mime_type)

    extraction.extract = _record  # type: ignore[method-assign]

    credit_memo_service.build(
        MemoInput(borrower=Borrower(id="acme", name="Acme"), analysis_id="an-bytes"),
        actor="analyst",
        principals=("borrower:acme",),
    )

    assert seen, "the pipeline never called the extraction port"
    assert any(b"EBITDA" in content for content in seen), (
        "extraction was handed no bytes: every citation page and every extracted figure "
        f"depends on this. Got: {seen!r}"
    )


def test_the_memo_carries_the_manifest_of_what_it_used(
    credit_memo_service, analysis_bundle
) -> None:
    """ "What was this assessed on" must have an answer on the memo, not in a log."""
    from credit_memo.domain.models import Borrower, MemoInput

    analysis_bundle.create("an-manifest", "acme", ("borrower:acme",), created_by="analyst")
    analysis_bundle.put_document(
        "an-manifest",
        b"Audited FY2025 statements.",
        "fs-2025.pdf",
        DocType.FINANCIAL_STATEMENT,
        ("borrower:acme",),
        declared_as_of="2025-12-31",
    )
    memo = credit_memo_service.build(
        MemoInput(borrower=Borrower(id="acme", name="Acme"), analysis_id="an-manifest"),
        actor="analyst",
        principals=("borrower:acme",),
    )
    assert memo.manifest is not None
    assert [d.filename for d in memo.manifest.documents] == ["fs-2025.pdf"]
    assert memo.manifest.expires_at is not None


def _two_page_pdf(first: str, second: str) -> bytes:
    """A minimal, real two-page PDF. Written by hand rather than mocked.

    The whole claim under test is that page boundaries survive from the file to the
    citation, so the test has to start from an actual file with actual pages in it.
    """

    def content_stream(text: str) -> bytes:
        body = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
        return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body)

    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents %d 0 R "
        b"/Resources << /Font << /F1 7 0 R >> >> >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        page % 4,
        content_stream(first),
        page % 6,
        content_stream(second),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_the_extractor_keeps_the_page_boundaries(extraction) -> None:
    """It always knew where the pages ended; it used to join them and throw that away."""
    from credit_memo.domain.models import Filing

    extract = extraction.extract(
        Filing(id="doc-multi"),
        _two_page_pdf("Revenue for the year", "Debt schedule and covenants"),
        "application/pdf",
    )
    assert extract.pages == 2
    assert [t.strip() for t in extract.pages_text] == [
        "Revenue for the year",
        "Debt schedule and covenants",
    ]


def test_a_multi_page_document_cites_the_page_it_came_from() -> None:
    """One passage per page, so a citation that says p.2 opens page 2.

    Uses the real FTS adapter rather than the recording fixture: the fixture records
    ingests without indexing them, which is right for asserting on call arguments and
    useless for asserting on what comes back out.
    """
    from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
    from credit_memo.config import LocalSettings
    from credit_memo.domain.models import Filing, RetrievalQuery

    knowledge_base = LocalFtsKnowledgeBaseAdapter(
        Settings(profile="local", local=LocalSettings(db_path=":memory:"))
    )
    knowledge_base.ingest(
        Filing(id="doc-multi", title="Statements", acl_tags=("borrower:acme",)),
        _two_page_pdf("Revenue for the year was strong", "Debt schedule and covenants"),
        ("borrower:acme",),
    )
    hits = knowledge_base.search(
        RetrievalQuery(text="debt schedule covenants", acl_principals=("borrower:acme",))
    )
    ours = [h for h in hits if h.citation.source_id == "doc-multi"]
    assert ours, "the ingested document was not retrievable"
    assert ours[0].citation.page == 2, (
        "the passage about the debt schedule is on page 2 and must cite page 2; "
        f"got p.{ours[0].citation.page}. The extractor's page boundaries were discarded."
    )


# --------------------------------------------------------------------------- #
# 4. It expires, and nobody else can read it
# --------------------------------------------------------------------------- #
def test_the_manifest_states_when_the_evidence_disappears(bundle) -> None:
    manifest = _open(bundle)
    assert manifest.expires_at is not None
    horizon = (datetime.now(UTC) + timedelta(days=15)) - manifest.expires_at
    assert abs(horizon.total_seconds()) < 120


def test_an_expired_analysis_is_refused_even_before_the_sweep_runs(bundle, tmp_path) -> None:
    """A laptop that never sweeps must still honour the window the console promised."""
    import json

    _open(bundle)
    path = tmp_path / "an-1" / "manifest.json"
    raw = json.loads(path.read_text())
    raw["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    path.write_text(json.dumps(raw))

    with pytest.raises(AnalysisExpiredError, match="retention window"):
        bundle.manifest("an-1", TENANT)


def test_the_sweep_reclaims_expired_bundles(bundle, tmp_path) -> None:
    import json

    _open(bundle, "an-old")
    _open(bundle, "an-current")
    path = tmp_path / "an-old" / "manifest.json"
    raw = json.loads(path.read_text())
    raw["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    path.write_text(json.dumps(raw))

    assert bundle.sweep() == 1
    assert not (tmp_path / "an-old").exists()
    assert bundle.manifest("an-current", TENANT).analysis_id == "an-current"


@pytest.mark.parametrize(
    "principals",
    [
        pytest.param((), id="no principals at all"),
        pytest.param(("borrower:acme",), id="right borrower, wrong tenant"),
        pytest.param(("tenant:demo-bank",), id="right tenant, wrong borrower"),
        pytest.param(("borrower:other", "tenant:other-bank"), id="another bank entirely"),
    ],
)
def test_a_caller_holding_less_than_every_tag_sees_nothing(bundle, principals) -> None:
    """Subset match, fail-closed. Holding some of the tags is holding none of them."""
    _open(bundle)
    with pytest.raises(AnalysisNotFoundError):
        bundle.manifest("an-1", principals)


def test_absent_and_forbidden_are_the_same_answer(bundle) -> None:
    """Otherwise the error message is an oracle for which analysis ids exist."""
    _open(bundle)
    forbidden = pytest.raises(AnalysisNotFoundError)
    with forbidden as denied:
        bundle.manifest("an-1", ("borrower:other",))
    with pytest.raises(AnalysisNotFoundError) as absent:
        bundle.manifest("an-does-not-exist", TENANT)
    assert str(denied.value).replace("an-1", "X") == str(absent.value).replace(
        "an-does-not-exist", "X"
    )


@pytest.mark.parametrize("hostile", ["../escape", "..", "a/b", "a\\b", "  ", ""])
def test_a_traversing_id_is_not_found_rather_than_sanitised(bundle, hostile) -> None:
    """A caller who sends ``..`` is not making a typo; rewriting it would serve them
    a different analysis than the one they asked for."""
    with pytest.raises(AnalysisNotFoundError):
        bundle.manifest(hostile, TENANT)


def test_delete_removes_the_evidence_now(bundle) -> None:
    _open(bundle)
    bundle.put_document("an-1", b"statements", "fs.pdf", DocType.FINANCIAL_STATEMENT, TENANT)
    assert bundle.delete("an-1", TENANT) is True
    with pytest.raises(AnalysisNotFoundError):
        bundle.manifest("an-1", TENANT)
    assert bundle.delete("an-1", TENANT) is False


# --------------------------------------------------------------------------- #
# Artifacts ride with the evidence and die with it
# --------------------------------------------------------------------------- #
def test_the_memo_lives_and_dies_with_the_evidence_it_was_built_from(bundle) -> None:
    _open(bundle)
    bundle.put_artifact("an-1", "memo", {"summary": "drafted"}, TENANT)
    assert bundle.get_artifact("an-1", "memo", TENANT) == {"summary": "drafted"}
    assert bundle.get_artifact("an-1", "never-written", TENANT) is None
    bundle.delete("an-1", TENANT)
    with pytest.raises(AnalysisNotFoundError):
        bundle.get_artifact("an-1", "memo", TENANT)
