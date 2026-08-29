// The console's Content-Security-Policy, in ONE module so it is built once and read by every
// layer that needs it.
//
// Living inline in `next.config.mjs`, emitted through the static `headers()` table, would carry
// a single directive: `frame-ancestors`. That table cannot express a per-request
// value, which is exactly what a script nonce is, so the console shipped with no `default-src`,
// no `script-src`, no `object-src` and no `base-uri` at all: anything the page referenced could
// load from anywhere, and a `<base>` tag injected into the document could re-point every relative
// URL on it.
//
// Adding `script-src 'self'` alone would have been worse than nothing. Next serves its hydration
// bootstrap as an INLINE script carrying the Flight payload, so a bare `'self'` blocks it,
// `__next_f` never fills, React never attaches, and the console renders its controls as dead
// markup while the headers, the type-check, the build and every test stay green. So the policy
// takes a per-request nonce, minted in `proxy.ts`, plus `'strict-dynamic'` so the nonced
// bootstrap may load its own chunks and nothing else may run.
//
// `next.config.mjs` no longer emits a `Content-Security-Policy` at all. Two layers both setting
// it would give the browser two policies to intersect, and the stricter one wins per directive,
// which would quietly reinstate the defect this module exists to remove.

/**
 * Origin of the API base, when the console is deployed cross-origin from its service.
 *
 * A rooted path is the SAME-ORIGIN deployment, which is what a host portal mounting this console
 * under its own route sets. There is no second origin to name there, and `'self'` already permits
 * it, so "" is the correct answer rather than an error: refusing it made the console answer 500
 * behind the portal, which is a working configuration reported as a broken one.
 *
 * A protocol-relative value is still refused. It names a DIFFERENT host while looking rooted, so
 * treating it as same-origin would drop a genuinely cross-origin API out of `connect-src`, which
 * is the silent-drop this function exists to prevent.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string} an origin to add to `connect-src`, or "" when same-origin
 */
function apiOrigin(env) {
  const raw = (env.NEXT_PUBLIC_API_BASE || "").trim();
  if (!raw) return "";
  if (raw.startsWith("//")) {
    throw new Error(`NEXT_PUBLIC_API_BASE must name its scheme, got: ${raw}`);
  }
  if (raw.startsWith("/")) return "";
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE must be an absolute URL or a rooted same-origin path, got: ${raw}`,
    );
  }
}

/**
 * Who may frame this console, in the SAME three states the service resolves.
 *
 * This mirrors `credit_memo.api.app._frame_ancestors` deliberately: the backend's CSP middleware
 * covers API responses, but the document a browser frames is served by Next, so the two halves of
 * the embedding posture must agree or an operator gets one answer from the API and another from
 * the page. Unset keeps the shipped `'self'`. Set to something naming no origin means the
 * operator expressed an intent that selected nothing, and CSP spells that `'none'`, not "same
 * origin may". Emitting the bare directive instead would be a parse error, and a browser that
 * discards the directive has no framing restriction left at all.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export class WildcardOriginError extends Error {}

/**
 * Exact tokens that may never be a framing ancestor.
 *
 * The set exists for `null`, which the asterisk rule below cannot see: it carries no asterisk and
 * is a wildcard by BEHAVIOUR rather than by spelling, because a sandboxed iframe presents a null
 * origin, so `frame-ancestors null` admits framing from a document whose own origin the browser
 * has already discarded. The other three are already refused by the asterisk rule and are named
 * here anyway, so the refused vocabulary is one list a reader can check rather than something
 * they have to derive from two rules at once.
 */
const WILDCARD_TOKENS = new Set(["*", "'*'", "null", "*.*"]);

/**
 * True when a token may not be a framing ancestor: one of the named tokens, or anything carrying
 * an asterisk. Matching is exact, so `https://nullify.example` stays a perfectly good origin.
 *
 * @param {string} token
 * @returns {boolean}
 */
function isWildcard(token) {
  return WILDCARD_TOKENS.has(token) || token.includes("*");
}

export function frameAncestors(env) {
  const raw = env.NEXT_PUBLIC_FRAME_ANCESTORS;
  if (raw === undefined || raw === null) return "'self'";
  const named = raw.split(/\s+/).filter(Boolean);
  const wildcards = named.filter(isWildcard);
  if (wildcards.length) {
    throw new WildcardOriginError(
      `NEXT_PUBLIC_FRAME_ANCESTORS origin policy must never contain a wildcard, got ` +
        `${JSON.stringify(wildcards)}. A wildcard lets any page frame the console and drive ` +
        "it as the signed-in user, a partial one (https://*.example) trusts every " +
        "subdomain including one an attacker took, and `null` is the origin a sandboxed iframe " +
        "presents, which is the same permission spelled without an asterisk. Name each " +
        "permitted origin in full.",
    );
  }
  return named.join(" ") || "'none'";
}

/**
 * The `X-Frame-Options` equivalent of `ancestors`, or "" where none exists.
 *
 * The pre-CSP backstop for browsers that ignore `frame-ancestors`. It expresses exactly two of
 * the three states, so a NAMED parent origin gets no header rather than a DENY that would break
 * the embed it was configured for. Mirrors `credit_memo.api.app._frame_options`.
 *
 * @param {string} ancestors
 * @returns {string}
 */
export function frameOptions(ancestors) {
  if (ancestors === "'self'") return "SAMEORIGIN";
  if (ancestors === "'none'") return "DENY";
  return "";
}

/**
 * The full default-deny policy.
 *
 * `style-src` carries `'unsafe-inline'` because the Next runtime injects critical CSS and there
 * is no nonce path for it. `script-src` does NOT: it takes the per-request nonce plus
 * `'strict-dynamic'`. Passing no nonce yields the strict `'self'` form, which is correct for any
 * response that is not a Next-rendered document and WRONG for one that is.
 *
 * @param {Record<string, string | undefined>} env
 * @param {string} [nonce] per-request nonce from {@link generateNonce}
 * @returns {string}
 */
export function contentSecurityPolicy(env, nonce) {
  // Dev only: Turbopack's HMR client evaluates the module updates it receives and opens a
  // websocket back to the dev server. Without both relaxations `npm run dev` serves a page that
  // renders completely and never hydrates, which is the failure
  // `org-metadata/docs/demos/demo-inventory.md` records. Neither is ever emitted by a production
  // build: `next build` / `next start` set NODE_ENV=production, so the policy below comes out
  // byte-identical to the one this console shipped before the branch existed.
  const isDev = env.NODE_ENV !== "production";
  const connectSrc = ["'self'", apiOrigin(env), isDev ? "ws: wss:" : ""]
    .filter(Boolean)
    .join(" ");
  const scriptSrc = [
    "script-src 'self'",
    nonce ? `'nonce-${nonce}' 'strict-dynamic'` : "",
    isDev ? "'unsafe-eval'" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    `frame-ancestors ${frameAncestors(env)}`,
  ].join("; ");
}

/** A fresh per-request nonce. Base64 of 16 random bytes from the Web Crypto global. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/** Raised when the nonce policy and the rendering mode disagree, which serves un-hydratable HTML. */
export class UnhydratableCspError extends Error {}

/**
 * Refuse a build whose CSP mints a nonce the rendered HTML can never carry.
 *
 * Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route. A
 * statically prerendered page was built before the nonce existed, so it emits bare script tags
 * while the header advertises a nonce, and because `'strict-dynamic'` switches off the `'self'`
 * fallback, that combination blocks strictly MORE than the unfixed policy did. The failure is
 * invisible to every check that does not execute the page, so it is refused at build time.
 *
 * No I/O happens here: the caller passes the source as a string, which keeps this module
 * importable from the edge-runtime proxy.
 *
 * @param {string} layoutSource contents of `app/layout.tsx`
 * @throws {UnhydratableCspError}
 */
export function assertHydratableCsp(layoutSource) {
  if (!/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(layoutSource)) {
    throw new UnhydratableCspError(
      'app/layout.tsx must set `export const dynamic = "force-dynamic"`. The CSP mints a ' +
        "per-request nonce, and Next can only stamp it onto script tags for a dynamically " +
        "rendered route. Statically prerendered HTML was built before the nonce existed, so " +
        "every script is blocked and the page never hydrates.",
    );
  }
}
