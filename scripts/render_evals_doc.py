#!/usr/bin/env python3
"""Regenerate the derived half of ``docs/evals.md`` from the rubrics, golden sets and floors.

A page that lists metrics and thresholds by hand goes stale the first time a bar moves, and
nothing notices. This repository had exactly that: the bars lived in a Python dict AND in the
rubric files AND in prose, and the three could disagree without anything failing. The dict is
gone; this makes the prose derived too.

    make evals-doc          # rewrite the generated sections
    make evals-doc-check    # non-zero when the page and the artifacts disagree (runs in check)

Only the sections named in :data:`BLOCKS` are generated. Everything else on the page is
hand-written prose addressed to a reviewer, and this script does not touch it: the point is a
document a person wrote, whose FACTS cannot drift from the artifacts they describe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from agent_eval_kit import load_jsonl, load_rubrics, render_main, required_positives
from agent_eval_kit.floors import load_quality_floors
from agent_eval_kit.rubrics import Rubric

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

DOC = _REPO_ROOT / "docs" / "evals.md"
RUBRICS = _REPO_ROOT / "eval" / "rubrics"
GOLDEN = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
NARRATIVE = _REPO_ROOT / "eval" / "datasets" / "narrative_golden.jsonl"
FLOORS = _REPO_ROOT / "config" / "quality-floors.toml"

#: The headings this script owns. Each runs from its heading to the next `\n## `.
BLOCKS = (
    "## What is measured, and against what bar",
    "## What is exercised",
    "## Where the narrative floor comes from",
)


def _denominator_kind(rubric: Rubric) -> str:
    """What a rubric says its bar is measured over. Read, never guessed from the number.

    0.99 is both the bar a leak metric carries (one leak anywhere fails it) and a perfectly
    ordinary rate. Guessing from the number would print "needs 100 cases" beside a metric a
    corpus of one already gates correctly, which is a confident wrong answer.
    """
    document = yaml.safe_load(Path(rubric.source).read_text(encoding="utf-8")) or {}
    declared = document.get("denominator") or {}
    node = declared.get(rubric.metric, declared) if isinstance(declared, dict) else {}
    if not isinstance(node, dict):
        node = {}
    return str(node.get("kind", "rate"))


def _metrics_block() -> list[str]:
    rubrics = load_rubrics(RUBRICS)
    cases = load_jsonl(GOLDEN)
    lines = [
        BLOCKS[0],
        "",
        "Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the",
        "runner reads it from there. There is no dict of thresholds in the runner any more: a",
        "metric scored with no reviewed bar fails the build, and so does a bar that names no",
        "metric, which is the direction that rots quietly because it rots toward looking well",
        "governed.",
        "",
        "The third column is the denominator rule, and it applies only where a score is a",
        "FRACTION over scored positives: such a threshold `t` tolerates a single miss only over",
        "at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no",
        "headroom, so a bigger corpus would not change what it means. Each rubric declares which",
        "it is rather than the rule being guessed from the number.",
        "",
        "| Metric | Bar | Denominator | What it measures |",
        "|---|---|---|---|",
    ]
    for rubric in rubrics:
        if _denominator_kind(rubric) == "all-or-nothing":
            needs = "all or nothing"
        else:
            needs = f"a rate; needs {required_positives(rubric.threshold)} positives"
        lines.append(
            f"| `{rubric.metric}` | {rubric.threshold:g} | {needs} | {rubric.description} |"
        )
    lines += ["", f"Scored over {len(cases)} golden cases.", ""]
    return lines


def _exercised_block() -> list[str]:
    import run_eval

    examples = run_eval.load_golden(run_eval.DEFAULT_DATASET)
    narrative = load_jsonl(NARRATIVE)
    covenants = sum(len(e.expected_covenants) for e in examples)
    spread = sum(len(p) for e in examples for p in e.expected_spread.values())
    ratios = sum(len(p) for e in examples for p in e.expected_ratios.values())
    planted = sum(1 for e in examples if e.pii_in_inputs)
    return [
        BLOCKS[1],
        "",
        f"- **{len(examples)} golden borrowers** in `eval/datasets/golden_cases.jsonl`, carrying",
        f"  {covenants} expected covenant statuses, {spread} spread line items across periods and",
        f"  {ratios} expected ratio figures. Every expectation is a reviewer's, read off the",
        "  source; none is derived from the engine, because an oracle computed from the thing",
        "  under test agrees with it by construction and measures nothing.",
        f"- **{planted} of them plant a raw identifier**, so the leak metric has a target it could",
        "  miss. A corpus that plants nothing scores a vacuous 1.0.",
        f"- **{len(narrative)} judged memo narratives** in",
        "  `eval/datasets/narrative_golden.jsonl`, each written once per profile with the band it",
        "  is expected to land in. A profile that quietly got BETTER fails too, because a band",
        "  nobody predicted is a change nobody reviewed.",
        "- **An adversarial run** (`make eval-adversarial`) drives the same gate with a",
        "  fabricating model, where a PASS is the bug.",
        "",
    ]


def _floors_block() -> list[str]:
    floors = load_quality_floors(FLOORS)
    lines = [
        BLOCKS[2],
        "",
        "`config/quality-floors.toml` is owned by model risk. A **floor** refuses: below it a",
        "profile must not serve this vertical, which is not the same as serving it worse. A",
        "**target** is full quality. Between the two is DEGRADED, the band a portability claim",
        "describes in adjectives and which nothing measured until there was a floor.",
        "",
        "| Vertical | Floor | Target | Why |",
        "|---|---|---|---|",
    ]
    for floor in floors:
        bars = f"{floor.floor:g} | {floor.target:g}"
        note = " ".join(floor.note.split())
        lines.append(f"| `{floor.vertical}` | {bars} | {note} |")
    lines.append("")
    return lines


def render() -> str:
    """The page, with the generated blocks replaced and the hand-written prose untouched."""
    text = DOC.read_text(encoding="utf-8")
    missing = [heading for heading in BLOCKS if heading not in text]
    if missing:
        raise SystemExit(
            f"{DOC}: missing generated section(s) {missing}. This script replaces named "
            "headings; it does not invent them, because a page it could create from nothing "
            "would silently replace one a person wrote."
        )
    generated = {
        BLOCKS[0]: _metrics_block(),
        BLOCKS[1]: _exercised_block(),
        BLOCKS[2]: _floors_block(),
    }
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line in generated:
            out.extend(generated[line])
            skipping = True
            continue
        if skipping:
            if line.startswith("## "):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    raise SystemExit(
        render_main(
            output=DOC,
            render=render,
            description="Regenerate docs/evals.md from the rubrics, golden sets and floors.",
            argv=sys.argv[1:],
        )
    )
