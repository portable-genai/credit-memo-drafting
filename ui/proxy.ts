// The only place the console's CSP reaches the wire.
//
// `next.config.mjs` deliberately emits no `Content-Security-Policy`: a per-request nonce cannot
// be expressed in a static `headers()` table, and two layers both emitting a policy would give
// the browser two to intersect, with the stricter winning per directive.
//
// Both header sets below are required, and they do different jobs:
//
//   * The REQUEST header is where Next reads the nonce it stamps onto every script tag it emits.
//     Setting only this proves nothing to a browser, which never sees it.
//   * The RESPONSE header is what the browser actually enforces. Setting only this blocks the
//     very scripts the nonce was added to allow.
//
// The request header name must be exactly `Content-Security-Policy`; Next parses the nonce out of
// its `script-src`.

import { type NextRequest, NextResponse } from "next/server";

import {
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "./lib/csp.mjs";

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const csp = contentSecurityPolicy(process.env, nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);

  const legacy = frameOptions(frameAncestors(process.env));
  if (legacy) response.headers.set("X-Frame-Options", legacy);
  return response;
}

export const config = { matcher: "/:path*" };
