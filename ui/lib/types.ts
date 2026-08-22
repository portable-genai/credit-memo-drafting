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
}

// --------------------------------------------------------------------------- //
// Governance / health
// --------------------------------------------------------------------------- //
export interface HealthStatus {
  status: string;
  profile: string;
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
