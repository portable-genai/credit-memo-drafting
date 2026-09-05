import type { Provenance } from "@/lib/types";

/**
 * One reading of where a figure came from, shown as a glyph AND a word.
 *
 * Never colour alone: "the engine calculated this" and "a model read it off a page" is
 * the single most consequential distinction on the memo, and a reader who cannot
 * separate green from amber must still be able to make it. The glyph is the fast scan,
 * the word is the answer, and the tooltip is why it matters.
 */
const PROVENANCE_META: Record<
  Provenance,
  { glyph: string; label: string; hint: string; className: string }
> = {
  computed: {
    glyph: "=",
    label: "computed",
    hint: "Calculated here from confirmed figures by a named formula. Replayable.",
    className: "border-emerald-300 bg-emerald-50 text-emerald-900",
  },
  user_entered: {
    glyph: "✎",
    label: "you entered",
    hint: "Typed or uploaded by a person. Canonical: no model overwrites it.",
    className: "border-regblue-300 bg-regblue-50 text-regblue-900",
  },
  confirmed: {
    glyph: "✓",
    label: "confirmed",
    hint: "Read off a document and then reviewed and accepted by a person.",
    className: "border-regblue-300 bg-regblue-50 text-regblue-900",
  },
  extracted: {
    glyph: "⌘",
    label: "extracted",
    hint: "Read off a document, not yet confirmed by a person. Check before relying on it.",
    className: "border-amber-300 bg-amber-50 text-amber-900",
  },
  model_drafted: {
    glyph: "∼",
    label: "model drafted",
    hint: "Prose a language model wrote. Every figure in it should also appear above.",
    className: "border-ink-300 bg-ink-50 text-ink-700",
  },
  web_grounded: {
    glyph: "↗",
    label: "web",
    hint: "Retrieved from the public web. Context only; it feeds no calculation.",
    className: "border-ink-300 bg-ink-50 text-ink-700",
  },
  vendor: {
    glyph: "◦",
    label: "vendor",
    hint: "Supplied pre-computed by a data vendor. Context only.",
    className: "border-ink-300 bg-ink-50 text-ink-700",
  },
};

export function ProvenanceTag({
  provenance,
  detail,
}: {
  provenance: Provenance;
  /** Appended to the tooltip: the formula, the page, or who typed it. */
  detail?: string;
}) {
  const meta = PROVENANCE_META[provenance] ?? PROVENANCE_META.extracted;
  const title = detail ? `${meta.hint} ${detail}` : meta.hint;
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${meta.className}`}
      title={title}
    >
      <span aria-hidden="true">{meta.glyph}</span>
      {meta.label}
    </span>
  );
}

/** The legend, so the glyphs are readable on first encounter rather than on hover. */
export function ProvenanceLegend() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
      <span className="font-medium text-ink-600">How to read a figure:</span>
      {(["computed", "user_entered", "extracted", "model_drafted"] as Provenance[]).map(
        (p) => (
          <ProvenanceTag key={p} provenance={p} />
        ),
      )}
    </div>
  );
}
