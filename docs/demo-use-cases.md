# The business use-case demo

One deal, walked end to end through the product a credit team would actually use: the
built console talking to the real service. Nineteen acts, each a beat a credit audience
recognises, and each one asserted so the demo cannot quietly rot.

```bash
# Build the console once (its API base is inlined at build time), then present.
make walkthrough                      # a browser opens; all nineteen acts

make walkthrough ACT="The checker"    # just one use case
make walkthrough-list                 # what you can name

# The same acts, asserted, with no window. CI runs them in its demo-browser job.
make demo-console
```

Both entry points share one list — [`scripts/demo_console/acts.py`](../scripts/demo_console/acts.py).
That is deliberate. This repository has shipped capabilities that were fully built and
reachable by nobody: a spread extractor no route called, a revision chain with no endpoint,
engines whose results no schema carried. Each passed a green gate, because a port that is
bound, contract-tested and never called looks exactly like a working feature from inside
the suite. A demo asserts the one thing those checks cannot — that a person can still get
to it.

## The deal, and why every figure in it is checkable

**Flowserve Corporation** (NYSE: FLS, SEC CIK 30625) is asked for a USD 400m five-year
term facility. The borrower is real, and every financial figure comes from its Form 10-K
for the year ended 31 December 2025, accession `0000030625-26-000003`. The credit file the
demo uploads is committed under [`demo/documents/`](../demo/documents/), with
[`SOURCES.md`](../demo/documents/SOURCES.md) recording where each figure came from.

That matters more than presentation. A fictional borrower never broke the memo — grounding
is retrieval over uploaded evidence, so an invented company works fine — but nothing could
be *checked*, and three real defects sat behind it: EDGAR grounding that mixed fiscal years
and read this company's revenue as zero, an offline drafter that answered "Acme is a
profitable manufacturer…" for every borrower it was handed, and an extractor whose
placeholder text meant the presenter demo reported figures its own evidence never
contained. All three were invisible until the numbers had to be right.

| | |
|---|---|
| Leverage | **3.18x** against the 3.00x this bank proposes — a **BREACH**, and policy exception `LEV-01` |
| The borrower's own figure | **1.64x**, net of USD 760.2m cash, and it reports full compliance with its existing covenants |
| Current ratio | **2.03x** against a 2.00x floor — passing by 1.3%, inside the thin-headroom band, so **AT RISK** |
| DSCR | **5.42x** — comfortably met, and strong enough that a 200bp rate rise never breaks it |
| Four ratios | not computable, each naming the line it was missing |

The disagreement is the point of the whole demo, and it is now real rather than staged.
Both numbers are correct arithmetic on the same filing: the borrower nets its cash and adds
back USD 58.3m of recurring realignment charges, and this bank does neither. The
reconciliation reports both and names the cause instead of quietly picking one. That is the
conversation a credit officer actually needs to have, and it could not be shown honestly
with an invented borrower.

**What is ours, not the company's.** The facility request, the proposed covenant
thresholds, and every limit in `config/policy_pack.example.yaml` are this demo bank's and
are invented. So an exception raised here is a statement about that example appetite, never
an allegation about Flowserve — which, measured its own way against its own covenants,
reports compliance.

## The acts

| # | Act | Point at |
|---|-----|----------|
| 1 | Who is asking | The persona picker: four seeded people, in two different banks |
| 2 | The credit file | The manifest — every file, its digest and page count, and the date the evidence is deleted |
| 3 | Figures nobody has vouched for | The amber "Not yet anybody's figures" panel, and a quote opened beside its source page |
| 4 | Becoming the person who stands behind them | The green "Confirmed by" line naming the analyst |
| 5 | The memo | The human-review banner, then the sections a committee reads |
| 6 | Same filing, two answers | The covenant pills, and the engine's 3.18x beside the borrower's reported 1.64x |
| 7 | It refuses to compute what it cannot | The ratio rows with no number, each naming the line it needed |
| 8 | The bank's own policy | Rule `LEV-01` with its waiver authority, and the grade's drivers |
| 9 | The reconciliations | The finding naming both figures, and that the cause is a definition rather than an error |
| 10 | The group | The "Incomplete" notice naming the two real Exhibit 21 subsidiaries nobody filed for |
| 11 | How far it can fall | The break-even column |
| 12 | The checker | The revision chain, and the comment that went stale instead of away |
| 13 | Figures are not editable prose | The refusal, which names the sections that *are* editable |
| 14 | Public context, for the analyst only | The results with their suggestion chips, then the line saying none of it is in the memo |
| 15 | The committee pack | The rendered pack: the standing sentence, then `LEV-01` and the reconciliation |
| 16 | Next year, and what changed | The checklist naming the missing prior memo, then the delta naming the file it measured against |
| 17 | Is this even bankable | The `TEN-01` knockout, and the absent rating |
| 18 | What it will not do | The inline refusal, then the amber guardrail notice |
| 19 | The evidence goes away | The 404 that does not confirm the analysis exists |

Every act drives the console. Acts 12, 15 and 19 could not until it grew the controls they
need: the reviewer's thread, the pack and the delete were API-only. Nor could act 16: the
renewal diff had no route, no wire field and no control. Where an act still calls the API it
is to check what the console did, or to show a refusal the console cannot express (act 13
types over a computed section, which its editor does not offer). The pack still goes on screen
as well as into a file: act 15 renders it in a browser tab.

## Presenting

The walkthrough stops twice over: before each act, saying what is about to happen, and
again *inside* the act at the beats worth talking through — once the form is filled and
before it is submitted, and again when the answer is on screen. Each stop prints the
business points to make as a numbered list and what to point at, then waits for any key
(`q` quits and still writes the trace). A point is a phrase to say; the justification
underneath it is for the question that phrase provokes, not to be read out.
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
prints the nineteen titles. Slow motion is a launch-time Playwright setting, so the
set-up acts run at whatever `SLOWMO_MS` the presented act uses; on this machine eleven
set-up acts take a few seconds headless.

Both servers log to `out/demo/logs/`, not to the terminal — a PDF library's "invalid pdf
header" chatter, emitted every time the extractor is handed a CSV, otherwise lands in the
middle of the sentence being read aloud. A server that fails to start still reports the
tail of its own log in the error.

## Checking a deployment

`make demo-console` proves the acts against a console and an API on this laptop. It says
nothing about a deployed service, and the difference is not cosmetic: every defect below
passed the offline gate and failed the moment a managed model, a real IAM policy and a real
proxy were involved.

```bash
CREDIT_MEMO_DEPLOYED_BASE=https://<host>/apps/credit-memo-drafting/api \
CREDIT_MEMO_DEPLOYED_TOKEN="$(gcloud auth print-identity-token \
    --impersonate-service-account=<e2e-sa> --audiences=<iap-oauth-client-id> --include-email)" \
  make verify-deployed
```

Twenty-four checks, walking the same business steps as the acts: the credit file into
custody, a managed model reading the figures, a named person confirming them, the memo, the
engine's arithmetic, the reconciliation, the bank's policy, the peer set, and the evidence
being deleted again. Both variables unset skips, so it stays runnable in a checkout with no
cloud access. Everything it asserts is recomputed from the committed fixture rather than
matched against prose.

**What it caught that nothing else could.** A response schema Vertex refuses (`{"type":
["integer","null"]}` is a union; it takes one type plus `nullable`). A token budget that
covers the model's *thinking* as well as its answer, so the memo stopped mid-JSON and the
service reported that the evidence did not support one. Citations returned as
`source_id p.4`, exactly as the prompt asks, matching nothing. An IAP assertion arriving
under the one header name the app did not read, because Google's serverless frontend strips
the reserved one. `roles/dlp.user` granting the redaction CALL but not the template READ.
Model Armor's screening permission living on the template. `application/octet-stream`, which
a browser sends for anything it cannot name and the model refuses outright. And a borrower
whose typed name never matched its own registrant title, because the stop-word list held
`corp` but not `corporation`.

## Swapping the demo borrower

The **deployed service needs no per-company setup at all**. Under the `gcp`/`live` profile
it resolves any real US-listed company by name against SEC EDGAR, pulls that company's own
filed figures, and finds its own SIC-code peers automatically — that is the whole point of
Demo C in `DEMO.md`. Nothing in the infrastructure, IAM or deployment config names
Flowserve.

The **curated 18-act script is a different matter**: it is built from Flowserve's actual
filed numbers, not placeholders, and swapping the company is real research, not a rename.

**What is Flowserve-specific and would need to change:**

```
demo/documents/flowserve-fy2025-financial-extract.txt   # real prose, real figures
demo/documents/flowserve-fy2025-spread.csv               # real spread
demo/documents/flowserve-covenant-position.txt           # real disclosed covenant language
demo/documents/SOURCES.md
scripts/demo_console/fixtures.py                          # every dollar figure as a constant
scripts/demo_console/acts.py                               # narration strings quote exact numbers
scripts/verify_deployed_demo.py                            # imports fixtures, recomputes from them
ui/app/page.tsx                                            # default borrower name
eval/datasets/golden_cases.jsonl (case-flowserve-real)
DEMO.md, README.md, this file, docs/ADOPTING.md,
docs/practices-audit.md, docs/faq/compliance-faq.md
```

**What researching a replacement needs, in order:**

1. **Confirm it is a going concern on EDGAR.** Two candidates were disqualified this way
   while researching Flowserve: Hillenbrand and Chart Industries were both taken private and
   are absent from `company_tickers.json`, so `EdgarClient.resolve` cannot find them at all.
2. **Pull one coherent period of real figures** (revenue, EBITDA components, debt, capex,
   tax, scheduled debt service, current assets/liabilities) via `latest_annual_facts`. Two
   traps cost hours the first time and apply to any company: `fy` on a companyfacts row is
   the *filing* year, not the period it covers; and a preferred tag reporting a literal zero
   can beat the tag actually holding the real figure (`latest_annual_facts` now guards both,
   but the replacement figures still have to be assembled from one consistent period).
3. **Find the definitional gap that makes the reconciliation act mean something.** The
   center of the demo is that the borrower reports leverage under its own covenant
   definition and the bank's gross-debt calculation disagrees. Flowserve discloses this
   cleanly — it nets cash and adds back a named realignment charge. Not every filing states
   its own adjustments this explicitly; without an equivalent, that act has nothing real to
   show and the fix must not be to invent one.
4. **Find real Exhibit 21 subsidiaries with no separate financials**, for the group act.
5. Rewrite the documents and constants, then run `make demo-console` and
   `make verify-deployed` and confirm the new numbers still produce the shape of the story:
   a breach, a thin-headroom ratio, an uncomputable line, and a reconciliation that reports
   a real disagreement rather than a manufactured one.

`config/policy_pack.example.yaml` (the bank's 3.00x leverage / 1.25x DSCR / 2.00x current
ratio limits) is the bank's own appetite and does not change with the borrower — though
whether a replacement's real leverage happens to land near an interesting threshold against
those fixed limits is a property of the company, not something to tune.

## What the run leaves behind

`out/demo/` — one full-page screenshot per act, a Playwright trace (`trace.zip`), and a video
where the machine can render one. The trace is the artefact worth keeping: it holds the DOM,
the network and a screencast at every step, so a question asked after the demo can be answered
from the recording rather than from memory. The video needs Playwright's own ffmpeg binary
(`playwright install ffmpeg`), which the CI runner does not ship, so a run there records
everything except the video and says so rather than failing the acts over it.

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

**Closed since.** Export, memo amendment with its revision chain, comments and delete were
API-only: routes and tests with no client in `ui/lib/api.ts`, which from outside is
indistinguishable from capabilities nobody built. The console now carries all four in one
review panel, the client issues `PATCH` and `DELETE`, and the API's CORS allowlist admits
exactly the verbs the client sends, which it did not before: a cross-origin `PATCH` was
refused by the browser before it reached a route.
`tests/unit/test_the_console_reaches_the_api.py` holds both halves structurally, so a new
route with no client fails on the day it is added.

The console also now carries stable `data-*` hooks on every control and panel
the acts drive or read (`data-panel`, `data-field`, `data-action`, `data-section`, and
identifying attributes on repeated rows such as `data-line` and `data-covenant`), and
[`scripts/demo_console/locators.py`](../scripts/demo_console/locators.py) locates by them
alone. The demo used to find controls by label and role, so a reworded button broke an act
that proved nothing about wording. `tests/unit/test_console_data_hooks.py` fails the offline
gate when a hook the demo names is missing from `ui/`, or when an act locates by wording again.

An unset `NEXT_PUBLIC_API_BASE` used to ship a console its own CSP
blocked: `ui/lib/api.ts` fell back to the loopback API while `ui/lib/csp.mjs` admitted an
origin only when the variable was set, and `make ui-build` set it and hid the defect. Both
now resolve the base in `ui/lib/api-base.mjs`; `ui/tests/csp.test.mjs` pins the policy and
`make ui-check`, which builds with the variable unset, asserts the served `connect-src`
admits the origin the build calls.

**Closed by this work.** Grounding with Google Search was fully built — three adapters, a
per-analysis cost cap, refuse-don't-scrub query redaction, a licence-driven isolation rule
and a gate metric proving that rule holds — and reachable by nobody: no route, no client,
no UI, so `Provenance.WEB_GROUNDED` and its console badge could never render. Act 14 exists
because that is now wired end to end. Moving onto real filings closed three more: EDGAR
grounding that mixed fiscal years, an offline drafter that ignored its borrower, and an
extractor whose placeholder left the presenter demo reporting figures its evidence never
held.

`RenewalDiffService` was the sixth and last of them: written, contract-tested and reachable by
nobody, with no route computing a `renewal_delta`, nothing reading an uploaded `prior_memo`,
and `AnalysisManifest.missing()` absent from the wire, so nothing could tell an analyst that a
renewal needs the memo being renewed. Act 16 is the renewal act that was planned for this demo
and dropped for exactly that reason. The build now attaches a delta for the kinds written
against a prior memo, `GET .../checklist` serves the comparison against what the analysis
actually holds, and the console carries both: the checklist at intake and the delta as the
memo's first section.

Two things that act asserts are worth naming, because both are how this could quietly stop
being true. There is no memo of record here, so the delta NAMES the upload it was measured
against, and when there is nothing to compare it says so in a sentence rather than rendering an
empty table that would read as "nothing moved". And the prior memo is never read for this
period's figures or indexed as evidence: last cycle's numbers arriving with a quote and a page
would look exactly like figures read off the borrower's own statements.

**Still open.** Stale claims in the docs. [`DEMO.md`](../DEMO.md) refers to an "Upload borrower
evidence" panel and [`ui/README.md`](../ui/README.md) to a `.env.local.example`; neither
exists. [`README.md`](../README.md)'s HTTP table lists six routes where the service serves
about twenty-five. [`SPEC.md`](../SPEC.md) §6.1 is the current list.

## Gated in CI

The acts run on every pull request, in the `demo-browser` job. That target now builds the
console and runs the whole browser suite rather than excluding the console acts by marker, and
this repository's entry in `ci/gcp/repository-policy.json` gives the job what it needs to do
that: `npm_directory: ui` with `npm_directory_first` for the console's node modules, the pinned
`[demo]` extra through `extra_lockfiles`, and `demo_browser_required`, so an absent browser
fails the job instead of skipping it and reporting the same green a run reports.

The acts do not ride in a job of their own, and the reason is worth recording rather than
rediscovering. The runner refuses any make target outside a reviewed allowlist (`APPROVED_TARGETS`
in `org-metadata/scripts/render-gcp-ci-manifest.py`, mirrored in the runner's own
`run-grc-ci`), and `demo-console` is not on it: a job declaring
`"make_targets": ["demo-console"]` exits 2 with `refusing unapproved Make target` and runs
nothing at all. Adding a target to that allowlist means rebuilding and re-releasing the pinned
runner image, which is a fleet change rather than a repository one. So the acts ride in the
approved `demo-browser` target, and `make demo-console` stays the local entry point for the acts
without the presenter-server suite.

`.github/workflows/gate.yaml` is GENERATED from that policy and `--check` fails the gate on
drift, so the job cannot be added by editing the workflow here.
[`tests/unit/test_console_demo_is_gated.py`](../tests/unit/test_console_demo_is_gated.py) holds
both halves offline: that `demo-browser` builds the console and does not exclude the acts, and
that the rendered caller still hands that job its node modules and a required browser.

The demo's borrower is real and its figures are its own published SEC filings
([`SOURCES.md`](../demo/documents/SOURCES.md)); the facility, the covenant thresholds and
the policy limits are this bank's and invented. Do not run this against live borrower data
without your own legal, security and model-risk sign-off.
