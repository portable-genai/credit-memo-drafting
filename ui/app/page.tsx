"use client";

import { useEffect, useRef, useState } from "react";
import { api, DOCUMENT_UPLOAD_TEMPLATE_URL, uploadBorrowerDocument, type Persona } from "@/lib/api";
import {
  isBlocked,
  type BlockedEnvelope,
  type CreditMemo,
  type CreditRequest,
  type FinancialSpread,
} from "@/lib/types";
import { MemoView } from "@/components/MemoView";
import { emptyRequest, FacilityForm } from "@/components/FacilityForm";
import { emptySpread, SpreadGrid } from "@/components/SpreadGrid";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

/**
 * B2 demo console: enter a borrower and build a cited credit memo. This is a thin
 * presentation layer over the FastAPI backend (POST /v1/credit-memo); the backend
 * owns the grounded, audited, maker-checker-gated build pipeline (SPEC §5).
 *
 * Identity is server-verified: the UI never sends an actor. In the LOCAL profile the
 * backend resolves a seeded dev persona, so a "Demo identity" picker (below) lets a
 * demo/test choose one via the X-Dev-Persona header. Secure profiles resolve identity
 * from the IAP assertion, so the picker is hidden.
 */
export default function Home() {
  const [name, setName] = useState("Acme Manufacturing Pte Ltd (FICTIONAL)");
  const [sector, setSector] = useState("manufacturing");
  const [jurisdiction, setJurisdiction] = useState("SG");
  const [loading, setLoading] = useState(false);
  const [memo, setMemo] = useState<CreditMemo | null>(null);
  const [blocked, setBlocked] = useState<BlockedEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [request, setRequest] = useState<CreditRequest>(emptyRequest);
  const [spread, setSpread] = useState<FinancialSpread>(() =>
    emptySpread("acme-manufacturing-pte-ltd-fictional"),
  );
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await api.healthz();
        if (!cancelled && status.profile === "live") {
          // Live grounds on real SEC EDGAR records: suggest a real listed company
          // instead of the fictional local-profile sample borrower.
          setName("Apple Inc");
          setSector("technology hardware");
          setJurisdiction("US");
        }
        if (status.profile !== "local") return;
        const list = await api.listPersonas();
        if (cancelled || list.length === 0) return;
        setPersonas(list);
        setSelectedPersona(list[0].id);
        api.setDevPersona(list[0].id);
      } catch {
        // Persona picker is dev-only convenience; ignore lookup failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function onPersonaChange(id: string) {
    setSelectedPersona(id);
    api.setDevPersona(id);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setMemo(null);
    setBlocked(null);
    try {
      const borrowerId = name.toLowerCase().replace(/\s+/g, "-");
      const result = await api.buildCreditMemo({
        borrower: { id: borrowerId, name, sector, jurisdiction },
        request,
        // Only send a spread that has figures in it. An empty grid would be a spread
        // with no line items, which computes nothing and reads as though the engine
        // failed rather than as though nobody typed anything.
        spreads: spread.items.length
          ? [{ ...spread, borrower_id: borrowerId }]
          : [],
      });
      if (isBlocked(result)) {
        setBlocked(result);
      } else {
        setMemo(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      {!IS_EMBEDDED && personas.length > 0 ? (
        <div className="mb-6 rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
          <span className="mb-1 block text-sm font-semibold text-ink-900">
            Demo identity
          </span>
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Persona (local profile only)</span>
            <select
              value={selectedPersona}
              onChange={(e) => onPersonaChange(e.target.value)}
              className="w-full rounded border border-ink-300 px-2 py-1.5 sm:w-96"
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.subject} · {p.tenant}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      <form
        onSubmit={onSubmit}
        className="mb-6 grid gap-3 rounded-xl border border-ink-200 bg-white p-4 shadow-panel xl:grid-cols-3"
      >
        <label className="text-sm xl:col-span-3">
          <span className="mb-1 block text-ink-500">Borrower</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-ink-500">Sector</span>
          <input
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="w-full rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-ink-500">Jurisdiction</span>
          <input
            value={jurisdiction}
            onChange={(e) => setJurisdiction(e.target.value)}
            className="w-full rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <div className="xl:col-span-3">
          <span className="mb-2 block text-sm font-semibold text-ink-900">
            The ask
          </span>
          <FacilityForm request={request} onChange={setRequest} />
        </div>

        <div className="xl:col-span-3">
          <span className="mb-2 block text-sm font-semibold text-ink-900">
            Financial spread
          </span>
          <SpreadGrid spread={spread} onChange={setSpread} />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="self-end rounded bg-regblue-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50 xl:col-span-3 xl:justify-self-start"
        >
          {loading ? "Building..." : "Build credit memo"}
        </button>
      </form>

      <div className="mb-6 rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-ink-900">
            Upload borrower evidence
          </span>
          <a
            href={DOCUMENT_UPLOAD_TEMPLATE_URL}
            download
            className="text-xs font-medium text-regblue-600 underline decoration-dotted"
          >
            Download upload template
          </a>
        </div>
        <p className="mt-1 text-xs text-ink-500">
          For a borrower without public filings, upload its financial statements
          (PDF or text); the memo grounds on the uploaded evidence for the borrower
          named above.
        </p>
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            const file = fileRef.current?.files?.[0];
            if (!file || !uploadTitle.trim() || uploading) return;
            const borrowerId = name.toLowerCase().replace(/\s+/g, "-");
            setUploading(true);
            setUploadNote(null);
            uploadBorrowerDocument(file, borrowerId, uploadTitle.trim())
              .then((r) =>
                setUploadNote({
                  ok: true,
                  text: `Indexed ${r.chunks} passage${r.chunks === 1 ? "" : "s"} as ${r.document_id} for ${r.borrower_id}`,
                }),
              )
              .catch((err) =>
                setUploadNote({
                  ok: false,
                  text: err instanceof Error ? err.message : String(err),
                }),
              )
              .finally(() => setUploading(false));
          }}
        >
          <label className="min-w-64 flex-1 text-sm">
            <span className="mb-1 block text-ink-500">Document title</span>
            <input
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="2025 Audited Financial Statements"
              className="w-full rounded border border-ink-300 px-2 py-1.5"
            />
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.txt,application/pdf,text/plain"
            className="text-xs text-ink-500 file:mr-2 file:rounded file:border file:border-ink-300 file:bg-white file:px-2 file:py-1 file:text-xs"
          />
          <button
            type="submit"
            disabled={uploading || !uploadTitle.trim()}
            className="rounded bg-ink-900 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </form>
        {uploadNote ? (
          <p
            className={`mt-2 text-xs ${uploadNote.ok ? "text-emerald-600" : "text-red-600"}`}
          >
            {uploadNote.text}
          </p>
        ) : null}
      </div>

      <div aria-live="polite" aria-atomic="true">
        {loading ? (
          <p className="mb-4 text-sm text-ink-500">
            Building the memo: computing ratios, then drafting from the evidence.
          </p>
        ) : null}

        {error ? (
          <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <strong>Could not build the memo.</strong> {error}
            {/* 422 means the service had nothing to ground on. Point at the fix rather
                than restating the status code. */}
            {error.includes("422") || error.toLowerCase().includes("evidence") ? (
              <p className="mt-1">
                Upload the borrower&apos;s financial statements below, then build again.
                The memo grounds only on evidence you supply.
              </p>
            ) : null}
          </div>
        ) : null}

        {blocked ? (
          <div className="mb-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
            <strong>Blocked by guardrail.</strong> {blocked.detail} ({blocked.reason})
          </div>
        ) : null}
      </div>

      {memo ? <MemoView memo={memo} /> : null}
    </main>
  );
}
