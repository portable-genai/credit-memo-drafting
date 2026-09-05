"use client";

import { useRef, useState } from "react";
import type { AnalysisManifest, DocType } from "@/lib/types";
import { analysisDocumentUrl } from "@/lib/api";

/** The kinds an analyst actually brings, in the order a credit file is assembled. */
const DOC_TYPES: { value: DocType; label: string }[] = [
  { value: "financial_statement", label: "Audited financial statements" },
  { value: "management_accounts", label: "Management accounts" },
  { value: "tax_return", label: "Tax return" },
  { value: "bank_statement", label: "Bank statements" },
  { value: "debt_schedule", label: "Debt schedule" },
  { value: "ar_ap_aging", label: "AR / AP aging" },
  { value: "borrowing_base_certificate", label: "Borrowing-base certificate" },
  { value: "rent_roll", label: "Rent roll" },
  { value: "operating_statement", label: "Operating statement (T-12)" },
  { value: "loan_agreement", label: "Loan / facility agreement" },
  { value: "covenant_certificate", label: "Covenant compliance certificate" },
  { value: "valuation", label: "Valuation / appraisal" },
  { value: "policy_pack", label: "Credit policy pack" },
  { value: "prior_memo", label: "Prior credit memo" },
  { value: "rm_note", label: "RM call report / site visit" },
  { value: "exposure_snapshot", label: "Exposure snapshot" },
  { value: "projections", label: "Projections" },
  { value: "registry_document", label: "Registry / court search" },
  { value: "analyst_spread", label: "Your own spread" },
  { value: "filing", label: "Public filing" },
  { value: "other", label: "Other" },
];

export interface PendingDocument {
  file: File;
  docType: DocType;
  asOf: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The credit file for one analysis.
 *
 * Nothing is kept between analyses, which is the point: the evidence is brought to the
 * question, so the person asking it owns how current it is and can see exactly what fed
 * the answer. That is also why every row asks for an "as of" date — the service cannot
 * tell a management account printed yesterday from one printed last year, and a guessed
 * date would put a freshness claim in the memo that nobody made.
 */
export function DocumentPanel({
  pending,
  onChange,
  manifest,
  disabled = false,
}: {
  pending: PendingDocument[];
  onChange: (next: PendingDocument[]) => void;
  manifest: AnalysisManifest | null;
  disabled?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function add(files: FileList | null): void {
    if (!files?.length) return;
    onChange([
      ...pending,
      ...Array.from(files).map((file) => ({
        file,
        docType: "financial_statement" as DocType,
        asOf: "",
      })),
    ]);
  }

  function patch(index: number, change: Partial<PendingDocument>): void {
    onChange(pending.map((row, i) => (i === index ? { ...row, ...change } : row)));
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) add(e.dataTransfer.files);
        }}
        className={`rounded-lg border-2 border-dashed p-4 text-center text-sm ${
          dragging ? "border-regblue-500 bg-regblue-50" : "border-ink-300 bg-white"
        }`}
      >
        <p className="text-ink-700">
          Drop the credit file here, or{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() => fileRef.current?.click()}
            className="font-semibold text-regblue-700 underline disabled:opacity-40"
          >
            choose files
          </button>
          .
        </p>
        <p className="mt-1 text-xs text-ink-500">
          These files, and only these, feed the analysis. Nothing is carried over from a
          previous one.
        </p>
        <input
          ref={fileRef}
          type="file"
          multiple
          aria-label="Documents for this analysis"
          onChange={(e) => add(e.target.files)}
          className="sr-only"
        />
      </div>

      {pending.length ? (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full text-sm">
            <caption className="sr-only">Documents queued for this analysis</caption>
            <thead>
              <tr className="border-b border-ink-200 text-left text-ink-500">
                <th scope="col" className="py-1 pr-3 font-medium">
                  File
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  What it is
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  As of
                </th>
                <th scope="col" className="py-1 font-medium">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pending.map((row, index) => (
                <tr key={`${row.file.name}-${index}`} className="border-b border-ink-100">
                  <td className="py-1 pr-3 text-ink-800">
                    {row.file.name}
                    <span className="ml-2 text-xs text-ink-400">
                      {formatSize(row.file.size)}
                    </span>
                  </td>
                  <td className="py-1 pr-3">
                    <select
                      value={row.docType}
                      aria-label={`Document kind for ${row.file.name}`}
                      onChange={(e) => patch(index, { docType: e.target.value as DocType })}
                      className="w-56 rounded border border-ink-300 px-1.5 py-1"
                    >
                      {DOC_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-1 pr-3">
                    <input
                      type="date"
                      value={row.asOf}
                      aria-label={`Date ${row.file.name} speaks to`}
                      onChange={(e) => patch(index, { asOf: e.target.value })}
                      className="rounded border border-ink-300 px-1.5 py-1"
                    />
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      onClick={() => onChange(pending.filter((_, i) => i !== index))}
                      className="text-xs text-ink-500 underline hover:text-red-700"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {manifest ? <ManifestSummary manifest={manifest} /> : null}
    </div>
  );
}

/**
 * What the analysis was given, and when it disappears.
 *
 * Both halves matter to a reader. The list answers "what was this assessed on"; the date
 * answers "how long can I come back to it", which a person relying on a memo needs to
 * know before they rely on it rather than after the evidence is gone.
 */
export function ManifestSummary({ manifest }: { manifest: AnalysisManifest }) {
  return (
    <div className="rounded-lg border border-ink-200 bg-white p-3 text-sm shadow-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink-900">
          Assessed on {manifest.documents.length} document
          {manifest.documents.length === 1 ? "" : "s"}
        </span>
        <span className="font-mono text-xs text-ink-500">{manifest.analysis_id}</span>
      </div>
      <ul className="mt-2 space-y-1">
        {manifest.documents.map((d) => (
          <li key={d.id} className="flex flex-wrap items-baseline gap-x-2 text-ink-700">
            <a
              href={analysisDocumentUrl(manifest.analysis_id, d.id)}
              target="_blank"
              rel="noreferrer"
              className="text-regblue-700 underline decoration-dotted"
            >
              {d.filename}
            </a>
            <span className="text-xs text-ink-500">
              {d.doc_type.replace(/_/g, " ")}
              {d.pages ? ` · ${d.pages} pages` : ""}
              {d.declared_as_of ? ` · as of ${d.declared_as_of}` : " · no date given"}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
        {manifest.retention_note}
      </p>
    </div>
  );
}
