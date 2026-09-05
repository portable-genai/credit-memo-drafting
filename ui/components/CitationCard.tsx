import type { Citation } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  filing: "Filing",
  policy: "Credit policy",
  peer_data: "Peer data",
};

/** A compact, source-and-page citation chip (P-07: every claim is traceable). */
export function CitationCard({ citation }: { citation: Citation }) {
  const page = citation.page != null ? ` p.${citation.page}` : "";
  const label = SOURCE_LABEL[citation.source_type] ?? citation.source_type;
  return (
    <div className="rounded border border-ink-200 bg-white px-2 py-1 text-xs shadow-panel">
      <span className="font-mono text-ink-700">
        [{citation.source_id}
        {page}]
      </span>{" "}
      <span className="text-ink-500">{label}</span>
      {citation.title ? (
        <span className="text-ink-700"> · {citation.title}</span>
      ) : null}
      {citation.url ? (
        <>
          {" "}
          <a
            href={citation.url}
            target="_blank"
            rel="noreferrer"
            className="text-regblue-600 underline"
          >
            source
          </a>
        </>
      ) : null}
      {citation.score != null ? (
        <span
          className="ml-1 font-mono text-[10px] tabular-nums text-ink-400"
          title="Retrieval score: how strongly this passage matched the query"
        >
          {citation.score.toFixed(2)}
        </span>
      ) : null}
      {/* The snippet is the evidence itself. It was carried on every citation and never
          shown, so a reader had a reference with nothing to read. */}
      {citation.snippet ? (
        <p className="mt-1 border-l-2 border-ink-200 pl-2 text-[11px] leading-snug text-ink-600">
          {citation.snippet}
        </p>
      ) : null}
    </div>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) {
    return <p className="text-xs text-ink-400">(no citations)</p>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {citations.map((c, i) => (
        <CitationCard key={`${c.source_id}-${c.page}-${i}`} citation={c} />
      ))}
    </div>
  );
}
