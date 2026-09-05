import type { CreditMemo } from "@/lib/types";
import { CitationList } from "./CitationCard";
import { CovenantTable } from "./CovenantTable";
import { PeerComparisonView } from "./PeerComparisonView";
import { ProvenanceLegend, ProvenanceTag } from "./Provenance";
import { RatioTable } from "./RatioTable";
import { RiskFlagList } from "./RiskFlagList";

const KIND_LABEL: Record<string, string> = {
  new_facility: "New facility",
  renewal: "Renewal",
  annual_review: "Annual review",
  interim_review: "Interim review",
  rating_action: "Rating action",
  pre_screen: "Pre-screen",
  decline: "Decline",
};

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-ink-200 bg-ink-50 p-4 shadow-panel">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Renders the full CreditMemo artifact with its four cited sections. */
export function MemoView({ memo }: { memo: CreditMemo }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-regblue-200 bg-regblue-50 p-4 shadow-panel">
        <h2 className="text-lg font-semibold text-ink-900">
          {memo.borrower.name}
        </h2>
        <p className="text-sm text-ink-600">
          {memo.borrower.sector || "sector n/a"} ·{" "}
          {memo.borrower.jurisdiction || "jurisdiction n/a"}
        </p>
        {memo.request ? (
          <p className="mt-1 text-sm text-ink-700">
            {KIND_LABEL[memo.request.kind] ?? memo.request.kind} ·{" "}
            {memo.request.loan_type.replace(/_/g, " ")}
            {memo.request.total_amount
              ? ` · ${memo.request.facilities[0]?.currency ?? ""} ${memo.request.total_amount.toLocaleString()}`
              : ""}
            {memo.request.facilities[0]?.tenor_months
              ? ` over ${memo.request.facilities[0].tenor_months} months`
              : ""}
          </p>
        ) : null}
        {memo.requires_human_review ? (
          <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
            HUMAN REVIEW REQUIRED · maker-checker gate (P-06). Decision support,
            not a credit decision.
          </p>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <ProvenanceLegend />
          <span className="font-mono text-xs text-ink-400">
            built {new Date(memo.generated_at).toLocaleString()}
          </span>
        </div>
      </div>

      {/* The drafter's own verdict on its work, which the pipeline used to compute and
          then discard. Shown before the prose it qualifies, not after. */}
      {memo.caveats.length || memo.confidence ? (
        <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-ink-800">
              Drafting confidence
            </span>
            <span className="font-mono text-sm tabular-nums text-ink-800">
              {(memo.confidence * 100).toFixed(0)}%
            </span>
            <ProvenanceTag
              provenance="model_drafted"
              detail="A second model pass audited the draft against the evidence."
            />
          </div>
          {memo.caveats.length ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
              {memo.caveats.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <Section title="Summary">
        <p className="text-sm leading-relaxed text-ink-800">{memo.summary}</p>
      </Section>

      <Section title="Ratios">
        <RatioTable ratios={memo.ratios} />
      </Section>

      <Section title="Financial analysis">
        <p className="mb-2 flex items-center gap-2 text-xs text-ink-500">
          <ProvenanceTag provenance="model_drafted" />
          Normalised by the model from the evidence. The Ratios section above is the
          engine&apos;s own arithmetic; where the two disagree, the engine is the memo.
        </p>
        {memo.financial_metrics.length ? (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {memo.financial_metrics.map((m, i) => (
              <li
                key={`${m.name}-${i}`}
                className="rounded border border-ink-200 bg-white p-2 text-sm shadow-panel"
              >
                <span className="block text-xs uppercase text-ink-500">
                  {m.name}
                </span>
                <span className="font-mono text-ink-800">
                  {m.value} {m.currency}
                </span>
                {m.period ? (
                  <span className="block text-xs text-ink-400">{m.period}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-400">No metrics normalised.</p>
        )}
      </Section>

      <Section title="Covenants">
        <CovenantTable covenants={memo.covenants} />
      </Section>

      <Section title="Risk assessment">
        <RiskFlagList flags={memo.risk_flags} />
      </Section>

      <Section title="Peer comparison">
        <PeerComparisonView comparisons={memo.peer_comparison} />
      </Section>

      <Section title="Recommendation rationale">
        <p className="text-sm leading-relaxed text-ink-800">
          {memo.recommendation_rationale}
        </p>
      </Section>

      {memo.questions_for_client.length ? (
        <Section title="Questions for the borrower">
          <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-800">
            {memo.questions_for_client.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </Section>
      ) : null}

      <Section title="Citations">
        <CitationList citations={memo.citations} />
      </Section>
    </div>
  );
}
