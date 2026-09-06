"""The demo's act list and its presenter selectors, checked without a browser.

``tests/browser/test_console_use_cases.py`` proves the acts still work, but it needs Node,
a built console and Chromium, so it is skipped everywhere those are absent. These checks
need none of that: they hold the two things a presenter depends on before any of that is
installed — that ``--act`` picks the act they named, and that the pauses a presenter sees
cannot change what the suite asserts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from credit_memo_console_walkthrough import resolve_acts  # noqa: E402
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
