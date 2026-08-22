import type { PeerComparison } from "@/lib/types";

export function PeerComparisonView({
  comparisons,
}: {
  comparisons: PeerComparison[];
}) {
  if (!comparisons.length) {
    return <p className="text-sm text-ink-400">No peer comparison available.</p>;
  }
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-left text-ink-500">
            <th className="py-1 pr-4 font-medium">Metric</th>
            <th className="py-1 pr-4 font-medium">Borrower</th>
            <th className="py-1 pr-4 font-medium">Peer median</th>
            <th className="py-1 pr-4 font-medium">Delta</th>
            <th className="py-1 pr-4 font-medium">Percentile</th>
          </tr>
        </thead>
        <tbody>
          {comparisons.map((c, i) => (
            <tr key={`${c.metric}-${i}`} className="border-b border-ink-100">
              <td className="py-1 pr-4 font-medium text-ink-800">{c.metric}</td>
              <td className="py-1 pr-4 font-mono text-ink-700">
                {c.borrower_value}
              </td>
              <td className="py-1 pr-4 font-mono text-ink-700">
                {c.peer_median}
              </td>
              <td
                className={`py-1 pr-4 font-mono ${
                  c.delta_to_median > 0 ? "text-red-700" : "text-emerald-700"
                }`}
              >
                {c.delta_to_median > 0 ? "+" : ""}
                {c.delta_to_median.toFixed(2)}
              </td>
              <td className="py-1 pr-4 font-mono text-ink-700">
                p{Math.round(c.percentile * 100)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
