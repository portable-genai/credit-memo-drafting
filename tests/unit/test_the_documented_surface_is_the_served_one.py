"""The HTTP surface the documents describe is the one the application registers.

`README.md` listed six routes where the app serves twenty-six, and nothing noticed, because
a route table is a copied snapshot: it is stale the moment a route lands and no check looks at
it. Section 6.1 of `SPEC.md` is the normative list and had stayed current only by attention.

Both are now checked against `app.routes` in BOTH directions. A route added with no row fails,
and a row naming a route the app no longer serves fails, so neither document can describe a
fraction of the surface again and neither can keep advertising a path that has been removed.

The README and the SPEC are deliberately NOT checked against each other. They answer different
questions: the SPEC owns the request and response shapes and is the normative contract, and the
README owns the paths and what each is for. Comparing them would make one the other's copy,
which is how this went wrong in the first place.

What is not asserted here: the PURPOSE column, which is prose nobody can mechanically check,
and the ORDER, which each document chooses for its own reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from credit_memo.api.app import app

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
SPEC = REPO / "SPEC.md"

#: A markdown table row whose first cell is an HTTP verb and whose second is a backticked path.
_ROW = re.compile(r"^\|\s*(GET|POST|PATCH|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)

#: Path parameters are named differently in prose than in code (`{id}` against
#: `{analysis_id}`), and which name a document chooses is a readability decision rather than a
#: claim about the surface. The SHAPE is the claim, so every parameter flattens to `{}`.
_PARAM = re.compile(r"\{[^}]*\}")


def _flatten(path: str) -> str:
    return _PARAM.sub("{}", path.split("?")[0]).rstrip("/")


def _served() -> set[tuple[str, str]]:
    """Every (method, path) the application registers, HEAD and OPTIONS aside."""
    served = {
        (method, _flatten(route.path))
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    # A count, not a truthiness check: an import that quietly registered nothing would make
    # every comparison below pass over an empty set.
    assert len(served) >= 20, (
        f"the app registered only {len(served)} routes, so this proves nothing"
    )
    return served


def _documented(document: Path) -> set[tuple[str, str]]:
    rows = {(method, _flatten(path)) for method, path in _ROW.findall(document.read_text("utf-8"))}
    assert rows, f"{document.name} carries no HTTP route table, so nothing here is checked"
    return rows


@pytest.mark.parametrize("document", [README, SPEC], ids=["README", "SPEC"])
def test_the_document_names_every_route_the_app_serves(document: Path) -> None:
    missing = sorted(f"{m} {p}" for m, p in _served() - _documented(document))
    assert not missing, (
        f"{document.name} does not name {missing}. A route table that lists a fraction of the "
        "surface is worse than none: a reader takes it for the whole list."
    )


@pytest.mark.parametrize("document", [README, SPEC], ids=["README", "SPEC"])
def test_the_document_names_no_route_the_app_stopped_serving(document: Path) -> None:
    gone = sorted(f"{m} {p}" for m, p in _documented(document) - _served())
    assert not gone, (
        f"{document.name} advertises {gone}, which this application does not serve. A caller "
        "who writes against a documented path and gets a 404 has been misled by the document."
    )
