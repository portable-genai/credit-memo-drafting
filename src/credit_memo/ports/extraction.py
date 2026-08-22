"""DocumentExtractionPort — structured extraction from borrower filings.

Primary GCP adapter: **Document AI** on the Gemini Enterprise Agent Platform, pinned
to a single in-country region. It turns a raw filing (financial statement, loan
agreement, covenant certificate) into a :class:`DocumentExtract` of form fields plus
full text. On-prem migration swaps this for a placeholder adapter with no change to
callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DocumentExtract, Filing


@runtime_checkable
class DocumentExtractionPort(Protocol):
    def extract(self, document: Filing, content: bytes, mime_type: str) -> DocumentExtract:
        """Extract structured fields and text from a filing's bytes."""
        ...
