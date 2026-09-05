"use client";

import { useEffect, useState } from "react";
import { api, type Persona } from "@/lib/api";
import {
  isBlocked,
  type AnalysisManifest,
  type BlockedEnvelope,
  type CreditMemo,
  type CreditRequest,
  type Elimination,
  type FinancialSpread,
  type SpreadCandidate,
  type SpreadDecision,
} from "@/lib/types";
import { MemoView } from "@/components/MemoView";
import { emptyRequest, FacilityForm } from "@/components/FacilityForm";
import { emptySpread, SpreadGrid } from "@/components/SpreadGrid";
import { confirmBody, SpreadReview } from "@/components/SpreadReview";
import { groupBody, GroupPanel, type GroupEntityDraft } from "@/components/GroupPanel";
import { PublicContext } from "@/components/PublicContext";
import { DocumentPanel, type PendingDocument } from "@/components/DocumentPanel";

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
  const [documents, setDocuments] = useState<PendingDocument[]>([]);
  const [manifest, setManifest] = useState<AnalysisManifest | null>(null);
  const [stage, setStage] = useState("");
  const [request, setRequest] = useState<CreditRequest>(emptyRequest);
  const [spread, setSpread] = useState<FinancialSpread>(() =>
    emptySpread("acme-manufacturing-pte-ltd-fictional"),
  );
  // The extract -> review -> confirm path. `analysisId` is what makes it a path rather
  // than three unrelated calls: the analysis is opened once, and every later step names
  // it, so the figures confirmed are provably the ones read from the files uploaded.
  const [analysisId, setAnalysisId] = useState("");
  const [candidate, setCandidate] = useState<SpreadCandidate | null>(null);
  const [decisions, setDecisions] = useState<Record<string, SpreadDecision>>({});
  const [busy, setBusy] = useState("");
  // The group the analyst declares for THIS analysis. There is no standing ownership
  // graph, so an entity named here with no figures is reported on the memo as one the
  // consolidation could not include rather than quietly contributing nothing.
  const [groupEntities, setGroupEntities] = useState<GroupEntityDraft[]>([]);
  const [eliminations, setEliminations] = useState<Elimination[]>([]);

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

  function borrowerId(): string {
    return name.toLowerCase().replace(/\s+/g, "-");
  }

  /** Open the analysis once, and reuse it for every later step. */
  async function ensureAnalysis(): Promise<string> {
    if (analysisId) return analysisId;
    const opened = await api.openAnalysis(borrowerId(), documents, undefined, name);
    setManifest(opened);
    setAnalysisId(opened.analysis_id);
    return opened.analysis_id;
  }

  async function onExtract() {
    if (!documents.length) {
      setError(
        "Add the borrower's financial statements to the credit file first: there is " +
          "nothing to read the figures off.",
      );
      return;
    }
    setError(null);
    setBusy("Reading the figures off your documents");
    try {
      const id = await ensureAnalysis();
      const proposed = await api.extractSpread(id, { periods: spread.periods });
      setCandidate(proposed);
      setDecisions({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function onConfirm() {
    if (!candidate || !analysisId) return;
    const { body, error: invalid } = confirmBody(candidate, decisions);
    if (invalid) {
      setError(invalid);
      return;
    }
    setError(null);
    setBusy("Recording your confirmation");
    try {
      // The confirmed spread comes BACK from the service rather than being assembled
      // here. The copy the service returns is the one with a named confirmer on it, and
      // a console that assembled its own would be asserting figures nobody attributed.
      setSpread(await api.confirmSpread(analysisId, body));
      setCandidate(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!documents.length) {
      setError(
        "Add the borrower's documents to the credit file first. A memo is only ever built " +
          "on evidence you supply.",
      );
      return;
    }
    setLoading(true);
    setError(null);
    setMemo(null);
    setBlocked(null);
    try {
      const id = analysisId ? analysisId : (setStage("Uploading the credit file"), await ensureAnalysis());

      setStage("Reading the documents, computing the ratios, drafting the memo");
      const result = await api.buildAnalysisMemo(id, {
        request,
        ...groupBody(groupEntities, eliminations, spread, spread.confirmed_by),
        // Only send a spread that has figures in it. An empty grid computes nothing and
        // would read as though the engine failed rather than as though nobody typed
        // anything. A spread confirmed through the panel above is already stored against
        // this analysis, so sending nothing is what makes the service use that one.
        spreads:
          spread.items.length && !spread.confirmed_by
            ? [{ ...spread, borrower_id: borrowerId() }]
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
      setStage("");
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
            The credit file
          </span>
          <DocumentPanel
            pending={documents}
            onChange={setDocuments}
            manifest={manifest}
            disabled={loading}
          />
        </div>

        <div className="xl:col-span-3">
          <span className="mb-2 block text-sm font-semibold text-ink-900">
            The ask
          </span>
          <FacilityForm request={request} onChange={setRequest} />
        </div>

        <div className="xl:col-span-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-ink-900">Financial spread</span>
            <button
              type="button"
              onClick={onExtract}
              disabled={loading || busy !== "" || !documents.length}
              className="rounded border border-regblue-600 px-3 py-1 text-xs font-semibold text-regblue-600 disabled:opacity-40"
            >
              Extract from the documents
            </button>
          </div>

          {spread.confirmed_by ? (
            <p className="mb-2 rounded border border-green-300 bg-green-50 p-2 text-xs text-green-900">
              Confirmed by <strong>{spread.confirmed_by}</strong>. These are the figures the
              engines will compute from. Extract again to start over.
            </p>
          ) : null}

          {candidate ? (
            <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-3">
              <p className="mb-2 text-sm font-semibold text-amber-900">
                Not yet anybody&apos;s figures
              </p>
              <SpreadReview
                analysisId={analysisId}
                candidate={candidate}
                decisions={decisions}
                onChange={setDecisions}
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={busy !== ""}
                  className="rounded bg-regblue-600 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
                >
                  Confirm these figures
                </button>
                <button
                  type="button"
                  onClick={() => setCandidate(null)}
                  className="text-xs text-ink-500 underline"
                >
                  Discard and type them myself
                </button>
              </div>
            </div>
          ) : (
            <SpreadGrid
              spread={spread}
              onChange={setSpread}
              readOnly={spread.confirmed_by !== ""}
            />
          )}
        </div>

        <div className="xl:col-span-3">
          <span className="mb-2 block text-sm font-semibold text-ink-900">
            The group
          </span>
          <GroupPanel
            entities={groupEntities}
            onChange={setGroupEntities}
            eliminations={eliminations}
            onEliminationsChange={setEliminations}
            borrowerSpread={spread}
            analysisId={analysisId}
            disabled={loading || busy !== ""}
          />
        </div>

        {/* Deliberately its own panel, outside the memo. Grounded results may be shown
            only to the person who ran the search, so they must not be interspersed with
            the memo's own cited evidence — and a committee reading them beside the
            memo's sections would take them for evidence the bank stands behind. */}
        {analysisId ? (
          <div className="xl:col-span-3">
            <span className="mb-2 block text-sm font-semibold text-ink-900">
              Public context (analyst only)
            </span>
            <PublicContext
              analysisId={analysisId}
              borrower={name}
              disabled={loading || busy !== ""}
            />
          </div>
        ) : null}

        <button
          type="submit"
          disabled={loading}
          className="self-end rounded bg-regblue-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50 xl:col-span-3 xl:justify-self-start"
        >
          {loading ? "Building..." : "Build credit memo"}
        </button>
      </form>


      <div aria-live="polite" aria-atomic="true">
        {loading || busy ? (
          <p className="mb-4 text-sm text-ink-500">{busy || stage || "Working"}…</p>
        ) : null}

        {error ? (
          <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <strong>Could not build the memo.</strong> {error}
            {/* 422 means the service had nothing to ground on. Point at the fix rather
                than restating the status code. */}
            {error.toLowerCase().includes("evidence") ? (
              <p className="mt-1">
                Add the borrower&apos;s financial statements to the credit file above, then
                build again.
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
