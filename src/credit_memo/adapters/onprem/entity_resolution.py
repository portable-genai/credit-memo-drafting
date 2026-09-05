"""On-prem placeholder for ``EntityResolutionPort`` — the sovereign target.

A reversibility (P-02, P-12) migration placeholder, and a more pointed one than most: a
sovereign deployment with no route to the public internet cannot reach a public register at
all. Filling this body in means pointing it at whatever registry copy the institution holds
in country, which is a decision about their data rather than about this code.

Constructs with no external dependency and structurally satisfies the same Protocol, so the
contract tests prove interface parity.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import EntityGroup


class OnPremEntityResolutionAdapter:
    """Fail-fast placeholder: the same interface, no implementation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_group(
        self,
        name: str,
        jurisdiction: str = "",
        max_members: int = 25,
    ) -> EntityGroup | None:
        raise NotImplementedError(
            "On-prem EntityResolutionPort adapter is a migration placeholder; implement it "
            "against the in-country registry copy this institution holds. A sovereign "
            "deployment has no route to a public register."
        )

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - parity ergonomics
        raise NotImplementedError(f"On-prem EntityResolutionPort does not implement {item!r}")
