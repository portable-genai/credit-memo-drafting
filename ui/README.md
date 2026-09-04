# `credit-memo-drafting` UI: Credit-Memo / Underwriting Assistant console

A small React / Next.js console that renders the `credit-memo-drafting` credit memo with inline citation
chips, a covenant table, risk flags and peer comparisons.

## Run locally

```bash
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE (default http://localhost:8093)
npm install
npm run dev                        # http://localhost:3000
```

Point it at a running `credit-memo-drafting` API (`make run-api` in the repo root, FastAPI on :8093). The
console submits a borrower to `POST /v1/credit-memo` and renders the returned
`CreditMemo`: the summary, normalised financial metrics, covenants with a deterministic
tested status, risk flags, peer comparisons and the recommendation rationale - each with
citations, under a maker-checker (human-review) banner.

The synthetic data is fictional; do not use this against live borrower data without your
own legal, security and model-risk sign-off.

## Source map

| Path | What it owns |
|------|--------------|
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
