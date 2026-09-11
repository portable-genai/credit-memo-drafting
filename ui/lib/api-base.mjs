// The console's API base, resolved ONCE for the two layers that depend on it.
//
// `lib/api.ts` sends every request to this base and `lib/csp.mjs` must admit its origin in
// `connect-src`. They used to decide separately, and they disagreed in exactly one state: with
// NEXT_PUBLIC_API_BASE unset the client fell back to the loopback API while the policy added an
// origin only when the variable was set. A console built with the variable unset therefore
// blocked its own first request, and said so only in the browser's developer console. `make
// ui-build` set the variable, which hid the defect from every check that built the console that
// way. The default, the three-state decision and the shape rules now live here, and both layers
// import them, so the two halves cannot drift apart again.

import { ConfiguredEmptyError } from "./env-setting.mjs";

/** Where an unconfigured console looks for its API: the loopback service `make run-api` starts. */
export const DEFAULT_API_BASE = "http://localhost:8093";

/** Raised when NEXT_PUBLIC_API_BASE names something no browser request could be sent to. */
export class InvalidApiBaseError extends Error {}

/**
 * The API base this console calls, in THREE states rather than two.
 *
 * Unset keeps the documented loopback default, which is what a laptop wants. Set-and-empty
 * refuses: an emptied value names nothing, and inheriting the default would point the console at
 * a loopback API and widen `connect-src` to match, so a deliberate lockdown would be
 * byte-identical to an omission. A value is used as given, less trailing slashes.
 *
 * Two shapes are legitimate. An absolute http(s) URL is a cross-origin API. A rooted path is the
 * SAME-ORIGIN deployment a host portal sets when it mounts this console under its own route.
 * A protocol-relative value is refused: it names a DIFFERENT host while looking rooted, so
 * treating it as same-origin would drop a genuinely cross-origin API out of `connect-src`.
 *
 * @param {import("./env-setting.mjs").EnvSetting} setting the three-state read of NEXT_PUBLIC_API_BASE
 * @returns {string}
 */
export function resolveApiBase(setting) {
  if (setting.isConfiguredEmpty) {
    throw new ConfiguredEmptyError(
      "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
        `so it cannot inherit the unset default (${DEFAULT_API_BASE}), which points this ` +
        "console at a loopback API and widens connect-src to match. Unset it to take that " +
        "default deliberately, or give it the API origin this deployment should call.",
    );
  }
  if (!setting.hasValue) return DEFAULT_API_BASE;
  const raw = setting.value;
  if (raw.startsWith("//")) {
    throw new InvalidApiBaseError(`NEXT_PUBLIC_API_BASE must name its scheme, got: ${raw}`);
  }
  if (!raw.startsWith("/")) {
    let parsed;
    try {
      parsed = new URL(raw);
    } catch {
      parsed = null;
    }
    // `new URL("api.example:8443/v1")` parses, with `api.example:` as its scheme, so parsing
    // alone does not tell a mistyped host from a URL. Only http(s) reaches a fetch.
    if (!parsed || (parsed.protocol !== "http:" && parsed.protocol !== "https:")) {
      throw new InvalidApiBaseError(
        `NEXT_PUBLIC_API_BASE must be an absolute http(s) URL or a rooted same-origin path, got: ${raw}`,
      );
    }
  }
  return raw.replace(/\/+$/, "");
}

/**
 * The origin `connect-src` must admit for a resolved base, or "" when it is same-origin.
 *
 * "" is the correct answer for a rooted path rather than an error: `'self'` already permits it,
 * and refusing it made the console answer 500 behind the portal, which is a working
 * configuration reported as a broken one. A root of "/" resolves to "" and is same-origin too.
 *
 * @param {string} base a value returned by {@link resolveApiBase}
 * @returns {string}
 */
export function apiOrigin(base) {
  if (base === "" || base.startsWith("/")) return "";
  return new URL(base).origin;
}
