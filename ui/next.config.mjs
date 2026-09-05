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
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
  // Standalone output: the deployed image copies `.next/standalone` and starts it with
  // `node server.js`, so the runtime container carries no npm and no package manager. See
  // ui/Dockerfile, and the same shape in the sibling consoles.
  output: "standalone",
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
