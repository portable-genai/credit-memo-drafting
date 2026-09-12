"""The demo's act list and its presenter selectors, checked without a browser.

``tests/browser/test_console_use_cases.py`` proves the acts still work, but it needs Node,
a built console and Chromium, so it is skipped everywhere those are absent. These checks
need none of that: they hold the two things a presenter depends on before any of that is
installed — that ``--act`` picks the act they named, and that the pauses a presenter sees
cannot change what the suite asserts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from credit_memo_console_walkthrough import resolve_acts  # noqa: E402
from demo_console import servers  # noqa: E402
from demo_console.acts import ACTS, Stage  # noqa: E402
from demo_console.narrative import Point, render  # noqa: E402


def test_every_act_is_distinct_and_says_what_to_look_at() -> None:
    titles = [act.title for act in ACTS]
    assert len(set(titles)) == len(titles), "two acts share a title, so --act cannot pick one"
    assert len(ACTS) >= 18
    for act in ACTS:
        assert act.narration, f"{act.title} has nothing for the presenter to say"
        assert act.point_at.strip(), f"{act.title} does not say what to look at"
        assert callable(act.run)


def test_a_narration_is_points_a_presenter_can_read_at_a_glance() -> None:
    """The format is the feature: phrases to say, not paragraphs to find your place in."""
    for act in ACTS:
        for point in act.narration:
            assert isinstance(point, Point), f"{act.title} narrates with prose, not points"
            # Long enough to say something, short enough to take in off a terminal while a
            # room waits. The justification is where the sentences go.
            assert len(point.say) <= 130, f"{act.title} says a paragraph: {point.say!r}"


def test_a_point_with_nothing_to_say_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to say"):
        Point("   ")


def test_points_render_numbered_with_each_justification_under_its_phrase() -> None:
    out = render(
        (Point("The engine says 3.18x.", "The bank measures gross debt."), Point("A breach.")),
        look_at="the covenant table",
    )
    assert out.splitlines() == [
        "  1. The engine says 3.18x.",
        "     · The bank measures gross debt.",
        "  2. A breach.",
        "  →  the covenant table",
    ]


def test_rendering_carries_no_escape_codes_when_nobody_is_watching_a_terminal() -> None:
    """Piped into a recording or a CI log, the narration must still be readable."""
    assert "\033" not in render((Point("say this", "because that"),), look_at="here")


def test_an_act_is_selected_by_number() -> None:
    assert resolve_acts(["1"]) == [0]
    assert resolve_acts([str(len(ACTS))]) == [len(ACTS) - 1]


def test_an_act_is_selected_by_name_however_it_is_typed() -> None:
    checker = next(i for i, act in enumerate(ACTS) if act.title == "The checker")
    assert resolve_acts(["The checker"]) == [checker]
    assert resolve_acts(["the checker"]) == [checker]
    assert resolve_acts(["checker"]) == [checker]


def test_several_acts_come_back_in_running_order_without_repeats() -> None:
    assert resolve_acts(["9", "2", "2"]) == [1, 8]


def test_an_ambiguous_name_is_refused_rather_than_guessed() -> None:
    # Half the titles begin "The ", and showing whichever came first would put the wrong
    # act in front of a room.
    with pytest.raises(ValueError, match="matches more than one act"):
        resolve_acts(["The "])


def test_an_unknown_act_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError) as caught:
        resolve_acts(["renewal"])
    assert "no act is called" in str(caught.value)
    assert ACTS[0].title in str(caught.value), "the refusal does not list what can be run"

    with pytest.raises(ValueError, match="there is no act"):
        resolve_acts([str(len(ACTS) + 1)])


def test_a_presenter_pause_is_inert_when_nobody_is_presenting() -> None:
    """The pytest suite builds a Stage without a presenter; every cue must cost nothing."""
    stage = Stage(page=None, api=None, ui_base="", api_base="")
    assert stage.beat is None
    stage.cue(Point("this must not raise, print, or block"), look_at="nor this")


def test_a_presenter_pause_reaches_the_presenter_when_there_is_one() -> None:
    seen: list[tuple[tuple[Point, ...], str]] = []
    stage = Stage(
        page=None,
        api=None,
        ui_base="",
        api_base="",
        beat=lambda points, look_at: seen.append((points, look_at)),
    )
    stage.cue(Point("say this", "because that"), look_at="look here")
    assert seen == [((Point("say this", "because that"),), "look here")]


def test_the_demo_drives_the_api_origin_an_unconfigured_console_calls() -> None:
    """The demo serves the console with NEXT_PUBLIC_API_BASE unset, so both must name one origin.

    ``servers.py`` starts the API where the console's own default points, and the API's dev CORS
    allowlist admits the console's origin. If the default in ``ui/lib/api-base.mjs`` moved and
    this constant did not, every act would fail on a refused request rather than on the product.
    """
    source = (REPO_ROOT / "ui" / "lib" / "api-base.mjs").read_text(encoding="utf-8")
    match = re.search(r'export const DEFAULT_API_BASE = "([^"]+)";', source)
    assert match, "ui/lib/api-base.mjs no longer declares DEFAULT_API_BASE"
    assert match.group(1) == servers.API_BASE_FOR_BROWSER


class _FakeContext:
    """A context that fails the way Playwright does when the video renderer is absent."""

    def __init__(self, video: bool, *, renderer: bool) -> None:
        self.video = video
        self._renderer = renderer
        self.closed = False

    def new_page(self) -> str:
        if self.video and not self._renderer:
            raise RuntimeError(
                "BrowserContext.new_page: Executable doesn't exist at "
                "/home/ci/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux. "
                "Video rendering requires ffmpeg binary."
            )
        return "page"

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, *, renderer: bool, fail_with: str = "") -> None:
        self._renderer = renderer
        self._fail_with = fail_with
        self.contexts: list[_FakeContext] = []

    def new_context(self, **options: object) -> _FakeContext:
        if self._fail_with:
            raise RuntimeError(self._fail_with)
        context = _FakeContext(bool(options.get("record_video_dir")), renderer=self._renderer)
        self.contexts.append(context)
        return context


def test_a_machine_with_no_video_renderer_still_runs_the_acts(tmp_path: Path) -> None:
    """CI ships a distribution Chromium and no ffmpeg, and reported nineteen errors about it.

    The video is a courtesy; the trace and the screenshots are the evidence. So a missing
    renderer costs the video, is reported, and costs nothing else.
    """
    from demo_console import evidence

    browser = _FakeBrowser(renderer=False)
    context, page, note = evidence.open_context(browser, tmp_path)
    assert page == "page"
    assert not context.video, "the fallback context still asks for a video"
    assert browser.contexts[0].closed, "the context that could not render was left open"
    assert "ffmpeg" in note and "trace" in note


def test_a_machine_that_can_render_one_records_it(tmp_path: Path) -> None:
    from demo_console import evidence

    context, page, note = evidence.open_context(_FakeBrowser(renderer=True), tmp_path)
    assert context.video and page == "page"
    assert note == ""


def test_a_failure_that_is_not_the_renderer_is_not_swallowed(tmp_path: Path) -> None:
    """A browser that cannot open a page at all is the demo failing, not its evidence."""
    from demo_console import evidence

    with pytest.raises(RuntimeError, match="no browser"):
        evidence.open_context(_FakeBrowser(renderer=True, fail_with="no browser here"), tmp_path)
