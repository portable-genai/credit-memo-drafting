"""The memo as a document: one ordered structure, rendered by every exporter.

Separating "what the pack says" from "how a format writes it" is what stops the DOCX and
the PDF drifting apart. There is one place that decides a committee pack opens with the
ask, carries the manifest, prints the provenance legend and ends with the sources — and
it is here, in the domain, with no dependency on any rendering library.

Two rules this structure exists to keep, because an exporter is exactly where they get
quietly dropped:

* **Provenance survives the export.** Every figure keeps the label saying whether it was
  computed, read off a page, typed by a person or drafted by a model. A pack that loses
  those labels reads as though the bank stands behind all of it equally.
* **Web-grounded content is absent.** Grounded search results may be shown only to the
  person who ran the query, and an export is read by other people. There is no branch here
  that could include one, which is a stronger guarantee than a filter that might.

Pure standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .memo_templates import template_for
from .models import AnalysisManifest, CreditMemo, MemoKind, Provenance

#: How a provenance reads in a printed document, where a tooltip cannot help. The wording
#: is longer than the console's on purpose: a reader holding paper has no hover.
_PROVENANCE_LABEL: dict[str, str] = {
    Provenance.COMPUTED.value: "computed by the bank's engine",
    Provenance.USER_ENTERED.value: "entered by the analyst",
    Provenance.CONFIRMED.value: "read from a document and confirmed by the analyst",
    Provenance.EXTRACTED.value: "read from a document, not confirmed",
    Provenance.MODEL_DRAFTED.value: "drafted by the model",
    Provenance.VENDOR.value: "supplied by a data vendor",
}


@dataclass(frozen=True, slots=True)
class Block:
    """One renderable element. ``kind`` is what a format switches on."""

    kind: str  # "heading" | "paragraph" | "table" | "bullets" | "note"
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    headers: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    level: int = 1


@dataclass(frozen=True, slots=True)
class MemoDocument:
    """The whole pack, ordered, ready for any renderer."""

    title: str
    subtitle: str = ""
    blocks: tuple[Block, ...] = field(default_factory=tuple)


def _retention_note(manifest: AnalysisManifest) -> str:
    """When the evidence behind this pack disappears, said in the pack itself.

    A committee reading an exported memo has no console to tell them, and "the sources
    are gone" is something to learn before relying on the document rather than after.
    """
    if manifest.expires_at is None:
        return (
            f"Assessed on {manifest.document_count} document(s). No retention window is "
            "configured for this analysis."
        )
    return (
        f"This analysis and the {manifest.document_count} file(s) it used are available "
        f"until {manifest.expires_at.date().isoformat()}, then deleted. After that date "
        "the figures in this pack can no longer be traced to their sources."
    )


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "not available"
    if unit == "x":
        return f"{value:,.2f}x"
    return f"{value:,.2f}"


def build_document(memo: CreditMemo) -> MemoDocument:
    """Render ``memo`` into ordered blocks, in the section order its kind expects."""
    kind = memo.request.kind if memo.request else MemoKind.NEW_FACILITY
    template = template_for(kind)
    blocks: list[Block] = []

    # The standing sentence. First, not buried in a footer: a reader who stops after one
    # line should still have read it.
    blocks.append(
        Block(
            kind="note",
            text=(
                "Decision support, not a credit decision. This memo was assembled by an "
                "assistant and requires review by a qualified credit officer before any "
                "reliance is placed on it."
            ),
        )
    )

    if memo.request:
        facility = memo.request.facilities[0] if memo.request.facilities else None
        parts = [template.title, memo.request.loan_type.value.replace("_", " ")]
        if facility and facility.amount:
            parts.append(f"{facility.currency} {facility.amount:,.0f}")
        if facility and facility.tenor_months:
            parts.append(f"{facility.tenor_months} months")
        blocks.append(Block(kind="heading", text="The request", level=2))
        blocks.append(Block(kind="paragraph", text=" · ".join(parts)))
        if memo.request.purpose:
            blocks.append(Block(kind="paragraph", text=f"Purpose: {memo.request.purpose}"))
        if facility and facility.repayment_source:
            blocks.append(
                Block(kind="paragraph", text=f"Repayment source: {facility.repayment_source}")
            )

    # What this was assessed on, and until when. Near the front, because a reader deciding
    # how much weight to give the pack needs it before the conclusions rather than after.
    if memo.manifest:
        blocks.append(Block(kind="heading", text="What this was assessed on", level=2))
        blocks.append(
            Block(
                kind="table",
                headers=("Document", "Kind", "Pages", "As of"),
                rows=tuple(
                    (
                        d.filename,
                        d.doc_type.value.replace("_", " "),
                        str(d.pages or "-"),
                        d.declared_as_of or "not stated",
                    )
                    for d in memo.manifest.documents
                ),
            )
        )
        blocks.append(Block(kind="note", text=_retention_note(memo.manifest)))

    blocks.append(Block(kind="heading", text="Summary", level=2))
    blocks.append(Block(kind="paragraph", text=memo.summary or "No summary was produced."))

    if memo.caveats:
        blocks.append(
            Block(
                kind="bullets",
                text=f"Drafting confidence {memo.confidence * 100:.0f}%. The drafter noted:",
                items=memo.caveats,
            )
        )

    if memo.ratios:
        blocks.append(Block(kind="heading", text="Ratios", level=2))
        blocks.append(
            Block(
                kind="table",
                headers=("Ratio", "Period", "Value", "Definition", "Source"),
                rows=tuple(
                    (
                        r.name,
                        r.period,
                        _fmt(r.value, r.unit) if r.value is not None else "not computable",
                        r.definition,
                        _PROVENANCE_LABEL.get(r.provenance.value, r.provenance.value)
                        if r.value is not None
                        else r.reason_missing,
                    )
                    for r in memo.ratios
                ),
            )
        )

    if memo.covenants:
        blocks.append(Block(kind="heading", text="Covenants", level=2))
        blocks.append(
            Block(
                kind="table",
                headers=("Covenant", "Test", "Current", "Source of current", "Status"),
                rows=tuple(
                    (
                        c.type.value.replace("_", " "),
                        f"{c.operator.value} {c.threshold:,.2f}",
                        _fmt(c.current_value),
                        _PROVENANCE_LABEL.get(c.value_provenance.value, c.value_provenance.value),
                        c.status.value.replace("_", " "),
                    )
                    for c in memo.covenants
                ),
            )
        )

    if memo.policy_exceptions:
        blocks.append(Block(kind="heading", text="Policy exceptions", level=2))
        blocks.append(
            Block(
                kind="paragraph",
                text=f"Tested against policy pack {memo.policy_version or 'unversioned'}.",
            )
        )
        blocks.append(
            Block(
                kind="table",
                headers=("Rule", "Requirement", "Measured", "Severity", "Waiver authority"),
                rows=tuple(
                    (
                        f"{e.rule_id} {e.description}",
                        f"{e.operator.value} {_fmt(e.limit)}",
                        _fmt(e.measured),
                        e.severity.value,
                        e.waiver_authority or "not named in the pack",
                    )
                    for e in memo.policy_exceptions
                ),
            )
        )

    if memo.rating:
        blocks.append(Block(kind="heading", text="Risk rating", level=2))
        rating = memo.rating
        blocks.append(
            Block(
                kind="paragraph",
                text=(
                    f"Proposed grade {rating.grade} (score {rating.score:,.2f}, scorecard "
                    f"{rating.scorecard_version or 'unversioned'}). "
                    + (
                        f"Overridden from {rating.obligor_grade} by {rating.override_by}: "
                        f"{rating.override_reason}. "
                        if rating.override_grade
                        else ""
                    )
                    + "Proposed for a credit officer to accept or override; this is not an "
                    "assigned grade."
                ),
            )
        )
        blocks.append(
            Block(
                kind="table",
                headers=("Factor", "Measured", "Band", "Points", "Weight"),
                rows=tuple(
                    (
                        d.name,
                        _fmt(d.measured),
                        d.band,
                        f"{d.points:,.1f}",
                        f"{d.weight:,.1f}",
                    )
                    for d in rating.drivers
                ),
            )
        )

    if memo.risk_flags:
        blocks.append(Block(kind="heading", text="Risks and mitigants", level=2))
        for flag in memo.risk_flags:
            blocks.append(
                Block(
                    kind="paragraph",
                    text=(
                        f"{flag.category.value.replace('_', ' ')} "
                        f"({flag.severity.value}): {flag.detail}"
                    ),
                )
            )
            if flag.mitigants:
                blocks.append(
                    Block(
                        kind="bullets",
                        text="Mitigants:",
                        items=tuple(
                            m.detail
                            + (
                                f" (confirmed by {m.confirmed_by})"
                                if m.confirmed_by
                                else " (proposed, not confirmed)"
                            )
                            for m in flag.mitigants
                        ),
                    )
                )

    if memo.tie_out:
        blocks.append(Block(kind="heading", text="Reconciliation findings", level=2))
        blocks.append(
            Block(
                kind="bullets",
                text="These figures should agree and do not:",
                items=tuple(f"[{f.severity.value}] {f.detail}" for f in memo.tie_out),
            )
        )

    blocks.append(Block(kind="heading", text="Recommendation", level=2))
    blocks.append(
        Block(
            kind="paragraph",
            text=memo.recommendation_rationale or "No recommendation rationale was produced.",
        )
    )
    if memo.recommendation and memo.recommendation.conditions:
        blocks.append(
            Block(
                kind="table",
                headers=("Condition", "When", "Owner", "Due"),
                rows=tuple(
                    (c.detail, c.kind.value, c.owner or "-", c.due or "-")
                    for c in memo.recommendation.conditions
                ),
            )
        )
    if memo.recommendation and memo.recommendation.decline_reasons:
        blocks.append(
            Block(
                kind="bullets",
                text="Reasons this request is not supported:",
                items=tuple(
                    r.detail + (f" ({r.rule_id})" if r.rule_id else "")
                    for r in memo.recommendation.decline_reasons
                ),
            )
        )

    if memo.questions_for_client:
        blocks.append(Block(kind="heading", text="Questions for the borrower", level=2))
        blocks.append(Block(kind="bullets", text="", items=memo.questions_for_client))

    if memo.citations:
        blocks.append(Block(kind="heading", text="Sources", level=2))
        blocks.append(
            Block(
                kind="table",
                headers=("Source", "Page", "Title"),
                rows=tuple(
                    (c.source_id, str(c.page) if c.page else "-", c.title) for c in memo.citations
                ),
            )
        )

    # The legend last, where a reader returns to check a label they saw earlier.
    blocks.append(Block(kind="heading", text="How to read a figure", level=2))
    blocks.append(
        Block(
            kind="bullets",
            text="",
            items=tuple(
                f"{label[0].upper()}{label[1:]}"
                for label in (
                    _PROVENANCE_LABEL[Provenance.COMPUTED.value]
                    + ": calculated here from confirmed figures by a named, versioned formula.",
                    _PROVENANCE_LABEL[Provenance.CONFIRMED.value]
                    + ": a person reviewed and accepted the extraction.",
                    _PROVENANCE_LABEL[Provenance.USER_ENTERED.value]
                    + ": typed or uploaded by a person; canonical.",
                    _PROVENANCE_LABEL[Provenance.MODEL_DRAFTED.value]
                    + ": narrative. Every figure in it should also appear in a table above.",
                )
            ),
        )
    )

    borrower = memo.borrower
    return MemoDocument(
        title=f"Credit memo — {borrower.name}",
        subtitle=" · ".join(
            part
            for part in (
                template.title,
                borrower.sector,
                borrower.jurisdiction,
                memo.generated_at.strftime("%d %B %Y"),
            )
            if part
        ),
        blocks=tuple(blocks),
    )
