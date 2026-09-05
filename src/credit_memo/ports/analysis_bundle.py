"""AnalysisBundlePort — the whole of one analysis, in one place, for a fixed window.

This service keeps nothing standing. There is no document library, no index that
survives a request, no memo of record. What exists is an *analysis*: the files a user
uploaded for one question, the ask, the confirmed spread, the memo built from them, and
a stage log — held together under one id and deleted on a schedule the user is told
about.

That is a deliberate posture, not a limitation:

* **The user owns freshness.** Evidence is brought to each analysis rather than
  accumulated, so nothing is assessed against a statement somebody uploaded last year
  and forgot. There is no stale corpus because there is no corpus.
* **The user can see what was used.** One bundle means the manifest is complete by
  construction: every file that fed the memo is in it, and nothing else could have been.
* **Idle cost is zero.** No standing index, no warm instance, no vector store. An
  account with no analyses running is an account paying for empty object storage.

Custody is still custody while it lasts. Bytes are held under the same fail-closed
subset ACL as retrieval: a caller must hold EVERY one of a bundle's ``acl_tags`` to read
it, and a bundle the caller may not read raises the same error as one that does not
exist, so ids cannot be probed.

Primary managed adapter: a regional CMEK bucket with a lifecycle rule. ``local`` keeps
the bundle in a directory under the profile's data path. ``onprem`` is the adopter's own
vault.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import AnalysisManifest, DocType, StoredDocument


@runtime_checkable
class AnalysisBundlePort(Protocol):
    def create(
        self,
        analysis_id: str,
        borrower_id: str,
        acl_tags: tuple[str, ...],
        created_by: str = "",
    ) -> AnalysisManifest:
        """Open a bundle and return its manifest, whose ``expires_at`` is already set.

        The expiry is decided by the adapter from the deployment's retention setting, not
        by the caller: a per-request TTL is a per-request promise, and the console prints
        this one to the user.
        """
        ...

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
        """Add one file to the bundle and return its record (id, digest, size)."""
        ...

    def get_document(
        self, analysis_id: str, document_id: str, acl_principals: tuple[str, ...]
    ) -> bytes:
        """The stored bytes, so a citation can open the page it names."""
        ...

    def manifest(self, analysis_id: str, acl_principals: tuple[str, ...]) -> AnalysisManifest:
        """What this analysis was given, and until when it can be reopened."""
        ...

    def set_pages(self, analysis_id: str, document_id: str, pages: int) -> None:
        """Record the page count extraction discovered (best-effort metadata)."""
        ...

    def put_artifact(
        self,
        analysis_id: str,
        name: str,
        payload: dict,
        acl_principals: tuple[str, ...],
    ) -> None:
        """Write a named JSON artifact into the bundle (the memo, the stage log).

        Named rather than typed so a wave can add an artifact without changing five
        adapters: the shapes are the domain's business, and the store's job is bytes
        under an id.
        """
        ...

    def get_artifact(
        self, analysis_id: str, name: str, acl_principals: tuple[str, ...]
    ) -> dict | None:
        """Read a named artifact back, or None when it has not been written yet."""
        ...

    def delete(self, analysis_id: str, acl_principals: tuple[str, ...]) -> bool:
        """Delete the bundle now; False when it was already gone.

        The lifecycle rule is the guarantee, but a user who wants their evidence gone
        before then should not have to wait for it.
        """
        ...
