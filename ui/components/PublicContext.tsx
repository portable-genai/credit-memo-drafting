"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { MarketContext } from "@/lib/types";
import { ProvenanceTag } from "./Provenance";

/**
 * What the public web says about this borrower — for the analyst who asked, and nobody else.
 *
 * The one place in this console that reaches outside the bank's own evidence, and it is
 * fenced on three sides, each for a different reason.
 *
 * **Licensing.** Google's Service Specific Terms section 20(k) permit Grounded Results to
 * be displayed only to the End User who submitted the prompt, forbid interspersing them
 * with other content, and survive termination. A credit memo is read by a checker, a
 * committee and later an examiner — none of whom submitted the prompt. So what lands here
 * stays here: it is never posted back, never written into the memo, never exported. The
 * panel sits apart from the memo on purpose; putting these rows among the memo's cited
 * sections would breach the term and, worse, would read to a committee as evidence the
 * bank stands behind.
 *
 * **The chips are not decoration.** `search_suggestions` are rendered verbatim because
 * Google requires it. Tidying them away is a licence breach that looks like a UI
 * improvement, which is exactly why it is worth saying here rather than trusting that
 * nobody will.
 *
 * **The engine boundary.** Nothing on a `WebEvidence` is a number, so no ratio, covenant
 * test, policy rule or scorecard can read an operand off this panel even by accident. An
 * analyst who wants a figure from here in the memo types it into the spread, which makes
 * it `user_entered` — theirs to stand behind, with the URL cited beside it.
 */
export function PublicContext({
  analysisId,
  borrower,
  disabled,
}: {
  analysisId: string;
  borrower: string;
  disabled?: boolean;
}) {
  const [context, setContext] = useState<MarketContext | null>(null);
  const [query, setQuery] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function search() {
    setNote("");
    setBusy(true);
    try {
      setContext(await api.research(analysisId, query.trim() || borrower.trim()));
    } catch (err) {
      // "We could not look" arrives here as an error, and it is a different answer from
      // "we looked and found nothing" — which arrives as a result with no rows. An
      // analyst deciding whether to go and check themselves needs to know which one this
      // was, so the message is shown rather than folded into an empty state.
      setContext(null);
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3" data-panel="public-context">
      <p className="text-xs text-ink-500">
        Sector and borrower context from the public web, for you and not for the memo.
        Results are shown to the person who ran the search and are never written into the
        memo or the committee pack. To use one of these facts, type the figure into the
        spread and cite the URL: that makes it yours.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block text-ink-500">Search the public web</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={borrower || "borrower name"}
            className="w-72 rounded border border-ink-300 px-2 py-1.5"
          />
        </label>
        <button
          type="button"
          onClick={search}
          disabled={disabled || busy || !analysisId}
          className="rounded border border-regblue-600 px-3 py-1.5 text-xs font-semibold text-regblue-600 disabled:opacity-40"
        >
          {busy ? "Searching..." : "Search public context"}
        </button>
      </div>

      {note ? <p className="text-xs text-ink-600">{note}</p> : null}

      {context && context.found_nothing ? (
        <p className="text-xs text-ink-600">
          The search ran and returned nothing for this borrower. That is not evidence that
          nothing has been published — most private companies leave little public trace.
        </p>
      ) : null}

      {context && !context.found_nothing ? (
        <div className="space-y-2">
          <ul className="space-y-2">
            {context.evidence.map((item) => (
              <li key={item.url} className="rounded border border-ink-200 bg-white p-2">
                <div className="flex items-start justify-between gap-2">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm font-medium text-regblue-600 underline"
                  >
                    {item.title}
                  </a>
                  <ProvenanceTag provenance={item.provenance} />
                </div>
                {item.snippet ? (
                  <p className="mt-1 text-xs text-ink-700">{item.snippet}</p>
                ) : null}
                <p className="mt-1 text-[10px] uppercase tracking-wide text-ink-400">
                  retrieved {item.retrieved_at.slice(0, 10)} · {context.provider}
                </p>
              </li>
            ))}
          </ul>

          {/* Rendered verbatim: Google requires these chips beside grounded results. */}
          {context.search_suggestions.length ? (
            <div className="rounded border border-ink-200 bg-ink-50 p-2">
              {context.search_suggestions.map((chip) => (
                <div
                  key={chip}
                  className="text-xs text-ink-700"
                  dangerouslySetInnerHTML={{ __html: chip }}
                />
              ))}
            </div>
          ) : null}

          <p className="text-xs font-medium text-ink-700">
            None of the above is in the memo, and none of it can be: nothing here carries a
            figure any ratio or covenant test could read.
          </p>
        </div>
      ) : null}
    </div>
  );
}
