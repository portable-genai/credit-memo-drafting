"""Concurrency regression tests for the local SQLite-backed adapters.

The ``local serve`` API serves sync endpoints from Starlette's anyio worker threadpool
while ``api/deps.get_container`` is ``@lru_cache`` (one process-wide container, hence one
process-wide SQLite connection). A request handled on a worker thread therefore calls
``record()`` / ``search()`` on a connection that was opened on a *different* thread. Unless
the adapter opens with ``check_same_thread=False`` and serialises access behind a lock,
SQLite raises "SQLite objects created in a thread can only be used in that same thread",
which drops the WORM audit event and 500s the request under concurrent load.

These tests construct each adapter ONCE (on the main thread) and then drive interleaved
writes and reads from many worker threads. They fail before the fix (the connection was
opened with the default ``check_same_thread=True`` and no lock) and pass after it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from credit_memo.adapters.local.audit import LocalAppendOnlyAuditAdapter
from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from credit_memo.config import Settings
from credit_memo.domain.models import (
    AuditEvent,
    Citation,
    Decision,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)

# A real on-disk DB path is used (not ``:memory:``) because the cross-thread failure is
# about the *connection* object, and an on-disk file most faithfully reproduces the
# process-wide single-connection ``serve`` scenario.
_THREADS = 8
_OPS_PER_THREAD = 25


def _settings(**local_kwargs) -> Settings:
    """Build a Settings whose ``.local`` block points at a per-test DB path."""
    settings = Settings.load()
    return replace(settings, local=replace(settings.local, **local_kwargs))


def _audit_event(i: int) -> AuditEvent:
    return AuditEvent(
        action="build_credit_memo",
        actor=f"officer-{i}",
        decision=Decision.ALLOWED,
        redacted_prompt="[REDACTED]",
        redacted_response="[REDACTED]",
    )


def test_local_audit_adapter_is_thread_safe(tmp_path) -> None:
    """record()/read_all() from many threads on one adapter: no error, exact row count."""
    settings = _settings(audit_path=str(tmp_path / "audit.db"))
    adapter = LocalAppendOnlyAuditAdapter(settings)

    def worker(t: int) -> int:
        for i in range(_OPS_PER_THREAD):
            adapter.record(_audit_event(t * _OPS_PER_THREAD + i))
            # Interleave a read so reads also exercise the cross-thread connection.
            adapter.read_all()
        return _OPS_PER_THREAD

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = [pool.submit(worker, t) for t in range(_THREADS)]
        written = sum(f.result() for f in as_completed(futures))

    assert written == _THREADS * _OPS_PER_THREAD
    assert len(adapter.read_all()) == _THREADS * _OPS_PER_THREAD


def test_local_knowledge_base_adapter_is_thread_safe(tmp_path) -> None:
    """search() (read) interleaved with ingest()/add() (write) from many threads: no error."""
    settings = _settings(db_path=str(tmp_path / "kb.db"))
    adapter = LocalFtsKnowledgeBaseAdapter(settings)
    # Start from a known empty index so the final count is deterministic.
    adapter.seed([])

    def passage(i: int) -> RetrievedPassage:
        return RetrievedPassage(
            text=f"borrower revenue covenant leverage ratio observation {i}",
            citation=Citation(
                source_id=f"doc-{i}",
                source_type=SourceType.FILING,
                title=f"Filing {i}",
                page=1,
                score=0.5,
            ),
            score=0.5,
        )

    def worker(t: int) -> int:
        for i in range(_OPS_PER_THREAD):
            adapter.add([passage(t * _OPS_PER_THREAD + i)])
            adapter.search(RetrievalQuery(text="covenant leverage", top_k=5))
        return _OPS_PER_THREAD

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = [pool.submit(worker, t) for t in range(_THREADS)]
        added = sum(f.result() for f in as_completed(futures))

    assert added == _THREADS * _OPS_PER_THREAD
    # Every added passage is in the index (matched by the shared FTS terms).
    results = adapter.search(RetrievalQuery(text="observation", top_k=10_000))
    assert len(results) == _THREADS * _OPS_PER_THREAD
