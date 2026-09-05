"""PolicyPackPort — the bank's own credit policy and scorecard, as the bank wrote them.

Nothing in this repository decides what a prudent leverage cap is, which grade a score of
3.2 deserves, or who may waive a tenor breach. Those are the bank's, they differ between
banks, and they change. So they arrive as an uploaded, versioned pack and this port is
how a service reaches them.

That separation is what makes a policy exception credible. "Your policy says maximum
leverage 3.0x and this request measures 4.1x, waivable by the Regional Credit Committee"
is a sentence a committee can act on. "Our software thinks this is too leveraged" is not.

Versions matter as much as contents. A memo that says "within policy" without saying
which policy is a claim nobody can check a year later, when the pack has moved on twice,
so ``current`` returns a pack carrying its own version and digest and ``load`` fetches a
specific one for replay.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import PolicyPack, RatingScorecard


@runtime_checkable
class PolicyPackPort(Protocol):
    def current(self) -> PolicyPack:
        """The pack in force. Empty rather than raising when none is configured.

        An empty pack means no exception can be raised, which is the honest outcome for a
        deployment that has not supplied a policy: the alternative is inventing limits and
        reporting the borrower against them.
        """
        ...

    def load(self, version: str) -> PolicyPack:
        """A specific version, so a stored memo can be replayed against the pack it used."""
        ...

    def scorecard(self) -> RatingScorecard | None:
        """The rating scorecard in force, or None where the bank has not supplied one."""
        ...
