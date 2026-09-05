"""RevisionService — which version the committee read, and who wrote which sentence.

A memo is decision-support somebody relied on. Two questions follow from that and neither
can be answered by a memo that exists only as the latest text:

* **Which version did they read?** Revisions are numbered and hash-chained. Each carries
  the digest of its parent, so altering an earlier revision's content breaks every digest
  after it. A quiet edit to what the committee saw becomes detectable rather than merely
  discouraged.
* **Who wrote this paragraph?** Authorship is tracked per section. A reader deciding
  whether to rely on a sentence is entitled to know whether a person stood behind it, and
  "the whole memo was reviewed" is not the same claim as "a person wrote this part".

What this is not: a durable archive. Revisions live in the analysis bundle and die with it
after the retention window, like everything else in this service. The chain protects
integrity *within* that window. A bank that needs the memo to outlive the evidence is
running a system of record, which this deliberately is not.

Pure domain code: no ports, no I/O, no model. The chaining is stdlib hashing over
canonical JSON, so a verifier needs nothing but the revisions themselves.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import (
    Authorship,
    MemoRevision,
    SectionEdit,
    utcnow,
)


def canonical_json(payload: Any) -> str:
    """Stable JSON: sorted keys, no incidental whitespace, ASCII-escaped.

    Stability is the whole requirement. A digest over JSON whose key order depends on
    dict insertion would change when nothing changed, and a chain that breaks for no
    reason is a chain everybody learns to ignore.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def digest_of(payload: Any, parent_digest: str = "") -> str:
    """SHA-256 over the parent digest and this revision's content.

    Including the parent is what makes it a chain rather than a set of independent
    checksums: a revision's digest depends on everything that came before it.
    """
    material = f"{parent_digest}\n{canonical_json(payload)}".encode()
    return hashlib.sha256(material).hexdigest()


class RevisionService:
    """Append revisions, record who edited what, and verify the chain still holds."""

    def first(self, memo_json: dict, actor: str, note: str = "") -> MemoRevision:
        """Revision 1: the memo as it was built, before anybody touched it.

        Every section is MODEL authorship, which is the honest starting state. A memo
        nobody has edited is a memo nobody has vouched for, and the reader should see
        that rather than infer it from an absence.
        """
        authorship = {section: Authorship.MODEL.value for section in _sections_of(memo_json)}
        return MemoRevision(
            revision=1,
            memo_json=memo_json,
            actor=actor,
            digest=digest_of(memo_json),
            parent_digest="",
            authorship=authorship,
            note=note or "initial draft",
        )

    def amend(
        self,
        previous: MemoRevision,
        memo_json: dict,
        actor: str,
        edits: tuple[SectionEdit, ...] = (),
        note: str = "",
    ) -> MemoRevision:
        """The next revision, chained to ``previous``.

        Authorship is carried forward and updated for the sections this revision touched:
        a section a person rewrote becomes ANALYST, one they altered becomes EDITED, and
        one they left alone keeps whatever it was. That distinction matters to a reader —
        "a person wrote this" and "a person tidied the model's version of this" are
        different levels of assurance.
        """
        authorship = dict(previous.authorship)
        for section in _sections_of(memo_json):
            authorship.setdefault(section, Authorship.MODEL.value)
        for edit in edits:
            authorship[edit.section] = (
                Authorship.ANALYST.value if not edit.before.strip() else Authorship.EDITED.value
            )
        return MemoRevision(
            revision=previous.revision + 1,
            memo_json=memo_json,
            actor=actor,
            digest=digest_of(memo_json, previous.digest),
            parent_digest=previous.digest,
            edits=edits,
            authorship=authorship,
            at=utcnow(),
            note=note,
        )

    @staticmethod
    def edits_between(
        before: dict, after: dict, actor: str, reason: str = ""
    ) -> tuple[SectionEdit, ...]:
        """Which narrative sections a person changed, and what they said before.

        Only the prose sections: the figures are the engines' and are not editable by
        hand, which is a property Wave 0 enforces by type rather than by convention here.
        """
        out: list[SectionEdit] = []
        for section in _EDITABLE_SECTIONS:
            old = str(before.get(section) or "")
            new = str(after.get(section) or "")
            if old != new:
                out.append(
                    SectionEdit(section=section, before=old, after=new, actor=actor, reason=reason)
                )
        return tuple(out)

    @staticmethod
    def verify(revisions: tuple[MemoRevision, ...]) -> tuple[bool, str]:
        """Whether the chain still holds, and where it first does not.

        Returns the reason rather than just False. "Revision 3's content no longer
        produces its recorded digest" tells a reviewer where to look; a bare False tells
        them to distrust everything.
        """
        parent = ""
        for index, revision in enumerate(revisions, start=1):
            if revision.revision != index:
                return False, (
                    f"revision numbering jumps at position {index}: found "
                    f"{revision.revision}. A missing revision is a version somebody read "
                    "and the record no longer holds."
                )
            if revision.parent_digest != parent:
                return False, (
                    f"revision {revision.revision} names parent {revision.parent_digest[:12]!r} "
                    f"but the previous revision hashes to {parent[:12]!r}"
                )
            recomputed = digest_of(revision.memo_json, parent)
            if recomputed != revision.digest:
                return False, (
                    f"revision {revision.revision}'s content no longer produces its recorded "
                    "digest: it was altered after it was saved"
                )
            parent = revision.digest
        return True, "the revision chain is intact"


#: The parts of a memo an analyst writes rather than an engine computes. Editing anywhere
#: else is refused upstream: a ratio is COMPUTED by type and a covenant status is tested,
#: so neither has an editable form to offer.
#: The sections a person may rewrite. Public because the API refuses an edit to anything
#: else and has to be able to say what IS editable; the figures belong to the engines, and
#: a memo whose leverage could be typed over by hand would put a number in front of a
#: committee that no formula produced.
EDITABLE_SECTIONS: tuple[str, ...] = (
    "summary",
    "recommendation_rationale",
)

_EDITABLE_SECTIONS = EDITABLE_SECTIONS


def _sections_of(memo_json: dict) -> tuple[str, ...]:
    """The sections authorship is tracked for: the prose, plus anything present."""
    return tuple(section for section in _EDITABLE_SECTIONS if section in memo_json)
