"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DocType, InputChecklist as Checklist, LoanType, MemoKind } from "@/lib/types";

/** What each kind reads as in a sentence an analyst is being asked to act on. */
const DOC_LABEL: Record<string, string> = {
  financial_statement: "audited financial statements",
  management_accounts: "management accounts",
  filing: "a public filing",
  tax_return: "a tax return",
  bank_statement: "bank statements",
  debt_schedule: "a debt schedule",
  ar_ap_aging: "an AR / AP aging",
  borrowing_base_certificate: "a borrowing-base certificate",
  rent_roll: "a rent roll",
  operating_statement: "an operating statement (T-12)",
  loan_agreement: "the loan agreement",
  covenant_certificate: "a covenant compliance certificate",
  valuation: "a valuation",
  policy_pack: "the bank's credit policy pack",
  prior_memo: "the prior credit memo",
  rm_note: "an RM call report",
  exposure_snapshot: "an exposure snapshot",
  projections: "projections",
  registry_document: "a registry search",
  analyst_spread: "your own spread",
  other: "other evidence",
};

function label(kind: DocType): string {
  return DOC_LABEL[kind] ?? kind.replace(/_/g, " ");
}

function sentence(kinds: DocType[]): string {
  const parts = kinds.map(label);
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * What the memo kind being written needs, against what this analysis actually holds.
 *
 * This exists for one moment in the work: intake. The service already knew that a renewal
 * cannot say what changed without the memo being renewed, and it knew it at build time, which
 * is far too late to be useful. A renewal built without its prior memo is a new-facility memo
 * wearing a renewal's title, and the difference between learning that here and learning it
 * from a committee paper that cannot answer the committee's first question is the whole point.
 *
 * Nothing here is a block. A missing recommended document is said and the build goes ahead; a
 * missing required one is said louder. Refusing to proceed would put this panel in charge of a
 * judgement that belongs to the analyst.
 */
export function InputChecklistPanel({
  analysisId,
  kind,
  loanType,
}: {
  analysisId: string;
  kind: MemoKind;
  loanType: LoanType;
}) {
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!analysisId) return;
    const abort = new AbortController();
    (async () => {
      try {
        setChecklist(await api.analysisChecklist(analysisId, kind, loanType, abort.signal));
        setError("");
      } catch (err) {
        if (abort.signal.aborted) return;
        setChecklist(null);
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => abort.abort();
    // Re-asked whenever the analyst changes the kind or the loan type: both change what the
    // memo needs, and an answer about the kind that was selected a minute ago is worse than
    // no answer, because it reads as current.
  }, [analysisId, kind, loanType]);

  if (error) {
    return (
      <p
        data-panel="checklist-error"
        className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800"
      >
        Could not check this credit file against what a {kind.replace(/_/g, " ")} needs: {error}
      </p>
    );
  }
  if (!checklist) return null;

  const missing = checklist.missing_required;
  return (
    <div
      data-panel="input-checklist"
      data-kind={checklist.kind}
      data-missing-required={missing.length}
      data-compares-with-prior={checklist.compares_with_prior ? "yes" : "no"}
      className={`rounded-lg border p-3 text-sm ${
        missing.length ? "border-amber-300 bg-amber-50" : "border-green-300 bg-green-50"
      }`}
    >
      {missing.length ? (
        <p className="font-semibold text-amber-900">
          This credit file is missing {sentence(missing)}.
        </p>
      ) : (
        <p className="font-semibold text-green-900">
          Every document this kind of memo requires is in the credit file.
        </p>
      )}

      {/* The reason the prior memo is on the list, rather than leaving it to look like one
          more box. A reader who knows WHY a document is required can decide what to do about
          it missing; one who does not can only comply or ignore it. */}
      {checklist.compares_with_prior && missing.includes("prior_memo") ? (
        <p data-checklist="why-prior-memo" className="mt-1 text-xs text-amber-900">
          A {checklist.kind.replace(/_/g, " ")} leads with what changed, and that is measured
          against the memo being renewed. Without it this memo can still be built, and it will
          say plainly that nothing was compared against rather than implying nothing moved.
          Export the previous memo as JSON and add it above.
        </p>
      ) : null}

      <ul className="mt-2 space-y-0.5 text-xs">
        {checklist.required.map((doc) => (
          <li key={doc} data-required-doc={doc} data-held={missing.includes(doc) ? "no" : "yes"}>
            <span className={missing.includes(doc) ? "text-amber-900" : "text-green-900"}>
              {missing.includes(doc) ? "Missing" : "Held"}
            </span>{" "}
            <span className="text-ink-700">{label(doc)}</span>
            <span className="text-ink-400"> · required</span>
          </li>
        ))}
        {checklist.recommended.map((doc) => (
          <li
            key={doc}
            data-recommended-doc={doc}
            data-held={checklist.missing_recommended.includes(doc) ? "no" : "yes"}
          >
            <span className="text-ink-500">
              {checklist.missing_recommended.includes(doc) ? "Not supplied" : "Held"}
            </span>{" "}
            <span className="text-ink-700">{label(doc)}</span>
            <span className="text-ink-400"> · would improve it</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
