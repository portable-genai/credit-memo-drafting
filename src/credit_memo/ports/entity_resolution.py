"""EntityResolutionPort — who else is in this borrower's group, according to a public register.

The group a memo consolidates is whatever the analyst uploaded, and that will stay true: this
port supplies a SUGGESTION about who else exists, never a figure. An entity it names with no
uploaded statements behind it lands in ``entities_without_figures`` exactly like one the
analyst typed, which is the outcome that keeps a global cash flow honest — the register
supplies the denominator of completeness, and the analyst still supplies every number.

Three fences, each for a different reason.

**Residency.** A register lookup sends the borrower's registered legal name outside the
deploy region. That is a weaker posture than the peer leg, which sends no borrower identity
at all, so this port is **off unless a deployment switches it on** and the deviation is
recorded rather than inherited. Queries carry public identity only, and one matching an
account number, a UEN/NRIC shape, an IBAN or an email address is refused rather than
scrubbed: a scrubbed query is a different question, and an analyst who receives an answer to
a question they did not ask has been misled more quietly than one who receives nothing.

**The engine boundary.** Everything this port returns is :class:`RelatedEntity` and carries
``Provenance.VENDOR``, which is not in ``ENGINE_READABLE``. A ``RelatedEntity`` holds no
figure at all, so there is nothing here for a ratio, a covenant test or a scorecard to reach
for. Match quality is an enum rather than a score for the same reason: a float on this path
is a number, and a number is the thing that must not cross.

**Ambiguity is reported, not resolved.** Two companies with similar names in the same
jurisdiction is the normal case, not the edge case, and picking the shortest name would
attach the wrong group to a credit file. The adapter says AMBIGUOUS and returns what it
found; choosing is the analyst's.

An adapter that cannot look returns ``None`` rather than an empty group, because "we did not
look" and "we looked and the register knows of no parent" lead an analyst to do different
things next.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import EntityGroup


@runtime_checkable
class EntityResolutionPort(Protocol):
    def resolve_group(
        self,
        name: str,
        jurisdiction: str = "",
        max_members: int = 25,
    ) -> EntityGroup | None:
        """The register's view of this company's group, or None if it could not look.

        One call rather than resolve-then-expand: an identifier the caller has to carry
        between two calls is an identifier a caller can substitute, and the whole value of
        this port is that the group it reports is the one the register holds for the name
        that was asked about.
        """
        ...
