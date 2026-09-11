# The business use-case demo

One deal, walked end to end through the product a credit team would actually use: the
built console talking to the real service. Eighteen acts, each a beat a credit audience
recognises, and each one asserted so the demo cannot quietly rot.

```bash
# Build the console once (its API base is inlined at build time), then present.
make walkthrough                      # a browser opens; all eighteen acts

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
| 16 | Is this even bankable | The `TEN-01` knockout, and the absent rating |
| 17 | What it will not do | The inline refusal, then the amber guardrail notice |
| 18 | The evidence goes away | The 404 that does not confirm the analysis exists |

Acts 12, 13, 15 and 18 are driven over the API rather than the console, because the console
has no control for them (see **Gaps** below). Where there is something to look at, it still
goes on screen: act 14 renders the committee pack in a browser tab.

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
prints the eighteen titles. Slow motion is a launch-time Playwright setting, so the
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

**Closed since.** The console now carries stable `data-*` hooks on every control and panel
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

**Still open.** `RenewalDiffService` is written, contract-tested and reachable by nobody —
no route, no wire field, no console control. A renewal act was planned for this demo and
dropped for exactly that reason. It is the same pattern, and it is still there.



Recorded here rather than fixed, because each is product work with its own review:

1. **Four capabilities are API-only.** Export, memo amendment plus revisions, comments and
   delete have no console control; `ui/lib/api.ts` has no client for any of them. The API's
   CORS allowlist compounds it — `allow_methods` is `GET, POST, OPTIONS`, so a browser
   console could not reach `PATCH` or `DELETE` cross-origin even if the buttons existed.
2. **`RenewalDiffService` is unreachable.** It is written, unit-tested and bound to nothing:
   no route computes `renewal_delta`, nothing reads an uploaded `prior_memo`, and
   `AnalysisManifest.missing()` — which would tell an analyst a renewal needs the prior memo
   — is not on the wire. A renewal act was planned for this demo and removed for that
   reason. This is a sixth instance of the pattern in note 1.
3. **Stale claims in the docs.** [`DEMO.md`](../DEMO.md) refers to an "Upload borrower
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

The demo's borrower is real and its figures are its own published SEC filings
([`SOURCES.md`](../demo/documents/SOURCES.md)); the facility, the covenant thresholds and
the policy limits are this bank's and invented. Do not run this against live borrower data
without your own legal, security and model-risk sign-off.
