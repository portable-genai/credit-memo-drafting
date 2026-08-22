"""``live`` profile adapters: real SEC EDGAR grounding and a local model server.

The live profile is the demo-facing stack: memo grounding comes from real public SEC
EDGAR records (plus any uploaded borrower documents), the peer comparison uses real
same-SIC filed figures, and generation runs on a local OpenAI-compatible model server.
Everything else reuses the SDK-free local adapters. The fictional built-in corpus
never appears under this profile.
"""
