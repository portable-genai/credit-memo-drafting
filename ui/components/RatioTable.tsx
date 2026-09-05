"use client";

import { useState } from "react";
import type { Ratio, RatioInput } from "@/lib/types";
import { ProvenanceTag } from "./Provenance";

function formatValue(ratio: Ratio): string {
  if (ratio.value == null) return "—";
  if (ratio.unit === "x") return `${ratio.value.toFixed(2)}x`;
  if (ratio.unit === "ratio") return ratio.value.toFixed(3);
  return ratio.value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function term(input: RatioInput): string {
  const sign = input.coefficient < 0 ? "−" : "+";
  const magnitude = Math.abs(input.coefficient);
  const scale = magnitude === 1 ? "" : `${magnitude} × `;
  return `${sign} ${scale}${input.code.replace(/_/g, " ")} ${input.value.toLocaleString()}`;
}

/**
 * The working, not just the answer.
 *
 * A credit officer challenging "leverage 2.5x" wants the two operands and the formula
 * version, and wants them without leaving the memo. Every row expands into exactly that.
 * Rows the engine could NOT compute are shown too, carrying the line that was missing:
 * omitting them would read as "we did not think leverage mattered" rather than "you did
 * not give us the debt figure".
 */
export function RatioTable({ ratios }: { ratios: Ratio[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (!ratios.length) {
    return (
      <p className="text-sm text-ink-400">
        No ratios computed. Enter a spread above and the engine will calculate them from
        it.
      </p>
    );
  }

  const periods = Array.from(new Set(ratios.map((r) => r.period)));

  return (
    <div className="space-y-4">
      {periods.map((period) => {
        const rows = ratios.filter((r) => r.period === period);
        return (
          <div key={period}>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
              {period}
            </h4>
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full text-sm">
                <caption className="sr-only">
                  Ratios computed for {period}, with the formula and operands behind each
                </caption>
                <thead>
                  <tr className="border-b border-ink-200 text-left text-ink-500">
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Ratio
                    </th>
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Value
                    </th>
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Definition
                    </th>
                    <th scope="col" className="py-1 pr-4 font-medium">
                      Source
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const key = `${r.formula_id}-${r.period}`;
                    const expanded = open === key;
                    return [
                      <tr key={key} className="border-b border-ink-100">
                        <td className="py-1 pr-4 font-medium text-ink-800">
                          {r.name}
                        </td>
                        <td className="py-1 pr-4 font-mono tabular-nums text-ink-800">
                          {r.value == null ? (
                            <span
                              className="text-ink-400"
                              title={r.reason_missing}
                            >
                              not computable
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setOpen(expanded ? null : key)}
                              aria-expanded={expanded}
                              className="underline decoration-dotted underline-offset-2 hover:text-regblue-700"
                            >
                              {formatValue(r)}
                            </button>
                          )}
                        </td>
                        <td className="py-1 pr-4 text-ink-600">{r.definition}</td>
                        <td className="py-1 pr-4">
                          {r.value == null ? (
                            <span className="text-xs text-ink-400">
                              {r.reason_missing}
                            </span>
                          ) : (
                            <ProvenanceTag
                              provenance={r.provenance}
                              detail={`Formula ${r.formula_id}.`}
                            />
                          )}
                        </td>
                      </tr>,
                      expanded ? (
                        <tr key={`${key}-detail`} className="border-b border-ink-100">
                          <td colSpan={4} className="bg-ink-50 px-3 py-2">
                            <p className="font-mono text-xs text-ink-700">
                              {r.formula_id} · {r.definition}
                            </p>
                            <ul className="mt-1 space-y-0.5 font-mono text-xs text-ink-600">
                              {(["numerator", "denominator"] as const).map((side) => {
                                const inputs = r.inputs.filter((i) => i.side === side);
                                if (!inputs.length) return null;
                                return (
                                  <li key={side}>
                                    <span className="text-ink-400">{side}: </span>
                                    {inputs.map(term).join(" ").replace(/^\+ /, "")}
                                  </li>
                                );
                              })}
                            </ul>
                          </td>
                        </tr>
                      ) : null,
                    ];
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
