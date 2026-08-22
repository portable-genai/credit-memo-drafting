import type { RiskFlag, Severity } from "@/lib/types";
import { CitationList } from "./CitationCard";

const SEVERITY_STYLE: Record<Severity, string> = {
  low: "bg-ink-100 text-ink-700 border-ink-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  critical: "bg-red-100 text-red-800 border-red-200",
};

export function RiskFlagList({ flags }: { flags: RiskFlag[] }) {
  if (!flags.length) {
    return <p className="text-sm text-ink-400">No risk flags identified.</p>;
  }
  return (
    <div className="space-y-3">
      {flags.map((f, i) => (
        <div
          key={`${f.category}-${i}`}
          className="rounded-lg border border-ink-200 bg-white p-3 shadow-panel"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-ink-800">
              {f.category}
            </span>
            <span
              className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase ${SEVERITY_STYLE[f.severity]}`}
            >
              {f.severity}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-600">{f.detail}</p>
          <div className="mt-2">
            <CitationList citations={f.citations} />
          </div>
        </div>
      ))}
    </div>
  );
}
