"""The business use-case demo, asserted act by act through a real browser.

``test_served_demo_ui.py`` covers the presenter server on :8094. This file covers the
PRODUCT: the built Next.js console talking to the FastAPI service, walked through the
seventeen acts in :mod:`scripts.demo_console.acts` — the same acts
``scripts/credit_memo_console_walkthrough.py`` narrates to an audience.

Why the demo is also a test. This repository has shipped capabilities that were fully
built and reachable by nobody: a spread extractor no route called, a revision chain with
no endpoint, engines whose results no schema carried. Every one of them passed a green
gate, because a port that is bound, contract-tested and never called looks exactly like a
working feature from inside the test suite. A demo asserts the only thing those checks
cannot: that a person can still get to it.

Playwright is pinned in the ``[demo]`` extra and the browser binary is a network download,
so a clean checkout's offline gate must not depend on either: with nothing set, an absent
extra or an unlaunchable browser skips LOUDLY. Set ``DEMO_BROWSER_REQUIRED`` and the same
conditions FAIL instead, because a suite that declines to run reports exactly the green a
suite that ran reports.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn

import pytest

from credit_memo.envread import boolean_setting

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from demo_console import evidence, servers  # noqa: E402
from demo_console.acts import ACTS, Stage  # noqa: E402

pytestmark = pytest.mark.console

CHROME_PATH = os.environ.get("CHROME_PATH") or None
BROWSER_REQUIRED = boolean_setting("DEMO_BROWSER_REQUIRED")


def _playwright_api() -> Any:
    if BROWSER_REQUIRED:
        import importlib

        return importlib.import_module("playwright.sync_api")
    return pytest.importorskip(
        "playwright.sync_api", reason="the pinned [demo] extra is not installed"
    )


playwright_api = _playwright_api()


def _unavailable(reason: str) -> NoReturn:
    """Skip only when nothing promised a browser; FAIL when something did."""
    if BROWSER_REQUIRED:
        pytest.fail(
            "DEMO_BROWSER_REQUIRED is set, so this demo was expected to run and must not "
            f"skip. {reason}",
            pytrace=False,
        )
    pytest.skip(reason)


@pytest.fixture(scope="module")
def stage(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stage]:
    """The API, the BUILT console, a browser, and the state the acts build up.

    The servers are entered INSIDE the try, not merely constructed there. Calling
    ``servers.api_server(...)`` only builds the context manager; its body — the port check,
    the process launch, the readiness wait — runs at ``with``. Catching around the
    construction alone let a ``DemoServerError`` escape the fixture, which pytest reports as
    seventeen ERRORS rather than the honest skip (or, when a browser was promised, the
    honest single failure).
    """
    analysis_root = tmp_path_factory.mktemp("analyses")
    with ExitStack() as stack:
        try:
            api_base = stack.enter_context(servers.api_server(analysis_root))
            ui_base = stack.enter_context(servers.console_server())
        except servers.DemoServerError as exc:  # pragma: no cover - environment-dependent
            _unavailable(str(exc))
        try:
            with playwright_api.sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH)
                except Exception as exc:  # pragma: no cover - environment-dependent
                    _unavailable(f"no pinned browser binary available: {exc}")
                out = evidence.reset()
                context = browser.new_context(
                    viewport={"width": 1280, "height": 1400},
                    record_video_dir=str(out / "video"),
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                request = p.request.new_context(base_url=api_base)
                try:
                    yield Stage(
                        page=context.new_page(),
                        api=request,
                        ui_base=ui_base,
                        api_base=api_base,
                    )
                finally:
                    context.tracing.stop(path=str(out / "trace.zip"))
                    request.dispose()
                    context.close()
                    browser.close()
        except NotImplementedError as exc:  # pragma: no cover - environment-dependent
            _unavailable(f"playwright cannot run here: {exc}")


#: Which act failed first, so the acts after it report the cause rather than a cascade of
#: confusing symptoms. The demo is a narrative: act 10 genuinely cannot run if act 2 did
#: not put a credit file in front of it.
_FAILED_AT: list[str] = []

#: Which acts actually ran to completion. Counted rather than inferred from ``_FAILED_AT``
#: being empty: when the fixture cannot start the servers, NO act runs and nothing fails,
#: so "no failures" was reporting green over a demo that never happened.
_COMPLETED: list[str] = []


@pytest.mark.parametrize(
    "index,act",
    list(enumerate(ACTS)),
    ids=[f"{i + 1:02d}-{a.title}" for i, a in enumerate(ACTS)],
)
def test_act(stage: Stage, index: int, act: Any) -> None:
    if _FAILED_AT:
        pytest.fail(
            f"this act did not run: the demo stopped at {_FAILED_AT[0]!r}, and every later "
            "act depends on the deal that one was walking through",
            pytrace=False,
        )
    try:
        act.run(stage)
    except Exception:
        _FAILED_AT.append(act.title)
        evidence.capture(stage.page, index + 1, f"FAILED-{act.title}")
        raise
    _COMPLETED.append(act.title)
    evidence.capture(stage.page, index + 1, act.title)


def test_the_demo_covered_every_act(stage: Stage) -> None:
    """A demo that quietly lost half its acts still reports green on the ones it kept.

    It takes ``stage`` so that it follows the same fate as the acts: where the fixture
    skipped because this machine has no browser or no built console, this skips with them
    rather than reporting a failure about acts that were never meant to run here. Where the
    fixture DID come up, every act must have completed.
    """
    assert stage is not None
    assert len(ACTS) >= 17, "acts have gone missing from the walkthrough"
    assert not _FAILED_AT, f"the demo did not complete: it stopped at {_FAILED_AT[0]!r}"
    # The check that matters when the environment, rather than the product, is what broke:
    # a run where the fixture never started reaches here with nothing failed and nothing
    # done, and used to report green.
    missing = [act.title for act in ACTS if act.title not in _COMPLETED]
    assert not missing, f"{len(missing)} act(s) never ran: {missing}"
