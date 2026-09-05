"""Presenter-controlled walkthrough of the credit-memo console: one deal, seventeen acts.

A real browser opens. Before each act the script says what is about to happen and what to
look at; inside an act it stops again at the beats worth talking through — once the form is
filled and before it is submitted, and again when the answer is on screen. Every stop waits
for a keystroke, so the room moves at the presenter's pace rather than the software's.

It drives the SAME acts ``tests/browser/test_console_use_cases.py`` asserts, so what an
audience sees is what CI keeps working. Each act still checks itself here: if something is
broken you learn it on the spot rather than talking past it, and the walkthrough carries on
so one broken act does not end the session.

Usage — build the console once, then run it::

    npm ci --prefix ui && NEXT_PUBLIC_API_BASE=http://localhost:8093 \\
        NEXT_TELEMETRY_DISABLED=1 npm --prefix ui run build

    .venv/bin/python scripts/credit_memo_console_walkthrough.py           # all 17 acts
    .venv/bin/python scripts/credit_memo_console_walkthrough.py --list    # the act names
    .venv/bin/python scripts/credit_memo_console_walkthrough.py --act "The checker"
    .venv/bin/python scripts/credit_memo_console_walkthrough.py --act 6 --act 9

An act is named by its title (exact, or any unambiguous part of it) or by its number. Acts
build on each other — the memo needs the confirmed spread, the spread needs the credit file
— so a named act runs everything before it first, silently and without pauses, and then
presents the act you asked for. One line per set-up act says how far it has got.

Environment overrides:
    HEADLESS=1   run without a window (recording / self-test)
    DEMO_AUTO=1  don't wait for a keystroke — advance automatically
    SLOWMO_MS    per-action slow motion (default 250 headed, 0 headless)
    CHROME_PATH  explicit Chromium / Chrome binary (else Playwright's own)
    DEMO_OUT_DIR where screenshots, video and the trace are written
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
import textwrap
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_console import evidence, servers  # noqa: E402
from demo_console.acts import ACTS, Stage  # noqa: E402

_RULE = "-" * 78


class Quit(Exception):
    """The presenter pressed q. Not a failure: pack up and go."""


# --------------------------------------------------------------------------- #
# Choosing which acts to present
# --------------------------------------------------------------------------- #
def resolve_acts(selectors: list[str]) -> list[int]:
    """Map what a presenter typed onto act indices, in act order.

    A selector is an act number (``6``), its exact title, or any unambiguous part of one
    (``checker``). Ambiguity is refused rather than guessed at: picking the first of two
    matches would put the wrong act in front of a room, and the presenter would find out
    from the audience.

    Pure, and deliberately so — it is the one piece of this script that can be tested
    without a browser, a built console or a running API.
    """
    titles = [act.title for act in ACTS]
    chosen: list[int] = []
    for raw in selectors:
        selector = raw.strip()
        if not selector:
            raise ValueError("an empty --act selects nothing")
        chosen.append(_resolve_one(selector, titles))
    return sorted(set(chosen))


def _resolve_one(selector: str, titles: list[str]) -> int:
    if selector.isdigit():
        number = int(selector)
        if not 1 <= number <= len(titles):
            raise ValueError(
                f"there is no act {number}; the demo has {len(titles)}.\n{_numbered(titles)}"
            )
        return number - 1

    folded = selector.casefold()
    exact = [i for i, title in enumerate(titles) if title.casefold() == folded]
    if exact:
        return exact[0]
    for match in (
        [i for i, title in enumerate(titles) if title.casefold().startswith(folded)],
        [i for i, title in enumerate(titles) if folded in title.casefold()],
    ):
        if len(match) == 1:
            return match[0]
        if len(match) > 1:
            names = ", ".join(f"{i + 1}. {titles[i]}" for i in match)
            raise ValueError(f"{selector!r} matches more than one act: {names}")
    raise ValueError(f"no act is called {selector!r}.\n{_numbered(titles)}")


def _numbered(titles: list[str]) -> str:
    return "\n".join(f"  {i + 1:2d}. {title}" for i, title in enumerate(titles))


# --------------------------------------------------------------------------- #
# Waiting for the presenter
# --------------------------------------------------------------------------- #
def _read_key() -> str:
    """One keystroke, without an Enter after it. Falls back to a line when it must.

    Raw single-key reading needs a terminal and a POSIX ``termios``. Neither is present
    when the walkthrough is piped, recorded, or run on Windows, so those get ``input()``:
    a demo that hangs waiting for a key nobody can send is worse than one that asks for
    Enter.
    """
    if not sys.stdin.isatty():
        try:
            return input()[:1]
        except EOFError:
            return ""
    try:
        import termios
        import tty
    except ImportError:  # pragma: no cover - Windows
        try:
            return input()[:1]
        except EOFError:
            return ""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _wrap(text: str, indent: str = "  ", hanging: str | None = None) -> str:
    """Wrap for a terminal, labelling only the first line.

    ``SAY`` repeated down the left margin of a five-line paragraph is harder to read at a
    glance than the paragraph itself, and a presenter is reading this while a room waits.
    """
    return textwrap.fill(
        text,
        width=76,
        initial_indent=indent,
        subsequent_indent=" " * len(indent) if hanging is None else hanging,
    )


class Presenter:
    """Prints what to say, and holds until the room has seen it."""

    def __init__(self, auto: bool) -> None:
        self.auto = auto

    def hold(self, prompt: str) -> None:
        if self.auto:
            time.sleep(0.6)
            return
        sys.stdout.write(f"        {prompt} ")
        sys.stdout.flush()
        key = _read_key()
        sys.stdout.write("\n")
        sys.stdout.flush()
        if key.lower() == "q":
            raise Quit()

    def beat(self, say: str, look_at: str = "") -> None:
        """A pause inside an act: what to say now, and what is on screen while you say it."""
        print()
        print(_wrap(say, indent="    SAY  "))
        if look_at:
            print(_wrap(f"look at: {look_at}", indent="      →  ", hanging=" " * 15))
        self.hold("[any key to go on, q to quit]")


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def _present(stage: Stage, presenter: Presenter, index: int, act: Any) -> str:
    """Show one act with its narration and its pauses. Returns "" or why it failed."""
    print(f"[{index + 1}/{len(ACTS)}] {act.title}")
    print(_wrap(act.narration))
    if act.point_at:
        print(_wrap(f"Look at: {act.point_at}", indent="  →  ", hanging=" " * 13))
    presenter.hold("[any key to run this act, q to quit]")

    stage.beat = presenter.beat
    try:
        act.run(stage)
    except Quit:
        raise
    except Exception as exc:  # noqa: BLE001 - a live demo keeps going
        print(f"        ✗ {type(exc).__name__}: {exc}")
        return f"{act.title}: {type(exc).__name__}"
    finally:
        stage.beat = None
    print("        ✓ shown, and asserted")
    return ""


def _set_up(stage: Stage, index: int, act: Any) -> str:
    """Run an act the presenter did not ask for, because a later one needs what it leaves."""
    sys.stdout.write(f"  setting up · {index + 1:2d}. {act.title} ... ")
    sys.stdout.flush()
    stage.beat = None
    try:
        act.run(stage)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED\n        {type(exc).__name__}: {exc}")
        return f"{act.title}: {type(exc).__name__}"
    print("ok")
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="credit_memo_console_walkthrough",
        description="Walk the credit-memo console through its business use cases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="With no --act the whole demo runs, all seventeen acts in order.",
    )
    parser.add_argument(
        "--act",
        action="append",
        default=[],
        metavar="NAME|N",
        help="present just this act (repeatable). Its predecessors still run, silently.",
    )
    parser.add_argument("--list", action="store_true", help="print the act names and exit")
    parser.add_argument("--auto", action="store_true", help="do not wait for a keystroke")
    parser.add_argument("--headless", action="store_true", help="run without a window")
    args = parser.parse_args(argv)

    if args.list:
        print(f"{len(ACTS)} acts:\n{_numbered([act.title for act in ACTS])}")
        return 0

    try:
        present = resolve_acts(args.act) if args.act else list(range(len(ACTS)))
    except ValueError as exc:
        print(f"Cannot choose an act: {exc}")
        return 2

    headless = args.headless or os.environ.get("HEADLESS") == "1"
    auto = args.auto or os.environ.get("DEMO_AUTO") == "1"
    slowmo = int(os.environ.get("SLOWMO_MS", "0" if headless else "250"))
    chrome_path = os.environ.get("CHROME_PATH") or None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Install the pinned demo extra:")
        print("  make install-demo")
        return 2

    analysis_root = Path(tempfile.mkdtemp(prefix="credit-memo-demo-"))
    presenter = Presenter(auto=auto)
    everything = len(present) == len(ACTS)
    last = max(present)
    failures: list[str] = []
    quit_early = False

    with ExitStack() as servers_running:
        # Both servers are ENTERED inside the try, not merely constructed there. Calling
        # ``servers.api_server(...)`` does nothing at all — it is a generator — so a version
        # of this that guarded only the construction guarded nothing, and a busy port or an
        # unbuilt console produced a traceback in front of a room instead of the sentence
        # that names the fix.
        try:
            api_base = servers_running.enter_context(servers.api_server(analysis_root))
            ui_base = servers_running.enter_context(servers.console_server())
        except servers.DemoServerError as exc:
            print(f"Cannot start the demo:\n{exc}")
            return 2

        print(f"\n{_RULE}\nCredit-memo console demo — API {api_base}, console {ui_base}")
        if everything:
            print(f"{len(ACTS)} acts, in order.")
        else:
            names = ", ".join(f"{i + 1}. {ACTS[i].title}" for i in present)
            print(f"Presenting {names}")
            if last + 1 > len(present):
                print(f"Setting the stage first: {last + 1 - len(present)} earlier act(s).")
        print(f"{_RULE}\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless, slow_mo=slowmo, executable_path=chrome_path
            )
            out = evidence.reset() if everything else evidence.prepare()
            context = browser.new_context(
                viewport={"width": 1280, "height": 1400}, record_video_dir=str(out / "video")
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
            request = p.request.new_context(base_url=api_base)
            stage = Stage(page=context.new_page(), api=request, ui_base=ui_base, api_base=api_base)
            # Load the console before the first pause, not during it. Act 1 itself does
            # this navigation too — it is the thing act 1 is ABOUT — but the presenter's
            # very first prompt happens before any act has run, and a screen showing
            # about:blank under "press any key to run this act" reads as broken rather
            # than as paced. Any failure here is left for act 1 to hit and report properly.
            with contextlib.suppress(Exception):
                stage.page.goto(ui_base, wait_until="load")

            try:
                for index in range(last + 1):
                    act = ACTS[index]
                    if index in present:
                        if not everything:
                            evidence.clear(index + 1)
                        failed = _present(stage, presenter, index, act)
                        evidence.capture(stage.page, index + 1, act.title)
                        print()
                    else:
                        failed = _set_up(stage, index, act)
                    if failed:
                        failures.append(failed)
                    if failed and index not in present:
                        # A later act cannot be shown on a stage that was never set.
                        print(
                            "\n  Stopping: the act you asked for needs what this one leaves behind."
                        )
                        break
            except Quit:
                quit_early = True

            print(_RULE)
            if quit_early:
                print("Stopped at the presenter's request.")
            elif failures:
                print(f"{len(failures)} act(s) did not hold:")
                for failure in failures:
                    print(f"  ✗ {failure}")
            elif everything:
                print("Every act held.")
            else:
                print("Held.")
            print(f"Evidence in {out}")
            if not quit_early:
                # A q here means the same as any other key: we are already finished.
                with contextlib.suppress(Quit):
                    presenter.hold("[any key to close the browser]")
            context.tracing.stop(path=str(out / "trace.zip"))
            request.dispose()
            context.close()
            browser.close()

    if quit_early:
        return 130
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
