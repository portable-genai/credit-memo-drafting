"""Human-in-the-loop (maker-checker) policy — General Principle P-06.

B2 is *decision-support*, never a credit decision. P-06 (maker-checker) requires that a
human (a credit officer) reviews any consequential or low-assurance output before it is
relied upon. This module centralises that gate so the orchestrator applies identical
rules and the threshold is auditable in one place.

Policy (SPEC §5):
* A credit memo is consequential and **always** requires human review: a maker (the
  assistant) proposes and a checker (a qualified credit officer) disposes.
* Any BREACH covenant, or any HIGH / CRITICAL risk flag, **escalates** the memo (a
  stronger signal than the always-on review flag) so it is routed to enhanced review and
  the audit decision is ESCALATED.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Covenant,
    CovenantStatus,
    RiskFlag,
    Severity,
)

#: Risk-flag severities that escalate a memo to enhanced review.
_ESCALATING_SEVERITIES: frozenset[Severity] = frozenset({Severity.HIGH, Severity.CRITICAL})


@dataclass(frozen=True, slots=True)
class CreditReviewPolicy:
    """Maker-checker gate (P-06). Pure decision logic; no side effects."""

    def requires_review(self) -> bool:
        """A credit memo always requires human review (it is consequential)."""
        return True

    def escalates(
        self,
        covenants: tuple[Covenant, ...] = (),
        risk_flags: tuple[RiskFlag, ...] = (),
    ) -> bool:
        """Decide whether the memo escalates to enhanced review.

        Escalates when any covenant is in BREACH or any risk flag is HIGH/CRITICAL.
        Escalation only ever *raises* the review bar.

        Args:
            covenants: the covenants attached to the memo (with tested status).
            risk_flags: the risk flags attached to the memo.

        Returns:
            True if the memo must be routed to enhanced (escalated) review.
        """
        if any(c.status is CovenantStatus.BREACH for c in covenants):
            return True
        return any(f.severity in _ESCALATING_SEVERITIES for f in risk_flags)
