"""Which version the committee read, and what a renewal actually says.

Two mechanisms, both of which exist because a memo is something somebody relied on.

**Revisions** answer "which version did they read". The chain is hash-linked, so altering
an earlier revision breaks every digest after it: a quiet edit to what the committee saw
becomes detectable rather than merely discouraged. Authorship answers the narrower
question a reader actually asks of a paragraph — did a person write this, or tidy it, or
neither.

**The renewal diff** answers "what changed". A renewal re-underwrites a facility the bank
already holds; its reader knows the borrower and needs the difference. A renewal that
repeats the history has buried its own point, so "unchanged" is stated rather than
re-stated.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from credit_memo.domain.models import (
    Authorship,
    Borrower,
    Covenant,
    CovenantOperator,
    CovenantStatus,
    CovenantType,
    CreditMemo,
    PolicyException,
    PolicyOperator,
    Ratio,
    RiskRatingProposal,
    Severity,
)
from credit_memo.domain.renewal_diff_service import RenewalDiffService
from credit_memo.domain.revision_service import RevisionService

ANALYST = "analyst@bank.example"
DRAFT = {"summary": "The model's draft.", "recommendation_rationale": "Support."}


# --------------------------------------------------------------------------- #
# Revisions
# --------------------------------------------------------------------------- #
def test_the_first_revision_says_nobody_has_vouched_for_it_yet() -> None:
    """A memo nobody has edited is a memo nobody has stood behind, and should say so."""
    first = RevisionService().first(DRAFT, actor="system")
    assert first.revision == 1
    assert first.parent_digest == ""
    assert set(first.authorship.values()) == {Authorship.MODEL.value}


def test_editing_a_section_records_who_and_what_it_said_before() -> None:
    service = RevisionService()
    first = service.first(DRAFT, actor="system")
    edited = {**DRAFT, "summary": "The analyst's rewrite."}
    second = service.amend(
        first, edited, actor=ANALYST, edits=service.edits_between(DRAFT, edited, ANALYST)
    )

    assert second.revision == 2
    assert second.parent_digest == first.digest
    (edit,) = second.edits
    assert edit.section == "summary"
    assert edit.before == "The model's draft."  # what the machine actually said, kept
    assert edit.actor == ANALYST
    # Edited, not authored: a person tidying the model's version is a different level of
    # assurance from a person writing it.
    assert second.authorship["summary"] == Authorship.EDITED.value
    assert second.authorship["recommendation_rationale"] == Authorship.MODEL.value


def test_writing_a_section_that_was_empty_counts_as_authorship() -> None:
    service = RevisionService()
    blank = {"summary": "", "recommendation_rationale": "Support."}
    first = service.first(blank, actor="system")
    written = {**blank, "summary": "Written from scratch by the analyst."}
    second = service.amend(
        first, written, actor=ANALYST, edits=service.edits_between(blank, written, ANALYST)
    )
    assert second.authorship["summary"] == Authorship.ANALYST.value


def test_an_intact_chain_verifies() -> None:
    service = RevisionService()
    first = service.first(DRAFT, actor="system")
    second = service.amend(first, {**DRAFT, "summary": "v2"}, actor=ANALYST)
    third = service.amend(second, {**DRAFT, "summary": "v3"}, actor=ANALYST)
    intact, reason = service.verify((first, second, third))
    assert intact, reason


def test_altering_an_earlier_revision_breaks_the_chain() -> None:
    """The property the whole mechanism exists for.

    Someone with write access can change what revision 1 said. What they cannot do is
    make revision 2's digest reconcile afterwards.
    """
    service = RevisionService()
    first = service.first(DRAFT, actor="system")
    second = service.amend(first, {**DRAFT, "summary": "v2"}, actor=ANALYST)

    tampered = replace(first, memo_json={**DRAFT, "summary": "Something else entirely."})
    intact, reason = service.verify((tampered, second))
    assert not intact
    assert "altered after it was saved" in reason


def test_a_removed_revision_is_detected() -> None:
    """A missing version is a version somebody read and the record no longer holds."""
    service = RevisionService()
    first = service.first(DRAFT, actor="system")
    second = service.amend(first, {**DRAFT, "summary": "v2"}, actor=ANALYST)
    third = service.amend(second, {**DRAFT, "summary": "v3"}, actor=ANALYST)

    intact, reason = service.verify((first, third))
    assert not intact
    assert "numbering jumps" in reason or "parent" in reason


def test_the_digest_is_stable_across_key_order() -> None:
    """A chain that breaks for no reason is a chain everybody learns to ignore."""
    service = RevisionService()
    one = service.first({"summary": "a", "recommendation_rationale": "b"}, actor="x")
    two = service.first({"recommendation_rationale": "b", "summary": "a"}, actor="x")
    assert one.digest == two.digest


def test_verify_says_where_the_chain_broke_not_merely_that_it_did() -> None:
    """A bare False tells a reviewer to distrust everything, which is not actionable."""
    service = RevisionService()
    first = service.first(DRAFT, actor="system")
    second = service.amend(first, {**DRAFT, "summary": "v2"}, actor=ANALYST)
    _, reason = service.verify((replace(first, memo_json={"summary": "x"}), second))
    assert "revision 1" in reason


# --------------------------------------------------------------------------- #
# The renewal diff
# --------------------------------------------------------------------------- #
def _memo(**overrides) -> CreditMemo:
    base = {
        "borrower": Borrower(id="acme", name="Acme"),
        "summary": "This year's summary.",
        "recommendation_rationale": "Support.",
        "ratios": (
            Ratio(
                formula_id="leverage.v1",
                name="Leverage",
                period="FY2025",
                value=3.4,
                definition="total debt / EBITDA",
            ),
        ),
        "covenants": (
            Covenant(
                type=CovenantType.LEVERAGE,
                description="Net leverage",
                threshold=3.0,
                operator=CovenantOperator.LE,
                current_value=3.4,
                status=CovenantStatus.BREACH,
            ),
        ),
        "policy_exceptions": (
            PolicyException(
                rule_id="LEV-01",
                description="Maximum leverage",
                measured=3.4,
                limit=3.0,
                operator=PolicyOperator.LE,
                severity=Severity.HIGH,
            ),
        ),
        "rating": RiskRatingProposal(obligor_grade="4 - Acceptable", score=3.9),
    }
    return CreditMemo(**{**base, **overrides})


PRIOR = {
    "generated_at": "2025-09-01T00:00:00+00:00",
    "summary": "Last year's summary.",
    "recommendation_rationale": "Support.",
    "ratios": [{"formula_id": "leverage.v1", "period": "FY2025", "value": 2.5}],
    "covenants": [{"type": "leverage", "current_value": 2.5}],
    "policy_exceptions": [{"rule_id": "DSCR-01"}],
    "rating": {"obligor_grade": "2 - Good"},
}


def test_a_material_move_is_reported_with_both_numbers_and_a_direction() -> None:
    delta = RenewalDiffService().compare(_memo(), PRIOR)
    (leverage,) = delta.ratios
    assert leverage.before == 2.5 and leverage.after == 3.4
    assert leverage.direction == "up"
    assert leverage.change == pytest.approx(0.9)


def test_an_immaterial_move_is_not_reported() -> None:
    """A renewal flagging 2.500 to 2.501 trains its reader to skim the delta table."""
    prior = {
        **PRIOR,
        "ratios": [{"formula_id": "leverage.v1", "period": "FY2025", "value": 3.4005}],
    }
    assert not RenewalDiffService().compare(_memo(), prior).ratios


def test_a_rating_that_moved_is_flagged_with_both_grades() -> None:
    delta = RenewalDiffService().compare(_memo(), PRIOR)
    assert delta.rating_moved
    assert delta.rating_before == "2 - Good" and delta.rating_after == "4 - Acceptable"


def test_new_and_cleared_exceptions_are_both_reported() -> None:
    """A cleared exception is the argument for the renewal, and is invisible unless said."""
    delta = RenewalDiffService().compare(_memo(), PRIOR)
    assert delta.new_exceptions == ("LEV-01",)
    assert delta.cleared_exceptions == ("DSCR-01",)


def test_unchanged_sections_are_named_so_a_reader_can_skip_them() -> None:
    """ "Unchanged" is information: it is what makes a renewal shorter than a new memo."""
    delta = RenewalDiffService().compare(_memo(), PRIOR)
    assert "Recommendation rationale" in delta.unchanged_sections
    assert "Summary" not in delta.unchanged_sections  # it did change


def test_a_prior_memo_in_an_older_format_produces_fewer_deltas_not_an_error() -> None:
    """The prior memo is an upload, so it may predate half these fields."""
    delta = RenewalDiffService().compare(_memo(), {"summary": "Old."})
    assert delta.rating_before == ""
    assert delta.ratios  # everything present now is "new" against a memo that had none
    assert delta.ratios[0].direction == "new"
