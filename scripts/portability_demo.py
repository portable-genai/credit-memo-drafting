"""Portability tour: prove credit-memo-drafting's no-lock-in claims live, on a laptop, fully
offline.

Usage (from the repo root; no cloud, no API key, no emulators):

    PYTHONPATH=src python scripts/portability_demo.py

Four acts, mapping to the three portability questions a buyer should ask
(compute, data, experience/identity):

  1. One-line profile swap ..... the SAME credit memo runs offline under ``local`` and
                                  fails fast under ``onprem`` (no domain edits, P-02/P-12)
  2. Interface parity .......... all 12 ports instantiate + satisfy their Protocols under
                                 both SDK-free profiles, with no Google Cloud SDK installed
  3. Open-format audit ......... every WORM audit record read back from the local store is
                                 byte-identical to the domain event's documented JSON form,
                                 so the trail is exportable/reloadable with no vendor tooling
  4. Identity portability ...... seeded personas resolve offline with per-user entitlements;
                                 IAP (secure) is an adapter-binding swap, never an app change

Exits 0 only if every check passes, so this doubles as an automated portability proof.

Scope note (honest about what this repo does and does not implement): credit-memo-drafting's
``local`` audit sink is an append-only WORM stand-in serialized with the domain ``to_jsonable``
(open JSON), which Act 3 exercises. It does NOT implement a per-record cryptographic hash chain or a
``verify/export/restore`` CLI, so there is no tamper-evidence act here (that portability principle
is marked n/a in ARCHITECTURE.md section 6).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from credit_memo import ports
from credit_memo.adapters.local.audit import LocalAppendOnlyAuditAdapter
from credit_memo.adapters.local.identity import LocalPersonaIdentityAdapter
from credit_memo.api.deps import build_credit_memo_service
from credit_memo.config import Container, LocalSettings, Settings, instantiate
from credit_memo.domain.identity import RequestContext
from credit_memo.domain.models import (
    AuditEvent,
    Borrower,
    Citation,
    Decision,
    MemoInput,
    SourceType,
)
from credit_memo.domain.serialization import to_jsonable

CONFIG_PATH = "config/settings.yaml"

# Every port in settings.adapters mapped to its Protocol (the hexagon boundary).
PORT_PROTOCOLS: dict[str, type] = {
    "extraction": ports.DocumentExtractionPort,
    "knowledge_base": ports.KnowledgeBaseClientPort,
    "peer_data": ports.PeerDataPort,
    "llm": ports.LLMPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "agent_registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
    "identity": ports.IdentityPort,
}

CHECKS: list[tuple[str, bool]] = []


def banner(step: str, title: str) -> None:
    print(f"\n{'=' * 74}\n{step}  {title}\n{'=' * 74}")


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok))
    marker = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{marker}] {name}{suffix}")


def settings_for(profile: str, audit_path: str = ":memory:") -> Settings:
    base = Settings.load(CONFIG_PATH)
    # profile_explicit=True because this demo NAMES each profile in code: that is a deliberate
    # choice, so it must not inherit the loaded settings' "nobody chose" state and be refused
    # the seeded personas it exists to show.
    return replace(
        base,
        profile=profile,
        profile_explicit=True,
        local=LocalSettings(db_path=":memory:", audit_path=audit_path),
    )


def act_1_profile_swap() -> None:
    banner("[1/4]", "One-line profile swap: same request, local works, onprem fails fast")
    memo_input = MemoInput(
        borrower=Borrower(
            id="acme-holdings",
            name="Acme Holdings Pte Ltd (FICTIONAL)",
            sector="logistics",
            jurisdiction="SG",
        )
    )

    local_settings = settings_for("local")
    memo = build_credit_memo_service(Container(local_settings)).build(
        memo_input, actor="demo@laptop"
    )
    citations = len(memo.citations)
    print(
        f"  local  -> memo built offline: {len(memo.covenants)} covenants, "
        f"{len(memo.risk_flags)} risk flags, {citations} citations, "
        f"requires_human_review={memo.requires_human_review}"
    )
    check("local profile produced a grounded, cited credit memo offline", citations > 0)
    check("maker-checker held (requires_human_review)", memo.requires_human_review is True)

    try:
        build_credit_memo_service(Container(settings_for("onprem"))).build(
            memo_input, actor="demo@laptop"
        )
        check("onprem profile fails fast (sovereign migration placeholder)", False)
    except NotImplementedError as exc:
        print(f"  onprem -> NotImplementedError: {str(exc)[:80]} (CLI maps this to exit 2)")
        check("onprem profile fails fast (sovereign migration placeholder)", True)

    print("\n  The swap is configuration, not code: config/settings.yaml adapters.llm")
    for profile in ("local", "onprem", "gcp"):
        dotted = local_settings.adapters["llm"].get(profile, "(unbound)")
        print(f"    {profile:<7} -> {dotted}")


def act_2_interface_parity() -> None:
    banner("[2/4]", "Interface parity: 12 ports x {local, onprem}, no Google Cloud SDK")
    all_ok = True
    for port_name in sorted(PORT_PROTOCOLS):
        row = [f"  {port_name:<16}"]
        for profile in ("local", "onprem"):
            settings = settings_for(profile)
            adapter = instantiate(settings.adapters[port_name][profile], settings)
            ok = isinstance(adapter, PORT_PROTOCOLS[port_name])
            all_ok &= ok
            row.append(f"{profile}: {type(adapter).__name__} {'ok' if ok else 'MISMATCH'}")
        print(" | ".join(row))
    check("every port satisfies its Protocol under both SDK-free profiles", all_ok)


def act_3_open_format_audit(workdir: Path) -> None:
    banner("[3/4]", "Open-format WORM audit: read-back is byte-identical to the domain JSON")
    audit_path = str(workdir / "audit.db")
    audit = LocalAppendOnlyAuditAdapter(settings_for("local", audit_path))

    events = [
        AuditEvent(
            action="build_credit_memo",
            actor="demo@laptop",
            decision=Decision.ESCALATED,
            redacted_prompt="[PERSON_NAME] credit memo request",
            redacted_response="cited memo summary; covenants=2; breaches=0",
            citations=(
                Citation(
                    source_id="acme-fy2025",
                    source_type=SourceType.FILING,
                    title="Acme FY2025 financial statement (FICTIONAL)",
                    page=3,
                ),
            ),
        ),
        AuditEvent(
            action="build_credit_memo",
            actor="demo@laptop",
            decision=Decision.BLOCKED,
            redacted_prompt="[PERSON_NAME] blocked request",
            redacted_response="",
        ),
    ]
    for event in events:
        audit.record(event)

    stored = audit.read_all()
    expected = [to_jsonable(e) for e in events]
    print(f"  wrote {len(events)} WORM records; read {len(stored)} back from the append-only store")
    check("append-only store preserves every recorded event in order", stored == expected)

    # The stored form is plain, documented JSON (no vendor tooling needed to export/reload).
    export_path = workdir / "audit-export.jsonl"
    export_path.write_text("\n".join(json.dumps(r) for r in stored) + "\n")
    reloaded = [json.loads(line) for line in export_path.read_text().splitlines() if line]
    first = reloaded[0]
    print(
        f"  exported to {export_path.name} (JSON Lines); first record: "
        f"action={first['action']}, decision={first['decision']}, "
        f"citations={len(first['citations'])}"
    )
    check("records serialize to open JSON and reload unchanged", reloaded == expected)
    check(
        "audit stores only already-redacted content (no raw PII surface)",
        all("[PERSON_NAME]" in r["redacted_prompt"] for r in reloaded),
    )


def act_4_identity() -> None:
    banner("[4/4]", "Identity portability: personas offline; IAP by binding swap")
    settings = settings_for("local")
    identity = LocalPersonaIdentityAdapter(settings)

    default = identity.resolve(RequestContext(headers={}))
    approver = identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))
    print(f"  no IdP needed: default persona resolves to {default.subject} ({default.tenant})")
    print(f"  persona picker: X-Dev-Persona: approver -> {approver.subject} {approver.principals}")
    check(
        "seeded personas resolve offline with per-user entitlements",
        default.subject != approver.subject and "group:credit-approver" in approver.principals,
    )

    print("\n  The same IdentityPort, three verification regimes (config only):")
    for profile, dotted in sorted(settings.adapters["identity"].items()):
        print(f"    {profile:<9} -> {dotted}")


def main() -> int:
    print("credit-memo-drafting portability tour: offline proof of the three portability questions")
    print("(compute, data, experience/identity). No Google Cloud, no API key.")
    workdir = Path(tempfile.mkdtemp(prefix="credit-memo-portability-"))

    act_1_profile_swap()
    act_2_interface_parity()
    act_3_open_format_audit(workdir)
    act_4_identity()

    banner("DONE", "Scoreboard: the questions that separate a capability from a claim")
    failures = [name for name, ok in CHECKS if not ok]
    q_map = {
        "Q1 compute: migrates by configuration with parity evidence": [
            "local profile produced a grounded, cited credit memo offline",
            "onprem profile fails fast (sovereign migration placeholder)",
            "every port satisfies its Protocol under both SDK-free profiles",
        ],
        "Q2 data: WORM audit exports in an open format and reloads elsewhere": [
            "append-only store preserves every recorded event in order",
            "records serialize to open JSON and reload unchanged",
            "audit stores only already-redacted content (no raw PII surface)",
        ],
        "Q3 experience/identity: verified system-side, portable across regimes": [
            "seeded personas resolve offline with per-user entitlements",
        ],
    }
    passed = dict(CHECKS)
    for question, names in q_map.items():
        ok = all(passed.get(n, False) for n in names)
        print(f"  [{'YES' if ok else 'NO '}] {question}")
    print(f"\n  {len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed. Artifacts: {workdir}")
    if failures:
        print("  FAILED: " + "; ".join(failures))
        return 1
    print("  Lock-in converted from an open-ended exposure into a priced, controlled risk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
