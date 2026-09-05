"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type {
  Elimination,
  EntityGroup,
  FinancialSpread,
  LineItemCode,
  Period,
} from "@/lib/types";

/** One entity the analyst is declaring, with the figures they have for it. */
export interface GroupEntityDraft {
  id: string;
  name: string;
  role: string;
  /** Keyed by line code; a blank string means "not supplied", never zero. */
  figures: Partial<Record<LineItemCode, string>>;
  /** True when a register proposed this entity rather than the analyst typing it. */
  suggested?: boolean;
}

const ROLES = [
  ["parent", "Parent"],
  ["subsidiary", "Subsidiary"],
  ["affiliate", "Affiliate"],
  ["guarantor_corporate", "Corporate guarantor"],
  ["guarantor_personal", "Personal guarantor"],
] as const;

/**
 * The lines a global cash flow consolidates — deliberately not the whole spread.
 * Consolidating a balance-sheet total across entities with different year ends produces a
 * figure that looks authoritative and means very little.
 */
const LINES: { code: LineItemCode; label: string }[] = [
  { code: "revenue", label: "Revenue" },
  { code: "ebitda", label: "EBITDA" },
  { code: "interest_expense", label: "Interest" },
  { code: "tax_expense", label: "Tax" },
  { code: "capex", label: "Capex" },
  { code: "scheduled_debt_service", label: "Debt service" },
  { code: "total_debt", label: "Total debt" },
];

function slug(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

/**
 * Who else is in the group, and what each of them earns.
 *
 * Most mid-market lending is to a group: the borrower is an operating subsidiary, the
 * property sits in a holdco, a director has guaranteed it personally. The question a credit
 * officer is actually asking is whether the combined cash covers the combined debt, and a
 * memo that answers it for the borrowing entity alone has answered a narrower one.
 *
 * An entity listed here with no figures is not a mistake and is not dropped: it appears on
 * the memo as one the consolidation could not include. That is the whole point of naming it
 * — "we did not look" is a weaker and truer claim than a total that quietly omits it.
 */
export function GroupPanel({
  entities,
  onChange,
  eliminations,
  onEliminationsChange,
  borrowerSpread,
  analysisId,
  disabled,
}: {
  entities: GroupEntityDraft[];
  onChange: (next: GroupEntityDraft[]) => void;
  eliminations: Elimination[];
  onEliminationsChange: (next: Elimination[]) => void;
  borrowerSpread: FinancialSpread;
  analysisId: string;
  disabled?: boolean;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>("parent");
  const [note, setNote] = useState("");

  const period = periodOf(borrowerSpread);

  function add() {
    const trimmed = name.trim();
    if (!trimmed) return;
    onChange([...entities, { id: slug(trimmed), name: trimmed, role, figures: {} }]);
    setName("");
  }

  async function suggest() {
    setNote("");
    try {
      const group: EntityGroup = await api.suggestGroup(analysisId);
      const known = new Set(entities.map((e) => e.id));
      const added = group.members
        .filter((m) => !known.has(slug(m.name)))
        .map((m) => ({
          id: slug(m.name),
          name: m.name,
          role: m.role,
          figures: {},
          suggested: true,
        }));
      onChange([...entities, ...added]);
      setNote(
        added.length
          ? `${group.source} proposed ${added.length}. ${group.coverage_note}`
          : `${group.source} added nothing new. ${group.coverage_note}`,
      );
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-500">
        Figures for {period || "the borrower's period"}, in the same unit as the spread
        above. Leave an entity&apos;s row blank if you do not have its statements: the memo
        will name it as one the consolidation could not include, rather than quietly
        totalling without it.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block text-ink-500">Entity</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Holdings Pte Ltd"
            className="w-56 rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-ink-500">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="rounded border border-ink-300 px-2 py-1.5"
          >
            {ROLES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={add}
          disabled={disabled || !name.trim()}
          className="rounded border border-regblue-600 px-3 py-1.5 text-xs font-semibold text-regblue-600 disabled:opacity-40"
        >
          Add to the group
        </button>
        <button
          type="button"
          onClick={suggest}
          disabled={disabled || !analysisId}
          className="rounded border border-ink-300 px-3 py-1.5 text-xs text-ink-600 disabled:opacity-40"
          title="Ask a public register who else is in this group"
        >
          Suggest from the register
        </button>
      </div>

      {note ? <p className="text-xs text-ink-500">{note}</p> : null}

      {entities.length ? (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full min-w-[42rem] text-sm">
            <caption className="sr-only">
              Group entities, one row each, with the figures the analyst supplied
            </caption>
            <thead>
              <tr className="border-b border-ink-200 text-left text-ink-500">
                <th scope="col" className="py-1 pr-3 font-medium">Entity</th>
                {LINES.map((line) => (
                  <th key={line.code} scope="col" className="py-1 pr-2 font-medium">
                    {line.label}
                  </th>
                ))}
                <th scope="col" className="py-1 font-medium">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {entities.map((entity, index) => (
                <tr key={entity.id} className="border-b border-ink-100">
                  <th scope="row" className="py-1 pr-3 text-left font-normal text-ink-700">
                    {entity.name}
                    <span className="block text-[10px] uppercase tracking-wide text-ink-400">
                      {entity.role.replace(/_/g, " ")}
                      {entity.suggested ? " · suggested" : ""}
                    </span>
                  </th>
                  {LINES.map((line) => (
                    <td key={line.code} className="py-1 pr-2">
                      <input
                        inputMode="decimal"
                        aria-label={`${line.label} for ${entity.name}`}
                        value={entity.figures[line.code] ?? ""}
                        onChange={(e) => {
                          const next = [...entities];
                          next[index] = {
                            ...entity,
                            figures: { ...entity.figures, [line.code]: e.target.value },
                          };
                          onChange(next);
                        }}
                        className="w-20 rounded border border-ink-300 px-1.5 py-1 text-right font-mono tabular-nums"
                      />
                    </td>
                  ))}
                  <td className="py-1">
                    <button
                      type="button"
                      onClick={() => onChange(entities.filter((_, i) => i !== index))}
                      className="text-xs text-ink-400 underline"
                    >
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {entities.length ? (
        <EliminationRow
          eliminations={eliminations}
          onChange={onEliminationsChange}
          period={period}
        />
      ) : null}
    </div>
  );
}

/**
 * Intercompany amounts to take out, each saying what it is and between whom.
 *
 * Shown on the memo rather than netted away: a group whose revenue halves on consolidation
 * is telling the reader something important about how it trades with itself.
 */
function EliminationRow({
  eliminations,
  onChange,
  period,
}: {
  eliminations: Elimination[];
  onChange: (next: Elimination[]) => void;
  period: string;
}) {
  const [code, setCode] = useState<LineItemCode>("revenue");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");

  function add() {
    const value = Number(amount.trim());
    if (!Number.isFinite(value) || !amount.trim() || !reason.trim()) return;
    onChange([
      ...eliminations,
      { code, period, amount: value, between: "", reason: reason.trim() },
    ]);
    setAmount("");
    setReason("");
  }

  return (
    <div className="rounded border border-ink-200 bg-white p-2">
      <span className="mb-1 block text-xs font-semibold text-ink-700">
        Intercompany eliminations
      </span>
      <div className="flex flex-wrap items-end gap-2">
        <select
          aria-label="Line to eliminate from"
          value={code}
          onChange={(e) => setCode(e.target.value as LineItemCode)}
          className="rounded border border-ink-300 px-2 py-1 text-sm"
        >
          {LINES.map((line) => (
            <option key={line.code} value={line.code}>
              {line.label}
            </option>
          ))}
        </select>
        <input
          inputMode="decimal"
          aria-label="Amount to eliminate"
          placeholder="amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="w-24 rounded border border-ink-300 px-1.5 py-1 text-right font-mono tabular-nums"
        />
        <input
          aria-label="Why this is eliminated"
          placeholder="why (e.g. management fee)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-56 rounded border border-ink-300 px-1.5 py-1 text-sm"
        />
        <button
          type="button"
          onClick={add}
          disabled={!amount.trim() || !reason.trim()}
          className="rounded border border-ink-300 px-2 py-1 text-xs text-ink-600 disabled:opacity-40"
        >
          Eliminate
        </button>
      </div>
      {eliminations.length ? (
        <ul className="mt-1 text-xs text-ink-600">
          {eliminations.map((e, i) => (
            <li key={`${e.code}-${i}`}>
              {e.code.replace(/_/g, " ")} −{e.amount} · {e.reason}{" "}
              <button
                type="button"
                onClick={() => onChange(eliminations.filter((_, j) => j !== i))}
                className="text-ink-400 underline"
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** The period the group is consolidated for: the borrower's own latest. */
export function periodOf(spread: FinancialSpread): string {
  const periods: Period[] = spread.periods;
  return periods.length ? periods[periods.length - 1].label : "";
}

/**
 * The drafts as the build endpoint takes them.
 *
 * An entity with no figures contributes no spread, which is what puts it in
 * `entities_without_figures` on the memo instead of silently vanishing from the group.
 * Every figure is `user_entered` — the analyst typed it, so it is theirs — which is also
 * what makes each entity spread confirmed by construction.
 */
export function groupBody(
  entities: GroupEntityDraft[],
  eliminations: Elimination[],
  borrowerSpread: FinancialSpread,
  confirmedBy: string,
) {
  const period = periodOf(borrowerSpread);
  const entity_spreads: Record<string, FinancialSpread> = {};
  for (const entity of entities) {
    const items = Object.entries(entity.figures)
      .filter(([, raw]) => (raw ?? "").trim() !== "" && Number.isFinite(Number(raw)))
      .map(([code, raw]) => ({
        code: code as LineItemCode,
        period,
        value: Number(raw),
        currency: borrowerSpread.currency,
        provenance: "user_entered" as const,
        citations: [],
      }));
    if (!items.length) continue;
    entity_spreads[entity.id] = {
      borrower_id: entity.id,
      periods: [{ label: period, ends_on: "", months: 12, audited: false }],
      items,
      currency: borrowerSpread.currency,
      unit: borrowerSpread.unit,
      confirmed_by: confirmedBy || "analyst",
    };
  }
  return {
    related_entities: entities.map((e) => ({
      id: e.id,
      name: e.name,
      role: e.role,
      ownership_pct: null,
      jurisdiction: "",
      provenance: e.suggested ? "vendor" : "user_entered",
    })),
    entity_spreads,
    eliminations: eliminations.map((e) => ({ ...e, period })),
  };
}
