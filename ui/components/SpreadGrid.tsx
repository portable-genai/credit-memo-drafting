"use client";

import type { FinancialSpread, LineItem, LineItemCode, Period } from "@/lib/types";

/** The lines the ratio catalogue can reference, grouped as an analyst reads a spread. */
const ROWS: { code: LineItemCode; label: string; group: string }[] = [
  { code: "revenue", label: "Revenue", group: "Income statement" },
  { code: "ebitda", label: "EBITDA", group: "Income statement" },
  { code: "interest_expense", label: "Interest expense", group: "Income statement" },
  { code: "tax_expense", label: "Tax expense", group: "Income statement" },
  { code: "lease_expense", label: "Lease expense", group: "Income statement" },
  { code: "capex", label: "Capital expenditure", group: "Cash flow" },
  {
    code: "scheduled_debt_service",
    label: "Scheduled debt service",
    group: "Cash flow",
  },
  { code: "current_assets", label: "Current assets", group: "Balance sheet" },
  { code: "inventory", label: "Inventory", group: "Balance sheet" },
  {
    code: "current_liabilities",
    label: "Current liabilities",
    group: "Balance sheet",
  },
  { code: "total_debt", label: "Total debt", group: "Balance sheet" },
  { code: "total_equity", label: "Total equity", group: "Balance sheet" },
  { code: "intangible_assets", label: "Intangible assets", group: "Balance sheet" },
];

const GROUPS = Array.from(new Set(ROWS.map((r) => r.group)));

export const DEFAULT_PERIODS: Period[] = [
  { label: "FY2023", ends_on: "2023-12-31", months: 12, audited: true },
  { label: "FY2024", ends_on: "2024-12-31", months: 12, audited: true },
  { label: "FY2025", ends_on: "2025-12-31", months: 12, audited: true },
];

export function emptySpread(borrowerId: string): FinancialSpread {
  return {
    borrower_id: borrowerId,
    periods: DEFAULT_PERIODS,
    items: [],
    currency: "USD",
    unit: "millions",
    confirmed_by: "",
  };
}

/**
 * The analyst types the spread; the engine computes from it.
 *
 * Every cell is `user_entered`, which is the strongest provenance the system has: no
 * model overwrites these numbers, and the ratios below are arithmetic over exactly what
 * is on this grid. A blank cell stays blank — the engine reports the ratio that needed
 * it as "not computable" rather than imputing a zero, because "we were not given the
 * interest expense" and "interest cover is infinite" are different statements.
 */
export function SpreadGrid({
  spread,
  onChange,
}: {
  spread: FinancialSpread;
  onChange: (next: FinancialSpread) => void;
}) {
  const periods = spread.periods;

  function valueFor(code: LineItemCode, period: string): string {
    const item = spread.items.find((i) => i.code === code && i.period === period);
    return item == null ? "" : String(item.value);
  }

  function setCell(code: LineItemCode, period: string, raw: string): void {
    const rest = spread.items.filter(
      (i) => !(i.code === code && i.period === period),
    );
    const trimmed = raw.trim();
    if (trimmed === "") {
      onChange({ ...spread, items: rest });
      return;
    }
    const value = Number(trimmed);
    if (!Number.isFinite(value)) return;
    const item: LineItem = {
      code,
      period,
      value,
      currency: spread.currency,
      provenance: "user_entered",
      citations: [],
    };
    onChange({ ...spread, items: [...rest, item] });
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-ink-500">
        Figures in {spread.unit} of {spread.currency}. Leave a cell blank if you do not
        have it: the ratio that needs it will say so rather than assume a zero.
      </p>
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full min-w-[34rem] text-sm">
          <caption className="sr-only">
            Financial spread: one row per line item, one column per reporting period
          </caption>
          <thead>
            <tr className="border-b border-ink-200 text-left text-ink-500">
              <th scope="col" className="py-1 pr-3 font-medium">
                Line
              </th>
              {periods.map((p) => (
                <th key={p.label} scope="col" className="py-1 pr-3 font-medium">
                  {p.label}
                  {p.audited ? (
                    <span className="ml-1 text-[10px] uppercase text-ink-400">
                      audited
                    </span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          {GROUPS.map((group) => (
            <tbody key={group}>
              <tr className="border-b border-ink-100">
                <th
                  scope="colgroup"
                  colSpan={periods.length + 1}
                  className="bg-ink-50 py-1 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-500"
                >
                  {group}
                </th>
              </tr>
              {ROWS.filter((r) => r.group === group).map((row) => (
                <tr key={row.code} className="border-b border-ink-100">
                  <th
                    scope="row"
                    className="py-1 pr-3 text-left font-normal text-ink-700"
                  >
                    {row.label}
                  </th>
                  {periods.map((p) => (
                    <td key={p.label} className="py-1 pr-3">
                      <input
                        id={`cell-${row.code}-${p.label}`}
                        inputMode="decimal"
                        aria-label={`${row.label}, ${p.label}`}
                        value={valueFor(row.code, p.label)}
                        onChange={(e) => setCell(row.code, p.label, e.target.value)}
                        className="w-24 rounded border border-ink-300 px-1.5 py-1 text-right font-mono tabular-nums"
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}
