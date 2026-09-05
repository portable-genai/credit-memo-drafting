"""On-prem placeholder for ``AnalysisBundlePort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile this
port binds to a regional CMEK bucket with a lifecycle rule; switching ``profile`` to
``onprem`` rebinds it to the adopter's own document vault. The adapter constructs cleanly
with **no external dependencies** and structurally satisfies the same Protocol as the
managed adapter, so the contract tests prove interface parity.

Filling these bodies in is the whole of the port. One thing an implementer must carry
across rather than reinvent: the retention window is a promise the console prints to the
user, so the vault has to enforce it (a lifecycle rule, a scheduled purge, whatever the
platform offers) and reads must refuse an expired bundle rather than serve it.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AnalysisManifest, DocType, StoredDocument

_MESSAGE = (
    "On-prem AnalysisBundlePort adapter is a migration placeholder; implement against your "
    "on-premise document vault, including the retention window the console promises. Core "
    "domain logic is unchanged."
)


class OnPremAnalysisBundleAdapter:
    """Placeholder analysis-bundle adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(
        self,
        analysis_id: str,
        borrower_id: str,
        acl_tags: tuple[str, ...],
        created_by: str = "",
    ) -> AnalysisManifest:
        raise NotImplementedError(_MESSAGE)

    def put_document(
        self,
        analysis_id: str,
        content: bytes,
        filename: str,
        doc_type: DocType,
        acl_principals: tuple[str, ...],
        mime_type: str = "",
        declared_as_of: str = "",
        uploaded_by: str = "",
        third_party_sourced: bool = False,
    ) -> StoredDocument:
        raise NotImplementedError(_MESSAGE)

    def get_document(
        self, analysis_id: str, document_id: str, acl_principals: tuple[str, ...]
    ) -> bytes:
        raise NotImplementedError(_MESSAGE)

    def manifest(self, analysis_id: str, acl_principals: tuple[str, ...]) -> AnalysisManifest:
        raise NotImplementedError(_MESSAGE)

    def set_pages(self, analysis_id: str, document_id: str, pages: int) -> None:
        raise NotImplementedError(_MESSAGE)

    def put_artifact(
        self,
        analysis_id: str,
        name: str,
        payload: dict,
        acl_principals: tuple[str, ...],
    ) -> None:
        raise NotImplementedError(_MESSAGE)

    def get_artifact(
        self, analysis_id: str, name: str, acl_principals: tuple[str, ...]
    ) -> dict | None:
        raise NotImplementedError(_MESSAGE)

    def delete(self, analysis_id: str, acl_principals: tuple[str, ...]) -> bool:
        raise NotImplementedError(_MESSAGE)
