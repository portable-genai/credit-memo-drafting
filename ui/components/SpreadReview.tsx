"use client";

import { useState } from "react";
import { analysisDocumentUrl } from "@/lib/api";
import type {
  CandidateLineItem,
  LineItemCode,
  SpreadCandidate,
  SpreadDecision,
} from "@/lib/types";

const LABELS: Record<string, string> = {
  revenue: "Revenue",
  ebitda: "EBITDA",
  ebit: "EBIT",
  net_income: "Net income",
  depreciation_amortisation: "Depreciation & amortisation",
  interest_expense: "Interest expense",
  tax_expense: "Tax expense",
  capex: "Capital expenditure",
  lease_expense: "Lease expense",
  current_assets: "Current assets",
  current_liabilities: "Current liabilities",
  inventory: "Inventory",
  cash: "Cash",
  total_assets: "Total assets",
  total_debt: "Total debt",
  total_equity: "Total equity",
  intangible_assets: "Intangible assets",
  scheduled_debt_service: "Scheduled debt service",
};

function slotKey(item: CandidateLineItem): string {
  return `${item.code}|${item.period}`;
}

/**
 * What the extractor read, put in front of the person who has to stand behind it.
 *
 * The panel is deliberately not a spread. Every row here is `extracted`, which the
 * backend's spread type refuses, so nothing on this screen can reach a ratio: the only
 * route runs through the Confirm button, and the backend attributes that to the verified
 * principal rather than to anything this console sends.
 *
 * Each row shows the quote the extractor says it took the figure from, and links to the
 * page it came from. That is the check worth making and the cheapest one available: a
 * reader who can see "EBITDA for the year was 18.0" beside the number knows in a second
 * whether the model read the right row, and nobody downstream can ever tell.
 */
export function SpreadReview({
  analysisId,
  candidate,
  decisions,
  onChange,
}: {
  analysisId: string;
  candidate: SpreadCandidate;
  decisions: Record<string, SpreadDecision>;
  onChange: (next: Record<string, SpreadDecision>) => void;
}) {
  const [openQuote, setOpenQuote] = useState<string>("");

  function decisionFor(item: CandidateLineItem): SpreadDecision {
    return decisions[slotKey(item)] ?? { verdict: "keep" };
  }

  function set(item: CandidateLineItem, next: SpreadDecision): void {
    onChange({ ...decisions, [slotKey(item)]: next });
  }

  const kept = candidate.items.filter((i) => decisionFor(i).verdict !== "reject").length;

  return (
    <div className="space-y-2">
      <p className="text-xs text-ink-500">
        {candidate.items.length} figures read from your documents by{" "}
        <span className="font-mono">{candidate.extractor_version || candidate.extractor}</span>.
        Nothing here is used until you confirm it: these are the extractor&apos;s reading, not
        yet anybody&apos;s figures. Keeping {kept} of {candidate.items.length}.
      </p>
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full min-w-[42rem] text-sm">
          <caption className="sr-only">
            Extracted figures awaiting confirmation, one row per figure
          </caption>
          <thead>
            <tr className="border-b border-ink-200 text-left text-ink-500">
              <th scope="col" className="py-1 pr-3 font-medium">Line</th>
              <th scope="col" className="py-1 pr-3 font-medium">Period</th>
              <th scope="col" className="py-1 pr-3 font-medium">Read as</th>
              <th scope="col" className="py-1 pr-3 font-medium">Source</th>
              <th scope="col" className="py-1 pr-3 font-medium">Your call</th>
            </tr>
          </thead>
          <tbody>
            {candidate.items.map((item) => {
              const key = slotKey(item);
              const decision = decisionFor(item);
              const rejected = decision.verdict === "reject";
              return (
                <tr
                  key={key}
                  className={`border-b border-ink-100 align-top ${rejected ? "opacity-50" : ""}`}
                >
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-700">
                    {LABELS[item.code] ?? item.code}
                  </th>
                  <td className="py-1.5 pr-3 text-ink-700">{item.period}</td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                    {rejected ? <s>{item.value}</s> : item.value}
                  </td>
                  <td className="py-1.5 pr-3">
                    <button
                      type="button"
                      onClick={() => setOpenQuote(openQuote === key ? "" : key)}
                      aria-expanded={openQuote === key}
                      className="text-xs text-regblue-600 underline"
                    >
                      {openQuote === key ? "Hide the quote" : "Show the quote"}
                    </button>
                    {openQuote === key ? (
                      <div className="mt-1 max-w-xs rounded bg-ink-50 p-2 text-xs text-ink-700">
                        <q>{item.quote || "the extractor recorded no quote"}</q>
                        {item.document_id ? (
                          <p className="mt-1">
                            <a
                              href={analysisDocumentUrl(analysisId, item.document_id, item.page)}
                              target="_blank"
                              rel="noreferrer"
                              className="text-regblue-600 underline"
                            >
                              Open {item.page ? `page ${item.page}` : "the document"}
                            </a>
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-3">
                    <div className="flex flex-wrap items-center gap-1">
                      {(["keep", "adjust", "reject"] as const).map((verdict) => (
                        <label key={verdict} className="text-xs">
                          <input
                            type="radio"
                            name={`verdict-${key}`}
                            checked={decision.verdict === verdict}
                            onChange={() =>
                              set(item, { ...decision, verdict })
                            }
                            className="mr-1"
                          />
                          {verdict}
                        </label>
                      ))}
                    </div>
                    {decision.verdict === "adjust" ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        <input
                          inputMode="decimal"
                          aria-label={`Adjusted value for ${LABELS[item.code] ?? item.code}, ${item.period}`}
                          placeholder={String(item.value)}
                          value={decision.value ?? ""}
                          onChange={(e) => set(item, { ...decision, value: e.target.value })}
                          className="w-24 rounded border border-ink-300 px-1.5 py-1 text-right font-mono tabular-nums"
                        />
                        <input
                          aria-label={`Reason for adjusting ${LABELS[item.code] ?? item.code}, ${item.period}`}
                          placeholder="why (required)"
                          value={decision.reason ?? ""}
                          onChange={(e) => set(item, { ...decision, reason: e.target.value })}
                          className="w-56 rounded border border-ink-300 px-1.5 py-1 text-sm"
                        />
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export interface RejectedSlot {
  code: LineItemCode;
  period: string;
}

export interface AdjustmentBody {
  code: LineItemCode;
  period: string;
  before: number | null;
  after: number;
  reason: string;
}

export interface ConfirmBody {
  rejected: RejectedSlot[];
  adjustments: AdjustmentBody[];
}

/**
 * The decisions as the confirm endpoint takes them, or the sentence that stops the send.
 *
 * An adjustment with no reason is caught here rather than at the API, so the analyst is
 * told WHICH row needs a reason instead of receiving a 422 about the request as a whole.
 * The service refuses it too; this only makes the refusal actionable.
 */
export function confirmBody(
  candidate: SpreadCandidate,
  decisions: Record<string, SpreadDecision>,
): { body: ConfirmBody; error: string } {
  const rejected: RejectedSlot[] = [];
  const adjustments: AdjustmentBody[] = [];
  for (const item of candidate.items) {
    const decision = decisions[slotKey(item)] ?? { verdict: "keep" };
    if (decision.verdict === "reject") {
      rejected.push({ code: item.code, period: item.period });
      continue;
    }
    if (decision.verdict !== "adjust") continue;
    const raw = (decision.value ?? "").trim();
    const value = Number(raw);
    const label = LABELS[item.code] ?? item.code;
    if (raw === "" || !Number.isFinite(value)) {
      return {
        body: { rejected, adjustments },
        error: `${label} (${item.period}) is marked adjusted but has no new figure.`,
      };
    }
    if (!(decision.reason ?? "").trim()) {
      return {
        body: { rejected, adjustments },
        error:
          `${label} (${item.period}) is adjusted but says no reason. A committee will ` +
          "ask what changed and why, so the service requires one.",
      };
    }
    adjustments.push({
      code: item.code,
      period: item.period,
      before: item.value,
      after: value,
      reason: (decision.reason ?? "").trim(),
    });
  }
  return { body: { rejected, adjustments }, error: "" };
}
