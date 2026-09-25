"use client";

import { useEffect, useState } from "react";

import { watchAnswers } from "../lib/answer-provenance.mjs";
import { API_BASE, healthz } from "../lib/api";

/**
 * Two small pills at the top right of every page: the model that ANSWERED, and `Search` when
 * the answer used an online search tool (owner decision, 2026-09-23; they replace the
 * full-width provenance banner).
 *
 * The pill names what answered, not what configuration would call. Until an answer arrives it
 * shows the service's configured `generator_model` from `/healthz`, dimmed, with where the
 * runtime sits in its title. From then on it shows the `X-Answered-By` header of the console's
 * last answering response, solid, and `Search` appears only while that response carried
 * `X-Search-Used: true`. Both headers are emitted by the service
 * (`install_answer_provenance` in `api/app.py`, which also names them in
 * `Access-Control-Expose-Headers` so this cross-origin console can read them).
 *
 * **Every value comes from the service**, and nothing here infers one. A UI that read its own
 * runtime from `window.location` would be right until the deployment served through a proxy,
 * and wrong silently after that.
 *
 * Health goes through the same client as every other call this console makes, at `API_BASE`
 * resolved once in `lib/api`. The `connect-src` this console ships is built from that same
 * value, so a health check on a base of its own would be silently refused, and the pills would
 * render nothing.
 */

interface Configured {
  model: string;
  where: string;
}

interface Answer {
  model: string;
  search: boolean;
}

const PILL =
  "max-w-[260px] truncate whitespace-nowrap rounded-full border px-[9px] py-px text-[11px] leading-[1.6]";

/**
 * Renders once the service has answered `/healthz`, and nothing before that.
 *
 * The null-until-known state is deliberate: a pill defaulting to a model or a runtime while the
 * fetch is in flight would state a falsehood on some page load, and a failed health call renders
 * nothing for the same reason. The page's own error surface owns the failure.
 */
export function ModelPills() {
  const [configured, setConfigured] = useState<Configured | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    const stop = watchAnswers(window, API_BASE, (next) => {
      if (live) setAnswer(next);
    });
    healthz(controller.signal)
      .then((status) => {
        if (!live || !status.runtime) return;
        setConfigured({
          model: String(status.generator_model ?? ""),
          where: status.runtime === "gcp" ? "running on GCP" : "running locally",
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
      controller.abort();
      stop();
    };
  }, []);

  if (!configured) return null;
  // Fixed at the top right, inside the header's own top padding, so the pills stay in view
  // without covering a control: the header's right side is empty and every control sits below
  // it. Each pill carries an opaque background, so it reads over whatever scrolls beneath.
  return (
    <div
      className="fixed right-2.5 top-1.5 z-50 flex max-w-[calc(100vw-20px)] gap-1.5"
      data-testid="model-pills"
    >
      {answer ? (
        <span
          className={`${PILL} border-ink-900 bg-ink-900 text-white`}
          data-state="answered"
          title="answered the last request"
        >
          {answer.model}
        </span>
      ) : (
        <span
          className={`${PILL} border-dashed border-ink-200 bg-ink-50 text-ink-500`}
          data-state="configured"
          title={configured.where}
        >
          {configured.model}
        </span>
      )}
      {answer?.search ? (
        <span
          className={`${PILL} border-emerald-600 bg-emerald-600 text-white`}
          title="the last answer used an online search tool"
        >
          Search
        </span>
      ) : null}
    </div>
  );
}
