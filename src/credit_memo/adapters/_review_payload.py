"""Shared conversion from an escalated credit memo to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. Redacts the subject
descriptor, summary and citation snippets before they leave the process (R1 / P-04 boundary), using
the shared ``pii-kit`` (the same pack the redaction adapter uses), so no raw borrower identifier
reaches human-review-console over the wire; human-review-console redacts again before its own audit
write (defense in depth). The maker (the officer/assistant that originated the memo) and the tenant
are asserted here and trusted by human-review-console because this is an authenticated S2S caller
(per-hop OBO is the deferred next layer).
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import CovenantStatus, CreditMemo, Severity

# Cap the citations carried on the wire: enough to let a reviewer trace the memo without copying
# the entire evidence set into the review console.
_MAX_CITATIONS = 8

# The review console is a shared sink: a memo for an SG borrower may still quote an HK id, so the
# payload is scrubbed against every jurisdiction's national ids plus universal email/phone,
# regardless of which market configured this producer.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

# Ordered weakest -> strongest so ``max`` picks the memo's most severe risk flag.
_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)


def _redact(text: str) -> str:
    """Mask every jurisdiction's national identifiers plus email/phone before the wire."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _overall_severity(memo: CreditMemo) -> Severity:
    """The memo's most severe risk flag, or LOW when it carries none."""
    present = [f.severity for f in memo.risk_flags if f.severity in _SEVERITY_ORDER]
    if not present:
        return Severity.LOW
    return max(present, key=_SEVERITY_ORDER.index)


def _escalated(memo: CreditMemo) -> bool:
    """Mirror the review policy: a covenant breach or a HIGH/CRITICAL risk flag escalates."""
    if any(c.status is CovenantStatus.BREACH for c in memo.covenants):
        return True
    return _overall_severity(memo) in (Severity.HIGH, Severity.CRITICAL)


def _kit_citations(memo: CreditMemo) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for c in memo.citations:
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_redact(c.snippet)))
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def memo_to_review(memo: CreditMemo, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a credit memo escalates."""
    borrower = memo.borrower
    descriptor = (
        f"Credit memo for {borrower.name} (id={borrower.id}, "
        f"sector={borrower.sector or 'unknown'}, "
        f"jurisdiction={borrower.jurisdiction or 'unknown'})"
    )
    breaches = sum(1 for c in memo.covenants if c.status is CovenantStatus.BREACH)
    summary = (
        f"risk_flags={len(memo.risk_flags)}; covenants={len(memo.covenants)} "
        f"(breaches={breaches}); metrics={len(memo.financial_metrics)}"
    )
    severity = _overall_severity(memo)
    # Dual control for the strongest bands or any escalation (breach / HIGH+ flag).
    dual = _escalated(memo) or severity in (Severity.HIGH, Severity.CRITICAL)
    return Review(
        action="credit_memo:build",
        subject=_redact(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_redact(summary),
        severity=severity.value,
        required_approvals=2 if dual else 1,
        sod_group="credit-maker-checker",
        case_ref=borrower.id,
        citations=_kit_citations(memo),
    )
