"""CommentService — a reviewer's objection, anchored to the text they actually read.

A checker reading a memo writes "this overstates the headroom" against a paragraph. Three
edits later that paragraph says something else. A comment system that silently re-points the
note has changed what the reviewer said, and put an objection next to text its author never
saw.

So every comment records the revision and the digest it was written against, and this
service reports — rather than resolves — the three situations that follow:

* **Open, current.** The section still reads as it did. The objection stands as written.
* **Open, but the text has moved on.** The section changed after the comment was left. The
  comment is still open, because nobody answered it, and it is flagged so a reader knows to
  re-read it against the new text rather than assume it was addressed.
* **Resolved.** A named person closed it and said what they did. Never a state the system
  reaches on its own: a comment that lapsed because the text changed underneath it was not
  answered, it was lost, and the two are indistinguishable in a list afterwards.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

from dataclasses import replace

from .models import MemoComment, MemoRevision, utcnow
from .revision_service import EDITABLE_SECTIONS, digest_of


class CommentService:
    """Add, resolve and age comments against a memo's revision chain."""

    def add(
        self,
        comments: tuple[MemoComment, ...],
        section: str,
        body: str,
        author: str,
        revisions: tuple[MemoRevision, ...],
    ) -> MemoComment:
        """A new comment against the LATEST revision, which is the one the author read.

        The section must be one the memo actually has. A comment on a section that does not
        exist is unanswerable, and accepting it produces a review thread that can never be
        cleared.
        """
        if not revisions:
            raise ValueError("there is no memo to comment on yet: build one before reviewing it.")
        latest = revisions[-1]
        if section not in latest.memo_json and section not in EDITABLE_SECTIONS:
            raise ValueError(
                f"the memo has no section {section!r}, so a comment on it could never be "
                f"answered. Sections a reviewer can anchor to: "
                f"{', '.join(sorted(set(latest.memo_json) | set(EDITABLE_SECTIONS)))}"
            )
        return MemoComment(
            id=self._next_id(comments),
            section=section,
            body=body,
            author=author,
            revision=latest.revision,
            anchor_digest=latest.digest,
        )

    @staticmethod
    def resolve(
        comments: tuple[MemoComment, ...], comment_id: str, actor: str, resolution: str = ""
    ) -> tuple[MemoComment, ...]:
        """Close one comment, naming who closed it.

        Re-resolving an already-closed comment is refused rather than silently overwriting
        the first resolution: the record of who answered an objection is exactly what a
        second write would destroy.
        """
        found = next((c for c in comments if c.id == comment_id), None)
        if found is None:
            raise ValueError(f"no comment {comment_id!r} on this memo")
        if not found.open:
            raise ValueError(
                f"comment {comment_id!r} was already resolved by {found.resolved_by}. "
                "Reopening is a new comment, so the first answer survives."
            )
        closed = replace(found, resolved_by=actor, resolved_at=utcnow(), resolution=resolution)
        return tuple(closed if c.id == comment_id else c for c in comments)

    @staticmethod
    def stale(comment: MemoComment, revisions: tuple[MemoRevision, ...]) -> bool:
        """Whether the section this comment names has changed since it was written.

        Compares the SECTION's text rather than the whole memo: an edit to the
        recommendation does not move an objection raised against the summary, and treating
        it as though it did would flag every open comment on every edit until reviewers
        stopped reading the flag.
        """
        if not revisions:
            return False
        anchored = next(
            (r for r in revisions if r.digest == comment.anchor_digest),
            None,
        ) or next((r for r in revisions if r.revision == comment.revision), None)
        if anchored is None:
            # The revision it was written against is not in the chain any more. That is a
            # stronger statement than "the text moved": the reader cannot see what was
            # commented on at all, so it is reported as stale.
            return True
        latest = revisions[-1]
        then = str(anchored.memo_json.get(comment.section) or "")
        now = str(latest.memo_json.get(comment.section) or "")
        return digest_of({"s": then}) != digest_of({"s": now})

    @staticmethod
    def _next_id(comments: tuple[MemoComment, ...]) -> str:
        """Sequential and human-quotable: a reviewer says "comment 4" out loud."""
        return f"c{len(comments) + 1}"
