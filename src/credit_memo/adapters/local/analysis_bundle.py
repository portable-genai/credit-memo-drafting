"""Local analysis-bundle adapter — one directory per analysis, expiring on read.

The SDK-free profile's custody. Each analysis is a directory holding the uploaded bytes,
a manifest, and whatever JSON artifacts the pipeline wrote:

    <root>/<analysis_id>/
      manifest.json          the ACL tags, the documents, created_at, expires_at
      documents/<doc_id>     the bytes, exactly as uploaded
      artifacts/<name>.json  the memo, the stage log

Retention is enforced on every read as well as by the sweep. A directory whose manifest
has expired raises rather than being served, so a laptop that never runs the sweep still
honours the window the console promised the user. The sweep then reclaims the disk.

Access control is the knowledge base's rule, repeated deliberately: subset match,
fail-closed, and the same error for "absent" and "not readable".

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...domain.errors import AnalysisExpiredError, AnalysisNotFoundError
from ...domain.models import AnalysisManifest, DocType, StoredDocument, utcnow

_MANIFEST = "manifest.json"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_segment(value: str) -> str:
    """A single path segment, or nothing usable.

    Ids reach this adapter from a URL. ``..`` and separators are refused rather than
    sanitised: a caller who sends one is not making a typo, and quietly rewriting the id
    would serve them a different analysis than the one they asked for.
    """
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        return ""
    return cleaned


class LocalAnalysisBundleAdapter:
    """Filesystem custody for one analysis at a time, with a retention window."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        configured = getattr(getattr(settings, "analysis_bundle", None), "root", "") or ""
        self._root = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".credit_memo" / "analyses"
        )
        self._retention_days = int(
            getattr(getattr(settings, "analysis_bundle", None), "retention_days", 15)
        )

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
        directory = self._dir(analysis_id, create=True)
        now = utcnow()
        manifest = AnalysisManifest(
            analysis_id=analysis_id,
            borrower_id=borrower_id,
            documents=(),
            created_at=now,
            expires_at=now + timedelta(days=self._retention_days),
            created_by=created_by,
        )
        self._write_manifest(directory, manifest, acl_tags)
        return manifest

    def manifest(self, analysis_id: str, acl_principals: tuple[str, ...]) -> AnalysisManifest:
        return self._read_manifest(analysis_id, acl_principals)[0]

    def delete(self, analysis_id: str, acl_principals: tuple[str, ...]) -> bool:
        directory = self._dir(analysis_id)
        if not directory.exists():
            return False
        # Read first: deleting something the caller may not read is still a write they
        # were not entitled to make.
        self._read_manifest(analysis_id, acl_principals)
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def sweep(self) -> int:
        """Delete every expired bundle. Returns how many went. Safe to call at any time."""
        if not self._root.exists():
            return 0
        removed = 0
        for directory in self._root.iterdir():
            if not directory.is_dir():
                continue
            try:
                raw = json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))
                expires = raw.get("expires_at")
                if expires and datetime.fromisoformat(expires) <= datetime.now(UTC):
                    shutil.rmtree(directory, ignore_errors=True)
                    removed += 1
            except (OSError, ValueError):
                continue
        return removed

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
        directory = self._dir(analysis_id, create=True)
        digest = _digest(content)
        document_id = f"doc-{digest[:16]}"

        # The same file twice is one document. Uploading the pack again after adding one
        # statement should not put the same balance sheet in the manifest twice, and a
        # citation must resolve to one file.
        existing = next((d for d in manifest.documents if d.id == document_id), None)
        if existing is not None:
            return existing

        (directory / "documents").mkdir(parents=True, exist_ok=True)
        (directory / "documents" / document_id).write_bytes(content)
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
            directory,
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
        segment = _safe_segment(document_id)
        path = (self._dir(analysis_id) / "documents" / segment) if segment else None
        if path is None or not path.is_file():
            raise AnalysisNotFoundError(f"document {document_id!r} is not available")
        return path.read_bytes()

    def set_pages(self, analysis_id: str, document_id: str, pages: int) -> None:
        directory = self._dir(analysis_id)
        if not (directory / _MANIFEST).exists():
            return
        raw = json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))
        for document in raw.get("documents", []):
            if document.get("id") == document_id:
                document["pages"] = int(pages)
        (directory / _MANIFEST).write_text(json.dumps(raw, indent=2), encoding="utf-8")

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
        directory = self._dir(analysis_id, create=True)
        segment = _safe_segment(name)
        if not segment:
            raise AnalysisNotFoundError(f"artifact name {name!r} is not usable")
        (directory / "artifacts").mkdir(parents=True, exist_ok=True)
        (directory / "artifacts" / f"{segment}.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

    def get_artifact(
        self, analysis_id: str, name: str, acl_principals: tuple[str, ...]
    ) -> dict | None:
        self._read_manifest(analysis_id, acl_principals)
        segment = _safe_segment(name)
        path = (self._dir(analysis_id) / "artifacts" / f"{segment}.json") if segment else None
        if path is None or not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return loaded if isinstance(loaded, dict) else None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _dir(self, analysis_id: str, create: bool = False) -> Path:
        """The bundle's directory. An unusable id is not-found, like any other miss.

        Raising rather than returning None keeps every caller honest: an id that cannot
        name a directory cannot name an analysis either, and the caller has nothing
        different to do about it.
        """
        segment = _safe_segment(analysis_id)
        if not segment:
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")
        directory = self._root / segment
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _write_manifest(
        self, directory: Path, manifest: AnalysisManifest, acl_tags: tuple[str, ...]
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
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _MANIFEST).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_manifest(
        self, analysis_id: str, acl_principals: tuple[str, ...]
    ) -> tuple[AnalysisManifest, tuple[str, ...]]:
        path = self._dir(analysis_id) / _MANIFEST
        if not path.is_file():
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")
        raw = json.loads(path.read_text(encoding="utf-8"))

        acl_tags = tuple(raw.get("acl_tags", []))
        # Subset, fail-closed: hold every tag or see nothing. Same error as absent.
        if acl_tags and not set(acl_tags) <= set(acl_principals):
            raise AnalysisNotFoundError(f"analysis {analysis_id!r} is not available")

        expires_at = datetime.fromisoformat(raw["expires_at"]) if raw.get("expires_at") else None
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise AnalysisExpiredError(
                f"analysis {analysis_id!r} passed its retention window on "
                f"{expires_at.date().isoformat()} and its evidence has been deleted"
            )

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
