"""Walk the demo's business steps against a DEPLOYED credit-memo service, and assert each.

`make demo-console` proves the acts against a console and API on this laptop. It cannot say
anything about a deployment, and the difference is not cosmetic: every defect this script was
written to catch passed the offline gate and failed the moment a managed model, a real IAM
policy and a real proxy were involved.

    CREDIT_MEMO_DEPLOYED_BASE   the app's API base, e.g.
                                https://rm-<ip>.nip.io/apps/credit-memo-drafting/api
    CREDIT_MEMO_DEPLOYED_TOKEN  a bearer token the deployment's edge accepts (behind IAP,
                                an OIDC token whose audience is the IAP OAuth client id)

Both unset skips, so this stays runnable in a checkout with no cloud access. What it asserts
is the same arithmetic the offline acts assert, recomputed here from the committed fixture
rather than matched against prose, plus the four things only a deployment exercises: that a
managed model returns a parseable structured answer, that its citations resolve to documents
somebody uploaded, that the reconciliation sees the borrower's own reported figure, and that
peers come back from a real filing index.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demo_console import fixtures as fx  # noqa: E402

from credit_memo.envread import setting_or_default  # noqa: E402

# Three-state reads, like everything else here: an emptied variable said something, and
# reading it as unset would silently check a different deployment from the one named.
BASE = setting_or_default("CREDIT_MEMO_DEPLOYED_BASE", "").rstrip("/")
TOKEN = setting_or_default("CREDIT_MEMO_DEPLOYED_TOKEN", "")
TIMEOUT = float(setting_or_default("CREDIT_MEMO_DEPLOYED_TIMEOUT", "900"))

_PASS, _FAIL = "  \033[32mok\033[0m  ", "  \033[31mFAIL\033[0m  "


class CheckFailed(AssertionError):
    """A deployed behaviour did not hold."""


def _request(method: str, path: str, body: bytes | None, content_type: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, data=body, method=method)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json(method: str, path: str, payload: Any = None) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    status, raw = _request(method, path, body, "application/json" if body else "")
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, {"raw": raw[:400].decode("utf-8", "replace")}


def _multipart(path: str, files: list[tuple[str, str, bytes]], fields: dict[str, str]) -> Any:
    """One multipart POST, hand-rolled so this script needs nothing but the standard library."""
    boundary = "----credit-memo-verify-boundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for field, filename, blob in files:
        # A real media type, not octet-stream: the model refuses an unsupported mimeType
        # outright, so mislabelling the upload here would test the label rather than the app.
        media = "text/csv" if filename.endswith(".csv") else "text/plain"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{filename}"\r\nContent-Type: {media}\r\n\r\n'.encode()
            + blob
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    status, raw = _request(
        "POST", path, b"".join(parts), f"multipart/form-data; boundary={boundary}"
    )
    if status != 201:
        raise CheckFailed(f"opening the analysis answered {status}: {raw[:300]!r}")
    return json.loads(raw)


def _close(got: float | None, want: float, tolerance: float = 1e-6) -> bool:
    return got is not None and abs(got - want) <= tolerance


def main() -> int:
    if not BASE or not TOKEN:
        print(
            "skipped: set CREDIT_MEMO_DEPLOYED_BASE and CREDIT_MEMO_DEPLOYED_TOKEN to check a "
            "deployment. Nothing about a deployed service can be asserted without them."
        )
        return 0

    checks: list[tuple[str, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, detail if not condition else ""))
        print(
            f"{_PASS if condition else _FAIL}{name}"
            + (f"\n        {detail}" if detail and not condition else "")
        )

    print(f"Verifying the deployed credit-memo service at {BASE}\n")

    # 1. The credit file reaches custody, attributed to the verified caller.
    opened = _multipart(
        "/v1/analyses",
        [
            ("files", "flowserve-fy2025-spread.csv", fx.spread_csv()),
            ("files", "flowserve-covenant-position.txt", fx.covenant_position()),
            ("files", "flowserve-fy2025-financial-extract.txt", fx.financial_extract()),
        ],
        {
            "borrower_id": fx.BORROWER_ID,
            "borrower_name": fx.BORROWER_NAME,
            "doc_types": "analyst_spread,covenant_certificate,financial_statement",
        },
    )
    analysis_id = opened["analysis_id"]
    uploaded = {d["id"] for d in opened["documents"]}
    check("the credit file is in custody", len(uploaded) == 3, f"documents: {opened['documents']}")
    check(
        "custody is attributed to the verified caller",
        all("@" in (d.get("uploaded_by") or "") for d in opened["documents"]),
        "an upload with no attributed uploader",
    )

    spread_doc = next(d["id"] for d in opened["documents"] if d["filename"].endswith(".csv"))

    # 2. A managed model reads the figures off the document.
    status, candidate = _json(
        "POST",
        f"/v1/analyses/{analysis_id}/spreads/extract",
        {
            "document_ids": [spread_doc],
            "periods": [
                {"label": fx.PERIOD, "ends_on": fx.PERIOD_ENDED, "months": 12, "audited": True}
            ],
            "currency": "USD",
            "unit": "millions",
        },
    )
    check("the managed extractor returns a spread", status == 200, f"{status}: {candidate}")
    items = {i["code"]: i for i in (candidate.get("items") or [])}
    check(
        "every proposed figure says where it was read",
        bool(items) and all(i.get("quote") and i.get("document_id") for i in items.values()),
        "a proposed figure with no quote or no document",
    )

    # 3. A named person accepts them, rejecting one line and adjusting another.
    status, confirmed = _json(
        "POST",
        f"/v1/analyses/{analysis_id}/spreads/confirm",
        {
            "rejected": [{"code": fx.REJECTED_CODE, "period": fx.PERIOD}],
            "adjustments": [
                {
                    "code": fx.ADJUSTED_CODE,
                    "period": fx.PERIOD,
                    "before": fx.ADJUSTED_FROM,
                    "after": fx.ADJUSTED_TO,
                    "reason": fx.ADJUSTMENT_REASON,
                }
            ],
        },
    )
    check("the spread is confirmed", status == 200, f"{status}: {confirmed}")
    confirmed_codes = {i["code"]: i for i in (confirmed.get("items") or [])}
    check(
        "the confirmation carries a name",
        "@" in (confirmed.get("confirmed_by") or ""),
        f"confirmed_by: {confirmed.get('confirmed_by')!r}",
    )
    check(
        "the rejected line does not reach the spread",
        fx.REJECTED_CODE not in confirmed_codes,
        f"{fx.REJECTED_CODE} survived rejection",
    )
    check(
        "the adjusted figure is the analyst's, not the document's",
        confirmed_codes.get(fx.ADJUSTED_CODE, {}).get("provenance") == "user_entered",
        f"{confirmed_codes.get(fx.ADJUSTED_CODE)}",
    )

    # 4. The memo, through the whole managed pipeline.
    status, memo = _json(
        "POST",
        f"/v1/analyses/{analysis_id}/build",
        {
            "request": {
                "kind": "new_facility",
                "loan_type": "ci_term",
                "total_amount": 400.0,
                "purpose": "Refinance the existing term loan and fund working capital",
                "facilities": [
                    {
                        "id": "fac-1",
                        "facility_type": "term_loan",
                        "amount": 400.0,
                        "currency": "USD",
                        "tenor_months": 60,
                        "purpose": "Refinance the existing term loan and fund working capital",
                        "repayment_source": "Operating cash flow",
                        "security": "Unsecured, ranking pari passu with the existing senior facilities",
                    }
                ],
            }
        },
    )
    check("the memo builds", status == 200, f"{status}: {str(memo)[:300]}")
    if status != 200:
        return _report(checks)

    # The managed model actually said something, and cited what it was given. Both of these
    # were false on the first deployment while every offline test passed.
    check(
        "the managed model returned a memo rather than a truncated one",
        bool((memo.get("summary") or "").strip())
        and "does not support a confident credit memo" not in memo["summary"],
        f"summary: {(memo.get('summary') or '')[:160]!r}",
    )
    cited = {c["source_id"] for c in memo.get("citations", [])}
    check(
        "its citations resolve to documents somebody uploaded",
        bool(cited) and cited <= uploaded,
        f"cited {cited or 'nothing'}; uploaded {uploaded}",
    )

    # 5. The arithmetic, recomputed here from the committed fixture.
    ratios = {r["formula_id"]: r for r in memo.get("ratios", [])}
    check(
        "leverage is the engine's, not the model's",
        _close(ratios.get("leverage.v1", {}).get("value"), fx.gross_leverage()),
        f"{ratios.get('leverage.v1', {}).get('value')} != {fx.gross_leverage()}",
    )
    check(
        "a ratio it cannot compute says which line was missing",
        any(r["value"] is None and r["reason_missing"] for r in ratios.values()),
        "no skipped ratio names the line it needed",
    )

    covenants = {c["type"]: c for c in memo.get("covenants", [])}
    check(
        "the leverage covenant breaches on the bank's definition",
        covenants.get("leverage", {}).get("status") == "breach",
        f"{covenants.get('leverage')}",
    )
    check(
        "thin headroom is flagged at risk rather than green",
        covenants.get("current_ratio", {}).get("status") == "at_risk",
        f"{covenants.get('current_ratio')}",
    )
    check(
        "a covenant that is met is reported as met",
        covenants.get("dscr", {}).get("status") == "compliant",
        f"{covenants.get('dscr')}",
    )

    # 6. The reconciliation, which is the point of the whole demo.
    reported = covenants.get("leverage", {}).get("reported_value")
    check(
        "the borrower's own reported figure is carried",
        _close(reported, fx.REPORTED_NET_LEVERAGE, 0.01),
        f"reported_value: {reported!r}, expected about {fx.REPORTED_NET_LEVERAGE}",
    )
    tie_out = [f for f in memo.get("tie_out", []) if f["check"] == "certificate_agrees"]
    check(
        "the disagreement is reported rather than resolved quietly",
        bool(tie_out) and all(f["expected"] != f["actual"] for f in tie_out),
        f"tie_out: {[(f['check'], f.get('expected'), f.get('actual')) for f in memo.get('tie_out', [])]}",
    )

    # 7. The bank's own policy, and a grade it proposes rather than assigns.
    exceptions = {e["rule_id"]: e for e in memo.get("policy_exceptions", [])}
    check(
        "the bank's policy raises its exception, with a waiver authority",
        "LEV-01" in exceptions and bool(exceptions["LEV-01"].get("waiver_authority")),
        f"exceptions: {list(exceptions)}",
    )
    rating = memo.get("rating") or {}
    check(
        "a grade is proposed by the scorecard, not by the model",
        bool(rating.get("obligor_grade")) and rating.get("provenance") == "computed",
        f"rating: {rating.get('obligor_grade')!r} provenance={rating.get('provenance')!r}",
    )

    # 8. Peers, which only a real filing index supplies.
    peers = memo.get("peer_comparison", [])
    check(
        "peers come back from the filing index",
        bool(peers) and all(p.get("peers") for p in peers),
        "no peer comparison; the borrower may not have resolved on EDGAR",
    )

    check("every memo is marked for human review", bool(memo.get("requires_human_review")))

    # 9. The evidence can be taken away again.
    status, _ = _json("DELETE", f"/v1/analyses/{analysis_id}")
    check("the analysis can be deleted", status == 204, f"delete answered {status}")
    status, _ = _json("GET", f"/v1/analyses/{analysis_id}")
    check("the evidence is gone", status == 404, f"a deleted analysis answered {status}")

    return _report(checks)


def _report(checks: list[tuple[str, str]]) -> int:
    failed = [name for name, detail in checks if detail]
    print()
    if failed:
        print(f"{len(failed)} of {len(checks)} checks failed:")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"All {len(checks)} checks held against the deployment.")
    return 0


if __name__ == "__main__":
    start = time.monotonic()
    code = main()
    print(f"({time.monotonic() - start:.0f}s)")
    sys.exit(code)
