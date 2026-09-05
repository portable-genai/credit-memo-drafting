"""Local document-extraction adapter (DocumentExtractionPort) — Document AI stand-in.

SDK-free, deterministic plain-text extraction. If ``pypdf`` is importable and the bytes
look like a PDF, the per-page text is joined; otherwise the bytes are decoded as UTF-8
text. When no content is supplied (the CLI / memo pipeline ingests filings by reference),
a deterministic placeholder body keyed off the filing is returned so the local knowledge
base still indexes something searchable. There is no Google emulator for Document AI, so
this path is unconditional and imports no google-cloud package.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DocumentExtract, Filing


class LocalDocumentExtractionAdapter:
    """Parse a filing into structured fields + plain text, no SDK required."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, document: Filing, content: bytes, mime_type: str) -> DocumentExtract:
        pages_text = self._pages_from(content, mime_type)
        text = "\n\n".join(pages_text)
        pages = len(pages_text)
        if not text:
            # No bytes supplied (ingest-by-reference): synthesise a deterministic body so
            # the local KB has something to index and the memo run stays grounded.
            text = (
                f"{document.title or document.id} ({document.doc_type.value}). "
                "Synthetic local extract: borrower financials, covenants and credit-policy "
                "context for offline grounding."
            )
            pages = 1
            pages_text = (text,)
        return DocumentExtract(
            document_id=document.id,
            fields={"doc_type": document.doc_type.value, "title": document.title},
            text=text,
            pages=pages,
            pages_text=tuple(pages_text),
        )

    @staticmethod
    def _pages_from(content: bytes, mime_type: str) -> tuple[str, ...]:
        """One entry per page, in order.

        Returning the pages rather than a joined blob is what lets a citation say p.7 and
        mean it. The join still happens for ``text``, which callers that only want the
        whole document keep using unchanged.
        """
        if not content:
            return ()
        if LocalDocumentExtractionAdapter._looks_like_pdf(content, mime_type):
            pdf_pages = LocalDocumentExtractionAdapter._extract_pdf_pages(content)
            if pdf_pages:
                return tuple(pdf_pages)
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        return (text,) if text else ()

    @staticmethod
    def _looks_like_pdf(content: bytes, mime_type: str) -> bool:
        if "pdf" in (mime_type or "").lower():
            return True
        return isinstance(content, bytes) and content[:5] == b"%PDF-"

    @staticmethod
    def _extract_pdf_pages(content: bytes) -> list[str]:
        """Extract per-page text via pypdf when available; empty list if it is not."""
        try:
            import io

            from pypdf import PdfReader  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 - pypdf is optional; fall back to text decode
            return []
        try:
            reader = PdfReader(io.BytesIO(content))
            return [(page.extract_text() or "") for page in reader.pages]
        except Exception:  # noqa: BLE001 - a malformed PDF falls back to text decode
            return []
