"""Capture what the demo showed, so a run is reusable as slides.

A presenter who has just walked fifteen acts should not have to walk them again to get a
screenshot of act seven. Each act writes one full-page PNG named after itself, and the
whole run writes a Playwright trace, which is the artefact worth keeping: it holds the
DOM, the network and a screencast at every step, so a question asked after the demo can be
answered from the recording rather than from memory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# One directory for the whole run, resolved in ``servers`` because the servers start
# before any act does and their logs belong beside the screenshots.
from .servers import OUT_DIR


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def prepare() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR


def reset() -> Path:
    """Start a run with an empty evidence directory.

    Without this a run inherits the screenshots of every earlier one, including the
    ``FAILED-`` frames of a run that has since been fixed. A presenter reaching for act 7
    would find two files claiming to be it, and no way to tell which run each came from.
    """
    prepare()
    for stale in OUT_DIR.glob("*.png"):
        stale.unlink()
    return OUT_DIR


def clear(index: int) -> None:
    """Drop the frames for one act, so a re-run of it does not leave two of them.

    A run of a single act must not ``reset()``: that would delete the other sixteen frames
    of the full run a presenter may be part-way through. Clearing only this act's index
    keeps both runs' evidence honest, including a stale ``FAILED-`` frame from before the
    fix.
    """
    prepare()
    for stale in OUT_DIR.glob(f"{index:02d}-*.png"):
        stale.unlink()


def capture(page: Any, index: int, title: str) -> Path:
    """One full-page screenshot of the act just performed.

    Full page rather than viewport: the memo is nineteen sections long, and a viewport
    shot of it would prove the top of the page and nothing else.
    """
    prepare()
    path = OUT_DIR / f"{index:02d}-{_slug(title)}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:  # noqa: BLE001 - evidence is a courtesy, never the demo's point
        return path
    return path
