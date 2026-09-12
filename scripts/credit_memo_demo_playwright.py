"""Presenter-controlled Playwright walkthrough of the live credit-memo demo.

Drives a headed browser through the cited credit-memo build served by
``scripts/credit_memo_demo_server.py``. It is **paced by the presenter**: before each step
it prints the business points to make, in order, and waits for you to press Enter, then
performs the action (click "Next") and highlights the panel to look at. You stay in control
of timing.

Each point is a phrase to say; its justification prints underneath in a dimmer hand, for
the question the phrase provokes rather than to be read out. See
:mod:`demo_console.narrative`, which the nineteen-act console walkthrough renders through
too, so the two demos read the same way.

Usage (two terminals)::

    # terminal 1 — the live demo server
    PYTHONPATH=src python scripts/credit_memo_demo_server.py

    # terminal 2 — the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/credit_memo_demo_playwright.py

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8094)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter — advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_console import narrative  # noqa: E402
from demo_console.narrative import Point  # noqa: E402

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8094")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = os.environ.get("CHROME_PATH") or None

# (heading, the points to make, whether this step clicks "Next", panel to spotlight)
STEPS = [
    (
        "The memo is built",
        (
            Point(
                "The full offline pipeline has run for the synthetic borrower Acme Manufacturing.",
                "Redact, guardrail, grounded retrieval, then LLM synthesis. No cloud, no API key.",
            ),
            Point(
                "The amber banner: decision support, not a credit decision.",
                "A memo always goes to a human checker, whatever it says.",
            ),
        ),
        False,
        ".review",
    ),
    (
        "Financial analysis",
        (
            Point("Revenue USD 120m, EBITDA USD 24m, net leverage 2.5x."),
            Point(
                "Normalised from the audited statements.",
                "Each figure is traceable back to the source filing it was read from.",
            ),
        ),
        True,
        ".metrics",
    ),
    (
        "Covenants",
        (
            Point("Compliant / at-risk / breach is computed, not written."),
            Point(
                "The status compares the current value against the threshold, deterministically.",
                "The LLM drafts prose but never overrides a breach computation.",
            ),
            Point("Each row carries its source."),
        ),
        True,
        "table.cov",
    ),
    (
        "Risk assessment",
        (
            Point("A concentration risk flag."),
            Point(
                "Grounded in the manufacturing sector credit policy, cited to its page.",
                "Not the model's general knowledge of the sector.",
            ),
        ),
        True,
        ".item",
    ),
    (
        "Peer comparison",
        (
            Point("The borrower's metrics against the cohort."),
            Point(
                "The peer median and percentile are computed arithmetically.",
                "Peer numbers are never invented — an LLM asked for a median will produce "
                "a plausible one.",
            ),
        ),
        True,
        ".peer",
    ),
    (
        "Maker-checker",
        (
            Point(
                "Every memo requires human review (P-06).",
                "A credit officer is the checker; the assistant is only ever the maker.",
            ),
            Point("Each claim is cited on the Sources & audit page."),
        ),
        True,
        ".review",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE + "/state", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  PYTHONPATH=src python scripts/credit_memo_demo_server.py")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== Credit-memo live demo — press Enter to advance each step ===\n")
        page.goto(BASE + "/restart", wait_until="load")  # always start clean
        page.goto(BASE + "/", wait_until="load")

        for i, (title, points, click, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {title}")
            print(narrative.render(points))
            _pause("        press Enter to run this step... ")
            if click:
                btn = page.locator(".democtl button.next")
                if btn.count() and btn.is_enabled():
                    btn.click()
                    page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            print()

        print("Demo complete. The browser stays open for questions.")
        _pause("        press Enter to close the browser... ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
