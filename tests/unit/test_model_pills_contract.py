"""The half of the model-pill contract that lives in the BROWSER.

Every served console shows, at the top right of every page, two small pills: the model that
ANSWERED the last request, and `Search` when that answer used an online search tool (owner
decision, 2026-09-23). They replaced the full-width provenance banner, which named the model
configuration would call rather than the one that answered. The SERVICE half (the profile
implies a runtime, ``/healthz`` names the model the binding calls, the adapters note what
answered and the app emits it as headers) is pinned in ``tests/unit/test_health_provenance.py``
and ``tests/unit/test_answer_provenance.py`` and is not restated here.

This file pins the other half, because the other half is the one that broke before. On
2026-09-04 eight consoles were found to have been rendering NOTHING on every page load since the
banner landed: the component named ``/api/agent``, the same-origin route handler the service
template ships, in trees that ship no such handler. The health call reached a path nothing
serves, took the failure branch, and the failure branch renders nothing, deliberately, because a
pill that guessed would assert provenance it does not have. A check that cannot fail loudly
fails as an ABSENCE, and an absent pill is exactly what no reviewer notices.

The assertions pin AGREEMENT rather than literals where the fleet legitimately runs the console
in more than one shape: this console calls its service directly at ``API_BASE``, where a
template-shaped one proxies through ``/api/agent``.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path("ui")

#: The wording the configured pill carries in its title, spelled once in the component that
#: owns it. Located by what it SAYS rather than by where it sits: the fleet has kept this strip
#: in three different places, and a path-keyed check reported working consoles as empty.
_WORDING = "running on GCP"

#: Build output and vendored packages are not this console's source.
_NOT_SOURCE = frozenset({"node_modules", ".next", "dist", "out", "coverage"})


def _code_only(source: str) -> str:
    """``source`` without its comments, so a sentence ABOUT a call cannot stand in for one."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def _console_sources() -> list[Path]:
    """Every ``.tsx`` this console actually ships, build output and vendored trees pruned."""
    found: list[Path] = []
    pending = [UI]
    while pending:
        for child in pending.pop().iterdir():
            if child.is_dir():
                if child.name not in _NOT_SOURCE:
                    pending.append(child)
            elif child.suffix == ".tsx":
                found.append(child)
    return sorted(found)


def _pills_source() -> Path:
    """The component that renders the pills, wherever this console keeps it."""
    hits = [p for p in _console_sources() if _WORDING in p.read_text()]
    assert hits, (
        "no component under ui/ states where the service runs, so this console names neither "
        "its runtime nor its model on any page"
    )
    assert len(hits) == 1, (
        f"more than one component renders the provenance ({[str(p) for p in hits]}), so two "
        "pages can phrase the same fact differently"
    )
    return hits[0]


def test_the_pills_are_mounted_in_the_layout_rather_than_in_a_page() -> None:
    """Being on EVERY page is a property of the console, not of any page."""
    layout = Path("ui/app/layout.tsx")
    assert layout.is_file(), "this console has no root layout, so nothing can be mounted for it"
    owner = _pills_source().stem
    assert f"<{owner} />" in layout.read_text(), (
        f"{owner} renders the model pills but the root layout does not mount it, so they reach "
        "only the pages that remember to"
    )


def test_the_pills_read_the_base_this_console_actually_serves() -> None:
    """The defect that shipped, stated as an assertion.

    A tree with ``ui/app/api/agent`` proxies through its own origin and the pills should name
    that path; a tree without one must reach its backend the way the rest of the console does,
    through the base resolved once in ``ui/lib/api``, for both the health call and the answer
    watcher. The combination that shipped (naming the proxy while having none) is never right.
    """
    source = _pills_source()
    pills = _code_only(source.read_text())
    proxies_through_own_origin = Path("ui/app/api/agent").is_dir()
    assert ('"/api/agent"' in pills) == proxies_through_own_origin, (
        f"{source} names /api/agent but this console has no route handler at ui/app/api/agent"
        if not proxies_through_own_origin
        else f"this console ships a /api/agent route handler but {source} does not use it"
    )
    if not proxies_through_own_origin:
        assert re.search(r'from\s+"(?:\.\./)+lib/api"', pills), (
            f"{source} must reach its backend through ui/lib/api rather than a base of its own"
        )
        assert "watchAnswers(window, API_BASE," in pills, (
            "the answer watcher does not match the base every other call uses, so it would "
            "ignore the very responses that name the model"
        )


def test_the_pills_start_from_healthz_and_follow_both_answer_headers() -> None:
    """The whole chain, held from the offline gate.

    The pills start from the service's own ``/healthz``, read both answer headers through the
    one fetch wrapper, and the service exposes both to a cross-origin console. A console that
    could not read the headers would leave the pills configured forever with every node test
    green. ``ui/tests/answer-provenance.test.mjs`` proves the wrapper itself.
    """
    pills = _code_only(_pills_source().read_text())
    assert "healthz(" in pills, "the pills do not start from the service's own /healthz"
    assert "generator_model" in pills and "runtime" in pills
    for state in ('data-state="configured"', 'data-state="answered"'):
        assert state in pills
    assert 'data-testid="model-pills"' in pills
    assert re.search(r">\s*Search\s*<", pills), "the search pill is not spelled Search"
    watcher = (UI / "lib" / "answer-provenance.mjs").read_text(encoding="utf-8")
    for header in ('"x-answered-by"', '"x-search-used"'):
        assert header in watcher, "the pills never read " + header
    assert (UI / "tests" / "answer-provenance.test.mjs").is_file()
    app = _code_only(Path("src/credit_memo/api/app.py").read_text(encoding="utf-8"))
    assert "install_answer_provenance(app)" in app, "the service emits no answer headers"
    assert not (UI / "components" / "ProvenanceBanner.tsx").exists(), "the old banner is back"


#: Utility classes that move an element UP, out of the viewport.
_PULLS_UP = ("-mt-", "-my-", "-top-", "-inset-y-", "-inset-")


def test_the_pills_are_pinned_where_a_reader_can_see_them() -> None:
    """Fixed to the viewport's top right, and never hoisted out of it.

    A strip that renders off-screen satisfies every other assertion in this file; that happened
    to the banner in eight trees. The pills are ``position: fixed`` and anchored by ``top`` and
    ``right``, so no page's padding can move them, and nothing may pull them up.
    """
    pills = _code_only(_pills_source().read_text())
    container = re.search(r'className="([^"]*)"\s*\n\s*data-testid="model-pills"', pills)
    assert container, "the pills' container carries no class list this check can read"
    classes = container.group(1).split()
    assert "fixed" in classes
    assert any(c.startswith("top-") for c in classes), classes
    assert any(c.startswith("right-") for c in classes), classes
    assert any(c.startswith("z-") for c in classes), "the pills can slide under page content"
    offenders = sorted(
        {token for token in re.findall(r"[-\w:./\[\]%]+", pills) if token.startswith(_PULLS_UP)}
    )
    assert not offenders, f"the pills carry {offenders}, which pulls them above the viewport"
