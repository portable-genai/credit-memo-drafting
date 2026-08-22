"""No CI gate may be disarmed by a calendar date baked into the workflow.

An `npm audit` step that compares `$(date -u +%F)` against a hardcoded expiry and, until
that day, waves a hand-written allowlist of advisories through is the shape this forbids.
It is self-rotting: it is green while the exception is live, green again the moment someone
bumps the literal, and the allowlist it guards silently stops matching the advisories that
actually fail the build. It is also invisible in review, because the step keeps its
reassuring name.

So the property is asserted, not remembered: a workflow may not read the current date and
compare it to a literal. A supply-chain finding is either fixed or it fails the build.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: A shell read of the current date: `$(date -u +%F)`, `` `date +%Y-%m-%d` ``, etc.
_READS_TODAY = re.compile(r"(?:\$\(|`)\s*date\b")

#: A bare YYYY-MM-DD literal. Harmless on its own (changelog dates, advisory dates); it is
#: only a defect when the same script also reads the current date.
_DATE_LITERAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

#: The conditional shape on its own: a comparison operator against a quoted date literal,
#: e.g. `> "2026-08-06"`. Caught even if the date is read some way this file has not seen.
_COMPARED_TO_DATE = re.compile(r"(?:[<>]=?|==|!=|-(?:gt|ge|lt|le|eq|ne))\s*[\"']?\d{4}-\d{2}-\d{2}")


def _workflow_files() -> list[Path]:
    return sorted(p for p in _WORKFLOWS.rglob("*") if p.suffix in {".yaml", ".yml"})


def test_the_repo_has_workflows_to_scan() -> None:
    """A scanner pointed at nothing is a scanner that always passes."""
    assert _workflow_files(), f"no workflow files under {_WORKFLOWS}"


def test_no_workflow_gate_expires_on_a_hardcoded_date() -> None:
    violations: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_ROOT)
        for number, line in enumerate(text.splitlines(), start=1):
            if _COMPARED_TO_DATE.search(line):
                violations.append(
                    f"{rel}:{number}: compares against a date literal: {line.strip()}"
                )
        if _READS_TODAY.search(text) and _DATE_LITERAL.search(text):
            reads = [
                f"{number}"
                for number, line in enumerate(text.splitlines(), start=1)
                if _READS_TODAY.search(line)
            ]
            violations.append(
                f"{rel}: reads the current date (line(s) {', '.join(reads)}) and also carries a "
                "YYYY-MM-DD literal"
            )

    assert not violations, (
        "A CI gate must not expire on a hardcoded date; fix the finding instead of dating an "
        "exception.\n" + "\n".join(violations)
    )
