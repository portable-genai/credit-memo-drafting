# `credit-memo-drafting` UI: Credit-Memo / Underwriting Assistant console

A small React / Next.js console that renders the `credit-memo-drafting` memo with inline citation
chips, a covenant table, risk flags and peer comparisons.

It also carries a **public-context panel**, deliberately outside the memo. Grounded web
results may be shown only to the person who ran the query, so they are never posted back,
never written into the memo and never exported; the panel says so on its face and renders
Google's suggestion chips verbatim, as the licence requires. It appears only where the
deployment set `CREDIT_MEMO_RESEARCH_ENABLED`.

## Run locally

```bash
npm install
npm run dev                        # http://localhost:3000
```

There is no environment file to copy, and deliberately none to ship. `NEXT_PUBLIC_API_BASE` is
read in three states by `lib/api-base.mjs`: **unset** takes the documented loopback default
`http://localhost:8093`, which is what a laptop wants and what `make ui-check` builds against;
**set** is used as given, either an absolute http(s) URL for a cross-origin API or a rooted path
for the same-origin deployment a host portal mounts this console under; **set and empty**
refuses to start rather than inheriting the default, because an emptied variable names nothing
and a deliberate lockdown must not be byte-identical to an omission. An example file would
invite a fourth state, a copied value nobody chose, and Next inlines the variable at BUILD time,
so a value corrected in the environment afterwards changes nothing.

Point it at a running `credit-memo-drafting` API (`make run-api` in the repo root, FastAPI on :8093). The
console submits a borrower to `POST /v1/credit-memo` and renders the returned
`CreditMemo`: the summary, normalised financial metrics, covenants with a deterministic
tested status, risk flags, peer comparisons and the recommendation rationale - each with
citations, under a maker-checker (human-review) banner.

The synthetic data is fictional and the demo's borrower is a listed company, grounded on
its own published SEC filings. Neither is a real borrower of yours: do not use this against
live borrower data without your own legal, security and model-risk sign-off.

## Source map

| Path | What it owns |
|------|--------------|
| `lib/api-base.mjs` | The API base, resolved ONCE for the client (`lib/api.ts`) and the policy's `connect-src`: the loopback default when unset, a refusal when emptied, and the shape rules. One resolver is what keeps an unset console from blocking its own requests. |
| `lib/csp.mjs` | The Content-Security-Policy, built ONCE. Directives, the three-state `frame-ancestors` (mirroring the service's `_frame_ancestors`), the per-request nonce, and the build-time refusal of a nonce policy on a statically rendered route. |
| `proxy.ts` | The only layer that puts the policy on the wire: on the REQUEST headers, where Next reads the nonce it stamps onto script tags, and on the RESPONSE, where the browser enforces it. Both are required. |
| `next.config.mjs` | Base path, and the two genuinely static headers. Emits NO CSP: two layers emitting one means the browser intersects them and the stricter wins per directive. |
| `app/layout.tsx` | `export const dynamic = "force-dynamic"`, required by the nonce CSP rather than chosen for performance. |
| `scripts/assert-hydratable.mjs` | Starts the BUILT server and asserts the served markup, not the policy string. |

## Gate

```bash
make ui-install    # npm ci
make ui-check      # tsc --noEmit, node --test, next build, assert-hydratable
```

`assert-hydratable` runs LAST, against the artefact the build just produced. It exists because
every cheaper check passes in the broken state: a `script-src` with no nonce blocks Next's inline
hydration bootstrap, so `__next_f` never fills, React never attaches, and the console renders all
of its controls as dead markup while the headers, the type-check, the build and the unit tests
stay green. The unit tests in `tests/csp.test.mjs` cover only what a policy STRING can decide.
