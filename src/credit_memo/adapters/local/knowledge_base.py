"""Local knowledge-base adapter (KnowledgeBaseClientPort) — SQLite FTS5 governed RAG.

The ``local`` profile's stand-in for the **A2 Enterprise Knowledge Base** (and the
standalone Agent Search adapter): a ``sqlite3`` database with an **FTS5** virtual table
over the borrower-filing and credit-policy passages, queried with BM25 (``ORDER BY
rank``). It is SDK-free, deterministic and **seedable**, so the same code grounds the
offline CLI run and the unit tests. There is no Google emulator for Agent Search, so this
path is unconditional (no emulator branch).

``ingest`` indexes a borrower filing's text (parsed by the local document parser) with
its ACL tags; ``search`` returns ranked :class:`RetrievedPassage` objects with the same
page-level :class:`Citation` provenance the managed adapter returns, preserving interface
parity. The index self-seeds from the built-in synthetic corpus on first use so an
out-of-the-box local run grounds a memo without any ingestion step.

Default DB path is under a per-package local dir (``~/.credit_memo/local.db``); tests
pass ``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import (
    Citation,
    Filing,
    IngestResult,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)
from ._seed import SEED_PASSAGES

# Default on-disk location for the local index (overridable via settings.local.db_path).
_DEFAULT_DB_DIR = Path.home() / ".credit_memo"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text question never
# trips an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class LocalFtsKnowledgeBaseAdapter:
    """Governed RAG store backed by a local SQLite FTS5 index (BM25 ranked)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # check_same_thread=False + an RLock keeps the FTS5 store usable from Starlette's
        # worker threadpool: deps.get_container is lru_cached (one process-wide connection),
        # but sync endpoints run on worker threads other than the one that opened the
        # connection, so an unguarded cross-thread search()/ingest() would raise "SQLite
        # objects created in a thread can only be used in that same thread". The RLock
        # serialises access (single-writer) and is re-entrant so seed()/ingest() can call
        # the locked _insert() helper without deadlocking.
        self._lock = threading.RLock()
        self._conn = self._connect(db_path)
        self._init_schema()
        self._maybe_seed()

    def _maybe_seed(self) -> None:
        """Self-seed the built-in fictional corpus so a local run grounds out of the box.

        Never under the ``live`` profile: live grounds on real ingested evidence (SEC
        EDGAR facts and uploaded borrower documents), and this guard covers every
        construction path, including the live subclass.
        """
        if self.settings.profile != "live" and self._is_empty():
            self.seed(SEED_PASSAGES)

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False (paired with the adapter's RLock) keeps the index usable
        # from Starlette's worker threadpool under ``local serve``: the lru_cached container
        # opens the connection on one thread but search()/ingest() run on others.
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # One FTS5 table holds the searchable text; citation metadata rides alongside as
        # UNINDEXED columns so a single query returns everything needed to cite a hit.
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    text,
                    source_id UNINDEXED,
                    source_type UNINDEXED,
                    title UNINDEXED,
                    url UNINDEXED,
                    page UNINDEXED,
                    score UNINDEXED,
                    acl_tags UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM passages").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding / ingestion
    # ------------------------------------------------------------------ #
    def seed(self, passages: tuple[RetrievedPassage, ...] | list[RetrievedPassage]) -> int:
        """Replace the index contents with ``passages`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM passages")
            return self._insert(list(passages))

    def add(self, passages: list[RetrievedPassage]) -> int:
        """Append ``passages`` to the index without clearing existing rows."""
        return self._insert(passages)

    def _insert(self, passages: list[RetrievedPassage]) -> int:
        rows = []
        for p in passages:
            c = p.citation
            rows.append(
                (
                    p.text,
                    c.source_id,
                    c.source_type.value,
                    c.title,
                    c.url,
                    "" if c.page is None else str(c.page),
                    f"{p.score:.6f}",
                    ",".join(p.acl_tags),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO passages "
                "(text, source_id, source_type, title, url, page, score, acl_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # KnowledgeBaseClientPort
    # ------------------------------------------------------------------ #
    def ingest(self, document: Filing, content: bytes, acl_tags: tuple[str, ...]) -> IngestResult:
        """Index a borrower filing into the local FTS5 store with ACL tags."""
        from .extraction import LocalDocumentExtractionAdapter

        parser = LocalDocumentExtractionAdapter(self.settings)
        extract = parser.extract(document, content, "application/pdf")
        text = (extract.text or "").strip()
        passages: list[RetrievedPassage] = []
        if text:
            passages.append(
                RetrievedPassage(
                    text=text,
                    citation=Citation(
                        source_id=document.id,
                        source_type=SourceType.FILING,
                        title=document.title or document.id,
                        url=document.uri,
                        page=1,
                        snippet=text[:280],
                        score=0.5,
                    ),
                    score=0.5,
                    acl_tags=tuple(acl_tags),
                )
            )
        # Re-index this document: drop any prior rows for it, then add the new passages.
        with self._lock:
            self._conn.execute("DELETE FROM passages WHERE source_id = ?", (document.id,))
            self._conn.commit()
            n = self.add(passages) if passages else 0
        return IngestResult(
            document_id=f"local-{document.id}",
            chunks=n,
            status="indexed",
            ok=True,
            detail=f"indexed {n} passages into local FTS5",
        )

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Return ranked passages with page-level citations for ``query`` (ACL-filtered)."""
        match = self._build_match(query.text)
        principals = set(query.acl_principals or ())

        with self._lock:
            if not match:
                # No usable query terms: fall back to a score-ordered scan so the pipeline
                # still gets something deterministic rather than an FTS5 syntax error.
                cursor = self._conn.execute(
                    "SELECT * FROM passages ORDER BY score DESC LIMIT ?", (max(query.top_k, 1),)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM passages WHERE passages MATCH ? ORDER BY rank LIMIT ?",
                    (match, max(query.top_k, 1)),
                )
            rows = cursor.fetchall()

        passages = [self._row_to_passage(row) for row in rows]
        return [p for p in passages if self._acl_ok(p, principals)]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _acl_ok(passage: RetrievedPassage, principals: set[str]) -> bool:
        """Visible only when untagged, or when the caller holds EVERY tag (subset, fail-closed).

        Subset (all-of) semantics: evidence tagged ``borrower:<id>`` AND ``tenant:<t>`` is
        visible only to a caller whose principals carry BOTH, so a borrower id guessed from
        the request body alone never crosses a tenant boundary, and an empty principal set
        sees only untagged (public reference) passages. This closes the C2 fail-open finding:
        the prior rule allowed all when principals were empty and used ANY-match tag
        intersection (widening), so any authenticated caller could name any borrower id and
        retrieve that borrower's tagged evidence.
        """
        if not passage.acl_tags:
            return True
        return set(passage.acl_tags) <= principals

    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_passage(row: sqlite3.Row) -> RetrievedPassage:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            score = 0.0
        acl_tags = tuple(t for t in (row["acl_tags"] or "").split(",") if t)
        citation = Citation(
            source_id=row["source_id"],
            source_type=LocalFtsKnowledgeBaseAdapter._parse_source_type(row["source_type"]),
            title=row["title"],
            url=row["url"],
            page=page,
            snippet=(row["text"] or "")[:280],
            score=score,
        )
        return RetrievedPassage(text=row["text"], citation=citation, score=score, acl_tags=acl_tags)

    @staticmethod
    def _parse_source_type(value: str | None) -> SourceType:
        try:
            return SourceType(str(value))
        except (ValueError, AttributeError):
            return SourceType.FILING
