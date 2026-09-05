"""Two properties only a managed model exercises, and both shipped broken.

The offline stand-in returns whatever the schema asks for, instantly, with no token budget
and echoing the bare source ids it was handed. A real model does neither, so both of these
passed every test in this repository and failed on the first deployed build:

* **The token budget covers thinking AND the answer.** At 4096 the reasoning alone took
  ~3,000 tokens on a real credit file, the JSON stopped mid-object at MAX_TOKENS, the
  defensive parser read nothing, and the memo said "the available evidence does not support
  a confident credit memo" -- a statement about the evidence for what was a budget.
* **A model cites the way the prompt asked it to.** The prompt says `[source_id p.N]`, so
  the model returns "doc-8526 p.4"; matching the raw string against retrieved source ids
  found none, every claim came back uncited, and the memo read as though the model had
  refused to ground itself when it had grounded itself and named the page.
"""

from __future__ import annotations

from credit_memo.domain import _grounded as g
from credit_memo.domain.models import Citation, RetrievedPassage, SourceType


def _passage(source_id: str, page: int) -> RetrievedPassage:
    return RetrievedPassage(
        text="evidence",
        citation=Citation(
            source_id=source_id,
            source_type=SourceType.FILING,
            title="A filing",
            url="https://example.invalid/x",
            page=page,
        ),
        score=0.9,
    )


def test_the_token_budget_leaves_room_for_the_answer_after_the_thinking() -> None:
    """Thinking is charged to the same budget, so 4096 truncated the memo mid-JSON."""
    request = g.build_llm_request("system", "user", None, None)
    assert request.max_output_tokens >= 8192


def test_a_citation_that_names_the_page_still_matches_its_source() -> None:
    """`[source_id p.N]` is what the prompt asks for, so it is what comes back."""
    passages = [_passage("doc-8526", 4)]

    cited = g.citations_for_source_ids(["doc-8526 p.4"], passages)

    assert [c.source_id for c in cited] == ["doc-8526"]
    assert [c.page for c in cited] == [4], "the retrieval page is kept, not the model's"


def test_a_bare_source_id_still_matches() -> None:
    assert [
        c.source_id for c in g.citations_for_source_ids(["doc-8526"], [_passage("doc-8526", 4)])
    ] == ["doc-8526"]


def test_an_id_nobody_retrieved_is_still_dropped() -> None:
    """The page-suffix tolerance must not become a way to cite anything at all."""
    passages = [_passage("doc-8526", 4)]

    assert g.citations_for_source_ids(["src-invented p.9"], passages) == ()
    assert g.citations_for_source_ids(["src-invented"], passages) == ()
