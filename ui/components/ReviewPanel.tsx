"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CommentList, CreditMemo, RevisionList } from "@/lib/types";

/**
 * What happens to a memo after it is built: it is edited, objected to, circulated, and deleted.
 *
 * All four were API-only. The routes existed, were tested and were reachable by nobody: the
 * console had no control for any of them and `lib/api.ts` had no client either, so the one
 * audience who could use them, the people the product is for, could not. The API's CORS
 * allowlist compounded it, admitting GET and POST alone, so a browser would have refused the
 * PATCH and the DELETE before they reached a route even once the buttons existed.
 *
 * Two properties are deliberately the SERVICE's and not this panel's, because a console that
 * kept its own copy would drift into offering what the service refuses:
 *
 * * which sections may be edited (`editable_sections` on the revision chain). The figures are
 *   never among them: a memo whose leverage could be typed over would put a number in front of
 *   a committee that no formula produced;
 * * which sections a comment may name (`sections` on the thread), which is every section the
 *   memo has, because a reviewer objects to a figure as readily as to a sentence.
 *
 * Nothing here decides anything either. An edit becomes a new revision chained to the last, a
 * comment is anchored to the revision its author actually read, a resolution names the person
 * who made it, and a delete is what the retention promise looks like when a user acts on it
 * rather than reads about it.
 */
export function ReviewPanel({
  analysisId,
  memo,
  onMemoChange,
  onDeleted,
}: {
  analysisId: string;
  memo: CreditMemo;
  /** The amended memo, so the page shows the version a committee would now receive. */
  onMemoChange: (memo: CreditMemo) => void;
  onDeleted: () => void;
}) {
  const [chain, setChain] = useState<RevisionList | null>(null);
  const [thread, setThread] = useState<CommentList | null>(null);
  const [formats, setFormats] = useState<string[]>([]);
  const [section, setSection] = useState("summary");
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [commentSection, setCommentSection] = useState("summary");
  const [commentBody, setCommentBody] = useState("");
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [format, setFormat] = useState("docx");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  const refresh = useCallback(async () => {
    const [revisions, comments, exportable] = await Promise.all([
      api.listRevisions(analysisId),
      api.listComments(analysisId),
      api.exportFormats(analysisId),
    ]);
    setChain(revisions);
    setThread(comments);
    setFormats(exportable);
    if (exportable.length && !exportable.includes(format)) setFormat(exportable[0]);
  }, [analysisId, format]);

  // Re-read after every build as well as on mount: a rebuild opens a new chain, and a stale
  // revision number beside a fresh memo is the kind of thing a reviewer would rely on.
  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [refresh, memo.generated_at]);

  // The text as it stands now, so an edit starts from the memo rather than from an empty box.
  useEffect(() => {
    const current = (memo as unknown as Record<string, unknown>)[section];
    setDraft(typeof current === "string" ? current : "");
  }, [memo, section]);

  const editable = chain?.editable_sections ?? [];
  const commentable = thread?.sections ?? editable;

  async function run(what: string, action: () => Promise<void>): Promise<void> {
    setBusy(what);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const amend = () =>
    run("Saving the revision", async () => {
      const revision = await api.amendMemo(analysisId, {
        sections: { [section]: draft },
        reason,
        note,
      });
      onMemoChange(revision.memo_json);
      setReason("");
      setNote("");
      await refresh();
    });

  const comment = () =>
    run("Leaving the comment", async () => {
      await api.addComment(analysisId, { section: commentSection, body: commentBody });
      setCommentBody("");
      await refresh();
    });

  const resolve = (id: string) =>
    run("Resolving", async () => {
      await api.resolveComment(analysisId, id, resolutions[id] ?? "");
      await refresh();
    });

  const download = () =>
    run("Preparing the pack", async () => {
      const { blob, filename } = await api.exportMemo(analysisId, format);
      // A blob URL and a synthetic click: the bytes are already in the page, so the browser
      // saves them without a second round trip, and nothing needs a readable filename header.
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });

  const remove = () =>
    run("Deleting the evidence", async () => {
      await api.deleteAnalysis(analysisId);
      setConfirming(false);
      onDeleted();
    });

  return (
    <section data-panel="review" className="mt-4 space-y-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
        Review, circulate, delete
      </h2>

      {error ? (
        <p
          data-panel="review-error"
          className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800"
        >
          {error}
        </p>
      ) : null}
      <p aria-live="polite" className="text-xs text-ink-500" data-review-busy={busy}>
        {busy ? `${busy}...` : ""}
      </p>

      {/* ---- the edit, and the chain it lands in ---------------------------------- */}
      <div
        data-panel="amend"
        className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel"
      >
        <span className="mb-1 block text-sm font-semibold text-ink-900">Edit the prose</span>
        <p className="mb-2 text-xs text-ink-500">
          The narrative sections are editable and the figures are not: they belong to the
          engines, and this picker offers only what the service accepts.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Section</span>
            <select
              data-field="amend-section"
              value={section}
              onChange={(e) => setSection(e.target.value)}
              className="w-full rounded border border-ink-300 px-2 py-1.5"
            >
              {editable.map((name) => (
                <option key={name} value={name}>
                  {name.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Why this changed</span>
            <input
              data-field="amend-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="The drafted summary understated the breach"
              className="w-full rounded border border-ink-300 px-2 py-1.5"
            />
          </label>
        </div>
        <label className="mt-2 block text-sm">
          <span className="mb-1 block text-ink-500">The text a committee will read</span>
          <textarea
            data-field="amend-text"
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Note on the revision</span>
            <input
              data-field="amend-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Rewritten to lead with the covenant position"
              className="w-72 rounded border border-ink-300 px-2 py-1.5"
            />
          </label>
          <button
            type="button"
            data-action="amend-memo"
            onClick={amend}
            disabled={busy !== ""}
            className="rounded bg-regblue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save as a new revision
          </button>
        </div>
      </div>

      {chain ? (
        <div
          data-panel="revisions"
          data-revisions={chain.revisions.length}
          data-chain-intact={chain.chain_intact ? "true" : "false"}
          className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel"
        >
          <span className="mb-1 block text-sm font-semibold text-ink-900">
            Versions ({chain.revisions.length})
          </span>
          <p className="mb-2 text-xs text-ink-500">
            {chain.chain_intact
              ? "Every version is linked to the one before it, and the chain verifies."
              : `The chain does not verify: ${chain.chain_detail}`}
          </p>
          <ul className="space-y-1 text-sm">
            {chain.revisions.map((revision) => (
              <li
                key={revision.revision}
                data-revision={revision.revision}
                className="rounded border border-ink-100 p-2"
              >
                <span className="font-mono text-xs text-ink-500">
                  revision {revision.revision}
                </span>{" "}
                <span className="text-ink-800">{revision.actor}</span>
                {revision.note ? (
                  <span className="block text-xs text-ink-600">{revision.note}</span>
                ) : null}
                {revision.edits.map((edit, index) => (
                  <span key={index} className="block text-xs text-ink-500">
                    {edit.section.replace(/_/g, " ")}
                    {edit.reason ? `: ${edit.reason}` : ""}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* ---- the objection, anchored to the text its author read ------------------ */}
      <div
        data-panel="comments"
        data-open-count={thread?.open_count ?? 0}
        data-stale-count={thread?.stale_count ?? 0}
        className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel"
      >
        <span className="mb-1 block text-sm font-semibold text-ink-900">
          Comments ({thread?.open_count ?? 0} open)
        </span>
        <p className="mb-2 text-xs text-ink-500">
          A comment is anchored to the version its author read. Edit the text underneath one and
          it is flagged for re-reading rather than closed: a comment that lapsed because the
          text moved was lost, not answered.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Section</span>
            <select
              data-field="comment-section"
              value={commentSection}
              onChange={(e) => setCommentSection(e.target.value)}
              className="rounded border border-ink-300 px-2 py-1.5"
            >
              {commentable.map((name) => (
                <option key={name} value={name}>
                  {name.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">The objection</span>
            <input
              data-field="comment-body"
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="Say who is being asked to waive this"
              className="w-80 rounded border border-ink-300 px-2 py-1.5"
            />
          </label>
          <button
            type="button"
            data-action="add-comment"
            onClick={comment}
            disabled={busy !== "" || !commentBody.trim()}
            className="rounded border border-regblue-600 px-3 py-1.5 text-xs font-semibold text-regblue-600 disabled:opacity-40"
          >
            Leave the comment
          </button>
        </div>

        <ul className="mt-2 space-y-2 text-sm">
          {(thread?.comments ?? []).map((item) => (
            <li
              key={item.id}
              data-comment-id={item.id}
              data-open={item.open ? "true" : "false"}
              data-stale={item.stale ? "true" : "false"}
              className="rounded border border-ink-100 p-2"
            >
              <span className="text-ink-800">{item.body}</span>
              <span className="block text-xs text-ink-500">
                {item.author} on {item.section.replace(/_/g, " ")}, against revision{" "}
                {item.revision}
                {item.stale ? " (the text has changed since: re-read it)" : ""}
                {item.open ? "" : ` (resolved by ${item.resolved_by}: ${item.resolution})`}
              </span>
              {item.open ? (
                <span className="mt-1 flex flex-wrap items-center gap-2">
                  <input
                    data-field="resolution"
                    value={resolutions[item.id] ?? ""}
                    onChange={(e) =>
                      setResolutions({ ...resolutions, [item.id]: e.target.value })
                    }
                    placeholder="what was done about it"
                    className="w-72 rounded border border-ink-300 px-1.5 py-1 text-sm"
                  />
                  <button
                    type="button"
                    data-action="resolve-comment"
                    onClick={() => resolve(item.id)}
                    disabled={busy !== ""}
                    className="rounded border border-ink-300 px-2 py-1 text-xs text-ink-700 disabled:opacity-40"
                  >
                    Resolve
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </div>

      {/* ---- the pack, and the deletion ------------------------------------------ */}
      <div
        data-panel="export"
        className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel"
      >
        <span className="mb-1 block text-sm font-semibold text-ink-900">
          The committee pack
        </span>
        <p className="mb-2 text-xs text-ink-500">
          Built from the memo as it stands now, so a committee receives the version that was
          reviewed. The formats are the ones this deployment can actually produce; `json` is the
          memo as the service stores it, which is what a later renewal reads to say what changed.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm">
            <span className="mb-1 block text-ink-500">Format</span>
            <select
              data-field="export-format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="rounded border border-ink-300 px-2 py-1.5"
            >
              {formats.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            data-action="export-memo"
            onClick={download}
            disabled={busy !== "" || !formats.length}
            className="rounded bg-regblue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
          >
            Download the pack
          </button>
        </div>
      </div>

      <div
        data-panel="delete"
        className="rounded-xl border border-red-200 bg-white p-4 shadow-panel"
      >
        <span className="mb-1 block text-sm font-semibold text-ink-900">
          Delete the evidence now
        </span>
        <p className="mb-2 text-xs text-ink-500">
          The analysis, the files it holds and the memo built from them go together, before the
          retention window rather than after it. Nothing here can be reopened afterwards.
        </p>
        {confirming ? (
          <span className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-action="confirm-delete"
              onClick={remove}
              disabled={busy !== ""}
              className="rounded bg-red-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              Delete now
            </button>
            <button
              type="button"
              data-action="cancel-delete"
              onClick={() => setConfirming(false)}
              className="text-xs text-ink-500 underline"
            >
              Keep it
            </button>
          </span>
        ) : (
          <button
            type="button"
            data-action="delete-analysis"
            onClick={() => setConfirming(true)}
            className="rounded border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-700"
          >
            Delete this analysis
          </button>
        )}
      </div>
    </section>
  );
}
