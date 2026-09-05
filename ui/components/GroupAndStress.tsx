import type { CreditMemo, GlobalCashFlow, ScenarioResult } from "@/lib/types";

const LINE_LABELS: Record<string, string> = {
  revenue: "Revenue",
  ebitda: "EBITDA",
  interest_expense: "Interest expense",
  tax_expense: "Tax expense",
  capex: "Capital expenditure",
  scheduled_debt_service: "Scheduled debt service",
  total_debt: "Total debt",
};

const money = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 });

/**
 * Whose cash actually services this debt.
 *
 * Three things this shows that a consolidated total would not, and each is the reason the
 * section exists rather than a single figure:
 *
 * - **Every contribution.** A consolidated EBITDA of 115 says nothing about whether that
 *   is one strong entity and two weak ones, which is the difference between a group that
 *   can support the facility and one where a single subsidiary can.
 * - **The eliminations.** A group whose revenue halves on consolidation is telling the
 *   reader something important about how it trades with itself.
 * - **Who is missing.** A cash flow that quietly omits the guarantor whose accounts
 *   nobody uploaded reads as though that guarantor contributes nothing, which is a
 *   stronger claim than "we did not look".
 */
export function GlobalCashFlowView({ gcf }: { gcf: GlobalCashFlow }) {
  return (
    <div className="space-y-2">
      {gcf.complete ? null : (
        <p className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          <strong>Incomplete.</strong> No figures were supplied for{" "}
          {gcf.entities_without_figures.join(", ")}. They contribute nothing to the totals
          below because nobody uploaded their statements, not because they have nothing to
          contribute.
        </p>
      )}
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full min-w-[34rem] text-sm">
          <caption className="sr-only">
            Consolidated group cash flow, one row per line with each entity&apos;s share
          </caption>
          <thead>
            <tr className="border-b border-ink-200 text-left text-ink-500">
              <th scope="col" className="py-1 pr-3 font-medium">Line</th>
              <th scope="col" className="py-1 pr-3 font-medium">Period</th>
              <th scope="col" className="py-1 pr-3 text-right font-medium">Group</th>
              <th scope="col" className="py-1 pr-3 font-medium">Made up of</th>
            </tr>
          </thead>
          <tbody>
            {gcf.lines.map((line) => (
              <tr key={`${line.code}-${line.period}`} className="border-b border-ink-100 align-top">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-700">
                  {LINE_LABELS[line.code] ?? line.code}
                </th>
                <td className="py-1.5 pr-3 text-ink-700">{line.period}</td>
                <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-ink-900">
                  {money(line.total)}
                </td>
                <td className="py-1.5 pr-3 text-xs text-ink-600">
                  {line.contributions
                    .map((c) => `${c.entity_name} ${money(c.value)}`)
                    .join(" · ")}
                  {line.eliminations.length ? (
                    <span className="block text-amber-800">
                      less{" "}
                      {line.eliminations
                        .map((e) => `${money(e.amount)} (${e.reason || e.between})`)
                        .join(", ")}
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-ink-500">
        Figures in {gcf.currency}. Each total is the sum of figures a person confirmed, and
        the ratios computed from them are marked as calculated.
      </p>
    </div>
  );
}

/**
 * How far this can fall before it breaks.
 *
 * Both numbers, on purpose. A committee has no way to judge whether a 15% decline is the
 * right test for this sector this year; they can judge "it survives twice that", which is
 * a question about their own view of the world rather than about the model's.
 */
export function ScenarioView({ scenarios }: { scenarios: ScenarioResult[] }) {
  if (!scenarios.length) {
    return (
      <p className="text-sm text-ink-400">
        No scenario could be run: the confirmed spread does not carry the figures the
        coverage ratio needs.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="sr-only">Stress scenarios with break-even</caption>
        <thead>
          <tr className="border-b border-ink-200 text-left text-ink-500">
            <th scope="col" className="py-1 pr-3 font-medium">Scenario</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Base</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Stressed</th>
            <th scope="col" className="py-1 pr-3 font-medium">Against the covenant</th>
            <th scope="col" className="py-1 pr-3 font-medium">Breaks at</th>
          </tr>
        </thead>
        <tbody>
          {scenarios.map((s) => (
            <tr key={s.scenario_id} className="border-b border-ink-100">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-700">
                {s.scenario_name}
              </th>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                {s.base_value == null ? "—" : `${s.base_value.toFixed(2)}x`}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                {s.stressed_value == null ? "—" : `${s.stressed_value.toFixed(2)}x`}
              </td>
              <td className="py-1.5 pr-3 text-xs">
                {s.threshold == null ? (
                  <span className="text-ink-400">no covenant states one</span>
                ) : s.passes ? (
                  <span className="text-green-800">
                    passes {s.threshold.toFixed(2)}x
                  </span>
                ) : (
                  <span className="text-red-800">
                    fails {s.threshold.toFixed(2)}x
                  </span>
                )}
              </td>
              <td className="py-1.5 pr-3 text-xs text-ink-700">
                {s.breaks_at == null ? (
                  <span className="text-ink-400">survives everything modelled</span>
                ) : s.breaks_at === 0 ? (
                  "already below the covenant before any stress"
                ) : (
                  `${s.breaks_at.toFixed(2)}x this scenario`
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Who is in the group and who stands behind the facility. */
export function GroupRoster({ memo }: { memo: CreditMemo }) {
  return (
    <ul className="space-y-1 text-sm text-ink-800">
      {memo.related_entities.map((e) => (
        <li key={e.id}>
          <span className="font-medium">{e.name}</span>{" "}
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {e.role.replace(/_/g, " ")}
          </span>
          {e.ownership_pct == null ? null : (
            <span className="text-xs text-ink-500">
              {" · "}
              {e.ownership_pct}% of it held by its parent
            </span>
          )}
        </li>
      ))}
      {memo.guarantors.map((g) => (
        <li key={g.entity_id} className="text-ink-700">
          <span className="font-medium">{g.name}</span>{" "}
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {g.is_personal ? "personal guarantee" : "corporate guarantee"}
            {g.limited ? ", limited" : ", unlimited"}
          </span>
          {g.reliance ? (
            <span className="block text-xs text-ink-500">{g.reliance}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
