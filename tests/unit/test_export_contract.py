"""What a committee pack must carry out of the application, and what it must not.

An export is the memo's only output that reaches people who cannot log in: a committee
reading a document, an examiner asking for one years later. It is also exactly where the
properties that make the memo checkable get quietly dropped, because a renderer's author
is thinking about layout rather than about provenance.

So the contract is tested rather than trusted:

* the standing "decision support, not a credit decision" sentence survives, and comes first
* the input manifest survives, so a reader can see what the memo was assessed on
* every figure keeps its provenance label, spelled out in words for a reader on paper
* an unmeasured figure still says it is unmeasured, rather than rendering as blank
* **no web-grounded content appears at all** — grounded results may be shown only to the
  person who ran the query, and an export is by definition read by other people

The DOCX is opened as a real ZIP and its XML read back, rather than asserting on the
builder's own output. An exporter that produced an unopenable file would otherwise pass.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from credit_memo.adapters.local.export import LocalExportAdapter
from credit_memo.config import Settings
from credit_memo.domain.memo_document import build_document
from credit_memo.domain.models import (
    AnalysisManifest,
    Borrower,
    Citation,
    Covenant,
    CovenantOperator,
    CovenantStatus,
    CovenantType,
    CreditMemo,
    CreditRequest,
    DocType,
    Facility,
    LoanType,
    MemoKind,
    PolicyException,
    PolicyOperator,
    Provenance,
    RatingDriver,
    Ratio,
    RiskRatingProposal,
    Severity,
    SourceType,
    StoredDocument,
)


@pytest.fixture
def memo() -> CreditMemo:
    return CreditMemo(
        borrower=Borrower(id="acme", name="Acme Manufacturing (FICTIONAL)", sector="manufacturing"),
        summary="Revenue of 620.0 and EBITDA of 100.0 support the requested facility.",
        recommendation_rationale="Support subject to the conditions below.",
        request=CreditRequest(
            kind=MemoKind.NEW_FACILITY,
            loan_type=LoanType.CI_TERM,
            facilities=(Facility(id="f1", amount=40.0, currency="USD", tenor_months=60),),
            purpose="Refinance and expand",
        ),
        ratios=(
            Ratio(
                formula_id="leverage.v1",
                name="Leverage",
                period="FY2025",
                value=2.5,
                definition="total debt / EBITDA",
            ),
            Ratio(
                formula_id="dscr.v1",
                name="Debt-service coverage",
                period="FY2025",
                value=None,
                definition="(EBITDA - capex - tax) / scheduled debt service",
                reason_missing="capex not supplied for FY2025",
            ),
        ),
        covenants=(
            Covenant(
                type=CovenantType.LEVERAGE,
                description="Net leverage <= 3.0x",
                threshold=3.0,
                operator=CovenantOperator.LE,
                current_value=2.5,
                status=CovenantStatus.COMPLIANT,
                value_provenance=Provenance.COMPUTED,
            ),
        ),
        policy_exceptions=(
            PolicyException(
                rule_id="TEN-01",
                description="Maximum tenor",
                measured=120.0,
                limit=84.0,
                operator=PolicyOperator.LE,
                severity=Severity.HIGH,
                waiver_authority="Board Credit Committee",
                detail="Maximum tenor: policy requires <= 84.00, this request measures 120.00.",
            ),
        ),
        rating=RiskRatingProposal(
            obligor_grade="3 - Satisfactory",
            score=2.8,
            scorecard_version="example-scorecard-2026.09",
            drivers=(
                RatingDriver(
                    name="Leverage", measured=2.5, band="2.50 to 3.50", points=3.0, weight=2.0
                ),
            ),
        ),
        citations=(
            Citation(
                source_id="doc-fs",
                source_type=SourceType.FILING,
                title="Audited statements",
                page=4,
            ),
        ),
        confidence=0.86,
        caveats=("The debt schedule was not supplied.",),
        questions_for_client=("Provide the FY2025 debt schedule.",),
        manifest=AnalysisManifest(
            analysis_id="an-1",
            borrower_id="acme",
            documents=(
                StoredDocument(
                    id="doc-fs",
                    filename="fs-2025.pdf",
                    doc_type=DocType.FINANCIAL_STATEMENT,
                    pages=12,
                    declared_as_of="2025-12-31",
                ),
            ),
        ),
    )


def _docx_text(payload: bytes) -> str:
    """The document's visible text, read back out of a real ZIP."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    import re

    return " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))


@pytest.fixture
def adapter() -> LocalExportAdapter:
    return LocalExportAdapter(Settings(profile="local"))


# --------------------------------------------------------------------------- #
# It is a real document
# --------------------------------------------------------------------------- #
def test_the_docx_is_a_zip_word_can_open(adapter, memo) -> None:
    payload, content_type = adapter.export(memo, "docx")
    assert content_type.endswith("wordprocessingml.document")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
    # The four parts Word requires; without any one of them the file will not open.
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"} <= names


def test_the_same_memo_exports_to_the_same_bytes(adapter, memo) -> None:
    """An export whose digest changes on every run cannot be checked against what was sent."""
    assert adapter.export(memo, "docx")[0] == adapter.export(memo, "docx")[0]


def test_a_format_this_deployment_cannot_produce_is_refused_not_substituted(adapter, memo) -> None:
    """A caller who asked for a PDF and received HTML finds out at the worst moment."""
    assert "pdf" not in adapter.formats()
    with pytest.raises(ValueError, match="cannot export"):
        adapter.export(memo, "pdf")


# --------------------------------------------------------------------------- #
# What must survive the export
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_the_standing_sentence_survives_and_comes_first(adapter, memo, fmt: str) -> None:
    """A reader who stops after one line should still have read it."""
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "Decision support, not a credit decision" in text
    body = text[text.index("Acme Manufacturing") :]
    assert body.index("Decision support") < body.index("Summary")


@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_the_manifest_survives(adapter, memo, fmt: str) -> None:
    """A reader who cannot see the inputs is being asked to trust the output."""
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "fs-2025.pdf" in text
    assert "2025-12-31" in text  # the declared as-of, not an inferred one


@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_every_figure_keeps_its_provenance_in_words(adapter, memo, fmt: str) -> None:
    """A reader holding paper cannot hover over a glyph."""
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "computed by the bank's engine" in text
    assert "How to read a figure" in text


@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_an_uncomputable_ratio_says_so_rather_than_rendering_blank(adapter, memo, fmt: str) -> None:
    """A blank cell reads as zero, or as an oversight. Neither is what happened."""
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "not computable" in text
    assert "capex not supplied for FY2025" in text


@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_the_policy_exception_carries_its_waiver_authority(adapter, memo, fmt: str) -> None:
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "Board Credit Committee" in text


@pytest.mark.parametrize("fmt", ["docx", "html"])
def test_the_rating_is_labelled_as_proposed(adapter, memo, fmt: str) -> None:
    """The pack must not read as though the bank has graded this borrower."""
    payload, _ = adapter.export(memo, fmt)
    text = _docx_text(payload) if fmt == "docx" else payload.decode("utf-8")
    assert "not an assigned grade" in text
    assert "example-scorecard-2026.09" in text  # which scorecard, printed at the point of use


# --------------------------------------------------------------------------- #
# What must never appear
# --------------------------------------------------------------------------- #
def test_no_web_grounded_content_can_reach_an_export(memo) -> None:
    """Grounded results may be shown only to the person who ran the query.

    An export is by definition read by other people, so there is no branch in the document
    builder that could include one. This asserts on the built document rather than on a
    rendered string: a future block type carrying web content would fail here before any
    renderer had a chance to hide it.
    """
    document = build_document(memo)
    rendered = " ".join(
        block.text + " ".join(block.items) + " ".join(" ".join(r) for r in block.rows)
        for block in document.blocks
    ).lower()
    for forbidden in ("web_grounded", "web-grounded", "search result", "retrieved from the web"):
        assert forbidden not in rendered

    # And no provenance label in the legend offers one.
    legend = next(
        b
        for b in document.blocks
        if "read a figure" in b.text.lower() or b.items and "computed" in b.items[0].lower()
    )
    assert not any("web" in item.lower() for item in legend.items)
