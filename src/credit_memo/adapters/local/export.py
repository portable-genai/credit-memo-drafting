"""Local export adapter (ExportPort) — DOCX and HTML from the standard library alone.

A committee pack is the memo's only output that leaves the application, so it must work
on every profile including the SDK-free one. That rules out python-docx here, and it
turns out not to matter: a .docx is a ZIP of XML, and the subset a credit memo needs
(headings, paragraphs, tables, bullets) is a few hundred lines of WordprocessingML that
Word, Pages and LibreOffice all open.

The alternative was shipping HTML and calling it an export. A committee that asked for a
document and received a web page has to convert it themselves, and the conversion is
where the formatting and the provenance labels get lost.

What every export carries, and why an exporter is exactly where these get dropped:

* the manifest, so a reader can see which files the memo was assessed on and when that
  evidence expires;
* the provenance label on every figure, spelled out in words rather than glyphs because
  a reader holding paper cannot hover;
* the standing "decision support, not a credit decision" sentence, first.

What no export carries: web-grounded content. Grounded results may be shown only to the
person who ran the query, and an export is by definition read by other people. There is
no branch here that could include one.

Standard library only.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from ...config import Settings
from ...domain.memo_document import Block, MemoDocument, build_document
from ...domain.models import CreditMemo

# The OOXML namespace and content-type URIs are fixed by the standard and cannot be
# shortened or wrapped inside an XML attribute, so this block is exempt from the line
# limit rather than mangled to satisfy it.
# ruff: noqa: E501
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

#: Minimal styles. Heading1/2 and a table grid are all the document uses; anything more
#: would be this file having opinions about a bank's house format, which it should not.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>
<w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Note"><w:name w:val="Note"/>
<w:rPr><w:i/><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:color="999999"/><w:left w:val="single" w:sz="4" w:color="999999"/>
<w:bottom w:val="single" w:sz="4" w:color="999999"/><w:right w:val="single" w:sz="4" w:color="999999"/>
<w:insideH w:val="single" w:sz="4" w:color="999999"/><w:insideV w:val="single" w:sz="4" w:color="999999"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>"""


def _para(text: str, style: str = "") -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{style_xml}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _cell(text: str, bold: bool = False) -> str:
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return (
        '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
        f'<w:p><w:r>{run_props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p></w:tc>'
    )


def _table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    out = [
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
    ]
    if headers:
        out.append("<w:tr>" + "".join(_cell(h, bold=True) for h in headers) + "</w:tr>")
    for row in rows:
        out.append("<w:tr>" + "".join(_cell(c) for c in row) + "</w:tr>")
    out.append("</w:tbl>")
    # Word renders consecutive tables as one without a paragraph between them.
    out.append("<w:p/>")
    return "".join(out)


def _blocks_to_xml(document: MemoDocument) -> str:
    parts = [_para(document.title, "Title")]
    if document.subtitle:
        parts.append(_para(document.subtitle, "Note"))
    for block in document.blocks:
        parts.append(_block_to_xml(block))
    return "".join(parts)


def _block_to_xml(block: Block) -> str:
    if block.kind == "heading":
        return _para(block.text, f"Heading{min(max(block.level, 1), 2)}")
    if block.kind == "note":
        return _para(block.text, "Note")
    if block.kind == "table":
        return _table(block.headers, block.rows)
    if block.kind == "bullets":
        lead = _para(block.text) if block.text else ""
        return lead + "".join(_para(f"•  {item}") for item in block.items)
    return _para(block.text)


class LocalExportAdapter:
    """Render a memo to DOCX or HTML using nothing but the standard library."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def formats(self) -> tuple[str, ...]:
        # No PDF. Producing one without a rendering library means hand-writing a PDF
        # generator, and a bad PDF is worse than an honest "this deployment does not make
        # PDFs": the gcp profile's adapter does, and this says so rather than pretending.
        return ("docx", "html")

    def export(self, memo: CreditMemo, fmt: str = "docx") -> tuple[bytes, str]:
        document = build_document(memo)
        if fmt == "docx":
            return self._docx(document), (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        if fmt == "html":
            return self._html(document), "text/html; charset=utf-8"
        raise ValueError(
            f"this deployment cannot export {fmt!r}; it produces {', '.join(self.formats())}. "
            "A caller who asked for one format and received another finds out at the worst "
            "moment, so this refuses rather than substituting."
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _docx(document: MemoDocument) -> bytes:
        body = _blocks_to_xml(document)
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}"
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
            "</w:body></w:document>"
        )
        buffer = io.BytesIO()
        # Deterministic: a fixed timestamp on every entry, so the same memo exports to the
        # same bytes. An export whose digest changes on every run cannot be checked against
        # the one the committee received.
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in (
                ("[Content_Types].xml", _CONTENT_TYPES),
                ("_rels/.rels", _RELS),
                ("word/_rels/document.xml.rels", _DOC_RELS),
                ("word/styles.xml", _STYLES),
                ("word/document.xml", document_xml),
            ):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return buffer.getvalue()

    @staticmethod
    def _html(document: MemoDocument) -> bytes:
        parts = [
            '<!doctype html><meta charset="utf-8">',
            f"<title>{escape(document.title)}</title>",
            "<style>body{font:14px/1.5 system-ui,sans-serif;max-width:52rem;"
            "margin:2rem auto;"
            "padding:0 1rem;color:#171b19}h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:2rem}"
            "table{border-collapse:collapse;width:100%;font-size:.9rem;margin:.5rem 0}"
            "th,td{border:1px solid #ccc;padding:.35rem .5rem;text-align:left}"
            ".note{font-style:italic;color:#4a524d;border-left:3px solid #ccc;padding-left:.75rem}"
            "</style>",
            f"<h1>{escape(document.title)}</h1>",
            f'<p class="note">{escape(document.subtitle)}</p>',
        ]
        for block in document.blocks:
            if block.kind == "heading":
                parts.append(
                    f"<h{min(max(block.level, 1), 3)}>{escape(block.text)}</h{min(max(block.level, 1), 3)}>"
                )
            elif block.kind == "note":
                parts.append(f'<p class="note">{escape(block.text)}</p>')
            elif block.kind == "table":
                head = (
                    "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in block.headers) + "</tr>"
                    if block.headers
                    else ""
                )
                body = "".join(
                    "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>"
                    for row in block.rows
                )
                parts.append(f"<table>{head}{body}</table>")
            elif block.kind == "bullets":
                if block.text:
                    parts.append(f"<p>{escape(block.text)}</p>")
                parts.append(
                    "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in block.items) + "</ul>"
                )
            else:
                parts.append(f"<p>{escape(block.text)}</p>")
        return "".join(parts).encode("utf-8")
