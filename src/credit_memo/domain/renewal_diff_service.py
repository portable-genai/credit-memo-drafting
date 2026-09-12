"""RenewalDiffService — what moved since the last memo, which is the renewal's whole point.

A renewal re-underwrites a facility the bank already holds. Its reader knows the
borrower, has read the history, and does not need it again; what they need is the
difference. A renewal that opens with a repeated borrower overview has buried its own
point, and that is the most common failure of a renewal memo produced by a system that
treats it as a new-facility memo with a different title.

So this compares two memos and reports the movement: which ratios changed and by how
much, which spread lines moved, whether the rating shifted, which policy exceptions are
new and which have cleared. Everything else is named as unchanged rather than repeated —
"unchanged" is information a reader can act on, and re-stating it is not.

The prior memo arrives as an upload like everything else here (there is no archive to
read it from), so the comparison is against whatever the analyst supplied. That is a
property, not a limitation: the reader can see exactly which prior memo the deltas are
measured against, because it is in the manifest.

Pure domain code: no ports, no I/O, no model.
"""

from __future__ import annotations

import json
from typing import Any

from .models import RenewalDelta, SectionDelta

#: Below this, a movement is rounding or a restatement rather than news. A renewal that
#: flags leverage moving from 2.500 to 2.501 trains its reader to skim the delta table,
#: which is the one part they should not skim.
_MATERIAL = 0.005  # 0.5%


def _material(before: float | None, after: float | None) -> bool:
    if before is None or after is None:
        return True  # appearing or disappearing is always news
    scale = max(abs(before), abs(after), 1.0)
    return abs(after - before) > scale * _MATERIAL


def read_prior_memo(content: bytes) -> dict | None:
    """The uploaded prior memo as a dict, or ``None`` when the upload is not one.

    Only this service's own JSON export can be compared: it is the memo's wire shape, and
    every field the comparison reads is a key of it. A PDF of last year's memo is a perfectly
    good document and a useless baseline, so it is refused rather than parsed hopefully, and
    the refusal reaches the reader as a sentence rather than as an empty delta.

    Stdlib only, like the rest of this module.
    """
    if not content:
        return None
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    # A memo, not merely JSON. An upload carrying none of these keys would produce a delta
    # claiming every figure in this memo is new, which reads as a year of dramatic movement.
    if not any(key in parsed for key in ("summary", "ratios", "covenants", "spreads")):
        return None
    return parsed


class RenewalDiffService:
    """Compare this memo against the prior one and report what actually moved."""

    @staticmethod
    def no_comparison(reason: str, filename: str = "") -> RenewalDelta:
        """A memo whose kind leads with what changed, and which had nothing to compare against.

        Deliberately not an empty delta: that would tell a committee nothing moved, which is a
        statement about the borrower rather than about what the analysis was given. Two causes
        reach here, no prior memo at all and one that is not a memo this service produced, and
        both are said in the reason.
        """
        return RenewalDelta(prior_filename=filename, no_comparison_reason=reason)

    def compare(self, current: Any, prior: dict, prior_filename: str = "") -> RenewalDelta:
        """The movement between ``prior`` (an uploaded memo's JSON) and ``current``.

        ``prior`` is a dict rather than a ``CreditMemo`` because it arrives as an
        uploaded export rather than out of a store, and an older export will be missing
        fields this version has. Every read is defensive for that reason: a renewal
        against last year's format should produce fewer deltas, not an error.
        """
        return RenewalDelta(
            prior_version=str(prior.get("policy_version") or ""),
            prior_at=str(prior.get("generated_at") or ""),
            prior_filename=prior_filename,
            ratios=self._ratio_deltas(current, prior),
            spread=self._spread_deltas(current, prior),
            covenants=self._covenant_deltas(current, prior),
            rating_before=self._prior_grade(prior),
            rating_after=(current.rating.grade if current.rating else ""),
            new_exceptions=self._exception_ids(current, prior, new=True),
            cleared_exceptions=self._exception_ids(current, prior, new=False),
            unchanged_sections=self._unchanged(current, prior),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _ratio_deltas(current: Any, prior: dict) -> tuple[SectionDelta, ...]:
        before = {
            (r.get("formula_id"), r.get("period")): r.get("value")
            for r in (prior.get("ratios") or [])
            if isinstance(r, dict)
        }
        out: list[SectionDelta] = []
        for ratio in current.ratios:
            was = before.get((ratio.formula_id, ratio.period))
            if not _material(was, ratio.value):
                continue
            out.append(
                SectionDelta(
                    label=f"{ratio.name} ({ratio.period})",
                    before=was,
                    after=ratio.value,
                    unit=ratio.unit,
                    detail=ratio.definition,
                )
            )
        return tuple(out)

    @staticmethod
    def _spread_deltas(current: Any, prior: dict) -> tuple[SectionDelta, ...]:
        # float | None, not float: a prior memo may legitimately carry a null value for a
        # line it could not measure, and typing that away would have the diff treat "the
        # last memo did not have this figure" as if it had had a zero.
        before: dict[tuple[str, str], float | None] = {}
        for spread in prior.get("spreads") or []:
            for item in (spread or {}).get("items") or []:
                if isinstance(item, dict):
                    before[(str(item.get("code")), str(item.get("period")))] = item.get("value")
        out: list[SectionDelta] = []
        for spread in current.spreads:
            for item in spread.items:
                was = before.get((item.code.value, item.period))
                if not _material(was, item.value):
                    continue
                out.append(
                    SectionDelta(
                        label=f"{item.code.value.replace('_', ' ')} ({item.period})",
                        before=was,
                        after=item.value,
                        unit=item.currency,
                    )
                )
        return tuple(out)

    @staticmethod
    def _covenant_deltas(current: Any, prior: dict) -> tuple[SectionDelta, ...]:
        before = {
            str(c.get("type")): c.get("current_value")
            for c in (prior.get("covenants") or [])
            if isinstance(c, dict)
        }
        out: list[SectionDelta] = []
        for covenant in current.covenants:
            was = before.get(covenant.type.value)
            if not _material(was, covenant.current_value):
                continue
            out.append(
                SectionDelta(
                    label=covenant.type.value.replace("_", " "),
                    before=was,
                    after=covenant.current_value,
                    detail=f"tested {covenant.operator.value} {covenant.threshold:,.2f}",
                )
            )
        return tuple(out)

    @staticmethod
    def _prior_grade(prior: dict) -> str:
        rating = prior.get("rating")
        if not isinstance(rating, dict):
            return ""
        return str(rating.get("override_grade") or rating.get("obligor_grade") or "")

    @staticmethod
    def _exception_ids(current: Any, prior: dict, new: bool) -> tuple[str, ...]:
        """New exceptions, or ones that have cleared.

        Both directions matter and for different reasons. A new exception is a
        deterioration the committee has to approve; a cleared one is the borrower having
        fixed something, which is the argument for the renewal and is invisible unless
        somebody says so.
        """
        was = {
            str(e.get("rule_id"))
            for e in (prior.get("policy_exceptions") or [])
            if isinstance(e, dict)
        }
        now = {e.rule_id for e in current.policy_exceptions}
        return tuple(sorted(now - was if new else was - now))

    @staticmethod
    def _unchanged(current: Any, prior: dict) -> tuple[str, ...]:
        """Sections a reader can skip, said explicitly.

        "Unchanged" is information: it tells a reader they already know this part, which
        is exactly what makes a renewal shorter than a new-facility memo.
        """
        unchanged: list[str] = []
        if current.summary and current.summary == str(prior.get("summary") or ""):
            unchanged.append("Summary")
        if current.recommendation_rationale and current.recommendation_rationale == str(
            prior.get("recommendation_rationale") or ""
        ):
            unchanged.append("Recommendation rationale")
        prior_flags = {
            (str(f.get("category")), str(f.get("detail")))
            for f in (prior.get("risk_flags") or [])
            if isinstance(f, dict)
        }
        if prior_flags and prior_flags == {
            (f.category.value, f.detail) for f in current.risk_flags
        }:
            unchanged.append("Risks and mitigants")
        return tuple(unchanged)
