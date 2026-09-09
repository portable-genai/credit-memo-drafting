#!/usr/bin/env python3
"""The half a rule cannot score: is the memo's PROSE any good, judged, against a floor.

Everything in ``run_eval.py`` is deterministic and binary. Does the arithmetic reproduce. Is
the covenant status right. Does every citation resolve to something retrieved. Did anything
personal survive. Those are questions code can answer, and code answers them there.

They leave a gap, and it is the one output a credit officer actually reads. A memo can
reproduce every ratio, get every covenant right, cite every source and mask every identifier,
and still bury the covenant position, assert a certainty the evidence does not carry, or read
as a decision the committee has not taken. Deciding that is a judgement, so it is judged, and
the judge is held to the same standard as every other scorer here: it must be shown able to
fail before anything it certifies is believed.

The whole run is ``agent_eval_kit.narrative_main``. This file supplies only what is specific to
this service: where the table is, where the floors are, the profiles each memo is written in,
and which of them is the deliberate control.

    make eval-narrative                       # offline, no model, no credentials, no network

The judge is chosen HERE, on the command line, and never from the environment: a gate whose
scorer a stray variable could swap is not a gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agent_eval_kit import narrative_main

_REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = _REPO_ROOT / "eval" / "datasets" / "narrative_golden.jsonl"
FLOORS = _REPO_ROOT / "config" / "quality-floors.toml"

#: The three ways each memo is written. Profiles rather than adjectives: they name WHICH
#: deployment produced the prose, which is what a portability claim is about.
PROFILES = ("managed", "reduced", "regressed")

#: The control. It exists to sit below the floor, so a table where it passes is a table whose
#: floor is too low to refuse anything.
CONTROL = "regressed"


if __name__ == "__main__":
    raise SystemExit(
        narrative_main(
            dataset=DATASET,
            floors=FLOORS,
            profiles=PROFILES,
            control=CONTROL,
            description="Credit-memo narrative quality, judged against the model-risk floors.",
            argv=sys.argv[1:],
        )
    )
