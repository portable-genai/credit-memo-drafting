"""Whether invented evidence can ground a borrower that supplied its own.

The ``local`` profile ships a small fictional corpus (a made-up borrower's audited
accounts, facility agreement and covenant certificate) so an out-of-the-box CLI run
returns a real cited memo with no external evidence. Every passage in it was UNTAGGED,
and under this repo's ACL contract untagged means public. So the demo corpus was visible
to every borrower.

Visible was not the damage. Retrieval is ordered by relevance and capped at ``top_k``, so
the fictional passages did not merely join a borrower's own ingested filings: they
competed with them and, being written to read like model credit evidence, frequently won.
A memo for a real borrower was then grounded in, and cited, filings nobody had supplied,
and the covenant extractor read its leverage and DSCR out of them.

This adapter made it worse than the sibling it was copied from: ``search`` applied the
``LIMIT top_k`` inside SQL and only then filtered by ACL, so the seed rows consumed the
result budget BEFORE the borrower's own evidence was even considered for admission.

The rule these tests hold: the demo corpus grounds a query that would otherwise retrieve
nothing, and never competes with a borrower's own evidence for a place in the result.
"""

from __future__ import annotations

from credit_memo.adapters.local._seed import DEMO_CORPUS_TAG, SEED_PASSAGES
from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from credit_memo.config import LocalSettings, Settings
from credit_memo.domain.models import (
    Citation,
    DocType,
    Filing,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)

#: Wording chosen to collide with the seed corpus on the terms it indexes. A filing about
#: something the fixtures never mention would pass these tests without ever exercising the
#: competition that is the actual defect.
_FILING_TEXT = (
    "The audited financial statements report revenue, EBITDA and net debt for the "
    "borrower, and the covenant certificate states current net leverage and DSCR."
)

#: The tags ``domain.entitlements.borrower_acl`` stamps on ingested evidence.
_BORROWER_ACL = ("borrower:b-real", "tenant:demo-bank")

#: The query the memo pipeline issues (``memo_service._retrieval_query``), in miniature.
_QUERY_TEXT = "financial statements, covenants, credit policy and manufacturing context"


def _adapter() -> LocalFtsKnowledgeBaseAdapter:
    return LocalFtsKnowledgeBaseAdapter(
        Settings(profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:"))
    )


def _ingest_borrower_filing(adapter: LocalFtsKnowledgeBaseAdapter) -> None:
    adapter.ingest(
        Filing(
            id="doc-borrower-own", doc_type=DocType.FINANCIAL_STATEMENT, title="Borrower filing"
        ),
        _FILING_TEXT.encode(),
        _BORROWER_ACL,
    )


def _seeded_ids() -> set[str]:
    return {p.citation.source_id for p in SEED_PASSAGES}


def test_the_seed_corpus_is_not_public() -> None:
    """Untagged is public. Every seed passage must carry the demo tag instead."""

    assert SEED_PASSAGES, "the corpus must not be empty, or these tests prove nothing"
    for passage in SEED_PASSAGES:
        assert passage.acl_tags == (DEMO_CORPUS_TAG,), passage.citation.source_id


def test_a_borrower_with_its_own_evidence_is_grounded_only_in_that_evidence() -> None:
    """The defect, stated as a test: no fictional filing may reach a grounded borrower."""

    adapter = _adapter()
    _ingest_borrower_filing(adapter)

    passages = adapter.search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=_BORROWER_ACL, top_k=5)
    )

    assert passages, "the borrower's own filing must be retrievable"
    cited = {p.citation.source_id for p in passages}
    assert not (cited & _seeded_ids()), f"invented evidence grounded a real borrower: {cited}"
    assert cited == {"doc-borrower-own"}


def test_the_demo_corpus_still_grounds_a_run_that_supplied_nothing() -> None:
    """The affordance the corpus exists for, and the reason it is a fallback not a deletion.

    Deleting the corpus would also have closed the defect, and would have broken the
    documented out-of-the-box ``make memo`` run. This is the half of the behaviour worth
    keeping: a query with no evidence of its own is grounded rather than refused.
    """

    passages = _adapter().search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=("borrower:b-empty",), top_k=5)
    )

    assert passages, "an ungrounded local run must still find the built-in corpus"
    assert {p.citation.source_id for p in passages} <= _seeded_ids()


def test_the_fallback_does_not_reopen_the_door_for_a_grounded_borrower() -> None:
    """One retrieved passage is enough to shut it: the fallback is all-or-nothing.

    A fallback that topped a short result set up to ``top_k`` would restore the defect in
    its most confusing form: fictional evidence appearing only for borrowers whose real
    filings were thin, which is exactly when a reviewer is least able to notice.
    """

    adapter = _adapter()
    _ingest_borrower_filing(adapter)

    passages = adapter.search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=_BORROWER_ACL, top_k=5)
    )

    assert len(passages) == 1, "the borrower supplied exactly one passage"
    assert passages[0].citation.source_id == "doc-borrower-own"


def test_the_acl_filter_runs_before_the_top_k_budget_is_spent() -> None:
    """The seed rows must not consume the result budget ahead of admissible evidence.

    ``search`` used to apply ``LIMIT top_k`` in SQL and filter by ACL afterwards, so a
    ``top_k=1`` query could return NOTHING at all: the single row SQL handed back was a
    seed passage the caller was not entitled to, and the borrower's own filing was never
    looked at. Ungrounded is a hard error upstream, so that shape turned a leak into an
    outage as soon as the leak was tagged shut.
    """

    adapter = _adapter()
    _ingest_borrower_filing(adapter)

    passages = adapter.search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=_BORROWER_ACL, top_k=1)
    )

    assert [p.citation.source_id for p in passages] == ["doc-borrower-own"]


def test_an_index_seeded_before_the_fix_is_repaired_on_open(tmp_path: object) -> None:
    """Tagging the corpus in source does not by itself reach a laptop that already ran.

    Seeding only runs on an EMPTY index, so a machine that has used this repo once holds
    the built-in passages as untagged (public) rows forever. Without a repair the leak
    survives the fix on exactly the machines used most, silently: ``make memo`` prints a
    cited memo either way. This was observed by executing the pre-repair build against a
    real ``~/.credit_memo/local.db`` -- the fictional filings still reached a borrower
    that had just ingested its own.
    """

    db = f"{tmp_path}/legacy.db"
    # A pre-fix index: the same corpus, written UNTAGGED.
    legacy = LocalFtsKnowledgeBaseAdapter(
        Settings(profile="local", local=LocalSettings(db_path=db, audit_path=":memory:"))
    )
    with legacy._lock:  # noqa: SLF001 - constructing the legacy on-disk state under test
        legacy._conn.execute("UPDATE passages SET acl_tags = ''")  # noqa: SLF001
        legacy._conn.commit()  # noqa: SLF001

    # Re-opening the store must repair it rather than leave the public rows in place.
    adapter = LocalFtsKnowledgeBaseAdapter(
        Settings(profile="local", local=LocalSettings(db_path=db, audit_path=":memory:"))
    )
    _ingest_borrower_filing(adapter)

    passages = adapter.search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=_BORROWER_ACL, top_k=5)
    )

    cited = {p.citation.source_id for p in passages}
    assert not (cited & _seeded_ids()), f"the legacy index kept leaking: {cited}"
    assert cited == {"doc-borrower-own"}


def test_holding_the_demo_tag_is_what_admits_the_corpus() -> None:
    """The mechanism, asserted directly, so the fallback cannot be mistaken for a coincidence."""

    adapter = _adapter()
    _ingest_borrower_filing(adapter)

    with_tag = adapter.search(
        RetrievalQuery(text=_QUERY_TEXT, acl_principals=(*_BORROWER_ACL, DEMO_CORPUS_TAG), top_k=5)
    )

    assert {p.citation.source_id for p in with_tag} & _seeded_ids()


def test_the_fallback_corpus_survives_an_index_that_has_been_used(tmp_path) -> None:
    """The documented smoke run must not stop working because something was ingested.

    The local store is persistent and seeding only ran on a wholly EMPTY index, so the
    first `make demo` -- or any CLI run carrying a filing -- left it non-empty for good
    and `credit-memo build` began failing with RetrievalEmptyError on a machine where it
    had worked the day before. The error names the borrower, so nothing pointed at the
    cause.

    Worse, the presenter demo ingests its filings under the SAME source ids as the
    built-in corpus, tagged to its own borrower. Checking for the ids therefore found
    them, concluded the corpus was present, and left every other borrower with a fallback
    that could serve nothing.
    """
    db = str(tmp_path / "local.db")
    settings = Settings(profile="local", local=LocalSettings(db_path=db, audit_path=":memory:"))

    # A first run ingests a borrower's own evidence under the built-in source ids.
    first = LocalFtsKnowledgeBaseAdapter(settings)
    first.add(
        [
            RetrievedPassage(
                text="Some other borrower's own filing.",
                citation=Citation(
                    source_id="doc-financials",
                    source_type=SourceType.FILING,
                    title="Someone Else's Statements",
                    url="https://example.invalid/other",
                    page=1,
                ),
                score=0.9,
                acl_tags=("borrower:someone-else",),
            )
        ]
    )
    first._conn.execute("DELETE FROM passages WHERE acl_tags = ?", (DEMO_CORPUS_TAG,))
    first._conn.commit()

    # A later process opens the same store and must restore the fallback.
    second = LocalFtsKnowledgeBaseAdapter(settings)
    grounded = second.search(
        RetrievalQuery(
            text="financial statements covenants credit policy",
            top_k=5,
            acl_principals=("borrower:a-third-borrower",),
        )
    )
    assert grounded, "a borrower with no evidence of its own was left ungrounded"
    assert all(p.citation.url.startswith("https://example.test/") for p in grounded), (
        "the fallback served somebody else's ingested evidence"
    )
