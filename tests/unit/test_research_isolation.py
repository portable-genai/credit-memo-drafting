"""Nothing found on the web may reach a calculation, a memo, or an export.

The research panel is the one place this service reaches outside the bank's own evidence,
and it is fenced on three sides for three different reasons. These tests hold each fence,
because every one of them is the kind that fails silently:

**Licensing.** Google's Service Specific Terms section 20(k) permit Grounded Results to be
displayed only to the End User who submitted the prompt, forbid interspersing them with
other content, and survive termination. A credit memo is read by a checker, a committee
and an examiner — none of whom submitted the prompt. A memo that quietly included a
grounded snippet would look like a better memo and be a licence breach.

**Residency.** Queries carry public identity only. A borrower's registered name is public;
its UEN, its account numbers, its directors' names and the terms of its facility are not,
and a search string leaves the deploy region.

**The engine boundary.** ``WebEvidence`` carries no numeric field. Not a simplification:
it is the mechanism. A ratio, a covenant test, a policy rule and a scorecard all read
numbers, and a type with no number on it cannot supply one to any of them even by
accident.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from credit_memo.adapters.gcp.gemini_web_research import (
    GeminiWebResearchAdapter,
    build_query,
)
from credit_memo.adapters.local.web_research import LocalFixtureWebResearchAdapter
from credit_memo.config import Settings
from credit_memo.domain.memo_document import build_document
from credit_memo.domain.models import (
    Borrower,
    CreditMemo,
    MarketContext,
    Provenance,
    WebEvidence,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "credit_memo"


# --------------------------------------------------------------------------- #
# 1. The type cannot carry a number
# --------------------------------------------------------------------------- #
def test_web_evidence_has_no_numeric_field() -> None:
    """The mechanism, not a simplification.

    A ratio, a covenant test, a policy rule and a scorecard all read numbers. A type with
    no number on it cannot supply one to any of them, however carelessly it is passed
    around. Adding a float here would silently open every one of those doors, so this
    fails before that can happen.
    """
    numeric = [
        field.name
        for field in dataclasses.fields(WebEvidence)
        if field.type in {"float", "int", "float | None", "int | None"}
    ]
    assert not numeric, (
        f"WebEvidence gained numeric field(s) {numeric}. That is the whole fence between "
        "the public web and the bank's arithmetic: an analyst who wants a figure from the "
        "web in the memo types it, which makes it USER_ENTERED and theirs to stand behind."
    )


def test_web_evidence_cannot_claim_another_provenance() -> None:
    with pytest.raises(ValueError, match="web-grounded by definition"):
        WebEvidence(title="t", url="u", provenance=Provenance.CONFIRMED)


# --------------------------------------------------------------------------- #
# 2. No engine can even name the type
# --------------------------------------------------------------------------- #
DETERMINISTIC_SERVICES = (
    "ratio_service.py",
    "covenant_service.py",
    "policy_exception_service.py",
    "risk_rating_service.py",
    "tie_out_service.py",
    "peer_comp_service.py",
    "spread_service.py",
)


@pytest.mark.parametrize("filename", DETERMINISTIC_SERVICES)
def test_no_engine_imports_or_names_web_context(filename: str) -> None:
    """An engine that can see the type is an engine that can read from it.

    The AST is checked rather than the runtime behaviour because the failure this guards
    against is a future edit, not a current bug.
    """
    module = ast.parse((SRC / "domain" / filename).read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names = {alias.name for alias in node.names}
            offences += [f"imports {n}" for n in names & {"WebEvidence", "MarketContext"}]
        elif isinstance(node, ast.Name) and node.id in {"WebEvidence", "MarketContext"}:
            offences.append(f"names {node.id}")
    assert not offences, f"{filename} {offences}: web context must not reach an engine"


# --------------------------------------------------------------------------- #
# 3. It never reaches the memo or the export
# --------------------------------------------------------------------------- #
def test_the_memo_has_nowhere_to_put_web_context() -> None:
    """Not filtered out of the memo. There is no field for it.

    A filter can be forgotten; an absent field cannot be populated. If a future wave wants
    web context on the memo, it has to add a field here and this test will make that a
    decision rather than an accident.
    """
    fields = {f.name for f in dataclasses.fields(CreditMemo)}
    for forbidden in ("market_context", "web_evidence", "research", "web_citations"):
        assert forbidden not in fields, (
            f"CreditMemo gained {forbidden!r}. Grounded results may be displayed only to "
            "the user who ran the query, and a memo is read by a checker, a committee and "
            "an examiner."
        )


def test_the_export_builder_cannot_render_web_context() -> None:
    """Asserted on the built document rather than a rendered string.

    A renderer that hid the content would still pass a string check. This fails at the
    point the pack's contents are decided, which is where the licence obligation actually
    binds.
    """
    document = build_document(
        CreditMemo(borrower=Borrower(id="acme", name="Acme"), summary="A summary.")
    )
    rendered = " ".join(
        block.text + " ".join(block.items) + " ".join(" ".join(r) for r in block.rows)
        for block in document.blocks
    ).lower()
    for forbidden in ("web_grounded", "web-grounded", "grounded result", "search suggestion"):
        assert forbidden not in rendered


# --------------------------------------------------------------------------- #
# 4. The query carries public identity only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "unsafe",
    [
        pytest.param("Acme Pte Ltd account 0123456789", id="account number"),
        pytest.param("Acme Pte Ltd UEN 201812345K", id="SG UEN"),
        pytest.param("Acme Pte Ltd SG12ABCD1234567890123", id="IBAN"),
        pytest.param("contact tan.wei.ming@acme.example about covenants", id="a person"),
    ],
)
def test_a_query_carrying_bank_data_is_refused_not_scrubbed(unsafe: str) -> None:
    """Refused, because a scrubbed query is a different question.

    An analyst who receives results for a question they did not ask has been misled more
    quietly than one who receives nothing.
    """
    adapter = GeminiWebResearchAdapter(Settings(profile="local"))
    assert adapter._safe_query(unsafe) == ""
    assert adapter.research(unsafe) is None


def test_public_identity_passes() -> None:
    adapter = GeminiWebResearchAdapter(Settings(profile="local"))
    query = build_query("Acme Manufacturing Pte Ltd", "manufacturing", "SG", "sector outlook")
    assert adapter._safe_query(query) == query


def test_the_per_analysis_query_cap_is_enforced() -> None:
    """Grounding is billed per query with no free allowance on this billing account."""
    adapter = GeminiWebResearchAdapter(Settings(profile="local"))
    adapter._queries_run = adapter.MAX_QUERIES_PER_ANALYSIS
    assert adapter.research("manufacturing sector outlook") is None


# --------------------------------------------------------------------------- #
# 5. "Could not look" and "looked and found nothing" stay distinguishable
# --------------------------------------------------------------------------- #
def test_no_fixture_returns_none_rather_than_an_empty_result() -> None:
    """The two answers lead an analyst to do different things next."""
    adapter = LocalFixtureWebResearchAdapter(Settings(profile="local"))
    assert adapter.research("a sector with no fixture") is None


def test_a_fixture_returns_evidence_and_the_required_suggestion_chips() -> None:
    adapter = LocalFixtureWebResearchAdapter(Settings(profile="local"))
    context = adapter.research("manufacturing sector outlook")
    assert context is not None
    assert context.evidence and not context.found_nothing
    assert all(e.url for e in context.evidence), "a claim with no URL is not usable"
    # Google requires the chips rendered; dropping them is a licence breach that looks
    # like a tidy interface.
    assert context.search_suggestions


def test_found_nothing_is_distinct_from_could_not_look() -> None:
    empty = MarketContext(query="q", evidence=())
    assert empty.found_nothing is True


# --------------------------------------------------------------------------- #
# 6. Off unless a deployment switches it on
# --------------------------------------------------------------------------- #
def test_research_is_off_by_default(monkeypatch) -> None:
    """The search leg leaves the region and is billed per query.

    Both are decisions a deployment should take deliberately rather than inherit.
    """
    from credit_memo.config import Container

    monkeypatch.delenv("CREDIT_MEMO_RESEARCH_ENABLED", raising=False)
    assert Container(Settings.load("config/settings.yaml")).web_research is None


def test_research_binds_when_switched_on(monkeypatch) -> None:
    from credit_memo.config import Container

    monkeypatch.setenv("CREDIT_MEMO_RESEARCH_ENABLED", "1")
    adapter = Container(Settings.load("config/settings.yaml")).web_research
    assert adapter is not None
