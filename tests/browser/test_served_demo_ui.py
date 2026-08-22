"""F2: the presenter demo is driven through a real headless browser, not a string.

``scripts/demo_selftest.py`` starts the real server and reads the served bytes, which
covers the server/renderer path browserlessly. This file closes the other half: a pinned
headless Chromium loads the SERVED pages, clicks the presenter's own ``Next`` button, and
reads every asserted figure back out of the LIVE DOM through the stable ``data-*``
evidence hooks. Nothing here is compared against hard-coded prose; every expectation is
recomputed from the running :class:`DemoSession`.

Playwright is pinned in the ``[demo]`` extra. The browser binary is a network download,
so a fork's day-one offline gate (D3) must not depend on it: the module skips when the
browser is absent and ``make demo-browser`` runs it for anyone who has the extra.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the pinned [demo] extra is not installed"
)


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo_server = _load("credit_memo_demo_server")


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, dict]]:
    """The REAL demo server, on an ephemeral port, for the duration of the module."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    server.session = demo_server.DemoSession()
    server.lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.session.data
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(served: tuple[str, dict]) -> Iterator[object]:
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - environment-dependent
                pytest.skip(f"no pinned browser binary available: {exc}")
            context = browser.new_context()
            yield context.new_page()
            context.close()
            browser.close()
    except NotImplementedError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"playwright cannot run here: {exc}")


def test_the_served_demo_walks_every_step_in_a_real_browser(page, served: tuple[str, dict]) -> None:
    base, data = served
    page.goto(f"{base}/restart", wait_until="load")

    steps = demo_server.STEPS
    breaches = sum(1 for c in data["covenants"] if c["status"] == "breach")

    for index in range(len(steps)):
        bar = page.locator("[data-demo='presenter-step']")
        assert bar.get_attribute("data-step") == str(index)

        # Figures read out of the LIVE DOM, checked against the running app.
        header = page.locator("[data-memo-borrower]")
        assert header.get_attribute("data-memo-borrower") == data["borrower"]["id"]
        assert header.get_attribute("data-memo-citations") == str(len(data["citations"]))
        assert header.get_attribute("data-memo-breaches") == str(breaches)
        assert (
            header.get_attribute("data-memo-review")
            == str(bool(data["requires_human_review"])).lower()
        )

        for panel in (
            "summary",
            "financial-analysis",
            "covenants",
            "risk-assessment",
            "peer-comparison",
        ):
            assert page.locator(f"[data-panel='{panel}']").count() == 1, panel

        table = page.locator("[data-covenant-count]")
        assert table.get_attribute("data-covenant-count") == str(len(data["covenants"]))
        assert table.get_attribute("data-covenant-breaches") == str(breaches)

        rendered_statuses = page.locator("[data-covenant-status]").evaluate_all(
            "rows => rows.map(r => r.getAttribute('data-covenant-status'))"
        )
        assert rendered_statuses == [c["status"] for c in data["covenants"]]

        rendered_metrics = page.locator("[data-metric]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-metric'))"
        )
        assert rendered_metrics == [m["name"] for m in data["financial_metrics"]]

        rendered_percentiles = page.locator("[data-peer-percentile]").evaluate_all(
            "els => els.map(e => e.getAttribute('data-peer-percentile'))"
        )
        assert rendered_percentiles == [
            str(int(p["percentile"] * 100)) for p in data["peer_comparison"]
        ]

        if index < len(steps) - 1:
            page.locator("button.next:not([disabled])").click()
            page.wait_for_load_state("load")

    assert page.locator("button.next[disabled]").count() == 1
    assert "Maker-checker review gate" in page.content()


def test_the_sources_page_serves_every_live_citation_in_the_browser(
    page, served: tuple[str, dict]
) -> None:
    base, data = served
    page.goto(f"{base}/sources", wait_until="load")
    content = page.content()
    assert data["citations"], "the running app produced no citations to prove"
    for citation in data["citations"]:
        assert citation["title"] in content or citation["source_id"] in content
