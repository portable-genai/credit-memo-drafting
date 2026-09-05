"""Local policy-pack adapter (PolicyPackPort) — a YAML file the bank uploaded.

Reads ``settings.policy_pack.path`` (defaulting to the shipped example) and parses it
into rules and a scorecard. Parsing lives here rather than in the domain deliberately:
the domain is standard-library only, and a YAML dependency in it would make the
credit-underwriting core depend on a serialisation format.

The shipped ``config/policy_pack.example.yaml`` is an EXAMPLE, and the word is load-
bearing. Its limits are plausible and made up. A deployment that leaves it in place is
reporting borrowers against numbers nobody at the bank chose, which is why ``current``
labels the version it returns.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ...config import Settings
from ...domain.models import (
    LoanType,
    MemoKind,
    PolicyOperator,
    PolicyPack,
    PolicyRule,
    RatingScorecard,
    Severity,
)


class LocalYamlPolicyPackAdapter:
    """Load the bank's policy pack and scorecard from a YAML file on disk."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        configured = getattr(getattr(settings, "policy_pack", None), "path", "") or ""
        self._path = (
            Path(configured).expanduser()
            if configured
            else Path(__file__).resolve().parents[3].parent / "config" / "policy_pack.example.yaml"
        )
        self._cache: tuple[PolicyPack, RatingScorecard | None] | None = None

    def current(self) -> PolicyPack:
        return self._load()[0]

    def load(self, version: str) -> PolicyPack:
        """This adapter holds one file, so a version it does not have is an empty pack.

        Empty rather than raising: a replay against a pack this deployment no longer has
        should say "no rules applied" rather than fail the whole memo.
        """
        pack = self.current()
        return pack if pack.version == version else PolicyPack(version=version, rules=())

    def scorecard(self) -> RatingScorecard | None:
        return self._load()[1]

    # ------------------------------------------------------------------ #
    def _load(self) -> tuple[PolicyPack, RatingScorecard | None]:
        if self._cache is not None:
            return self._cache
        if not self._path.is_file():
            self._cache = (PolicyPack(version="none", rules=()), None)
            return self._cache

        import yaml  # lazy: the domain stays stdlib-only, this adapter need not

        raw_text = self._path.read_text(encoding="utf-8")
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
        raw: dict[str, Any] = yaml.safe_load(raw_text) or {}

        rules = tuple(self._rule(entry) for entry in (raw.get("rules") or []))
        pack = PolicyPack(
            version=str(raw.get("version") or "unversioned"),
            rules=tuple(r for r in rules if r is not None),
            digest=digest,
            effective_from=str(raw.get("effective_from") or ""),
        )
        self._cache = (pack, self._scorecard(raw.get("scorecard"), digest))
        return self._cache

    @staticmethod
    def _rule(entry: Any) -> PolicyRule | None:
        if not isinstance(entry, dict):
            return None
        try:
            operator = PolicyOperator(str(entry.get("operator") or "<="))
            severity = Severity(str(entry.get("severity") or "medium"))
        except ValueError:
            return None
        limit = entry.get("limit")
        return PolicyRule(
            id=str(entry.get("id") or ""),
            description=str(entry.get("description") or ""),
            metric=str(entry.get("metric") or ""),
            operator=operator,
            limit=float(limit) if isinstance(limit, int | float) else None,
            options=tuple(str(o) for o in (entry.get("options") or [])),
            severity=severity,
            waiver_authority=str(entry.get("waiver_authority") or ""),
            applies_to_kinds=tuple(
                MemoKind(k) for k in (entry.get("applies_to_kinds") or []) if k in set(MemoKind)
            ),
            applies_to_loan_types=tuple(
                LoanType(t)
                for t in (entry.get("applies_to_loan_types") or [])
                if t in set(LoanType)
            ),
            knockout=bool(entry.get("knockout", False)),
            citation=str(entry.get("citation") or ""),
        )

    @staticmethod
    def _scorecard(raw: Any, digest: str) -> RatingScorecard | None:
        if not isinstance(raw, dict) or not raw.get("factors"):
            return None
        factors = []
        for entry in raw["factors"]:
            if not isinstance(entry, dict):
                continue
            bands = tuple(
                (float(b["up_to"]), float(b["points"]))
                for b in (entry.get("bands") or [])
                if isinstance(b, dict) and "up_to" in b and "points" in b
            )
            if not bands:
                continue
            factors.append(
                (
                    str(entry.get("name") or entry.get("metric") or ""),
                    str(entry.get("metric") or ""),
                    float(entry.get("weight", 1.0)),
                    bands,
                )
            )
        grade_bands = tuple(
            (float(b["up_to"]), str(b["grade"]))
            for b in (raw.get("grades") or [])
            if isinstance(b, dict) and "up_to" in b and "grade" in b
        )
        if not factors or not grade_bands:
            return None
        return RatingScorecard(
            version=str(raw.get("version") or "unversioned"),
            factors=tuple(factors),
            grade_bands=grade_bands,
            digest=digest,
            definitions_url=str(raw.get("definitions_url") or ""),
        )
