import type { RenewalDelta, SectionDelta } from "@/lib/types";

function figure(value: number | null, unit: string): string {
  if (value === null) return "not measured";
  if (unit === "x") return `${value.toFixed(2)}x`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** The arrow a reader scans for. The WORD comes from the engine; this only draws it. */
const ARROW: Record<string, string> = {
  up: "↑",
  down: "↓",
  unchanged: "→",
  new: "+",
  gone: "−",
};

function MovedRows({ lines }: { lines: SectionDelta[] }) {
  return (
    <>
      {lines.map((line) => (
        <tr key={line.label} data-moved-line={line.label} data-direction={line.direction}>
          <td className="py-1 pr-3 text-ink-800">{line.label}</td>
          <td className="py-1 pr-3 font-mono tabular-nums text-ink-600">
            {figure(line.before, line.unit)}
          </td>
          <td className="py-1 pr-3 font-mono tabular-nums text-ink-900">
            {figure(line.after, line.unit)}
          </td>
          <td className="py-1 text-ink-700">
            {ARROW[line.direction] ?? ""} {line.direction}
          </td>
        </tr>
      ))}
    </>
  );
}

/**
 * What changed since the last review, which is what a renewal's reader came for.
 *
 * Its reader knows this borrower: they approved the facility last cycle and read the memo
 * that did it. What they need is the difference, so this renders first among the sections and
 * says "unchanged" out loud rather than restating what held.
 *
 * The most important branch is the one where there is nothing to compare. There is no memo of
 * record in this service, so the baseline is whatever the analyst uploaded, and when they
 * uploaded nothing, or uploaded something that is not a memo this service produced, that is
 * said in a sentence. An empty table here would read as "nothing moved", which is a claim
 * about the borrower rather than about what the analysis was given, and the two are not
 * interchangeable.
 */
export function RenewalDeltaView({ delta }: { delta: RenewalDelta }) {
  if (delta.no_comparison_reason) {
    return (
      <div
        data-renewal="no-comparison"
        className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900"
      >
        <p className="font-semibold">Nothing was compared against.</p>
        <p className="mt-1">{delta.no_comparison_reason}</p>
        <p className="mt-1 text-xs">
          Read what follows as a full assessment rather than as a delta.
        </p>
      </div>
    );
  }

  const moved = [...delta.ratios, ...delta.covenants, ...delta.spread];
  return (
    <div className="space-y-2 text-sm">
      <p data-renewal="measured-against" className="text-ink-700">
        Measured against{" "}
        <span className="font-medium text-ink-900">
          {delta.prior_filename || "the prior memo supplied"}
        </span>
        {delta.prior_at ? `, generated ${delta.prior_at.slice(0, 10)}` : ""}
        {delta.prior_version ? ` under policy ${delta.prior_version}` : ""}.
      </p>

      {moved.length ? (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full text-sm">
            <caption className="sr-only">Lines that moved since the prior memo</caption>
            <thead>
              <tr className="border-b border-ink-200 text-left text-ink-500">
                <th scope="col" className="py-1 pr-3 font-medium">
                  Line
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Last time
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Now
                </th>
                <th scope="col" className="py-1 font-medium">
                  Movement
                </th>
              </tr>
            </thead>
            <tbody>
              <MovedRows lines={moved} />
            </tbody>
          </table>
        </div>
      ) : (
        <p data-renewal="nothing-moved" className="text-ink-700">
          No ratio, covenant or spread line moved materially since that memo. Stated rather than
          left out: that the figures held is something a reader can act on.
        </p>
      )}

      {delta.rating_before !== delta.rating_after ? (
        <p data-renewal="rating-moved" className="text-ink-800">
          The proposed grade moved from{" "}
          <span className="font-mono">{delta.rating_before || "none"}</span> to{" "}
          <span className="font-mono">{delta.rating_after || "none"}</span>.
        </p>
      ) : null}

      {delta.new_exceptions.length ? (
        <p data-renewal="new-exceptions" className="text-amber-900">
          Policy exceptions new since the last review: {delta.new_exceptions.join(", ")}.
        </p>
      ) : null}

      {/* A cleared exception is the argument FOR the renewal, and is invisible unless said. */}
      {delta.cleared_exceptions.length ? (
        <p data-renewal="cleared-exceptions" className="text-green-900">
          Cleared since the last review: {delta.cleared_exceptions.join(", ")}.
        </p>
      ) : null}

      {delta.unchanged_sections.length ? (
        <p data-renewal="unchanged" className="text-xs text-ink-500">
          Unchanged, and not restated here: {delta.unchanged_sections.join(", ")}.
        </p>
      ) : null}
    </div>
  );
}
