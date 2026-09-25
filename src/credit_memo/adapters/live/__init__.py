"""``live`` profile adapters: real SEC EDGAR grounding, answered by the local model.

The live profile is the laptop lane (owner decision 2026-09-23, amending 2026-08-30): memo
grounding comes from real public SEC EDGAR records (plus any uploaded borrower documents),
the peer comparison uses real same-SIC filed figures, and the CORE model is the fleet's
local open-weight model through the shared ``hex_service_kit.localmodel`` client.
Everything else reuses the SDK-free local adapters, so custody of the index and the audit
trail stays on the machine. The fictional built-in corpus never appears under this profile.

Gemini appears in exactly one place: the OPTIONAL public-web research leg
(:mod:`.web_research`), and only while ``CREDIT_MEMO_RESEARCH_ENABLED`` is on. With it off,
the default, the profile needs no cloud credentials at all. The UI's model pill states that
the runtime is local and names the local model that answers.
"""
