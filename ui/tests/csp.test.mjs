// What a STRING can decide about the console's CSP.
//
// These are NOT sufficient, and the reason matters. Every assertion here passed, byte for byte,
// in the broken state this policy was written to fix: the header was correct and the page was
// dead, because a statically prerendered document carries no nonce while the header advertises
// one. Only `scripts/assert-hydratable.mjs`, which starts the BUILT server and reads the served
// markup, can tell those two apart. These tests cover the half that is decidable from the policy
// string alone: that the directives exist, that none of them is empty, and that the three-state
// framing read matches the service's.

import assert from "node:assert/strict";
import test from "node:test";

import {
  UnhydratableCspError,
  WildcardOriginError,
  assertHydratableCsp,
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "../lib/csp.mjs";

/** Parse a policy string into directive -> value. */
function directives(csp) {
  return new Map(
    csp
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...value] = part.split(/\s+/);
        return [name, value.join(" ")];
      }),
  );
}

/** The environment a `next build` / `next start` deployment runs under. */
const PROD = { NODE_ENV: "production" };

test("the policy carries every directive a default-deny posture needs", () => {
  const parsed = directives(contentSecurityPolicy({}, "abc"));
  for (const name of [
    "default-src",
    "base-uri",
    "form-action",
    "object-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "connect-src",
    "frame-ancestors",
  ]) {
    assert.ok(parsed.has(name), `missing ${name}`);
  }
  assert.equal(parsed.get("object-src"), "'none'");
  assert.equal(parsed.get("base-uri"), "'self'");
});

test("no directive is ever emitted empty, in any of the three framing states", () => {
  for (const env of [{}, { NEXT_PUBLIC_FRAME_ANCESTORS: "" }, { NEXT_PUBLIC_FRAME_ANCESTORS: " " }]) {
    for (const nonce of [undefined, "abc"]) {
      for (const [name, value] of directives(contentSecurityPolicy(env, nonce))) {
        assert.notEqual(value, "", `${name} is empty for env ${JSON.stringify(env)}`);
      }
    }
  }
});

test("script-src takes the nonce and strict-dynamic only when a nonce exists", () => {
  assert.equal(
    directives(contentSecurityPolicy(PROD, "n0nce")).get("script-src"),
    "'self' 'nonce-n0nce' 'strict-dynamic'",
  );
  assert.equal(directives(contentSecurityPolicy(PROD)).get("script-src"), "'self'");
});

test("the dev server gets eval and a websocket, and a production build never does", () => {
  // `npm run dev` compiles with `eval` and talks to Turbopack's HMR endpoint over a websocket.
  // Without these two relaxations the dev-served console renders completely and never hydrates,
  // which is exactly the failure `org-metadata/docs/demos/demo-inventory.md` records. The
  // relaxations must therefore EXIST in development and must NEVER exist in a production build,
  // so both halves are pinned here: dropping either branch turns one of these assertions red.
  const dev = directives(contentSecurityPolicy({ NODE_ENV: "development" }, "n0nce"));
  assert.match(dev.get("script-src"), /'unsafe-eval'/);
  assert.match(dev.get("connect-src"), /\bws: wss:/);

  const prod = contentSecurityPolicy(PROD, "n0nce");
  assert.doesNotMatch(prod, /unsafe-eval/);
  assert.doesNotMatch(prod, /ws:/);
  assert.doesNotMatch(prod, /wss:/);
});

test("the production policy is byte-identical to the one that shipped before the dev branch", () => {
  // The dev branch is only safe if it is invisible to a deployment. This pins the whole
  // production string, so a relaxation leaking out of the `isDev` guard cannot pass review.
  assert.equal(
    contentSecurityPolicy(PROD, "n0nce"),
    "default-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'; " +
      "script-src 'self' 'nonce-n0nce' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'",
  );
});

test("frame-ancestors resolves in three states, matching the service", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "   " }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "  https://portal.example\n https://host.example " }),
    "https://portal.example https://host.example",
  );
});

test("X-Frame-Options is sent only for the two states it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  assert.equal(frameOptions("https://portal.example"), "");
});

test("connect-src widens to the API ORIGIN, not the full URL", () => {
  const parsed = directives(
    contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "https://api.example:8443/v1/credit-memo" }),
  );
  assert.equal(parsed.get("connect-src"), "'self' https://api.example:8443");
});

test("a rooted API base stays same-origin rather than being refused", () => {
  // A host portal mounting this console under its own route sets exactly this. Same-origin is
  // already covered by 'self', so it widens nothing, and refusing it answered 500 on a working
  // deployment. What must never happen is the value being dropped while it names a real origin,
  // which is the case below.
  const parsed = directives(
    contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "/apps/doc2/api" }),
  );
  assert.equal(parsed.get("connect-src"), "'self'");
});

test("a protocol-relative API base is refused rather than read as same-origin", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "//api.example/v1" }),
    /must name its scheme/,
  );
});

test("an API base that is neither absolute nor rooted is refused", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "api.example/v1" }),
    /NEXT_PUBLIC_API_BASE/,
  );
});

test("nonces are unique and base64", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = generateNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]+=*$/);
    seen.add(nonce);
  }
  assert.equal(seen.size, 50);
});

test("a layout without force-dynamic is refused at build time", () => {
  assert.throws(
    () => assertHydratableCsp("export default function RootLayout() {}"),
    UnhydratableCspError,
  );
  assert.doesNotThrow(() =>
    assertHydratableCsp('export const dynamic = "force-dynamic";\nexport default function L() {}'),
  );
});

test("a wildcard framing allowlist refuses, in bare and partial form", () => {
  // The FOURTH state. The backend refuses a wildcard; the console emits the header a browser
  // honours for the DOCUMENT, so a console that accepted `*` while the API refused it would be
  // the permissive half that governs. `https://*.example` is no better than the bare form: it
  // trusts every subdomain, including one an attacker managed to take.
  for (const value of ["*", "'self' https://*.parent.example"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      /wildcard/,
      `frameAncestors accepted ${value}`,
    );
    assert.throws(() => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"), /wildcard/);
  }
});

test("the wildcard refusal leaves the other three framing states alone", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: " https://a.example  https://b.example " }),
    "https://a.example https://b.example",
  );
});

test("the literal null is refused, though it carries no asterisk", () => {
  // The refusal tested `token.includes("*")`, which catches every wildcard that is SPELLED as one
  // and cannot see this one. A sandboxed iframe presents a null origin, so `frame-ancestors null`
  // admits exactly the framing the directive exists to refuse, from a document whose own origin
  // the browser has already thrown away. It is a wildcard by behaviour rather than by spelling,
  // so it needs naming rather than deriving.
  for (const value of ["null", "https://parent.example null", "null https://parent.example"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"),
      WildcardOriginError,
      `contentSecurityPolicy emitted ${JSON.stringify(value)}`,
    );
  }
});

test("every exact wildcard token is refused, asterisk or not", () => {
  // `*`, `'*'` and `*.*` already refuse under the asterisk rule. They are pinned against the
  // named set as well, so the two halves cannot drift apart and removing either one goes red.
  for (const value of ["*", "'*'", "*.*", "null"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
  }
});

test("refusing the tokens does not refuse an origin that merely contains one", () => {
  // The refusal is exact-token, not substring. A refusal that also refuses valid input is an
  // outage rather than a control, and `https://nullify.example` is a perfectly good origin.
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://nullify.example https://a.example" }),
    "https://nullify.example https://a.example",
  );
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://null.example" }), "https://null.example");
});
