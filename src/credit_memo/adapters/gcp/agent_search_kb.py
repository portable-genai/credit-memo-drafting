"""Agent Search knowledge-base adapter (KnowledgeBaseClientPort, standalone).

B2's governed RAG store **is** the A2 Enterprise KB; the ``platform`` adapter delegates
to A2 over HTTP. For a standalone run this adapter speaks directly to **Agent Search**
(Discovery Engine) on the Gemini Enterprise Agent Platform, pinned to a **regional**
endpoint in ``asia-southeast1`` so borrower documents stay in-country. ``ingest`` imports
a filing into the borrower data store with its ACL tags; ``search`` returns ranked
passages with page-level :class:`Citation` provenance.

All Google Cloud SDK imports are lazy so the on-prem / test profile imports this module
without ``google-cloud-discoveryengine`` installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import (
    Citation,
    Filing,
    IngestResult,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.cloud import discoveryengine_v1


class AgentSearchKnowledgeBaseAdapter:
    """Direct Agent Search governed-RAG adapter (standalone fallback for A2)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg = settings.knowledge_base
        self._location = cfg.location
        self._data_store_id = cfg.data_store_id
        self._top_k = cfg.top_k
        self._endpoint = f"{self._location}-discoveryengine.googleapis.com"
        self._search_client: Any | None = None
        self._doc_client: Any | None = None

    # ------------------------------------------------------------------ #
    # Lazy clients
    # ------------------------------------------------------------------ #
    def _search(self) -> discoveryengine_v1.SearchServiceClient:
        if self._search_client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import discoveryengine_v1

            self._search_client = discoveryengine_v1.SearchServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint),
            )
        return self._search_client

    def _documents(self) -> discoveryengine_v1.DocumentServiceClient:
        if self._doc_client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import discoveryengine_v1

            self._doc_client = discoveryengine_v1.DocumentServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint),
            )
        return self._doc_client

    def _branch(self) -> str:
        return (
            f"projects/{self._settings.project_id}/locations/{self._location}"
            f"/collections/default_collection/dataStores/{self._data_store_id}"
            f"/branches/default_branch"
        )

    def _serving_config(self) -> str:
        return (
            f"projects/{self._settings.project_id}/locations/{self._location}"
            f"/collections/default_collection/dataStores/{self._data_store_id}"
            f"/servingConfigs/default_search"
        )

    # ------------------------------------------------------------------ #
    # KnowledgeBaseClientPort
    # ------------------------------------------------------------------ #
    def ingest(self, document: Filing, content: bytes, acl_tags: tuple[str, ...]) -> IngestResult:
        """Index a filing into the borrower data store with its ACL tags."""
        from google.cloud import discoveryengine_v1

        client = self._documents()
        struct = {
            "source_id": document.id,
            "doc_type": document.doc_type.value,
            "uri": document.uri,
            "title": document.title,
            "acl_tags": list(acl_tags),
        }
        doc = discoveryengine_v1.Document(
            id=document.id,
            struct_data=struct,
            content=discoveryengine_v1.Document.Content(
                raw_bytes=content, mime_type="application/pdf"
            ),
        )
        client.create_document(parent=self._branch(), document=doc, document_id=document.id)
        return IngestResult(document_id=document.id, chunks=0, status="indexed", ok=True)

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Return ranked passages (ACL-filtered) with page-level citations."""
        from google.cloud import discoveryengine_v1

        client = self._search()
        content_spec = discoveryengine_v1.SearchRequest.ContentSearchSpec(
            extractive_content_spec=(
                discoveryengine_v1.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_segment_count=max(query.top_k, 1),
                    return_extractive_segment_score=True,
                )
            ),
        )
        request = discoveryengine_v1.SearchRequest(
            serving_config=self._serving_config(),
            query=query.text,
            page_size=query.top_k,
            filter=self._acl_filter(query.acl_principals),
            content_search_spec=content_spec,
        )
        response = client.search(request=request)
        passages: list[RetrievedPassage] = []
        for result in response.results:
            passages.extend(self._result_to_passages(result))
        return passages

    # ------------------------------------------------------------------ #
    # Mapping helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _acl_filter(principals: tuple[str, ...]) -> str:
        clauses = [f'acl_tags: ANY("{p}")' for p in principals if p]
        return " AND ".join(clauses)

    def _result_to_passages(self, result: Any) -> list[RetrievedPassage]:
        document = result.document
        struct = self._to_dict(getattr(document, "struct_data", None))
        derived = self._to_dict(getattr(document, "derived_struct_data", None))
        source_id = str(struct.get("source_id") or getattr(document, "id", "") or "unknown")
        title = str(struct.get("title") or struct.get("source_id") or source_id)
        url = str(struct.get("uri") or "")
        acl_tags = tuple(str(t) for t in (struct.get("acl_tags") or ()))

        segments = derived.get("extractive_segments") or []
        if not segments:
            citation = Citation(
                source_id=source_id,
                source_type=SourceType.FILING,
                title=title,
                url=url,
                page=None,
            )
            return [RetrievedPassage(text="", citation=citation, score=0.0, acl_tags=acl_tags)]

        passages: list[RetrievedPassage] = []
        for segment in segments:
            seg = self._to_dict(segment)
            text = str(seg.get("content") or "")
            page = self._parse_page(seg.get("pageIdentifier"))
            score = self._parse_score(seg.get("relevanceScore"))
            citation = Citation(
                source_id=source_id,
                source_type=SourceType.FILING,
                title=title,
                url=url,
                page=page,
                snippet=text[:280],
                score=score,
            )
            passages.append(
                RetrievedPassage(
                    text=text, citation=citation, score=score or 0.0, acl_tags=acl_tags
                )
            )
        return passages

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return dict(value)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _parse_page(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_score(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
