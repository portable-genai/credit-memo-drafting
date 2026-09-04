"""ReviewRouterPort: the boundary that routes an escalated credit memo to human-review-console (rule
R8).

Every credit memo is consequential decision-support and always requires human review (maker-
checker, P-06): the assistant is the maker, a qualified credit officer is the checker. Rule R8 says
a producer that sets ``requires_human_review`` MUST route the item to the human-review-console
Human-Review & Maker-Checker Console rather than terminate the escalation in a per-repo boolean.
This port is that hand-off. The domain stays pure: the adapter (not this port) depends on the shared
``review-kit`` client and does the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import CreditMemo


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, memo: CreditMemo, *, maker: str, tenant: str = "") -> None:
        """Route an escalated memo to human-review-console for human review (idempotent per borrower
        is ideal).
        """
        ...
