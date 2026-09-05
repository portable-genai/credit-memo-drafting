"use client";

import type {
  CreditRequest,
  Facility,
  FacilityType,
  LoanType,
  MemoKind,
} from "@/lib/types";

const MEMO_KINDS: { value: MemoKind; label: string; hint: string }[] = [
  {
    value: "new_facility",
    label: "New facility",
    hint: "New money: the full assessment, leading with the ask",
  },
  {
    value: "renewal",
    label: "Renewal",
    hint: "Re-underwrite a maturing facility, leading with what changed",
  },
  {
    value: "annual_review",
    label: "Annual review",
    hint: "Confirm the grade against unchanged terms",
  },
  {
    value: "interim_review",
    label: "Interim review",
    hint: "Event-driven: a breach, a late certificate, an adverse item",
  },
  {
    value: "rating_action",
    label: "Rating action",
    hint: "Upgrade, downgrade or watchlist, with the drivers",
  },
  {
    value: "pre_screen",
    label: "Pre-screen",
    hint: "Is this bankable? Policy knockouts from a thin package",
  },
  { value: "decline", label: "Decline", hint: "Structured reasons, not free prose" },
];

const LOAN_TYPES: { value: LoanType; label: string }[] = [
  { value: "ci_term", label: "C&I term / working capital" },
  { value: "sme", label: "SME (bank-statement led)" },
  { value: "cre_investor", label: "Investor CRE" },
  { value: "sponsor_backed", label: "Sponsor-backed / leveraged" },
  { value: "other", label: "Other" },
];

const FACILITY_TYPES: FacilityType[] = [
  "term_loan",
  "revolving_credit",
  "overdraft",
  "trade_line",
  "guarantee",
  "other",
];

export function emptyRequest(): CreditRequest {
  return {
    kind: "new_facility",
    loan_type: "ci_term",
    facilities: [
      {
        id: "fac-1",
        facility_type: "term_loan",
        amount: 0,
        currency: "USD",
        tenor_months: 60,
        purpose: "",
        repayment_source: "",
        security: "",
        pricing_note: "",
      },
    ],
    sources_and_uses: {
      sources: [],
      uses: [],
      total_sources: 0,
      total_uses: 0,
      imbalance: 0,
    },
    purpose: "",
    notes: "",
    total_amount: 0,
  };
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-500">{label}</span>
      {children}
      {hint ? <span className="mt-0.5 block text-xs text-ink-400">{hint}</span> : null}
    </label>
  );
}

/**
 * The ask the memo answers.
 *
 * Without it the pipeline reasons about a borrower and its documents but never about a
 * credit request, and a memo cannot carry a DSCR against *proposed* debt service, an
 * approval condition or a policy exception. Everything here is analyst-declared, which
 * is why it is labelled as such wherever it reaches the memo.
 */
export function FacilityForm({
  request,
  onChange,
}: {
  request: CreditRequest;
  onChange: (next: CreditRequest) => void;
}) {
  const facility: Facility = request.facilities[0] ?? emptyRequest().facilities[0];
  const kindHint = MEMO_KINDS.find((k) => k.value === request.kind)?.hint ?? "";

  function setFacility(patch: Partial<Facility>): void {
    onChange({ ...request, facilities: [{ ...facility, ...patch }] });
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <Field label="Memo kind" hint={kindHint}>
        <select
          value={request.kind}
          onChange={(e) => onChange({ ...request, kind: e.target.value as MemoKind })}
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        >
          {MEMO_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Loan type">
        <select
          value={request.loan_type}
          onChange={(e) =>
            onChange({ ...request, loan_type: e.target.value as LoanType })
          }
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        >
          {LOAN_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Facility type">
        <select
          value={facility.facility_type}
          onChange={(e) =>
            setFacility({ facility_type: e.target.value as FacilityType })
          }
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        >
          {FACILITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </Field>

      <Field label={`Amount (${facility.currency}, millions)`}>
        <input
          inputMode="decimal"
          value={facility.amount || ""}
          onChange={(e) => setFacility({ amount: Number(e.target.value) || 0 })}
          className="w-full rounded border border-ink-300 px-2 py-1.5 text-right font-mono tabular-nums"
        />
      </Field>

      <Field label="Tenor (months)">
        <input
          inputMode="numeric"
          value={facility.tenor_months || ""}
          onChange={(e) => setFacility({ tenor_months: Number(e.target.value) || 0 })}
          className="w-full rounded border border-ink-300 px-2 py-1.5 text-right font-mono tabular-nums"
        />
      </Field>

      <Field label="Primary repayment source">
        <input
          value={facility.repayment_source}
          onChange={(e) => setFacility({ repayment_source: e.target.value })}
          placeholder="Operating cash flow"
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        />
      </Field>

      <Field label="Purpose" hint="What the money is for, in the borrower's terms">
        <input
          value={facility.purpose}
          onChange={(e) => setFacility({ purpose: e.target.value })}
          placeholder="Refinance existing term debt and fund plant expansion"
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        />
      </Field>

      <Field label="Security">
        <input
          value={facility.security}
          onChange={(e) => setFacility({ security: e.target.value })}
          placeholder="First charge over plant and equipment"
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        />
      </Field>

      <Field
        label="Pricing note"
        hint="Recorded from the RM and never assessed: pricing is out of scope"
      >
        <input
          value={facility.pricing_note}
          onChange={(e) => setFacility({ pricing_note: e.target.value })}
          placeholder="SORA + 250bp, as quoted"
          className="w-full rounded border border-ink-300 px-2 py-1.5"
        />
      </Field>
    </div>
  );
}
