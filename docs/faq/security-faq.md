# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an identity adapter
(`api/security.py::get_principal`), never from the request body. The request schemas carry no
`actor` field, and any client-asserted actor or ACL is discarded. The audit actor and the
entitlement principals both come from the verified `Principal`. This repo owns **no web login
flow**: on the managed profiles identity is the **IAP-injected signed assertion**
(`adapters/gcp/iap_identity.py`); the `local` profile uses seeded dev personas (no IdP, offline
only). There is no `api/auth.py`, OIDC adapter, or session-cookie code to harden here.

### How is object-level authorization (multi-tenant isolation) enforced?

The retrieval ACL is derived server-side in `domain/entitlements.py`: a caller gets the
`borrower:<id>` retrieval principal only after an entitlement check (`may_access_borrower` /
`borrower_scope`) against the verified principal, so an authenticated in-tenant caller cannot
name any borrower they like. Evidence is tagged with **both** `borrower:<id>` and
`tenant:<tenant>` at ingest, and the knowledge-base ACL match is **subset-based and
fail-closed** (a reader must hold every tag on a passage), so a user in another tenant gets zero
passages for a borrower id they merely guessed. All three borrower routes answer **403** before
any retrieval. Proven in `tests/unit/test_entitlements.py` and
`test_api_identity.py::test_cross_tenant_persona_is_denied_borrower_evidence` (both verified RED
against the pre-fix behaviour).

### What about the service-to-service calls in the `platform` profile?

The platform adapters (`adapters/platform/_s2s.py`, sourced from the shared `hex-service-kit`)
require `https://` base URLs outside loopback (rejected at construction), attach a bearer
credential from `S2S_TOKEN`, and propagate the verified end-user actor as an HMAC-signed
`X-Cm-Actor` / `X-Cm-Actor-Sig` pair (key from `S2S_SIGNING_KEY`) rather than a trust-me
JSON field. All six platform delegates (`remote_audit`, `remote_guardrail`,
`remote_knowledge_base`, `remote_redaction`, `remote_registry`, `remote_evaluation`) validate
their base URL. The receiving platform services own verification.

### Is the demo/dev server safe? Does anything bind 0.0.0.0 by default?

No. There are two bounds, and the load-bearing one rides the **app object** rather than an
entry point.

`main()` binds **loopback (127.0.0.1)** via `hex_service_kit.resolve_bind_host`, and the
Makefile defaults `API_HOST` to `127.0.0.1`. On its own that is a property of one entry
point, not of the application: the Dockerfile `CMD` is
`uvicorn credit_memo.api.app:app --host 0.0.0.0 --port ${PORT}`, and a `uvicorn ... --host
0.0.0.0` typed by hand behaves the same way, so neither ever reaches that call. The real
bound is `add_loopback_exposure_guard`, registered on the app object as the outermost
middleware, so it holds however the service is started: a non-loopback peer is refused with a
503 before CORS, before the header baseline and before any route or dependency runs.

**What switches it off is the identity BINDING, and nothing else.** The guard asks the
adapter bound to the identity port whether it verifies the end user (see
`src/credit_memo/ports/identity.py`). The seeded persona adapter reads `X-Dev-Persona`, a
header the caller writes, so it declares `client-asserted` and the guard stays on, under
`live` exactly as under `local`; the on-premises placeholder resolves nobody, so it declares
`unimplemented` and the guard stays on; only the IAP adapter, which verifies a signed
assertion, declares `verified` and stands the guard down. A run that named NO profile is
bounded too, and additionally refuses the seeded personas outright, so a lost environment
variable cannot publish an unauthenticated API.

A service-to-service credential is deliberately **not** part of that decision. It
authenticates a calling service and no end user, so setting one changes nothing about the
end-user routes. A guard derived from it would switch off for exactly the routes it was
protecting.

`CREDIT_MEMO_ALLOW_INSECURE_DEMO=1` remains the single documented opt-out. Secure profiles
keep the container-friendly `0.0.0.0` (ingress is fronted by the platform / IAP and the
identity adapter verifies the caller). The demo server
(`scripts/credit_memo_demo_server.py`, port `8094`) is clearly dev-only. Proven by
`tests/unit/test_serving_path_exposure.py` and `tests/unit/test_netdefaults.py`.

### What HTTP security headers are set?

The API middleware (`app._security_headers`) and the Next.js UI (`ui/next.config.mjs`) both emit
CSP `frame-ancestors` and `X-Frame-Options` (the anti-clickjacking slice). CORS never uses `*`:
`cors_allowlist` requires an explicit `CREDIT_MEMO_CORS_ORIGINS`, and the localhost dev-origin
fallback is **local-profile-only**. Note the residual gap the practices audit records against
check C6: `X-Content-Type-Options: nosniff`, `Referrer-Policy`, HSTS and a scoped
`default-src 'self'` / `connect-src` CSP are not yet emitted. Harden this before you expose the
UI.

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store (`LocalAppendOnlyAuditAdapter`) wraps the shared
`hex_service_kit.audit.HashChainedAuditLog`: a SHA-256 chain over canonical JSON with SQLite
`UPDATE` / `DELETE` blocked by triggers, JSONL export / restore with per-line verification, and
a `verify_chain()` method. The module docstring states exactly which tamper classes are and are
not caught (a hash chain with no external anchor cannot detect a full-rewrite by itself). In
production the `gcp` profile uses a locked WORM bucket, which provides non-rewritability itself.
This repo does not *replace* the platform audit system (`agent-observability`); see
[features-faq.md](features-faq.md). Proven by `tests/unit/test_audit_chain.py`.

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, produced by
`uv pip compile`) are installed in CI and the Docker build; the base image is pinned by digest
(`python:3.12-slim@sha256:...`); every workflow `uses:` is a 40-char SHA; `.github/dependabot.yml`
proposes bumps; and a CI `supply-chain` job runs `pip-audit` over both lockfiles as a hard gate.
`ruff` is pinned exactly (`ruff==0.15.18`). The one caveat: `npm audit` on the UI is advisory
pending a breaking Next.js major bump; `pip-audit` is unaffected.

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` stores only the **names** of env vars
holding secrets (e.g. `CREDIT_MEMO_KMS_KEY`, `CREDIT_MEMO_AGENT_ENGINE`, `S2S_TOKEN`,
`S2S_SIGNING_KEY`); values are read at construction time and never logged. A literal-secret
scan over `src/` and `config/` is clean, and every fixture and figure is obviously fictional.

### What is explicitly out of scope / a residual risk?

- The security-header baseline is partial (check C6): nosniff / Referrer-Policy / HSTS /
  scoped-CSP are not yet emitted.
- The in-app posture assumes an edge WAF / rate limiter in front on the secure profiles.
- The hash chain needs the WORM bucket (or an external anchor) to resist a full rewrite.
- This is a reference build: run your own pen-test, threat model and model-risk review before
  any live-data deployment (stated throughout the docs).
