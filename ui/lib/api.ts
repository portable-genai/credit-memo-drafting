/**
 * Typed fetch client for the B2 Credit-Memo / Underwriting Assistant FastAPI backend.
 *
 * Routes (SPEC §6):
 *   POST /v1/credit-memo  -> CreditMemo  (or a blocked envelope)
 *   POST /v1/covenants    -> { borrower_id, covenants: Covenant[] }
 *   POST /v1/risk-flags   -> { borrower_id, risk_flags: RiskFlag[] }
 *   GET  /healthz         -> { status, profile, region }
 */

import type {
  BlockedEnvelope,
  Borrower,
  Covenant,
  CreditMemo,
  HealthStatus,
  RiskFlag,
} from "./types";
import { ConfiguredEmptyError, readEnvValue } from "./env-setting.mjs";

// The API base is resolved in THREE states, not two.
//
// Reading `process.env.NEXT_PUBLIC_API_BASE || "<loopback default>"` hands a
// variable an operator DELIBERATELY EMPTIED the loopback default. That is a widening: the
// console then talks to a local API instead of the configured one, and `connect-src` is built
// from the same value, so the emptied deployment is byte-identical to one that never configured
// the variable at all. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the wrong value is frozen
// into the bundle and cannot be corrected by fixing the environment at start-up.
//
// Unset keeps the documented loopback default, which is what a laptop wants. Set-and-empty
// refuses, because an emptied value names nothing and the default is the more permissive branch.
const DEFAULT_API_BASE = "http://localhost:8093";
// The literal member expression is required: a bundler substitutes the public value
// only where it sees exactly this, and handing it `process.env` leaves the browser
// reading {} and silently taking the hard-coded loopback default.
const API_BASE_SETTING = readEnvValue(
  "NEXT_PUBLIC_API_BASE",
  process.env.NEXT_PUBLIC_API_BASE,
);
if (API_BASE_SETTING.isConfiguredEmpty) {
  throw new ConfiguredEmptyError(
    "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
      "so it cannot inherit the unset default (" + DEFAULT_API_BASE + "), which points this " +
      "console at a loopback API and widens connect-src to match. Unset it to take that " +
      "default deliberately, or give it the API origin this deployment should call.",
  );
}
export const API_BASE = (API_BASE_SETTING.hasValue ? API_BASE_SETTING.value : DEFAULT_API_BASE).replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// Dev-only identity selection. In LOCAL mode the backend resolves identity from the
// X-Dev-Persona header; in secure profiles this is ignored (identity comes from an IAP
// assertion injected by the platform). The persona picker sets this; requests attach the
// header only when a persona has been chosen.
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

function jsonHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  return headers;
}

export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

async function parseJsonOrThrow(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail =
        (parsed && (parsed.detail || parsed.message || parsed.error)) || text;
    } catch {
      /* keep raw text */
    }
    throw new ApiError(
      `${res.status} ${res.statusText}: ${detail || "request failed"}`,
      res.status,
      text,
    );
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError("Malformed JSON in response", res.status, text);
  }
}

export interface MemoRequestBody {
  borrower: Partial<Borrower> & { id: string; name: string };
  documents?: { id: string; doc_type?: string; uri?: string; title?: string }[];
}

export async function buildCreditMemo(
  body: MemoRequestBody,
  signal?: AbortSignal,
): Promise<CreditMemo | BlockedEnvelope> {
  const res = await fetch(`${API_BASE}/v1/credit-memo`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  return (await parseJsonOrThrow(res)) as CreditMemo | BlockedEnvelope;
}

export async function extractCovenants(
  body: MemoRequestBody,
  signal?: AbortSignal,
): Promise<Covenant[]> {
  const res = await fetch(`${API_BASE}/v1/covenants`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  const raw = await parseJsonOrThrow(res);
  const obj = (raw ?? {}) as Record<string, unknown>;
  return (obj.covenants as Covenant[]) ?? [];
}

export async function flagRisks(
  body: MemoRequestBody,
  signal?: AbortSignal,
): Promise<RiskFlag[]> {
  const res = await fetch(`${API_BASE}/v1/risk-flags`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  const raw = await parseJsonOrThrow(res);
  const obj = (raw ?? {}) as Record<string, unknown>;
  return (obj.risk_flags as RiskFlag[]) ?? [];
}

export async function healthz(signal?: AbortSignal): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/healthz`, { method: "GET", signal });
  return (await parseJsonOrThrow(res)) as HealthStatus;
}

export async function listPersonas(signal?: AbortSignal): Promise<Persona[]> {
  const res = await fetch(`${API_BASE}/v1/personas`, {
    method: "GET",
    headers: jsonHeaders(),
    signal,
  });
  return ((await parseJsonOrThrow(res)) as Persona[]) ?? [];
}

/** Where the borrower-document upload contract can be downloaded (CSV). */
export const DOCUMENT_UPLOAD_TEMPLATE_URL = `${API_BASE}/v1/documents/template`;

export interface DocumentUploadResult {
  document_id: string;
  borrower_id: string;
  chunks: number;
  detail: string;
}

/** Ingest one borrower document (PDF or text) into the governed evidence store. */
export async function uploadBorrowerDocument(
  file: File,
  borrowerId: string,
  title: string,
  docType = "financial_statement",
  signal?: AbortSignal,
): Promise<DocumentUploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("borrower_id", borrowerId);
  form.append("title", title);
  form.append("doc_type", docType);
  // No Content-Type header: the browser sets the multipart boundary itself.
  const headers: Record<string, string> = {};
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  const res = await fetch(`${API_BASE}/v1/documents`, {
    method: "POST",
    headers,
    body: form,
    signal,
  });
  return (await parseJsonOrThrow(res)) as DocumentUploadResult;
}

export const api = {
  buildCreditMemo,
  extractCovenants,
  flagRisks,
  healthz,
  listPersonas,
  setDevPersona,
  getDevPersona,
  uploadBorrowerDocument,
};
