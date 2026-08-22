# Embedding and identity: client integration guide (Doc2 credit-memo-drafting)

This guide shows how an enterprise client runs the Doc2 Credit-Memo / Underwriting
Assistant and, when desired, embeds its UI inside an existing web application with secure
single sign-on (SSO) so users never see a second login. Everything described here is backed
by code on the current `main`: the FastAPI backend (`src/credit_memo/api/`), the
`IdentityPort` and its per-profile adapters (`ports/identity.py`,
`adapters/{local,gcp,onprem}/identity.py`), the embedding-surface controls in `api/app.py`
(CORS + CSP `frame-ancestors`), the UI build knobs (`ui/next.config.mjs`,
`ui/app/layout.tsx`, `ui/lib/api.ts`), and the profile bindings in `config/settings.yaml`.

For the deployment shapes below no application code changes are required to integrate: the
work is operational (choose a profile, set environment variables, add a proxy route and an
iframe tag). A short "further layers" note at the end points at deeper hardening.

---

## 1. The two pieces

The assistant ships as two cooperating pieces:

- **Backend**: a FastAPI service (default port `8093`) exposing the memo endpoints
  (`/v1/credit-memo`, `/v1/covenants`, `/v1/risk-flags`), health (`/healthz`), the persona
  list (`/v1/personas`), and the A2A agent card (`/.well-known/agent-card.json`).
- **UI**: a Next.js console (default port `3000`) that calls the backend and renders the
  cited memo. `NEXT_PUBLIC_EMBED=1` drops the UI's own header/chrome (`ui/app/layout.tsx`);
  the UI base path and API base are build-time env vars (`ui/next.config.mjs`,
  `ui/lib/api.ts`).

---

## 2. The three deployment shapes

Pick the cheapest shape the host can actually satisfy.

| # | Shape | Use when the host... | Host work | Identity |
|---|-------|----------------------|-----------|----------|
| 1 | **Embedded, same-origin reverse proxy** | controls its own edge (nginx / Next.js rewrites) and can federate its IdP into Cloud IAP. | Two proxy routes (`/agent/*`, `/agent/api/*`) plus one `<iframe src="/agent/">`. | IAP-verified `x-goog-iap-jwt-assertion`; the proxy forwards the header. |
| 2 | **Standalone behind Cloud IAP** | has no host app, or wants a separate console at its own URL. | DNS + HTTPS LB + IAP. | IAP-verified assertion; IAP + WIF gives SSO. |
| 3 | **Local dev, no auth** | is evaluating offline, no IdP. | None. | Seeded personas via `X-Dev-Persona` (`adapters/local/identity.py`). |

Because the iframe in shape 1 is first-party (same origin), there are no third-party-cookie
issues and no CORS to configure. Shapes 2 and 3 are top-level pages (not framed).

---

## 3. Shape 3: run locally, no auth

Local mode (`CREDIT_MEMO_PROFILE=local`) runs the entire pipeline offline: SQLite-backed
retrieval, a deterministic LLM, and no IdP, AD, or LDAP. Identity is resolved from a small
set of seeded dev personas (`adapters/local/identity.py`) selected by an `X-Dev-Persona`
request header, with the first persona as the default.

```bash
# Backend (repo root)
export CREDIT_MEMO_PROFILE=local
make run-api                      # uvicorn on http://localhost:8093

# UI (in ./ui)
cp .env.local.example .env.local  # NEXT_PUBLIC_API_BASE defaults to http://localhost:8093
npm install && npm run dev        # http://localhost:3000
```

The UI fetches `GET /v1/personas` and sends the chosen id as `X-Dev-Persona`. The seeded
personas deliberately span different entitlements and tenants (including a cross-tenant one),
so per-user and per-tenant authorization is demoable offline:

| Persona id | Subject | Tenant | Entitlement principals |
|-----------|---------|--------|------------------------|
| `analyst` | `demo.analyst@bank.example` | `demo-bank` | `group:credit-analyst`, `group:risk` |
| `approver` | `demo.approver@bank.example` | `demo-bank` | `group:credit-analyst`, `group:risk`, `group:credit-approver` |
| `auditor` | `demo.auditor@bank.example` | `demo-bank` | `group:audit` |
| `other-tenant` | `user@other-tenant.example` | `other-bank` | `group:credit-analyst` |

```bash
curl -s http://localhost:8093/v1/personas | python -m json.tool
curl -s -X POST http://localhost:8093/v1/credit-memo \
  -H 'Content-Type: application/json' -H 'X-Dev-Persona: auditor' \
  -d @your-case.json | python -m json.tool
```

In secure profiles `X-Dev-Persona` is ignored entirely (Section 5), and `/v1/personas`
returns an empty list, so leaving persona-selection code in the UI is harmless in production.

---

## 4. Shape 2: standalone behind Cloud IAP

When there is no host application, deploy the assistant on its own URL:

1. Deploy backend and UI behind the same HTTPS load balancer and Cloud IAP.
2. Set `CREDIT_MEMO_PROFILE=gcp` and `CREDIT_MEMO_IAP_AUDIENCE` so the backend verifies the
   IAP assertion (the exact structured protected-resource path, e.g.
   `/projects/<NUM>/global/backendServices/<ID>`). The backend refuses to verify without it.
3. Point the UI at the backend with `NEXT_PUBLIC_API_BASE`. If the UI and backend are on
   different origins, also set `CREDIT_MEMO_CORS_ORIGINS` to the UI origin (explicit
   allowlist, never `"*"`):

   ```bash
   export CREDIT_MEMO_CORS_ORIGINS="https://agent.client.com"
   export NEXT_PUBLIC_API_BASE="https://api.agent.client.com"
   ```

4. Share the URL with authorized users. IAP plus Workforce Identity Federation (WIF) gives
   silent SSO from the corporate IdP.

Leave `CREDIT_MEMO_FRAME_ANCESTORS` at its `'self'` default: nothing should iframe a
standalone deployment. The backend independently re-verifies the signed
`x-goog-iap-jwt-assertion` (`adapters/gcp/iap_identity.py`), the defense that survives an
edge bypass or a forged unsigned `x-goog-authenticated-user-*` header. The Google SDK imports
in that adapter are lazy, so the SDK-free `local`/`onprem` profiles never import them.

---

## 5. Shape 1: embed via same-origin reverse proxy

This is the smallest change for a host that controls its edge: serve the assistant under your
own origin at a sub-path (for example `/agent/`) via a reverse proxy, then drop an iframe
pointing at that same-origin path. The client owns exactly two things: a proxy route and an
iframe tag.

### 5a. Reverse-proxy `/agent/*` to the assistant service

**nginx**:

```nginx
# On https://portal.client.com
location /agent/ {
    proxy_pass         http://agent-ui.internal:3000/;   # the Next.js UI
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
}

# The UI's API calls (NEXT_PUBLIC_API_BASE=/agent/api) also resolve same-origin:
location /agent/api/ {
    proxy_pass         http://agent-backend.internal:8093/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # IAP runs in front of this origin, so the x-goog-iap-jwt-assertion header
    # is present on the inbound request and forwarded through to the backend.
}
```

**Next.js host app** (if the parent is itself Next.js, use `rewrites()` in its own config):

```js
// next.config.mjs of the PARENT app
const nextConfig = {
  async rewrites() {
    return [
      { source: "/agent/api/:path*", destination: "http://agent-backend.internal:8093/:path*" },
      { source: "/agent/:path*",     destination: "http://agent-ui.internal:3000/:path*" },
    ];
  },
};
export default nextConfig;
```

### 5b. Mount the assistant UI under the sub-path and hide its chrome

```bash
# Environment for the assistant UI (build-time)
NEXT_PUBLIC_BASE_PATH=/agent      # mount the UI (and assets) under the sub-path
NEXT_PUBLIC_API_BASE=/agent/api   # same-origin API calls (no CORS needed)
NEXT_PUBLIC_EMBED=1               # hide the UI's own header/nav chrome when embedded
```

### 5c. The iframe tag (host page)

```html
<!-- On https://portal.client.com, inside your existing page -->
<iframe
  src="/agent/"
  title="Credit-Memo Assistant"
  style="width:100%; height:100%; border:0;"
  loading="lazy">
</iframe>
```

Give the iframe a sized container: `height:100%` only renders correctly inside a host
container that already has a fixed pixel height (there is no child-to-parent resize message
in this shape).

### 5d. Allow the parent origin to frame the UI

The backend emits `Content-Security-Policy: frame-ancestors <CREDIT_MEMO_FRAME_ANCESTORS>`
via middleware (`api/app.py`), and the Next.js UI emits the same directive, inside a fuller
policy, on the document a browser actually frames (`ui/lib/csp.mjs`, applied by `ui/proxy.ts`;
see 5e). Both read the variable in three states:

| `CREDIT_MEMO_FRAME_ANCESTORS` | CSP directive | `X-Frame-Options` |
|---|---|---|
| unset | `frame-ancestors 'self'` | `SAMEORIGIN` |
| set and empty | `frame-ancestors 'none'` | `DENY` |
| set to one or more origins | `frame-ancestors <origins>` | not sent |

Unset and set-and-empty are different answers, so they get different results. Emptying the
allowlist is an expressed intent and it means "nobody may frame this", which CSP spells
`'none'`. Do not leave the variable assigned an empty value expecting the default: comment
it out instead.

`X-Frame-Options` is only a backstop for browsers predating `frame-ancestors`, and it cannot
express a multi-origin allowlist (`ALLOW-FROM` was never widely implemented), so the
allowlist case is left to the CSP directive alone rather than sent a `DENY` that would block
the very embed it was configured for.

```bash
export CREDIT_MEMO_FRAME_ANCESTORS="https://portal.client.com"
# multiple parents are space-separated, per the CSP grammar:
# export CREDIT_MEMO_FRAME_ANCESTORS="https://portal.client.com https://admin.client.com"
# nobody may frame it at all (note: this is what an EMPTY value means, not the default):
# export CREDIT_MEMO_FRAME_ANCESTORS=""
```

Scope note: `frame-ancestors` is honored only on the HTTP response of the document the
browser actually frames, and only when delivered as a real response header (not a
`<meta http-equiv>`). In this shape the framed document is served same-origin through the
proxy, so the backend header reaches it.

### 5e. The console's own Content-Security-Policy

The framed document is served by Next.js, not by the API, so the API's middleware never touches
it. The console builds its own full policy in ONE module, `ui/lib/csp.mjs`, and exactly one layer
puts it on the wire: `ui/proxy.ts`, per request. `ui/next.config.mjs` deliberately emits no
`Content-Security-Policy` and no `X-Frame-Options` at all, only the two genuinely static headers
(`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`). A policy emitted from two
layers is not additive: the browser intersects them and the stricter wins per directive, which is
how a "fix" in one layer silently deletes the other's.

The served policy is default-deny (`default-src 'self'`, `base-uri 'self'`, `form-action 'self'`,
`object-src 'none'`), widens `connect-src` to the ORIGIN of `NEXT_PUBLIC_API_BASE` when the
console is deployed cross-origin from its service, and carries the same three-state
`frame-ancestors` as the table above.

`script-src` is the load-bearing part. It reads `'self' 'nonce-<per-request>' 'strict-dynamic'`.
Next serves its hydration bootstrap as an INLINE script carrying the Flight payload, so a bare
`script-src 'self'` blocks it: the server HTML renders, `__next_f` never fills, React never
attaches, and the console shows all of its controls while none of them does anything. Headers,
type-check, build and screenshots all look correct in that state.

Two things must BOTH hold or the nonce path fails, in opposite directions:

1. `proxy.ts` sets the policy on the REQUEST headers as well as the response. The request copy is
   where Next reads the nonce it stamps onto every script tag; the response copy is what the
   browser enforces. Either one alone is broken.
2. The route must be DYNAMICALLY rendered, which is why `ui/app/layout.tsx` sets
   `export const dynamic = "force-dynamic"`. A statically prerendered page was built before the
   nonce existed, so nothing carries it, and `'strict-dynamic'` switches off the `'self'`
   fallback that had at least been loading the chunk scripts: the half-configured state blocks
   strictly MORE than no fix at all. `next.config.mjs` refuses to build or boot without that line.

Because that failure is invisible to every check that does not execute the page,
`ui/scripts/assert-hydratable.mjs` starts the BUILT server, fetches the served document and
asserts that every directive is present and non-empty, that the response carries a nonce, and
that every `<script>` tag carries that same nonce. It runs last in `make ui-check` and in CI. A
header-string assertion cannot stand in for it: the header is byte-identical in the working and
the broken case.

---

## 6. The identity contract

The single invariant, preserved across every shape: the server never trusts a client-asserted
actor or ACL. `get_principal` (`api/security.py`) builds a `RequestContext` from inbound
headers only, asks the active `IdentityPort` adapter to resolve a verified `Principal`, and a
failure is a hard 401. The request schemas carry no `actor` field. `CreditMemoService.build`
(and the covenant / risk-flag routes) receive `actor=principal.actor` and
`principals=principal.principals` from the verified `Principal`; the audit actor and the
entitlement principals merged into governed-retrieval ACLs both flow from here. There is no
path by which a caller can assert who they are or what they may see.

The `Principal` (`domain/identity.py`) models everything enforcement needs: `subject` (the
audit actor), `principals` (entitlement groups/ACL), `tenant` (multi-tenant partition),
`assurance` (auth-strength hint), and `source` (which adapter resolved it).

Identity options by profile (all implemented):

| Profile | What it does | Where it lives |
|---------|--------------|----------------|
| `local` | Seeded dev personas selected by `X-Dev-Persona`, no IdP. Default is the first persona; an unknown id is a 401. | `adapters/local/identity.py` |
| `gcp` / `platform` | Verifies the ES256-signed `x-goog-iap-jwt-assertion` (signature, `iss`, `exp`/`iat`, and the structured `aud` from `CREDIT_MEMO_IAP_AUDIENCE`) against Google's IAP public keys; `tenant` from the `hd` claim. | `adapters/gcp/iap_identity.py` |
| `onprem` | Fail-closed placeholder: raises `NotImplementedError` rather than trusting an unverified caller. Fill it in to verify your enterprise IdP (OIDC/SAML) and map claims to a `Principal`. | `adapters/onprem/identity.py` |

Defense-in-depth PEP: edge IAP/Apigee authenticates at ingress, the Hrz1 guardrail applies
central policy, and this backend re-validates the assertion and derives identity itself
(`api/security.py` plus the active adapter), then enforces per-user ACLs in governed
retrieval. Each layer assumes the others may be bypassed. This is the seam that defeats actor
spoofing and the confused-deputy risk.

---

## 7. Configuration reference

| Variable | Side | Purpose |
|----------|------|---------|
| `CREDIT_MEMO_PROFILE` | backend | `local` \| `gcp` \| `platform` \| `onprem`. Selects the identity adapter (and the whole adapter set). |
| `CREDIT_MEMO_IAP_AUDIENCE` | backend | The IAP audience string (the exact structured resource path) the backend verifies against. Required in `gcp`/`platform`. |
| `CREDIT_MEMO_CORS_ORIGINS` | backend | Explicit origin allowlist for the cross-origin / standalone case. Never `"*"`. Unset gives the dev origins under a deliberately chosen local profile and nothing otherwise; set and empty DENIES every cross-origin request. |
| `CREDIT_MEMO_FRAME_ANCESTORS` | backend + UI | CSP `frame-ancestors` allowlist: parent origins permitted to iframe the UI. Unset is `'self'`; set and empty is `'none'`. See 5d. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | The same allowlist for the Next.js document headers, read in the same three states. Unset is `'self'`; set and empty is `'none'`. Read per request by `ui/proxy.ts`, so it is a RUNTIME variable on the console's server. See 5e. |
| `NEXT_PUBLIC_API_BASE` | UI | Backend base URL the UI calls. Build-time. |
| `NEXT_PUBLIC_BASE_PATH` | UI | Sub-path the UI is mounted under. Blank keeps standalone. Build-time. |
| `NEXT_PUBLIC_EMBED` | UI | Set to `1` to hide the UI's own chrome. Build-time. |
| `X-Dev-Persona` | request header | Local profile only. Selects a seeded dev persona; ignored in secure profiles. |

---

## 8. Checklists

### Client-side integration checklist

**Shape 1 (same-origin reverse proxy):**

- [ ] Reverse-proxy route mapping `/agent/*` to the assistant UI service (5a).
- [ ] Reverse-proxy route mapping `/agent/api/*` to the assistant backend service.
- [ ] `<iframe src="/agent/">` on the host page in a sized container (5c).
- [ ] `CREDIT_MEMO_FRAME_ANCESTORS` set to the exact parent origin(s) (5d).
- [ ] IdP federated into IAP (WIF) so users carry one session through.

**Shape 2 (standalone):**

- [ ] DNS + HTTPS LB + IAP fronting the deployment.
- [ ] `CREDIT_MEMO_PROFILE=gcp` and `CREDIT_MEMO_IAP_AUDIENCE` set.
- [ ] URL shared with authorized users/groups.

### Security checklist

- [ ] **HTTPS everywhere** (the LB terminates TLS; IAP requires it).
- [ ] **IAP audience configured**: `CREDIT_MEMO_IAP_AUDIENCE` set to the exact structured
      protected-resource path in any IAP profile (the backend refuses to verify without it).
- [ ] **Framing locked down**: `CREDIT_MEMO_FRAME_ANCESTORS` set to the exact parent
      origin(s); `'self'` for standalone; never a wildcard.
- [ ] **Origins locked down**: same-origin proxy (no CORS) for shape 1; otherwise
      `CREDIT_MEMO_CORS_ORIGINS` is an explicit allowlist, never `"*"`.
- [ ] **No client-asserted identity trusted**: production uses `gcp`/`platform` (or an
      implemented `onprem`), never `local`. The request body carries no `actor`.

---

## 9. Further layers (not built in this slice)

This slice implements same-origin embedding and IAP/persona identity. Deeper hardening is
documented in the reference implementation, `cdd-sow-research`
(`docs/embedding-and-identity.md`), and would be added on the same seams here:

- **Cross-origin embedding** for hosts that cannot run a proxy or federate into IAP: a
  versioned loader plus a web-component tag, a host-to-iframe `postMessage` contract, and a
  bearer-token-in-memory handoff verified by a new JWKS adapter on the `IdentityPort` seam.
- **Mode 6 launch-in-new-tab** OIDC redirect login (a self-issued session cookie) for the
  simplest possible portable integration.
- **Per-hop OAuth2 token exchange (OBO) + Workload Identity + mTLS** to the Hrz platform
  services, and **DPoP / step-up (acr/amr)** for high-value actions such as approver sign-off.
- **Per-tenant framing/CORS/issuer policy** (request-time, keyed by the resolved tenant) and
  **fail-closed KB tenant partitioning** for a shared multi-tenant deployment.
- **Trusted Types** on the Next.js responses, for the cross-origin framed case. The rest of the
  hardened UI-document CSP (nonce-based `script-src`, scoped `connect-src`) is built: see 5e.
