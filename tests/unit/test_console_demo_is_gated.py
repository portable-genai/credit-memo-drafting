"""The business acts run on every pull request, not only on a presenter's laptop.

``make demo-console`` walks the acts through the built console, and until this check existed it
ran nowhere else: no job in the reviewed CI contract named it, so a capability could stop being
reachable from the console and every pull request would still merge green. That is the defect
class the demo exists to catch, turned back on the demo.

The contract's runner refuses any make target outside its approved list, and ``demo-console`` is
not on it, so the acts ride in the approved ``demo-browser`` target instead. These checks hold,
from this repository's side, the three things that make the acts run in CI:

1. ``demo-browser`` builds the console and runs the whole browser suite, the console acts
   included, rather than excluding them by marker as it used to;
2. the rendered caller installs the console's node modules before the target runs and requires
   a browser, so an absent one fails the job rather than skipping it;
3. the browser suite that target runs is where the acts are collected.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _make_target(name: str) -> tuple[str, str]:
    """The prerequisites and the recipe of one Makefile target."""
    lines = (REPO / "Makefile").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^{re.escape(name)}:([^#]*)", line)
        if not match:
            continue
        recipe: list[str] = []
        for following in lines[index + 1 :]:
            if not following.startswith("\t"):
                break
            recipe.append(following)
        return match.group(1), "\n".join(recipe)
    raise AssertionError(f"the Makefile has no {name!r} target")


def _caller_job(job_id: str) -> str:
    """One job's block out of the rendered GitHub Actions caller."""
    caller = (REPO / ".github" / "workflows" / "gate.yaml").read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(job_id)}:\n((?:    .*\n?)+)", caller, re.M)
    assert match, f".github/workflows/gate.yaml renders no {job_id!r} job"
    return match.group(1)


def test_the_ci_browser_target_builds_the_console_and_runs_its_acts() -> None:
    prerequisites, recipe = _make_target("demo-browser")
    assert "ui-build" in prerequisites.split(), (
        "demo-browser must build the console first: the acts run against the BUILT console"
    )
    assert "$(TESTS)/browser" in recipe, recipe
    assert "not console" not in recipe, (
        "demo-browser excludes the console acts again, so no pull request runs them"
    )


def test_the_ci_job_gives_that_target_node_and_a_required_browser() -> None:
    job = _caller_job("demo-browser")
    for line in (
        'make_targets: "demo-browser"',
        'npm_directory: "ui"',
        "npm_directory_first: true",
        "demo_browser_required: true",
        'extra_lockfiles: "requirements-demo.lock"',
        "extra_lockfiles_first: true",
    ):
        assert line in job, f"the demo-browser job no longer carries {line!r}:\n{job}"


def test_the_browser_suite_that_target_runs_collects_the_acts() -> None:
    suite = REPO / "tests" / "browser" / "test_console_use_cases.py"
    source = suite.read_text(encoding="utf-8")
    assert "from demo_console.acts import ACTS" in source
    assert "def test_act(" in source
