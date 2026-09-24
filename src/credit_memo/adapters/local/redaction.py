"""Local PII redaction adapter (PIIRedactionPort) — regex de-identification.

The ``local`` profile's stand-in for **Sensitive Data Protection / DLP** (and the A1
gateway redactor): masks the national identifiers for the configured jurisdiction(s) plus
universal email/phone with deterministic regexes, returning findings. Borrower PII is
removed at the boundary before it reaches a model, a trace span or the audit sink (P-04,
rule R1). The pattern set is jurisdiction-driven (``settings.pii.jurisdictions``, default
SG/HK/JP/AU) so a non-APAC deployment detects its own identifiers by config, not a code
change. There is no Google emulator for DLP, so this path is unconditional and imports no
google-cloud package.

The rows and their checksum validators come from the shared ``pii-kit`` package, NOT a
local copy: this redactor, the DLP adapter and the eval leak-check all read the SAME rows,
so a pattern fix is a version bump rather than a copy that drifts out of sync (a copy that
drifts narrows rows silently, and a narrowed row leaks identifiers no gate can see).

Rows that carry a checksum validator (JP My Number, AU TFN) mask only genuine identifiers,
so the ordinary digit runs a filing is full of (facility amounts, account and invoice
references) are left intact rather than falsely redacted out of the memo. B2 has no
bank-account row, so the universal email/phone rows lead and the national-id rows follow
with no bare-digit catch-all and therefore no row-ordering hazard.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit.patterns import Pattern

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult

# An eight-digit run that is an amount is not a phone number, and a credit case is full of
# them: "a facility of SGD 85000000" used to reach the model as "SGD [SG_PHONE]", and a
# balance of "98765432.10" as "[SG_PHONE].10". A phone match directly after a currency marker,
# or directly before a decimal fraction, is left alone. The shared phone rows cannot see
# either, so this redactor looks around the match before masking it.
_AMOUNT_PREFIX = re.compile(r"(?:[$€£¥]|\b(?:SGD|USD|HKD|AUD|JPY|EUR|GBP|CNY|RMB))\s?$")
_AMOUNT_FRACTION = re.compile(r"\.\d")


def _is_an_amount(match: re.Match[str]) -> bool:
    text = match.string
    return bool(
        _AMOUNT_PREFIX.search(text, 0, match.start()) or _AMOUNT_FRACTION.match(text, match.end())
    )


class LocalRegexRedactionAdapter:
    """Mask the configured jurisdictions' national ids + email/phone, like DLP de-identify."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Universal rows first, then the national-id rows for the configured jurisdictions.
        # B2 has no account row, so this order carries no subsumption hazard.
        self._patterns: tuple[Pattern, ...] = (
            *UNIVERSAL_PATTERNS,
            *tuple(national_patterns_for(settings.pii.jurisdictions)),
        )

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        counts: dict[str, int] = {}
        for info_type, pattern, validator in self._patterns:

            def _sub(
                m: re.Match[str],
                _it: str = info_type,
                _val: Callable[[str], bool] | None = validator,
            ) -> str:
                if _val is not None and not _val(m.group(0)):
                    return m.group(0)  # checksum fail: not a real identifier, leave it intact
                if "PHONE" in _it and _is_an_amount(m):
                    return m.group(0)  # an amount, not a phone number
                counts[_it] = counts.get(_it, 0) + 1
                return f"[{_it}]"

            redacted = pattern.sub(_sub, redacted)
        findings = tuple(RedactionFinding(info_type=it, count=n) for it, n in counts.items() if n)
        return RedactionResult(text=redacted, findings=findings)
