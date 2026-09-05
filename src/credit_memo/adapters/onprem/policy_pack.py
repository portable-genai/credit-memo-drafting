"""On-prem placeholder for ``PolicyPackPort`` — the sovereign target.

A reversibility (P-02, P-12) migration placeholder. The adopter's policy almost certainly
already lives in a system of record rather than a YAML file, and this is where that
system is bound. The contract to keep: return the pack IN FORCE with its version, and be
able to return an older one by version so a stored memo replays against the policy it was
actually written under.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import PolicyPack, RatingScorecard

_MESSAGE = (
    "On-prem PolicyPackPort adapter is a migration placeholder; bind it to the system of "
    "record that holds your credit policy and rating scorecard. It must return the pack in "
    "force with its version, and an older version on request. Core domain logic is unchanged."
)


class OnPremPolicyPackAdapter:
    """Placeholder policy-pack adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def current(self) -> PolicyPack:
        raise NotImplementedError(_MESSAGE)

    def load(self, version: str) -> PolicyPack:
        raise NotImplementedError(_MESSAGE)

    def scorecard(self) -> RatingScorecard | None:
        raise NotImplementedError(_MESSAGE)
