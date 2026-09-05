# The business use-case demo

One deal, walked end to end through the product a credit team would actually use: the
built console talking to the real service. Seventeen acts, each a beat a credit audience
recognises, and each one asserted so the demo cannot quietly rot.

```bash
# Build the console once (its API base is inlined at build time), then present.
make walkthrough                      # a browser opens; all seventeen acts

make walkthrough ACT="The checker"    # just one use case
make walkthrough-list                 # what you can name

# The same acts, asserted, with no window:
make demo-console
```

Both entry points share one list — [`scripts/demo_console/acts.py`](../scripts/demo_console/acts.py).
That is deliberate. This repository has shipped capabilities that were fully built and
reachable by nobody: a spread extractor no route called, a revision chain with no endpoint,
engines whose results no schema carried. Each passed a green gate, because a port that is
bound, contract-tested and never called looks exactly like a working feature from inside
the suite. A demo asserts the one thing those checks cannot — that a person can still get
to it.

## The deal

Acme Manufacturing Pte Ltd (FICTIONAL) asks for a USD 25m five-year term facility. Its
figures are chosen so the memo shows what a credit audience needs to see rather than a
happy path:

| | |
|---|---|
| Leverage | 3.5x against a 3.0x covenant — a **BREACH**, and policy exception `LEV-01` |
| DSCR | 1.29x against a 1.25x minimum — passing, but inside the thin-headroom band, so **AT RISK** |
| Four ratios | not computable, each naming the line it was missing |
| The certificate | says leverage is 2.50x where the engine computes 3.50x, and the reconciliation reports the disagreement |

The last one is the point of the whole demo. The extractor reads 2.5x off the page; the
engine computes 3.5x from the figures a named analyst confirmed; the covenant is a breach.
A demo where the model and the arithmetic agree proves nothing about which one the product
trusts.

## The acts

| # | Act | Point at |
|---|-----|----------|
| 1 | Who is asking | The persona picker: four seeded people, in two different banks |
| 2 | The credit file | The manifest — every file, its digest and page count, and the date the evidence is deleted |
| 3 | Figures nobody has vouched for | The amber "Not yet anybody's figures" panel, and a quote opened beside its source page |
| 4 | Becoming the person who stands behind them | The green "Confirmed by" line naming the analyst |
| 5 | The memo | The human-review banner, then the sections a committee reads |
| 6 | The breach the model did not see | The covenant pills, and the computed value beside the one the evidence reported |
| 7 | It refuses to compute what it cannot | The ratio rows with no number, each naming the line it needed |
| 8 | The bank's own policy | Rule `LEV-01` with its waiver authority, and the grade's drivers |
| 9 | The reconciliations | The finding naming both figures |
| 10 | The group | The "Incomplete" notice naming the guarantor nobody filed for, and the elimination row |
| 11 | How far it can fall | The break-even column |
| 12 | The checker | The revision chain, and the comment that went stale instead of away |
| 13 | Figures are not editable prose | The refusal, which names the sections that *are* editable |
| 14 | The committee pack | The rendered pack: the standing sentence, then `LEV-01` and the reconciliation |
| 15 | Is this even bankable | The `TEN-01` knockout, and the absent rating |
| 16 | What it will not do | The inline refusal, then the amber guardrail notice |
| 17 | The evidence goes away | The 404 that does not confirm the analysis exists |

Acts 12, 13, 14 and 17 are driven over the API rather than the console, because the console
has no control for them (see **Gaps** below). Where there is something to look at, it still
goes on screen: act 14 renders the committee pack in a browser tab.

## Presenting

The walkthrough stops twice over: before each act, saying what is about to happen, and
again *inside* the act at the beats worth talking through — once the form is filled and
before it is submitted, and again when the answer is on screen. Each stop prints what to
say and what to point at, then waits for any key (`q` quits and still writes the trace).
Those inner pauses live in `acts.py` beside the step they interrupt, because only that
module knows where a filled form stops and an answer begins; they are inert under pytest,
so a pause can never change what an act proves.

Naming one use case runs everything before it first — the memo needs the confirmed spread,
and the spread needs the credit file — silently, one status line each, and then presents
the act you asked for:

```bash
make walkthrough ACT=12                     # by number
make walkthrough ACT=checker                # any unambiguous part of the title
.venv/bin/python scripts/credit_memo_console_walkthrough.py --act 6 --act 9
```

An ambiguous name (`--act "The "`) is refused rather than guessed at, and an unknown one
prints the seventeen titles. Slow motion is a launch-time Playwright setting, so the
set-up acts run at whatever `SLOWMO_MS` the presented act uses; on this machine eleven
set-up acts take a few seconds headless.

Both servers log to `out/demo/logs/`, not to the terminal — a PDF library's "invalid pdf
header" chatter, emitted every time the extractor is handed a CSV, otherwise lands in the
middle of the sentence being read aloud. A server that fails to start still reports the
tail of its own log in the error.

## What the run leaves behind

`out/demo/` — one full-page screenshot per act, a video, and a Playwright trace
(`trace.zip`). The trace is the artefact worth keeping: it holds the DOM, the network and a
screencast at every step, so a question asked after the demo can be answered from the
recording rather than from memory.

## Side notes for a technical questioner

Deliberately not in the main demo — these are engineering stories, and a credit audience
did not come for them. Each is one command:

| Question | Answer |
|---|---|
| Does it run without Google Cloud? | `make memo` — the same pipeline, offline, no SDK and no API key |
| What happens on-premise? | `CREDIT_MEMO_PROFILE=onprem credit-memo build "X"` exits 2 with the migration message |
| Is quality gated? | `make eval`, and `make eval-adversarial` where a PASS is the bug |
| Is the portability claim tested? | `make portability` |
| How do other agents discover it? | `curl localhost:8093/.well-known/agent-card.json` |
| What tools does it expose? | `make mcp-serve` |
| Is there a slide-ready static render? | `make demo` writes `./out/memo.html` and `sources.html` |
| The older presenter server? | `make demo-server` on :8094, six steps, unchanged |

## Gaps this demo surfaced

Recorded here rather than fixed, because each is product work with its own review:

1. **Four capabilities are API-only.** Export, memo amendment plus revisions, comments and
   delete have no console control; `ui/lib/api.ts` has no client for any of them. The API's
   CORS allowlist compounds it — `allow_methods` is `GET, POST, OPTIONS`, so a browser
   console could not reach `PATCH` or `DELETE` cross-origin even if the buttons existed.
2. **`NEXT_PUBLIC_API_BASE` unset ships a broken console.** `ui/lib/api.ts` falls back to
   `http://localhost:8093`, but `ui/lib/csp.mjs` adds an origin to `connect-src` only when
   the variable **is** set. Leave it unset and the page's own default API call is blocked
   by its own CSP, visible only in the browser console. `make ui-build` sets it explicitly;
   the two halves should agree on their own.
3. **`RenewalDiffService` is unreachable.** It is written, unit-tested and bound to nothing:
   no route computes `renewal_delta`, nothing reads an uploaded `prior_memo`, and
   `AnalysisManifest.missing()` — which would tell an analyst a renewal needs the prior memo
   — is not on the wire. A renewal act was planned for this demo and removed for that
   reason. This is a sixth instance of the pattern in note 1.
4. **The console has almost no stable `data-*` hooks**, unlike the presenter server. The
   demo locates controls by role and label, all of them in
   [`scripts/demo_console/locators.py`](../scripts/demo_console/locators.py), so UI drift is
   one edit. Hooks on the covenant pills, ratio rows and section headings would make it
   sturdier.
5. **Stale claims in the docs.** [`DEMO.md`](../DEMO.md) refers to an "Upload borrower
   evidence" panel and [`ui/README.md`](../ui/README.md) to a `.env.local.example`; neither
   exists. [`README.md`](../README.md)'s HTTP table lists six routes where the service
   serves about twenty-four — [`SPEC.md`](../SPEC.md) §6.1 is the current list.

## Not yet gated in CI

`.github/workflows/gate.yaml` is GENERATED from `ci/gcp/repository-policy.json` in
`org-metadata`, and the gate fails when the checked-in file differs from what the contract
renders — so this job cannot be added by editing the workflow here. Registering it means
adding one entry to this repository's `jobs` array in that policy and re-rendering:

```json
{
  "job_id": "demo-console",
  "make_targets": ["demo-console"],
  "npm_directory": "ui",
  "npm_directory_first": true,
  "extra_lockfiles": ["requirements-demo.lock"],
  "extra_lockfiles_first": true,
  "demo_browser_required": true,
  "runtime_key": "python3.14-node24"
}
```

It needs both Node and the pinned `[demo]` extra, which is why it is its own job rather
than an addition to `demo-browser` (no node) or `offline-gate` (no browser). Until that
lands, the demo is verified locally by `make demo-console` and is not enforced on a pull
request.

All demo data is fictional. Do not run this against live borrower data without your own
legal, security and model-risk sign-off.
