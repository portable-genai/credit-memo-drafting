#!/usr/bin/env python3
"""Credential-free anti-rot check for the real credit-memo-drafting presenter demo.

Two stages, both executed, neither reading hard-coded prose:

1. **In-process** -- the real :class:`DemoSession` builds the real memo and renders
   every presenter step.
2. **Served** -- the real ``ThreadingHTTPServer`` is started on an ephemeral port and
   the whole journey is driven over HTTP with ``POST /advance``. Every figure asserted
   at this stage is read out of the SERVED bytes through the stable ``data-*`` evidence
   hooks and compared with the value the RUNNING app computed, so a renderer that stops
   emitting a figure, a server that stops advancing, or a hook that gets renamed all
   fail here. A step that only rendered in-process was invisible to the old check.

The headless-browser journey over the same served pages lives in
``tests/browser/test_served_demo_ui.py`` and needs the pinned ``[demo]`` extra.
"""

from __future__ import annotations

import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from credit_memo_demo_server import STEPS, DemoSession, Handler


def _hook(html: str, attribute: str) -> str:
    """Read one stable ``data-*`` evidence hook out of served markup."""
    match = re.search(rf"{attribute}='([^']*)'", html) or re.search(rf'{attribute}="([^"]*)"', html)
    assert match, f"evidence hook {attribute} is missing from the served page"
    return match.group(1)


def _hooks(html: str, attribute: str) -> list[str]:
    return re.findall(rf"{attribute}='([^']*)'", html) or re.findall(
        rf'{attribute}="([^"]*)"', html
    )


def check_in_process() -> None:
    session = DemoSession()
    opening = session.render()
    assert "Acme" in opening and "data-demo='presenter-step'" in opening
    assert session.data["citations"] and session.data["requires_human_review"]
    page = opening
    while not session.at_end:
        session.advance()
        page = session.render()
        assert f"data-step='{session.idx}'" in page
    assert session.idx == len(STEPS) - 1 and "Demo complete" in page
    assert "Maker-checker review gate" in page
    print("PASS demo: cited memo sections and maker-checker end state rendered")


def check_served() -> None:
    """Drive the REAL server over HTTP and assert live figures from served bytes."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    data = server.session.data  # type: ignore[attr-defined]

    try:
        for index in range(len(STEPS)):
            with urllib.request.urlopen(f"{base}/", timeout=20) as response:  # noqa: S310
                assert response.status == 200
                page = response.read().decode("utf-8")

            # The served page is at the step the served app believes it is at.
            assert _hook(page, "data-step") == str(index), f"served step marker is not {index}"

            # Live figures: served bytes vs what the running app computed.
            assert _hook(page, "data-memo-borrower") == data["borrower"]["id"]
            assert _hook(page, "data-memo-citations") == str(len(data["citations"]))
            breaches = sum(1 for c in data["covenants"] if c["status"] == "breach")
            assert _hook(page, "data-memo-breaches") == str(breaches)
            assert (
                _hook(page, "data-memo-review") == str(bool(data["requires_human_review"])).lower()
            )

            panels = _hooks(page, "data-panel")
            for required in (
                "summary",
                "financial-analysis",
                "covenants",
                "risk-assessment",
                "peer-comparison",
            ):
                assert required in panels, f"served page lost the {required} panel hook"

            assert _hook(page, "data-covenant-count") == str(len(data["covenants"]))
            assert _hook(page, "data-covenant-breaches") == str(breaches)
            assert _hooks(page, "data-covenant-status") == [c["status"] for c in data["covenants"]]
            assert _hook(page, "data-metric-count") == str(len(data["financial_metrics"]))
            assert _hooks(page, "data-metric") == [m["name"] for m in data["financial_metrics"]]
            assert _hook(page, "data-risk-count") == str(len(data["risk_flags"]))
            assert _hooks(page, "data-peer-percentile") == [
                str(int(p["percentile"] * 100)) for p in data["peer_comparison"]
            ]

            if index < len(STEPS) - 1:
                request = urllib.request.Request(f"{base}/advance", method="POST", data=b"")
                with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                    assert response.status in (200, 303)
            else:
                assert "Demo complete" in page

        # The sources/audit page must serve too, with every citation present.
        with urllib.request.urlopen(f"{base}/sources", timeout=20) as response:  # noqa: S310
            sources = response.read().decode("utf-8")
        assert response.status == 200
        for citation in data["citations"]:
            assert citation["title"] in sources or citation["source_id"] in sources
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "PASS served: every presenter step, panel hook and live figure read back over "
        "HTTP from the running demo server"
    )


def main() -> int:
    check_in_process()
    check_served()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
