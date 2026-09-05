import type { Covenant, CovenantStatus } from "@/lib/types";
import { CitationList } from "./CitationCard";
import { ProvenanceTag } from "./Provenance";

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
      {status.replace(/_/g, " ")}
    </span>
  );
}

/**
 * Covenant section. Status is computed by the backend (SPEC §5) — but so, now, is the
 * value it is computed FROM, wherever the confirmed spread supports the covenant's type.
 *
 * The two operands are rendered separately on purpose. The threshold was read out of an
 * agreement and the current value was calculated here, and a reader who cannot see which
 * is which cannot tell a covenant the bank measured from one a model asserted. Where the
 * extraction reported a different figure it is shown beside the computed one rather than
 * discarded: the disagreement is information.
 */
export function CovenantTable({ covenants }: { covenants: Covenant[] }) {
  if (!covenants.length) {
    return <p className="text-sm text-ink-400">No covenants extracted.</p>;
  }
  return (
    <div className="space-y-3">
      {covenants.map((c, i) => {
        const disagrees =
          c.measured != null &&
          c.reported_value != null &&
          c.measured.value != null &&
          Math.abs(c.measured.value - c.reported_value) > 1e-6;
        return (
          <div
            key={`${c.type}-${i}`}
            className="rounded-lg border border-ink-200 bg-white p-3 shadow-panel"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-ink-800">
                {c.type.replace(/_/g, " ")}
              </span>
              <StatusBadge status={c.status} />
            </div>
            <p className="mt-1 text-sm text-ink-600">{c.description}</p>

            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-ink-600">
              <span className="text-ink-500">current</span>
              <span className="font-semibold text-ink-800 tabular-nums">
                {c.current_value ?? "n/a"}
              </span>
              <ProvenanceTag
                provenance={c.value_provenance}
                detail={
                  c.measured
                    ? `${c.measured.formula_id}: ${c.measured.definition}.`
                    : "Read from the evidence; no confirmed spread supported this covenant."
                }
              />
              <span className="text-ink-400">{c.operator}</span>
              <span className="text-ink-800 tabular-nums">{c.threshold}</span>
              <ProvenanceTag
                provenance="extracted"
                detail="The threshold is a term of the agreement, read from the evidence."
              />
              {c.period ? <span className="text-ink-400">· {c.period}</span> : null}
            </div>

            {disagrees ? (
              <p className="mt-1 text-xs text-amber-800">
                The evidence reported {c.reported_value}; the engine computed{" "}
                {c.measured?.value}. The test above used the computed figure. Check the
                spread against the certificate.
              </p>
            ) : null}

            <div className="mt-2">
              <CitationList citations={c.citations} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
