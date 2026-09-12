"""What the service serves, the console can reach, and the browser will let it.

Four capabilities shipped with routes, unit tests and no client at all: export, memo amendment
with its revision chain, comments and delete. From outside, a capability with no client is
indistinguishable from one nobody built, and nothing in the gate went red. The CORS allowlist
compounded it: ``allow_methods`` was GET, POST and OPTIONS, so a browser would have refused a
cross-origin PATCH or DELETE before it reached a route even once the buttons existed, and that
refusal appears only in the browser's own console, which is the one place a green suite never
looks.

Two structural checks, so neither half can drift again:

1. the CORS allowlist admits exactly the verbs the client issues, and no more;
2. every route the app serves has a client in ``ui/lib/api.ts``, or is named below with the
   reason a console does not reach it.

Structural rather than a list of expected routes, because a hand-written list is what goes
stale: a new route with no client fails this test on the day it is added.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from credit_memo.api.app import app

CLIENT = Path(__file__).resolve().parents[2] / "ui" / "lib" / "api.ts"

#: Routes no console control reaches, each with the reason. An entry here is a reviewable
#: claim, not a way past the check: it says a browser has no business calling this route.
_NOT_REACHED_FROM_THE_CONSOLE = {
    ("GET", "/.well-known/agent-card.json"): (
        "agent-to-agent discovery. Another service reads this card; a person never does, and "
        "the console would have nothing to render from it."
    ),
    ("GET", "/v1/analyses/{analysis_id}/spreads"): (
        "both halves of the spread side by side. The console is HANDED each half as it happens, "
        "as the response to extract and to confirm, so it has nothing to read back: there is no "
        "route into an analysis opened in an earlier session. The demo reads it to check what "
        "the console was given."
    ),
}


def _client_source() -> str:
    return CLIENT.read_text(encoding="utf-8")


def _normalise(path: str) -> str:
    """A path with its parameters flattened, so a route and a template string compare equal.

    A trailing placeholder that is not its own segment is a query string the client appends
    (`.../research${suffix}`), not part of the path, so it is dropped rather than compared.
    """
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = re.sub(r"(?<=[^/]){}$", "", path)
    return path.split("?")[0].rstrip("/")


def _client_calls(source: str) -> set[tuple[str, str]]:
    """Every (method, path) the client actually issues, read off its fetch calls."""
    calls: set[tuple[str, str]] = set()
    for match in re.finditer(r"fetch\(\s*`([^`]+)`", source):
        url = match.group(1).replace("${API_BASE}", "")
        tail = source[match.end() : match.end() + 400]
        method = re.search(r'method:\s*"([A-Z]+)"', tail)
        calls.add(((method.group(1) if method else "GET"), _normalise(url)))
    return calls


def _cors_allow_methods() -> list[str]:
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return list(middleware.kwargs["allow_methods"])
    raise AssertionError("the app serves no CORS middleware, so no browser could call it")


def test_every_verb_the_client_issues_is_one_cors_admits() -> None:
    source = _client_source()
    calls = _client_calls(source)
    assert len(calls) >= 15, f"parsed only {len(calls)} client calls, so this asserts nothing"
    # Every call names its verb: an implicit GET would read as covered while being one more
    # thing the allowlist has to admit.
    assert source.count("fetch(") == source.count("method: "), (
        "a fetch in ui/lib/api.ts does not name its method, so the verb it sends is implicit"
    )
    issued = {method for method, _ in calls}
    allowed = set(_cors_allow_methods())
    assert "*" not in allowed, "a wildcard CORS allowlist trusts every verb"
    # Equality both ways. Missing verbs are the defect that shipped; extra ones widen the
    # surface a browser may use beyond what the console needs.
    assert issued <= allowed, f"the console issues {sorted(issued - allowed)}, which CORS refuses"
    assert allowed - issued == {"OPTIONS"}, (
        f"CORS admits {sorted(allowed - issued - {'OPTIONS'})}, which the console never issues"
    )


def test_every_route_the_app_serves_has_a_client_or_a_stated_reason() -> None:
    source = _client_source()
    calls = _client_calls(source)
    # A GET the console reaches by link rather than by fetch (a cited document, the upload
    # template) is reachable too: its URL is built in the same client module.
    templates = re.findall(r"`([^`]*\$\{API_BASE\}[^`]*)`", source)
    linked = {_normalise(url.replace("${API_BASE}", "")) for url in templates}

    unreachable: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            path = _normalise(route.path)
            if (method, path) in calls:
                continue
            if method == "GET" and path in linked:
                continue
            if (method, route.path) in _NOT_REACHED_FROM_THE_CONSOLE:
                continue
            unreachable.append(f"{method} {route.path}")

    assert not unreachable, (
        "these routes are served and no console control reaches them, which is how a "
        "capability ends up indistinguishable from one nobody built. Add a client in "
        "ui/lib/api.ts and a control, or name the route in _NOT_REACHED_FROM_THE_CONSOLE "
        f"with the reason: {sorted(unreachable)}"
    )


def test_every_stated_exception_still_names_a_route_this_app_serves() -> None:
    """An exemption that stops matching anything is an unreviewed permission left behind.

    It would sit here waiting for a future route of the same name to inherit the reason
    somebody wrote about a different one.
    """
    served = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    stale = sorted(key for key in _NOT_REACHED_FROM_THE_CONSOLE if key not in served)
    assert not stale, f"these exemptions name routes this app no longer serves: {stale}"
