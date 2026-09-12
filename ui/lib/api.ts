/**
 * Typed fetch client for the B2 Credit-Memo / Underwriting Assistant FastAPI backend.
 *
 * Routes (SPEC §6):
 *   POST /v1/credit-memo  -> CreditMemo  (or a blocked envelope)
 *   POST /v1/covenants    -> { borrower_id, covenants: Covenant[] }
 *   POST /v1/risk-flags   -> { borrower_id, risk_flags: RiskFlag[] }
 *   GET  /healthz         -> { status, profile, runtime, generator_model, region }
 */

import type {
  AnalysisManifest,
  CommentList,
  MemoComment,
  MemoRevision,
  RevisionList,
  BlockedEnvelope,
  Borrower,
  Covenant,
  CreditMemo,
  CreditRequest,
  FinancialSpread,
  HealthStatus,
  LineItemCode,
  Period,
  EntityGroup,
  MarketContext,
  RiskFlag,
  SpreadCandidate,
} from "./types";
import { resolveApiBase } from "./api-base.mjs";
import { readEnvValue } from "./env-setting.mjs";

// The API base is resolved in ONE module, `lib/api-base.mjs`, because `lib/csp.mjs` must admit
// the same origin in `connect-src`. Two independent answers are how an unset variable once
// shipped a console whose own CSP blocked its first request.
//
// The literal member expression is required: a bundler substitutes the public value only where
// it sees exactly this, and handing it `process.env` leaves the browser reading {} and silently
// taking the loopback default. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the value is frozen
// into the bundle and cannot be corrected by fixing the environment at start-up.
export const API_BASE = resolveApiBase(
  readEnvValue("NEXT_PUBLIC_API_BASE", process.env.NEXT_PUBLIC_API_BASE),
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

/** The dev-persona header alone, for requests that carry no JSON body (uploads, downloads). */
function personaHeaders(): Record<string, string> {
  return devPersona ? { "X-Dev-Persona": devPersona } : {};
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
  /** The ask the memo answers, and the spread its engines compute from. */
  request?: CreditRequest;
  spreads?: FinancialSpread[];
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

/**
 * Open an analysis: upload the credit file and get back the manifest of what was
 * received, including the date its evidence is deleted.
 *
 * The files go up per analysis rather than into a library. That is what makes the user
 * responsible for freshness and able to see exactly what fed the memo, and it is why
 * every upload carries a `declared_as_of` the uploader states rather than one the
 * service guesses.
 */
export async function openAnalysis(
  borrowerId: string,
  files: { file: File; docType: string; asOf: string }[],
  signal?: AbortSignal,
  borrowerName = "",
): Promise<AnalysisManifest> {
  const form = new FormData();
  form.append("borrower_id", borrowerId);
  // Display only. The id governs the ACL and every entitlement check, so this cannot point
  // a build at a different borrower; it is here so the memo names the borrower the way the
  // analyst wrote it rather than by its slug.
  if (borrowerName) form.append("borrower_name", borrowerName);
  for (const entry of files) form.append("files", entry.file);
  form.append("doc_types", files.map((f) => f.docType).join(","));
  form.append("declared_as_of", files.map((f) => f.asOf).join(","));
  const headers: Record<string, string> = {};
  const persona = getDevPersona();
  if (persona) headers["X-Dev-Persona"] = persona;
  const res = await fetch(`${API_BASE}/v1/analyses`, {
    method: "POST",
    headers,
    body: form,
    signal,
  });
  return (await parseJsonOrThrow(res)) as AnalysisManifest;
}

/** Build the memo from evidence already in the analysis. */
export async function buildAnalysisMemo(
  analysisId: string,
  body: Pick<MemoRequestBody, "request" | "spreads">,
  signal?: AbortSignal,
): Promise<CreditMemo | BlockedEnvelope> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/build`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  return (await parseJsonOrThrow(res)) as CreditMemo | BlockedEnvelope;
}

/**
 * Ask the extractor to read the figures off the documents already in this analysis.
 *
 * What comes back is a PROPOSAL. Every item is `extracted`, which the backend's spread
 * type refuses, so no ratio can be computed from any of it until a person confirms.
 */
export async function extractSpread(
  analysisId: string,
  body: { document_ids?: string[]; periods?: Period[]; currency?: string; unit?: string } = {},
  signal?: AbortSignal,
): Promise<SpreadCandidate> {
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/spreads/extract`,
    { method: "POST", headers: jsonHeaders(), body: JSON.stringify(body), signal },
  );
  return (await parseJsonOrThrow(res)) as SpreadCandidate;
}

/**
 * Accept the candidate this analysis holds, and become the person who stands behind it.
 *
 * There is no actor in the body and no spread in it either: the backend confirms the
 * candidate it already stored, attributed to the verified principal. A console that could
 * post its own table could produce a "confirmed" spread nobody saw beside a document.
 */
export async function confirmSpread(
  analysisId: string,
  body: {
    rejected?: { code: LineItemCode; period: string }[];
    adjustments?: {
      code: LineItemCode;
      period: string;
      before: number | null;
      after: number;
      reason: string;
    }[];
  },
  signal?: AbortSignal,
): Promise<FinancialSpread> {
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/spreads/confirm`,
    { method: "POST", headers: jsonHeaders(), body: JSON.stringify(body), signal },
  );
  return (await parseJsonOrThrow(res)) as FinancialSpread;
}

/**
 * Ask a public register who else is in this borrower's group.
 *
 * A suggestion about who EXISTS, never a figure. The analyst still uploads each entity's
 * statements, and one they do not supply figures for is reported on the memo as an entity
 * the consolidation could not include. Off unless the deployment switched it on, because
 * the lookup sends the borrower's registered name outside the deploy region.
 */
export async function suggestGroup(
  analysisId: string,
  name = "",
  jurisdiction = "",
  signal?: AbortSignal,
): Promise<EntityGroup> {
  const query = new URLSearchParams();
  if (name) query.set("name", name);
  if (jurisdiction) query.set("jurisdiction", jurisdiction);
  const suffix = query.toString() ? `?${query}` : "";
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/group/suggestions${suffix}`,
    { method: "GET", headers: jsonHeaders(), signal },
  );
  return (await parseJsonOrThrow(res)) as EntityGroup;
}

/**
 * Public-web context on this borrower, for the analyst who asked and nobody else.
 *
 * Google's Service Specific Terms section 20(k) permit Grounded Results to be displayed
 * only to the End User who submitted the prompt. A memo is read by a checker, a committee
 * and later an examiner, so nothing from here is sent back to the server, written into
 * the memo or carried into an export. An analyst who wants one of these facts in the memo
 * types it and cites the URL, which makes it theirs.
 *
 * Off unless the deployment switched it on: the search leg leaves the deploy region and
 * is billed per query.
 */
export async function research(
  analysisId: string,
  query = "",
  purpose = "",
  signal?: AbortSignal,
): Promise<MarketContext> {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (purpose) params.set("purpose", purpose);
  const suffix = params.toString() ? `?${params}` : "";
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/research${suffix}`,
    { method: "GET", headers: jsonHeaders(), signal },
  );
  return (await parseJsonOrThrow(res)) as MarketContext;
}

/** Where one uploaded file can be read back, so a citation can open its page. */
export function analysisDocumentUrl(
  analysisId: string,
  documentId: string,
  page?: number | null,
): string {
  const base = `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/documents/${encodeURIComponent(documentId)}`;
  return page ? `${base}#page=${page}` : base;
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

/**
 * Rewrite one or more PROSE sections, and record who rewrote them.
 *
 * The service decides which sections are editable and says so in `listRevisions`, so the
 * console offers exactly those rather than keeping a list that can drift out of agreement
 * with the refusal. The figures are never among them: a memo whose leverage could be typed
 * over by hand would put a number in front of a committee that no formula produced.
 */
export async function amendMemo(
  analysisId: string,
  body: { sections: Record<string, string>; reason?: string; note?: string },
  signal?: AbortSignal,
): Promise<MemoRevision> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/memo`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  return (await parseJsonOrThrow(res)) as MemoRevision;
}

/** Every version, and whether the chain from the first to the last still holds. */
export async function listRevisions(
  analysisId: string,
  signal?: AbortSignal,
): Promise<RevisionList> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/revisions`, {
    method: "GET",
    headers: jsonHeaders(),
    signal,
  });
  return (await parseJsonOrThrow(res)) as RevisionList;
}

/**
 * Leave a note against one section of the memo as it stands right now.
 *
 * There is no author in the body: it is the server-verified principal, which is what a
 * committee asks about. The comment anchors to the current revision, so an edit three
 * versions later cannot silently re-point the objection at text its author never saw.
 */
export async function addComment(
  analysisId: string,
  body: { section: string; body: string },
  signal?: AbortSignal,
): Promise<MemoComment> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/comments`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  return (await parseJsonOrThrow(res)) as MemoComment;
}

/** Every note, with the ones whose text has moved on flagged rather than closed. */
export async function listComments(
  analysisId: string,
  signal?: AbortSignal,
): Promise<CommentList> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/comments`, {
    method: "GET",
    headers: jsonHeaders(),
    signal,
  });
  return (await parseJsonOrThrow(res)) as CommentList;
}

/** Close one comment, saying what was done about it rather than merely that it is closed. */
export async function resolveComment(
  analysisId: string,
  commentId: string,
  resolution: string,
  signal?: AbortSignal,
): Promise<MemoComment> {
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/comments/${encodeURIComponent(commentId)}/resolve`,
    { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ resolution }), signal },
  );
  return (await parseJsonOrThrow(res)) as MemoComment;
}

/** Which formats this deployment can actually produce, asked rather than assumed. */
export async function exportFormats(analysisId: string, signal?: AbortSignal): Promise<string[]> {
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/export/formats`,
    { method: "GET", headers: jsonHeaders(), signal },
  );
  const raw = (await parseJsonOrThrow(res)) as Record<string, unknown>;
  return ((raw?.formats as string[]) ?? []).slice();
}

/**
 * The committee pack as bytes, with the name to save it under.
 *
 * The filename is built here rather than read from `Content-Disposition`: that header is not
 * readable cross-origin unless the service exposes it, and a pack that downloads as
 * "download" is a pack somebody has to rename before circulating it.
 */
export async function exportMemo(
  analysisId: string,
  fmt: string,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(
    `${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}/export?fmt=${encodeURIComponent(fmt)}`,
    { method: "POST", headers: personaHeaders(), signal },
  );
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = (parsed && (parsed.detail || parsed.message)) || text;
    } catch {
      /* keep the raw text */
    }
    throw new ApiError(`${res.status} ${res.statusText}: ${detail}`, res.status, text);
  }
  return { blob: await res.blob(), filename: `credit-memo-${analysisId}.${fmt}` };
}

/**
 * Delete the analysis now, rather than waiting for the retention window.
 *
 * The memo dies with the evidence it was built from: there is no memo of record here, which
 * is what makes the retention promise something a user can act on rather than read about.
 */
export async function deleteAnalysis(analysisId: string, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE}/v1/analyses/${encodeURIComponent(analysisId)}`, {
    method: "DELETE",
    headers: personaHeaders(),
    signal,
  });
  if (!res.ok && res.status !== 404) {
    const text = await res.text();
    throw new ApiError(`${res.status} ${res.statusText}: ${text}`, res.status, text);
  }
}

export const api = {
  amendMemo,
  listRevisions,
  addComment,
  listComments,
  resolveComment,
  exportFormats,
  exportMemo,
  deleteAnalysis,
  openAnalysis,
  extractSpread,
  confirmSpread,
  suggestGroup,
  research,
  buildAnalysisMemo,
  analysisDocumentUrl,
  buildCreditMemo,
  extractCovenants,
  flagRisks,
  healthz,
  listPersonas,
  setDevPersona,
  getDevPersona,
  uploadBorrowerDocument,
};
