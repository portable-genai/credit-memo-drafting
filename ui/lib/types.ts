/**
 * TypeScript mirrors of the B2 domain dataclasses.
 *
 * Source of truth: `src/credit_memo/domain/models.py`.
 * The backend serialises dataclasses with `domain/serialization.to_jsonable`
 * (SPEC §5): dataclass field names are preserved (snake_case) and every enum is
 * rendered as its `.value` string. These types follow that contract exactly.
 */

// --------------------------------------------------------------------------- //
// Borrower & financial inputs
// --------------------------------------------------------------------------- //
export interface Borrower {
  id: string;
  name: string;
  sector: string;
  jurisdiction: string;
}

/**
 * Where a value came from, which is what decides whether an engine was allowed to
 * consume it. Mirrors `domain/kernel.Provenance`. The console renders this as a glyph
 * plus a word, never as colour alone: "computed" and "extracted" must be distinguishable
 * to a reader who cannot tell green from amber.
 */
export type Provenance =
  | "user_entered"
  | "extracted"
  | "confirmed"
  | "computed"
  | "model_drafted"
  | "web_grounded"
  | "vendor";

export type DocType =
  | "financial_statement"
  | "filing"
  | "loan_agreement"
  | "covenant_certificate"
  | "other";

export interface FinancialMetric {
  name: string;
  value: number;
  period: string;
  currency: string;
}

// --------------------------------------------------------------------------- //
// Citation
// --------------------------------------------------------------------------- //
export type SourceType = "filing" | "policy" | "peer_data";

export interface Citation {
  source_id: string;
  source_type: SourceType;
  title: string;
  url: string;
  page: number | null;
  snippet: string;
  score: number | null;
}

// --------------------------------------------------------------------------- //
// Covenants
// --------------------------------------------------------------------------- //
export type CovenantType =
  | "leverage"
  | "dscr"
  | "interest_cover"
  | "current_ratio"
  | "min_ebitda"
  | "max_capex"
  | "tangible_net_worth"
  | "other";

export type CovenantOperator = "<=" | "<" | ">=" | ">" | "==";

export type CovenantStatus = "compliant" | "at_risk" | "breach";

export interface Covenant {
  type: CovenantType;
  description: string;
  threshold: number;
  operator: CovenantOperator;
  current_value: number | null;
  status: CovenantStatus;
  period: string;
  citations: Citation[];
  /** The engine's own measurement, when the confirmed spread supported one. */
  measured: Ratio | null;
  /** What the extraction claimed, kept even when the engine's figure was used. */
  reported_value: number | null;
  value_provenance: Provenance;
}

// --------------------------------------------------------------------------- //
// The spread and the ratio engine
// --------------------------------------------------------------------------- //
export type LineItemCode =
  | "revenue"
  | "ebitda"
  | "ebit"
  | "net_income"
  | "depreciation_amortisation"
  | "interest_expense"
  | "tax_expense"
  | "capex"
  | "lease_expense"
  | "current_assets"
  | "current_liabilities"
  | "inventory"
  | "cash"
  | "total_assets"
  | "total_debt"
  | "total_equity"
  | "intangible_assets"
  | "scheduled_debt_service";

export interface Period {
  label: string;
  ends_on: string;
  months: number;
  audited: boolean;
}

export interface LineItem {
  code: LineItemCode;
  period: string;
  value: number;
  currency: string;
  provenance: Provenance;
  citations: Citation[];
}

export interface FinancialSpread {
  borrower_id: string;
  periods: Period[];
  items: LineItem[];
  currency: string;
  unit: string;
  confirmed_by: string;
}

export interface RatioInput {
  code: LineItemCode;
  period: string;
  value: number;
  coefficient: number;
  side: "numerator" | "denominator";
}

export interface Ratio {
  formula_id: string;
  name: string;
  period: string;
  /** Null when an operand was missing; `reason_missing` then says which. */
  value: number | null;
  unit: string;
  higher_is_better: boolean;
  inputs: RatioInput[];
  definition: string;
  reason_missing: string;
  provenance: Provenance;
}

// --------------------------------------------------------------------------- //
// The credit request (the ask the memo answers)
// --------------------------------------------------------------------------- //
export type MemoKind =
  | "new_facility"
  | "renewal"
  | "annual_review"
  | "interim_review"
  | "rating_action"
  | "pre_screen"
  | "decline";

export type LoanType =
  | "ci_term"
  | "sme"
  | "cre_investor"
  | "sponsor_backed"
  | "other";

export type FacilityType =
  | "term_loan"
  | "revolving_credit"
  | "overdraft"
  | "trade_line"
  | "guarantee"
  | "other";

export interface Facility {
  id: string;
  facility_type: FacilityType;
  amount: number;
  currency: string;
  tenor_months: number;
  purpose: string;
  repayment_source: string;
  security: string;
  /** Recorded from the RM and never assessed: pricing is out of scope (SPEC §1). */
  pricing_note: string;
}

export interface FundingLine {
  label: string;
  amount: number;
  currency: string;
}

export interface SourcesAndUses {
  sources: FundingLine[];
  uses: FundingLine[];
  total_sources: number;
  total_uses: number;
  imbalance: number;
}

export interface CreditRequest {
  kind: MemoKind;
  loan_type: LoanType;
  facilities: Facility[];
  sources_and_uses: SourcesAndUses;
  purpose: string;
  notes: string;
  total_amount: number;
}

// --------------------------------------------------------------------------- //
// Risk flags
// --------------------------------------------------------------------------- //
export type Severity = "low" | "medium" | "high" | "critical";

export type RiskCategory =
  | "leverage"
  | "liquidity"
  | "profitability"
  | "governance"
  | "sector"
  | "concentration"
  | "other";

export interface RiskFlag {
  category: RiskCategory;
  severity: Severity;
  detail: string;
  citations: Citation[];
}

// --------------------------------------------------------------------------- //
// Peer comparison
// --------------------------------------------------------------------------- //
export interface PeerMetric {
  peer_name: string;
  metric: string;
  value: number;
}

export interface PeerComparison {
  metric: string;
  borrower_value: number;
  peer_median: number;
  percentile: number;
  delta_to_median: number;
  peers: PeerMetric[];
}

// --------------------------------------------------------------------------- //
// The credit memo (the bundled top-level artifact)
// --------------------------------------------------------------------------- //
export interface CreditMemo {
  borrower: Borrower;
  summary: string;
  financial_metrics: FinancialMetric[];
  covenants: Covenant[];
  risk_flags: RiskFlag[];
  peer_comparison: PeerComparison[];
  recommendation_rationale: string;
  citations: Citation[];
  requires_human_review: boolean;
  generated_at: string;
  request: CreditRequest | null;
  spreads: FinancialSpread[];
  ratios: Ratio[];
  /** How fully the drafter believed the evidence supported the memo (0.0-1.0). */
  confidence: number;
  caveats: string[];
  questions_for_client: string[];
}

// --------------------------------------------------------------------------- //
// Governance / health
// --------------------------------------------------------------------------- //
export interface HealthStatus {
  status: string;
  profile: string;
  // Provenance the banner states on every page: where the runtime sits and which model
  // answers. Both come from the service; nothing in the console infers either.
  runtime: string;
  generator_model: string;
  region: string;
}

/** A guardrail-blocked envelope the API returns instead of a memo. */
export interface BlockedEnvelope {
  blocked: true;
  requires_human_review: boolean;
  detail: string;
  reason: string;
}

export function isBlocked(value: unknown): value is BlockedEnvelope {
  return (
    !!value &&
    typeof value === "object" &&
    (value as Record<string, unknown>).blocked === true
  );
}
