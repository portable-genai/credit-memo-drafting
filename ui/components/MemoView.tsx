import type { CreditMemo } from "@/lib/types";
import { CitationList } from "./CitationCard";
import { CovenantTable } from "./CovenantTable";
import { PeerComparisonView } from "./PeerComparisonView";
import { RiskFlagList } from "./RiskFlagList";

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
        {memo.requires_human_review ? (
          <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
            HUMAN REVIEW REQUIRED · maker-checker gate (P-06). Decision support,
            not a credit decision.
          </p>
        ) : null}
      </div>

      <Section title="Summary">
        <p className="text-sm leading-relaxed text-ink-800">{memo.summary}</p>
      </Section>

      <Section title="Financial analysis">
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

      <Section title="Citations">
        <CitationList citations={memo.citations} />
      </Section>
    </div>
  );
}
