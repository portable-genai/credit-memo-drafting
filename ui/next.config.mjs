/** @type {import('next').NextConfig} */
import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

// Evaluated by both `next build` and `next start`, so a console whose CSP mints a nonce that its
// rendering mode can never carry refuses to come up at all, rather than serving dead markup that
// looks correct in every screenshot. See ui/lib/csp.mjs.
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

// Mount the UI (and its assets) under a reverse-proxy sub-path when embedding
// same-origin (e.g. NEXT_PUBLIC_BASE_PATH=/agent). Blank keeps the standalone build
// unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    // NO Content-Security-Policy and NO X-Frame-Options here. Both are emitted per request by
    // proxy.ts, because the policy carries a per-request script nonce and this table cannot
    // express one. A CSP set in both places is not additive: the browser intersects the two and
    // the stricter wins per directive, so the static copy would silently delete the nonce path
    // and the console would render as dead markup again. Only the headers that are genuinely
    // static live here.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
