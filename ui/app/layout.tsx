import type { Metadata } from "next";
import "./globals.css";

// Required by the nonce CSP, not a performance preference. `proxy.ts` mints a per-request script
// nonce, and Next can only stamp it onto the script tags of a DYNAMICALLY rendered route. A
// statically prerendered document was built before the nonce existed, so it would carry none
// while the header advertised one, and `'strict-dynamic'` switches off the `'self'` fallback that
// was at least loading the chunks: the half-configured state blocks strictly more than no fix at
// all. `next.config.mjs` refuses to build without this line; see ui/lib/csp.mjs.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "B2 Credit-Memo Assistant",
  description:
    "Grounded underwriting assistant: cited credit memos, covenants, risk flags and peer comparisons for a commercial bank's credit team. Decision support, not a credit decision.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // EMBED mode: the host page owns the chrome, so render children without our own
  // app header/branding wrapper. Standalone (unset/"0") keeps the full-page shell.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      <body className="min-h-screen">
        {embed ? (
          <main className="p-4">{children}</main>
        ) : (
          <>
            <header className="border-b border-ink-200 bg-white">
              <div className="mx-auto max-w-3xl px-4 py-4">
                <h1 className="text-lg font-semibold text-ink-900">
                  B2 · Credit-Memo Assistant
                </h1>
                <p className="text-sm text-ink-500">
                  Cited credit memos · region asia-southeast1 · synthetic data is fictional
                </p>
              </div>
            </header>
            {children}
          </>
        )}
      </body>
    </html>
  );
}
