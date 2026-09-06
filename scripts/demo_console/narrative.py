"""What a presenter says, as points rather than paragraphs.

A narration is read off a terminal, out loud, from a metre away, while a room waits. A
five-line paragraph is the wrong shape for that: the presenter has to find their place in
it, and the claim is tangled up with everything that justifies the claim.

So a narration here is an ordered list. Each :class:`Point` carries the phrase to say --
short enough to take in at a glance -- and an optional ``because``: the answer to the
question that phrase invites, printed underneath in a dimmer hand. The phrase is the demo;
the ``because`` is there for the one person in the room who asks, and is not read out.

That split is also an editing rule with teeth. If a phrase cannot be said without its
``because``, it is not a business point yet; if a ``because`` is not the answer to a
question the phrase raises, it belongs in the code comments where the mechanism lives.

Both walkthrough scripts render through :func:`render`, so the two demos read the same way.
"""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

from hex_service_kit.netdefaults import read_env_setting

#: Narrower than a terminal, so a wrapped line never depends on the window being maximised.
WIDTH = 92


@dataclass(frozen=True)
class Point:
    """One numbered line a presenter says, and the answer if the room asks for one."""

    say: str
    because: str = ""

    def __post_init__(self) -> None:
        if not self.say.strip():
            raise ValueError("a point with nothing to say is a pause, not a narration")


#: A narration, in the order it is spoken.
Narration = tuple[Point, ...]


def _styles() -> tuple[str, str, str]:
    """Bold, dim and reset -- or nothing at all when the output is not a terminal.

    Read per call rather than at import: the walkthrough is piped into a file often enough
    (recordings, CI logs) that baking the answer in at import time would put escape codes
    into artefacts nobody can read them from.

    ``has_value`` rather than a truthiness test because that is precisely what the NO_COLOR
    convention specifies -- present AND non-empty suppresses colour -- and it is the one
    reading of the three states that does not have to be guessed at.
    """
    if read_env_setting("NO_COLOR").has_value or not sys.stdout.isatty():
        return "", "", ""
    return "\033[1m", "\033[2m", "\033[0m"


def _fill(text: str, first: str, rest: str) -> list[str]:
    return textwrap.fill(
        text, width=WIDTH, initial_indent=first, subsequent_indent=rest
    ).splitlines()


def render(points: Sequence[Point], look_at: str = "", indent: str = "  ") -> str:
    """The presenter's lines, numbered, each justification tucked under its own phrase.

    Styling is applied a whole line at a time, after wrapping, because ``textwrap`` counts
    escape codes as characters and would wrap short lines to nothing.
    """
    bold, dim, off = _styles()
    marker_width = len(f"{len(points)}.")
    body = " " * (len(indent) + marker_width + 1)
    lines: list[str] = []
    for number, point in enumerate(points, start=1):
        head = f"{indent}{f'{number}.'.rjust(marker_width)} "
        lines += [f"{bold}{line}{off}" for line in _fill(point.say, head, body)]
        if point.because:
            lines += [
                f"{dim}{line}{off}" for line in _fill(point.because, body + "· ", body + "  ")
            ]
    if look_at:
        lines += [f"{dim}{line}{off}" for line in _fill(look_at, f"{indent}→  ", f"{indent}   ")]
    return "\n".join(lines)
