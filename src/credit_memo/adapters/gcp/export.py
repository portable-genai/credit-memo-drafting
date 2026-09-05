"""GCP export adapter (ExportPort) — the local renderer plus a PDF.

Everything the local adapter produces, with PDF added via ``reportlab``. The DOCX and
HTML paths delegate rather than duplicate: one place decides what a committee pack says
(``domain/memo_document.py``) and one place writes WordprocessingML, so the two formats
cannot drift.

PDF is here rather than in the local adapter because it needs a library, and the local
profile is SDK-free by contract. ``reportlab`` is an optional dependency under the
``[export]`` extra with a lazy import, so a deployment that never exports a PDF does not
install it and a profile that cannot is honest about which formats it produces.

Not Google Docs. The Drive export path leaves the deploy region and caps at 10 MB, and
rendering in-process keeps the pack in-region by construction — which for a document
containing a borrower's financial position is the whole question.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.memo_document import build_document
from ...domain.models import CreditMemo
from ..local.export import LocalExportAdapter


class GcpExportAdapter:
    """DOCX and HTML from the shared renderer; PDF from reportlab, in region."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._local = LocalExportAdapter(settings)

    def formats(self) -> tuple[str, ...]:
        return ("docx", "html", "pdf")

    def export(self, memo: CreditMemo, fmt: str = "docx") -> tuple[bytes, str]:
        if fmt == "pdf":
            return self._pdf(memo), "application/pdf"
        return self._local.export(memo, fmt)

    def _pdf(self, memo: CreditMemo) -> bytes:
        import io

        from reportlab.lib import colors  # lazy: only on the PDF path
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        document = build_document(memo)
        styles = getSampleStyleSheet()
        note_style = ParagraphStyle(
            "MemoNote",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            textColor=colors.HexColor("#4a524d"),
        )
        cell_style = ParagraphStyle("Cell", parent=styles["BodyText"], fontSize=8, leading=10)

        story: list[Any] = [
            Paragraph(document.title, styles["Title"]),
            Paragraph(document.subtitle, note_style),
            Spacer(1, 6),
        ]
        for block in document.blocks:
            if block.kind == "heading":
                story.append(
                    Paragraph(block.text, styles["Heading2" if block.level > 1 else "Heading1"])
                )
            elif block.kind == "note":
                story.append(Paragraph(block.text, note_style))
            elif block.kind == "table":
                # Every cell is a Paragraph so long text wraps instead of running off the
                # page. A table that overflows the margin is a table a committee cannot read.
                data = [
                    [Paragraph(str(c), cell_style) for c in row]
                    for row in ((block.headers,) if block.headers else ()) + block.rows
                ]
                if not data:
                    continue
                table = Table(data, hAlign="LEFT", repeatRows=1 if block.headers else 0)
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0ee")),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ]
                    )
                )
                story.extend([table, Spacer(1, 6)])
            elif block.kind == "bullets":
                if block.text:
                    story.append(Paragraph(block.text, styles["BodyText"]))
                story.append(
                    ListFlowable(
                        [ListItem(Paragraph(item, styles["BodyText"])) for item in block.items],
                        bulletType="bullet",
                        start="•",
                    )
                )
                story.append(Spacer(1, 4))
            else:
                story.append(Paragraph(block.text, styles["BodyText"]))

        buffer = io.BytesIO()
        SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=document.title,
        ).build(story)
        return buffer.getvalue()
