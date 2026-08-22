import type { Covenant, CovenantStatus } from "@/lib/types";
import { CitationList } from "./CitationCard";

const STATUS_STYLE: Record<CovenantStatus, string> = {
  compliant: "bg-emerald-100 text-emerald-800 border-emerald-200",
  at_risk: "bg-amber-100 text-amber-800 border-amber-200",
  breach: "bg-red-100 text-red-800 border-red-200",
};

function StatusBadge({ status }: { status: CovenantStatus }) {
  return (
    <span
      className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase ${STATUS_STYLE[status]}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

/** Covenant section: status is computed deterministically by the backend (SPEC §5). */
export function CovenantTable({ covenants }: { covenants: Covenant[] }) {
  if (!covenants.length) {
    return <p className="text-sm text-ink-400">No covenants extracted.</p>;
  }
  return (
    <div className="space-y-3">
      {covenants.map((c, i) => (
        <div
          key={`${c.type}-${i}`}
          className="rounded-lg border border-ink-200 bg-white p-3 shadow-panel"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-ink-800">
              {c.type.replace("_", " ")}
            </span>
            <StatusBadge status={c.status} />
          </div>
          <p className="mt-1 text-sm text-ink-600">{c.description}</p>
          <p className="mt-1 font-mono text-xs text-ink-500">
            current {c.current_value ?? "n/a"} {c.operator} {c.threshold}
            {c.period ? ` · ${c.period}` : ""}
          </p>
          <div className="mt-2">
            <CitationList citations={c.citations} />
          </div>
        </div>
      ))}
    </div>
  );
}
