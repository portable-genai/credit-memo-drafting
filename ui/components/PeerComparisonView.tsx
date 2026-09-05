import type { PeerComparison } from "@/lib/types";

/**
 * Which metrics are better when higher. The peer table coloured every positive delta
 * red and every negative one green, which reads "above the peer median is bad" -- true
 * of leverage, exactly backwards for margin, coverage and liquidity. The backend does
 * not send `higher_is_better` on a peer comparison, so this mirrors the ratio
 * catalogue's own answer by metric name and stays neutral for anything it does not
 * recognise, rather than guessing and colouring it wrongly.
 */
const HIGHER_IS_BETTER: Record<string, boolean> = {
  leverage: false,
  gearing: false,
  dscr: true,
  interest_cover: true,
  current_ratio: true,
  quick_ratio: true,
  ebitda_margin: true,
  revenue: true,
  ebitda: true,
  net_income: true,
  tangible_net_worth: true,
};

function deltaClass(metric: string, delta: number): string {
  const better = HIGHER_IS_BETTER[metric.toLowerCase()];
  if (better === undefined || delta === 0) return "text-ink-700";
  const good = better ? delta > 0 : delta < 0;
  return good ? "text-emerald-700" : "text-red-700";
}

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
            <th className="py-1 pr-4 font-medium">Peers</th>
          </tr>
        </thead>
        <tbody>
          {comparisons.map((c, i) => (
            <tr key={`${c.metric}-${i}`} className="border-b border-ink-100">
              <td className="py-1 pr-4 font-medium text-ink-800">{c.metric}</td>
              <td className="py-1 pr-4 font-mono tabular-nums text-ink-700">
                {c.borrower_value}
              </td>
              <td className="py-1 pr-4 font-mono tabular-nums text-ink-700">
                {c.peer_median}
              </td>
              <td
                className={`py-1 pr-4 font-mono tabular-nums ${deltaClass(
                  c.metric,
                  c.delta_to_median,
                )}`}
              >
                {c.delta_to_median > 0 ? "+" : ""}
                {c.delta_to_median.toFixed(2)}
              </td>
              <td className="py-1 pr-4 font-mono tabular-nums text-ink-700">
                p{Math.round(c.percentile * 100)}
              </td>
              <td className="py-1 pr-4 text-xs text-ink-500">
                {c.peers.length
                  ? c.peers
                      .map((peer) => `${peer.peer_name} ${peer.value.toFixed(2)}`)
                      .join(" · ")
                  : "cohort not disclosed"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
