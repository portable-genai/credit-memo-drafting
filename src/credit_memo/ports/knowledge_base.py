"""KnowledgeBaseClientPort — the borrower's governed RAG store (A2 Enterprise KB).

B2 does **not** build its own retrieval backend: the borrower's filings are ingested
into the shared **A2 Enterprise Knowledge Base** with borrower ACL tags and retrieved
from it (rule R3, governed RAG), along with the credit-policy / sector context the memo
is grounded against. The ``platform`` adapter is a thin HTTP client to A2's
``/v1/ingest`` and ``/v1/search`` (env ``HRZ_KB_URL``); the on-prem placeholder stub
raises, and a direct GCP adapter (Agent Search) is available for standalone runs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Filing, IngestResult, RetrievalQuery, RetrievedPassage


@runtime_checkable
class KnowledgeBaseClientPort(Protocol):
    def ingest(self, document: Filing, content: bytes, acl_tags: tuple[str, ...]) -> IngestResult:
        """Index a borrower filing into the governed RAG store with ACL tags."""
        ...

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Retrieve ranked passages (ACL-filtered) for grounding the memo."""
        ...
