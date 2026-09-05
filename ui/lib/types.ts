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
  | "management_accounts"
  | "filing"
  | "tax_return"
  | "bank_statement"
  | "debt_schedule"
  | "ar_ap_aging"
  | "borrowing_base_certificate"
  | "rent_roll"
  | "operating_statement"
  | "loan_agreement"
  | "covenant_certificate"
  | "valuation"
  | "policy_pack"
  | "prior_memo"
  | "rm_note"
  | "exposure_snapshot"
  | "projections"
  | "registry_document"
  | "analyst_spread"
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

/**
 * One figure extraction proposed, with where it says it read it.
 *
 * Never a `LineItem`: its provenance is `extracted`, which the backend's spread type
 * refuses, so nothing on this shape can reach a ratio. Turning it into a figure the
 * engines compute from is what the confirm step does, and it needs a person.
 */
export interface CandidateLineItem {
  code: LineItemCode;
  period: string;
  value: number;
  currency: string;
  document_id: string;
  page: number | null;
  quote: string;
  confidence: number;
  provenance: Provenance;
}

export interface SpreadCandidate {
  borrower_id: string;
  periods: Period[];
  items: CandidateLineItem[];
  currency: string;
  unit: string;
  extractor: string;
  extractor_version: string;
  extracted_at: string;
}

/** The analyst's verdict on one proposed figure. */
export interface SpreadDecision {
  /** `keep` accepts it as read, `reject` throws it out, `adjust` replaces the value. */
  verdict: "keep" | "reject" | "adjust";
  /** Only for `adjust`, and required then: the record a committee asks about. */
  value?: string;
  reason?: string;
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
export interface StoredDocument {
  id: string;
  filename: string;
  doc_type: DocType;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  pages: number;
  /** The uploader's own statement of how current this document is; never inferred. */
  declared_as_of: string;
  uploaded_at: string;
  uploaded_by: string;
  third_party_sourced: boolean;
}

export interface AnalysisManifest {
  analysis_id: string;
  borrower_id: string;
  /** Display only; the id governs every entitlement check. */
  borrower_name: string;
  documents: StoredDocument[];
  created_at: string;
  /** When the evidence behind this analysis is deleted. Printed, not buried. */
  expires_at: string | null;
  created_by: string;
  retention_note: string;
}

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
  /** Reconciliations the credit file did not survive. */
  tie_out: TieOutFinding[];
  /** Breaches of the bank's OWN uploaded limits, measured arithmetically. */
  policy_exceptions: PolicyException[];
  policy_version: string;
  /** A grade the service PROPOSES from the bank's scorecard. Never one of record. */
  rating: RiskRatingProposal | null;
  /** Whose cash actually services this debt. */
  related_entities: RelatedEntity[];
  guarantors: Guarantor[];
  global_cash_flow: GlobalCashFlow | null;
  /** How far the coverage can fall before the covenant breaks. */
  scenarios: ScenarioResult[];
  /** How fully the drafter believed the evidence supported the memo (0.0-1.0). */
  confidence: number;
  caveats: string[];
  questions_for_client: string[];
  /** Exactly which uploaded files this memo was assessed on. */
  manifest: AnalysisManifest | null;
}

export interface TieOutFinding {
  check: string;
  severity: Severity;
  detail: string;
  expected: number | null;
  actual: number | null;
  document_id: string;
  page: number | null;
  period: string;
}

export interface PolicyException {
  rule_id: string;
  description: string;
  measured: number | null;
  limit: number | null;
  operator: string;
  severity: Severity;
  waiver_authority: string;
  period: string;
  detail: string;
  citation: string;
}

export interface RatingDriver {
  name: string;
  measured: number | null;
  band: string;
  points: number;
  weight: number;
  detail: string;
}

export interface RiskRatingProposal {
  obligor_grade: string;
  score: number;
  drivers: RatingDriver[];
  scorecard_version: string;
  definitions_url: string;
  rationale: string;
  facility_grade: string;
}

export interface RelatedEntity {
  id: string;
  name: string;
  role: string;
  ownership_pct: number | null;
  jurisdiction: string;
  provenance: Provenance;
}

export interface Guarantor {
  entity_id: string;
  name: string;
  is_personal: boolean;
  support_amount: number | null;
  currency: string;
  limited: boolean;
  reliance: string;
}

export interface EntityContribution {
  entity_id: string;
  entity_name: string;
  role: string;
  value: number;
}

export interface Elimination {
  code: LineItemCode;
  period: string;
  amount: number;
  between: string;
  reason: string;
}

export interface GlobalCashFlowLine {
  code: LineItemCode;
  period: string;
  total: number;
  contributions: EntityContribution[];
  eliminations: Elimination[];
}

export interface GlobalCashFlow {
  periods: string[];
  lines: GlobalCashFlowLine[];
  entities: RelatedEntity[];
  /** The field that keeps the calculation honest: who could not be included. */
  entities_without_figures: string[];
  currency: string;
  complete: boolean;
}

/** A public register's view of who else is in the group. Suggestions, never figures. */
/** One thing a public-web search found. Carries no number, and that is the mechanism. */
export interface WebEvidence {
  title: string;
  url: string;
  snippet: string;
  retrieved_at: string;
  provenance: Provenance;
}

/**
 * What a search found, for the analyst who ran it and nobody else.
 *
 * Never written into a memo, never exported. `search_suggestions` are the chips Google
 * requires rendered verbatim beside grounded results.
 */
export interface MarketContext {
  query: string;
  purpose: string;
  evidence: WebEvidence[];
  search_suggestions: string[];
  retrieved_at: string;
  provider: string;
  /** The search ran and returned nothing — not the same as it could not run. */
  found_nothing: boolean;
}

export interface EntityGroup {
  subject: RelatedEntity;
  members: RelatedEntity[];
  source: string;
  as_of: string;
  quality: "exact" | "strong" | "ambiguous";
  /** Not the same as an empty members list: the company itself reported no parent. */
  register_reports_no_parent: boolean;
  /** What the register cannot see, which an empty answer is often really about. */
  coverage_note: string;
  candidates: string[];
  found_nothing: boolean;
}

export interface ScenarioResult {
  scenario_id: string;
  scenario_name: string;
  formula_id: string;
  period: string;
  base_value: number | null;
  stressed_value: number | null;
  threshold: number | null;
  passes: boolean | null;
  /** A severity multiple of the scenario: 2.0 means it takes twice the shock. */
  breaks_at: number | null;
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
