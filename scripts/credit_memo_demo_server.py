"""Live, presenter-controlled demo server for the credit-memo build (stdlib only).

Holds a real :class:`~credit_memo.domain.services.CreditMemoService` over the in-process
``local`` stack and reveals the *actual* memo one section per click — summary ->
financial analysis -> covenants (deterministic status) -> risk flags -> peer comps ->
maker-checker review — rendering the audit-first UI at each step. The memo is built once
(deterministically) on start / Restart; "Next" reveals the next cited section. No Google
Cloud, no API key, no extra dependencies.

    PYTHONPATH=src python scripts/credit_memo_demo_server.py [--port 8094]

Then open http://localhost:8094 and click "Next", or drive it with
``scripts/credit_memo_demo_playwright.py`` for a presenter-controlled walkthrough.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import credit_memo_demo as demo  # sibling script: reuse the synthetic Acme build
import render_credit_memo_ui as r  # sibling script: reuse the exact audit-first rendering

# The scripted reveal steps. Each "Next" reveals the section named by ``next``; the
# rendered page shows the step bar at index ``cur``.
STEPS = [
    {"cur": 0, "label": "Memo built — summary revealed", "next": "Show the financial analysis"},
    {"cur": 1, "label": "Financial analysis", "next": "Show the covenants (tested status)"},
    {
        "cur": 2,
        "label": "Covenants — deterministic compliance status",
        "next": "Show the risk flags",
    },
    {"cur": 3, "label": "Risk assessment", "next": "Show the peer comparison"},
    {
        "cur": 4,
        "label": "Peer comparison vs cohort median",
        "next": "Show the maker-checker review gate",
    },
    {"cur": 5, "label": "Maker-checker review gate — complete", "next": None},
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .pct{font-variant-numeric:tabular-nums;color:#cdd7e4;font-size:12px}
"""

# Which panels are visible at each reveal index (the others are dimmed to show progress).
_PANEL_ORDER = ["Summary", "Financial analysis", "Covenants", "Risk assessment", "Peer comparison"]


class DemoSession:
    """Builds the real memo once and reveals its cited sections one step at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        memo = demo.build_memo()
        self.data = demo.memo_payload(memo)
        self.idx = 0

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def advance(self) -> None:
        if not self.at_end:
            self.idx += 1

    def render(self) -> str:
        cur = STEPS[self.idx]["cur"]
        html = r.render_memo(self.data, cur=cur)
        html = self._dim_unrevealed(html, cur)
        return self._inject_controls(html)

    def _dim_unrevealed(self, html: str, cur: int) -> str:
        """Visually de-emphasise sections that have not been revealed yet."""
        for i, title in enumerate(_PANEL_ORDER):
            if i <= cur or cur >= len(_PANEL_ORDER):
                continue
            marker = f"<h2>{title}"
            html = html.replace(
                marker,
                marker.replace(
                    "<h2>",
                    "<h2 style='opacity:.35'>",
                ),
                1,
            )
        return html

    def _inject_controls(self, html: str) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        breaches = sum(1 for c in self.data["covenants"] if c["status"] == "breach")
        pill = (
            f"<span class='pct'>{len(self.data['citations'])} citations · {breaches} breach</span>"
        )
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"Next &nbsp;·&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete</button>"
        )
        bar = (
            f"<div class='democtl' data-demo='presenter-step' data-step='{self.idx}'>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} — <b>{r.esc(step['label'])}</b></span>"
            f"{pill}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'><button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/sources":
                self._send(r.render_sources(self._sess.data))
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live credit-memo demo server")
    parser.add_argument("--port", type=int, default=8094)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"Credit-memo demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
