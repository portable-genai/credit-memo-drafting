"""Every data-* hook the business demo locates by is one the console actually renders.

The browser suite proves the hooks work, and it needs Node, a built console and Chromium. This
check needs none of them, so it runs in the offline gate: it reads the selectors
``scripts/demo_console/locators.py`` spells and the console's own source, and fails when a hook
has been renamed or dropped on one side only. That is found here in a second, rather than as a
demo act timing out on a pull request several minutes later.

It also holds the other half of the change that introduced the hooks: the acts locate controls
by hook, not by label, role or visible text. Locating by wording tied every act to copy, so
rewording a button broke an act that proved nothing about wording.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCATORS = REPO / "scripts" / "demo_console" / "locators.py"
ACTS = REPO / "scripts" / "demo_console" / "acts.py"

#: ``[data-name="value"]`` with a literal value. A ``{placeholder}`` value is an f-string the
#: demo fills at run time, so only its attribute NAME can be checked statically.
_LITERAL_HOOK = re.compile(r'\[data-([a-z][a-z-]*)="([^"{}]+)"\]')
_HOOK_NAME = re.compile(r"\[data-([a-z][a-z-]*)[\]=]")

#: Hooks a shared component renders from a prop rather than spelling each value, so the value
#: appears in the source as that prop: ``<Section hook="summary">`` renders
#: ``data-section={hook}``. Both halves are required, the prop value AND the attribute wired to
#: the prop, or a hook named here could exist as a prop nobody renders.
_RENDERED_FROM_A_PROP = {"section": "hook"}

#: What an act must not locate a control by. Reading what a reader SEES is still fine
#: (``inner_text`` on a panel the act found by hook); FINDING the control by it is not.
_WORDING_LOCATORS = ("get_by_label(", "get_by_role(", "get_by_text(", "wait_for_selector(", "text=")


def _console_source() -> str:
    ui = REPO / "ui"
    files = sorted([*ui.glob("app/**/*.tsx"), *ui.glob("components/**/*.tsx")])
    assert files, "found no console source under ui/, so nothing below would be checked"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def _renders(source: str, name: str, value: str) -> bool:
    if f'data-{name}="{value}"' in source:
        return True
    prop = _RENDERED_FROM_A_PROP.get(name)
    return bool(prop) and f"data-{name}={{{prop}}}" in source and f'{prop}="{value}"' in source


def test_every_literal_hook_the_demo_names_is_rendered_by_the_console() -> None:
    selectors = LOCATORS.read_text(encoding="utf-8")
    hooks = sorted(set(_LITERAL_HOOK.findall(selectors)))
    # A count, not a truthiness check: a regex that silently stopped matching would report
    # green over nothing.
    assert len(hooks) >= 40, f"expected the demo's full hook set, parsed only {len(hooks)}"
    source = _console_source()
    missing = [
        f'data-{name}="{value}"' for name, value in hooks if not _renders(source, name, value)
    ]
    assert not missing, (
        "scripts/demo_console/locators.py names hooks the console does not render, so the acts "
        f"that use them find nothing: {missing}"
    )


def test_every_hook_attribute_the_demo_keys_on_is_rendered() -> None:
    names = sorted(set(_HOOK_NAME.findall(LOCATORS.read_text(encoding="utf-8"))))
    source = _console_source()
    missing = [f"data-{name}" for name in names if f"data-{name}=" not in source]
    assert not missing, f"the console renders no element carrying {missing}"


def test_no_act_locates_a_control_by_its_wording() -> None:
    code = ACTS.read_text(encoding="utf-8")
    found = [needle for needle in _WORDING_LOCATORS if needle in code]
    assert not found, (
        f"scripts/demo_console/acts.py locates by wording again ({found}). Add a data-* hook to "
        "the control, name it in locators.py, and locate by that."
    )
