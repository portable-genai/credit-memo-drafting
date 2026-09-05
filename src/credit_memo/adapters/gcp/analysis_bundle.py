"""GCP analysis-bundle adapter — a regional CMEK bucket with a lifecycle rule.

One object prefix per analysis in ``settings.analysis_bundle.bucket``: the uploaded
bytes, the manifest, the artifacts. The bucket is regional and CMEK-encrypted inside the
VPC-SC perimeter, so borrower evidence stays in the deploy region while it exists.

**Retention is the bucket's, not this adapter's.** A lifecycle rule deletes every object
older than ``retention_days``, which means the promise the console prints to the user is
kept by the storage layer rather than by a sweep this service has to remember to run.
Nothing here can extend it, and an expired bundle is simply absent: the object is gone,
so the read raises not-found exactly as an unknown id does.

That is the whole cost model. There is no index, no warm instance and no database; an
account with no analyses running holds an empty bucket and pays for it accordingly.

Access control mirrors the knowledge base: subset match, fail-closed, same error for
"absent" and "not readable" so ids cannot be probed. Bucket IAM is the outer boundary;
the per-object tag check is the object-level one.

The Cloud Storage SDK import is lazy so local, live, on-prem and test profiles import
this module without it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ...domain.errors import AnalysisNotFoundError
from ...domain.models import AnalysisManifest, DocType, StoredDocument, utcnow

_MANIFEST = "manifest.json"
_ACL_SEP = "|"  # object metadata values are plain strings


def _safe_segment(value: str) -> str:
    """One object-name segment, or nothing usable. ``..`` and separators are refused."""
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        return ""
    return cleaned


class GcsAnalysisBundleAdapter:
    """Hold one analysis in a regional CMEK bucket until its lifecycle rule removes it."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        bundle = getattr(settings, "analysis_bundle", None)
        self._bucket_name = getattr(bundle, "bucket", "") or ""
        self._prefix = (getattr(bundle, "prefix", "") or "analyses").strip("/")
        self._retention_days = int(getattr(bundle, "retention_days", 15))
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # Client
    # ------------------------------------------------------------------ #
    def _bucket(self) -> Any:
        from google.cloud import storage  # lazy import (GCP SDK only on this path)

        if self._client is None:
            self._client = storage.Client(project=self._settings.project_id)
        if not self._bucket_name:
            raise AnalysisNotFoundError(
                "no analysis bundle bucket is configured; set analysis_bundle.bucket"
            )
        return self._client.bucket(self._bucket_name)

    def _blob(self, analysis_id: str, *parts: str) -> Any:
        segments = [_safe_segment(analysis_id), *(_safe_segment(p) for p in parts)]
        if not all(segments):
            raise AnalysisNotFoundError("analysis or object name is not usable")
        return self._bucket().blob("/".join([self._prefix, *segments]))

    # ------------------------------------------------------------------ #
    # Bundle lifecycle
    # ------------------------------------------------------------------ #
    def create(
        self,
        analysis_id: str,
        borrower_id: str,
        acl_tags: tuple[str, ...],
        created_by: str = "",
    ) -> AnalysisManifest:
        now = utcnow()
        manifest = AnalysisManifest(
            analysis_id=analysis_id,
            borrower_id=borrower_id,
            documents=(),
            created_at=now,
            # Stated from the deployment's configured retention so the console can print
            # a date. The bucket's lifecycle rule is what actually enforces it.
            expires_at=now + timedelta(days=self._retention_days),
            created_by=created_by,
        )
        self._write_manifest(analysis_id, manifest, acl_tags)
        return manifest

    def manifest(self, analysis_id: str, acl_principals: tuple[str, ...]) -> AnalysisManifest:
        return self._read_manifest(analysis_id, acl_principals)[0]

    def delete(self, analysis_id: str, acl_principals: tuple[str, ...]) -> bool:
        try:
            self._read_manifest(analysis_id, acl_principals)
        except AnalysisNotFoundError:
            return False
        prefix = f"{self._prefix}/{_safe_segment(analysis_id)}/"
        blobs = list(self._client.list_blobs(self._bucket_name, prefix=prefix))  # type: ignore[union-attr]
        for blob in blobs:
            blob.delete()
        return bool(blobs)

    # ------------------------------------------------------------------ #
    # Documents
    # ------------------------------------------------------------------ #
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
        manifest, acl_tags = self._read_manifest(analysis_id, acl_principals)
        digest = hashlib.sha256(content).hexdigest()
        document_id = f"doc-{digest[:16]}"

        existing = next((d for d in manifest.documents if d.id == document_id), None)
        if existing is not None:
            return existing

        blob = self._blob(analysis_id, "documents", document_id)
        blob.metadata = {"filename": filename, "sha256": digest}
        blob.upload_from_string(content, content_type=mime_type or "application/octet-stream")

        record = StoredDocument(
            id=document_id,
            filename=filename,
            doc_type=doc_type,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=digest,
            declared_as_of=declared_as_of,
            uploaded_by=uploaded_by,
            third_party_sourced=third_party_sourced,
        )
        self._write_manifest(
            analysis_id,
            AnalysisManifest(
                analysis_id=manifest.analysis_id,
                borrower_id=manifest.borrower_id,
                documents=(*manifest.documents, record),
                created_at=manifest.created_at,
                expires_at=manifest.expires_at,
                created_by=manifest.created_by,
            ),
            acl_tags,
        )
        return record

    def get_document(
        self, analysis_id: str, document_id: str, acl_principals: tuple[str, ...]
    ) -> bytes:
        self._read_manifest(analysis_id, acl_principals)
        blob = self._blob(analysis_id, "documents", document_id)
        if not blob.exists():
            raise AnalysisNotFoundError(f"document {document_id!r} is not available")
        return bytes(blob.download_as_bytes())

    def set_pages(self, analysis_id: str, document_id: str, pages: int) -> None:
        blob = self._blob(analysis_id, _MANIFEST)
        if not blob.exists():
            return
        raw = json.loads(blob.download_as_text())
        for document in raw.get("documents", []):
            if document.get("id") == document_id:
                document["pages"] = int(pages)
        blob.upload_from_string(json.dumps(raw, indent=2), content_type="application/json")

    # ------------------------------------------------------------------ #
    # Artifacts
    # ------------------------------------------------------------------ #
    def put_artifact(
        self,
        analysis_id: str,
        name: str,
        payload: dict,
        acl_principals: tuple[str, ...],
    ) -> None:
        self._read_manifest(analysis_id, acl_principals)
        blob = self._blob(analysis_id, "artifacts", f"{_safe_segment(name)}.json")
        blob.upload_from_string(
            json.dumps(payload, indent=2, default=str), content_type="application/json"
        )

    def get_artifact(
        self, analysis_id: str, name: str, acl_principals: tuple[str, ...]
    ) -> dict | None:
        self._read_manifest(analysis_id, acl_principals)
        blob = self._blob(analysis_id, "artifacts", f"{_safe_segment(name)}.json")
        if not blob.exists():
            return None
        try:
            loaded = json.loads(blob.download_as_text())
        except ValueError:
            return None
        return loaded if isinstance(loaded, dict) else None

    # ------------------------------------------------------------------ #
    # Manifest
    # ------------------------------------------------------------------ #
    def _write_manifest(
        self, analysis_id: str, manifest: AnalysisManifest, acl_tags: tuple[str, ...]
    ) -> None:
        payload = {
            "analysis_id": manifest.analysis_id,
            "borrower_id": manifest.borrower_id,
            "created_at": manifest.created_at.isoformat(),
            "expires_at": manifest.expires_at.isoformat() if manifest.expires_at else None,
            "created_by": manifest.created_by,
            "acl_tags": list(acl_tags),
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "doc_type": d.doc_type.value,
                    "mime_type": d.mime_type,
                    "size_bytes": d.size_bytes,
                    "sha256": d.sha256,
                    "pages": d.pages,
                    "declared_as_of": d.declared_as_of,
                    "uploaded_at": d.uploaded_at.isoformat(),
                    "uploaded_by": d.uploaded_by,
                    "third_party_sourced": d.third_party_sourced,
                }
                for d in manifest.documents
            ],
        }
        blob = self._blob(analysis_id, _MANIFEST)
        # The ACL tags ride on the object's own metadata as well as inside the manifest,
        # so a document and its access-control facts cannot drift apart.
        blob.metadata = {"acl_tags": _ACL_SEP.join(acl_tags)}
        blob.upload_from_string(json.dumps(payload, indent=2), content_type="application/json")

    def _read_manifest(
        self, analysis_id: str, acl_principals: tuple[str, ...]
    ) -> tuple[AnalysisManifest, tuple[str, ...]]:
        blob = self._blob(analysis_id, _MANIFEST)
        if not blob.exists():
            # Either it never existed or the lifecycle rule reclaimed it. The caller is
            # told the same thing in both cases, which is also all they need to know.
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")
        raw = json.loads(blob.download_as_text())

        acl_tags = tuple(raw.get("acl_tags", []))
        if acl_tags and not set(acl_tags) <= set(acl_principals):
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")

        expires_at = datetime.fromisoformat(raw["expires_at"]) if raw.get("expires_at") else None
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")

        manifest = AnalysisManifest(
            analysis_id=raw["analysis_id"],
            borrower_id=raw.get("borrower_id", ""),
            documents=tuple(
                StoredDocument(
                    id=d["id"],
                    filename=d.get("filename", ""),
                    doc_type=DocType(d.get("doc_type", "other")),
                    mime_type=d.get("mime_type", ""),
                    size_bytes=int(d.get("size_bytes", 0)),
                    sha256=d.get("sha256", ""),
                    pages=int(d.get("pages", 0)),
                    declared_as_of=d.get("declared_as_of", ""),
                    uploaded_at=datetime.fromisoformat(d["uploaded_at"]),
                    uploaded_by=d.get("uploaded_by", ""),
                    third_party_sourced=bool(d.get("third_party_sourced", False)),
                )
                for d in raw.get("documents", [])
            ),
            created_at=datetime.fromisoformat(raw["created_at"]),
            expires_at=expires_at,
            created_by=raw.get("created_by", ""),
        )
        return manifest, acl_tags
