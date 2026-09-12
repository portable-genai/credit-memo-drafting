"""The demo, as an ordered list of acts. One deal, walked through the real product.

Each act is a business beat a credit audience recognises, and each one ASSERTS what it
claims on screen. That pairing is the point of the module: the walkthrough a presenter
shows and the suite CI runs are the same fifteen functions, so a capability that quietly
stops being reachable breaks the build instead of surprising somebody in front of a room.

Every expectation is recomputed from the running application: covenant status from the
threshold and the operator, ratios from the confirmed spread, the peer percentile from the
peer table. Nothing here matches a sentence the product happens to render today.

Every act drives the CONSOLE. Three of them could not, until the console grew the controls:
the committee pack, the reviewer's comment thread and deleting the evidence were API-only,
which made them indistinguishable from capabilities nobody had built. Where an act still calls
the API it is to CHECK what the console did, or to prove a refusal a console cannot even
express, such as typing over a computed section.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import fixtures as fx
from . import locators as loc
from .narrative import Narration, Point

ANALYST = "analyst"
APPROVER = "approver"
AUDITOR = "auditor"
OTHER_TENANT = "other-tenant"

#: The ask this memo answers, in millions to match the spread. The bank's hypothetical,
#: not anything the borrower has sought: ``demo/documents/SOURCES.md`` says so plainly, and
#: it is the only part of the deal that is not read off a filing.
FACILITY_AMOUNT = 400.0
FACILITY_TENOR = 60
FACILITY_PURPOSE = "Refinance the existing term loan and fund working capital"
FACILITY_SECURITY = "Unsecured, ranking pari passu with the existing senior facilities"
REPAYMENT_SOURCE = "Operating cash flow"

#: The tenor that trips the policy pack's one knockout rule (TEN-01, maximum 84 months).
KNOCKOUT_TENOR = 96

#: What the analyst rewrites the summary to, and what they rewrite it to again once the
#: checker asks who is being asked to waive the exception.
REVISED_SUMMARY = (
    "Revised by the analyst: leverage of 3.18x breaches the 3.00x covenant and the exception "
    "needs Regional Credit Committee waiver."
)
ANSWERED_SUMMARY = (
    "Revised again: the Regional Credit Committee is the waiver authority for the leverage "
    "exception."
)


class ActFailed(AssertionError):
    """An act did not show what it claims to show."""


@dataclass
class Stage:
    """Everything an act acts on: the browser, the API, and what earlier acts left behind."""

    page: Any
    api: Any
    ui_base: str
    api_base: str
    state: dict[str, Any] = field(default_factory=dict)
    #: Where a presenter's pauses go. ``None`` under pytest, where nobody is watching.
    beat: Callable[[Narration, str], None] | None = None

    # -- The presenter --------------------------------------------------- #
    def cue(self, *points: Point, look_at: str = "") -> None:
        """Hold here: read ``points`` out, point at ``look_at``, and wait for the presenter.

        The pause lives beside the step it interrupts rather than in the walkthrough
        script, because what is worth saying is a property of what just happened on
        screen. A form filled and not yet submitted, and the answer that came back, are
        two different things to talk about, and only this module knows where the boundary
        between them is.

        Inert when ``beat`` is None, which is how the pytest suite runs the same acts: an
        assertion never waits for a keystroke, and nothing here can change what an act
        proves.
        """
        if self.beat is not None:
            self.beat(points, look_at)

    # -- API helpers ----------------------------------------------------- #
    def get(self, path: str, persona: str = ANALYST) -> Any:
        return self.api.get(self.api_base + path, headers=_headers(persona))

    def post(self, path: str, body: Any = None, persona: str = ANALYST) -> Any:
        return self.api.post(
            self.api_base + path, headers=_headers(persona), data=body if body is not None else {}
        )

    def patch(self, path: str, body: Any, persona: str = ANALYST) -> Any:
        return self.api.patch(self.api_base + path, headers=_headers(persona), data=body)

    def delete(self, path: str, persona: str = ANALYST) -> Any:
        return self.api.delete(self.api_base + path, headers=_headers(persona))

    @property
    def analysis_id(self) -> str:
        analysis_id = self.state.get("analysis_id")
        if not analysis_id:
            raise ActFailed("no analysis has been opened yet; act 2 must run first")
        return str(analysis_id)

    @property
    def memo(self) -> dict:
        memo = self.state.get("memo")
        if not memo:
            raise ActFailed("no memo has been built yet; act 7 must run first")
        return dict(memo)


def _headers(persona: str) -> dict[str, str]:
    return {"X-Dev-Persona": persona, "Content-Type": "application/json"}


@dataclass(frozen=True)
class Act:
    """One beat of the demo: what to say, what to do, and what it must prove."""

    title: str
    #: The business points, in the order a presenter says them. See :mod:`.narrative`.
    narration: Narration
    run: Any
    #: What a presenter should look at while this act is on screen.
    point_at: str = ""
    #: ``optional`` acts need an environment the default demo does not have.
    optional: bool = False


# --------------------------------------------------------------------------- #
# Shared console helpers
# --------------------------------------------------------------------------- #
def _upload_files(stage: Stage) -> None:
    """Put the credit file into the console's upload panel."""
    stage.page.locator(loc.DOCUMENTS_INPUT).set_input_files(
        [
            {
                "name": "flowserve-fy2025-financial-extract.pdf",
                "mimeType": "application/pdf",
                "buffer": fx.audited_financials(),
            },
            {
                "name": "flowserve-fy2025-spread.csv",
                "mimeType": "text/csv",
                "buffer": fx.spread_csv(),
            },
            {
                "name": "flowserve-covenant-position.txt",
                "mimeType": "text/plain",
                "buffer": fx.covenant_position(),
            },
        ]
    )
    kinds = {
        "flowserve-fy2025-financial-extract.pdf": "Audited financial statements",
        "flowserve-fy2025-spread.csv": "Your own spread",
        "flowserve-covenant-position.txt": "Covenant compliance certificate",
    }
    for filename, label in kinds.items():
        stage.page.locator(loc.document_kind(filename)).select_option(label=label)
        stage.page.locator(loc.document_as_of(filename)).fill(fx.PERIOD_ENDED)


def _fill_request(stage: Stage, kind: str = "New facility", tenor: int = FACILITY_TENOR) -> None:
    page = stage.page
    page.locator(loc.MEMO_KIND).select_option(label=kind)
    page.locator(loc.LOAN_TYPE).select_option(label="C&I term / working capital")
    page.locator(loc.FACILITY_TYPE).select_option(label="term loan")
    page.locator(loc.AMOUNT).fill(str(FACILITY_AMOUNT))
    page.locator(loc.TENOR).fill(str(tenor))
    page.locator(loc.REPAYMENT_SOURCE).fill(REPAYMENT_SOURCE)
    page.locator(loc.PURPOSE).fill(FACILITY_PURPOSE)
    page.locator(loc.SECURITY).fill(FACILITY_SECURITY)


def _build(stage: Stage, timeout: int = 60_000) -> None:
    """Press Build and wait until that attempt has settled, answered or refused.

    Keyed on the console's count of settled attempts rather than on the "Building..." label
    going away: an attempt the console refuses before it starts never shows that label, so a
    wait for it to disappear could return before the press had been handled at all.
    """
    settled = int(stage.page.locator(loc.OUTCOME).get_attribute("data-outcomes") or "0")
    stage.page.locator(loc.BUILD).click()
    stage.page.locator(f'{loc.OUTCOME}[data-outcomes="{settled + 1}"]').wait_for(
        state="attached", timeout=timeout
    )


def _ok(response: Any, what: str) -> Any:
    if not response.ok:
        raise ActFailed(f"could not {what}: HTTP {response.status} {response.text()[:300]}")
    return response


def _text(stage: Stage) -> str:
    return str(stage.page.inner_text("body"))


def _as_persona(stage: Stage, persona: str) -> None:
    """Become somebody else in the console, which is what its identity picker is for.

    Every request the page makes after this carries that persona. The SERVICE still resolves
    the actor from it: what the console sends is a choice of seeded person, never a claim
    about who they are, which is why the confirmer, the comment author and the resolver all
    come back from the service rather than from the browser.
    """
    stage.page.locator(loc.PERSONA).select_option(persona)


def _console_page(stage: Stage) -> Any:
    """The deal's console page, closing whatever page an earlier act left on screen.

    Act 15 puts the rendered pack on screen and act 17 runs in a page of its own, so the page
    the stage holds is not always the console. The deal's page is the one that matters: it
    holds the memo, its revision chain, the comment thread and the delete, and a reload would
    lose all four.
    """
    console = stage.state.pop("console_page", None)
    if console is None:
        return stage.page
    if stage.page is not console:
        with contextlib.suppress(Exception):
            stage.page.close()
    stage.page = console
    return console


def _download(stage: Stage, fmt: str) -> bytes:
    """Press the console's own download button and read back what the browser saved."""
    page = stage.page
    page.locator(loc.EXPORT_FORMAT).select_option(fmt)
    with page.expect_download() as saved:
        page.locator(loc.EXPORT).click()
    return Path(saved.value.path()).read_bytes()


# --------------------------------------------------------------------------- #
# 1. Who is asking
# --------------------------------------------------------------------------- #
def act_identity(stage: Stage) -> None:
    page = stage.page
    page.goto(stage.ui_base, wait_until="load")
    # The picker is filled by a fetch the page makes after it hydrates, so waiting for the
    # OPTIONS rather than for the control is the difference between reading the personas
    # and reading an empty select that is about to be filled.
    picker = page.locator(loc.PERSONA)
    # ``attached`` rather than ``visible``: an <option> is never visible in its own right,
    # so waiting for visibility waits for something that cannot happen.
    picker.locator("option").first.wait_for(state="attached", timeout=30_000)
    options = picker.locator("option").all_inner_texts()
    if len(options) < 4:
        raise ActFailed(f"expected the four seeded personas, saw {options}")
    # The analyst is the default and the first option; select it explicitly so the demo
    # never depends on which persona happened to be remembered.
    picker.select_option(index=0)
    subject = options[0].split(" · ")[0]
    if "@" not in subject:
        raise ActFailed(f"the persona picker does not name a subject: {options[0]!r}")
    stage.state["actor"] = subject


# --------------------------------------------------------------------------- #
# 2. The credit file
# --------------------------------------------------------------------------- #
def act_credit_file(stage: Stage) -> None:
    page = stage.page
    page.locator(loc.BORROWER).fill(fx.BORROWER_NAME)
    page.locator(loc.SECTOR).fill(fx.SECTOR)
    page.locator(loc.JURISDICTION).fill(fx.JURISDICTION)
    _upload_files(stage)
    stage.cue(
        Point(
            "Three documents: the audited filing, the analyst's own spread of it, and the "
            "covenant position.",
            "An extract of Flowserve's FY2025 Form 10-K. The accession number is on every "
            "page, so anyone in the room can open the filing and check it.",
        ),
        Point(
            "Each is labelled with what it is, and the date it speaks to.",
            "The service cannot tell last year's management accounts from yesterday's, and "
            "will not guess.",
        ),
        look_at="the three rows, each with its own kind and as-of date, before anything is read",
    )

    # Opening the analysis is what puts the evidence in custody, and the console does it
    # on the first step that needs it. Extract is that step.
    page.locator(loc.EXTRACT).click()
    page.locator(loc.SPREAD_CANDIDATE).wait_for(timeout=60_000)

    # The manifest carries the analysis id as a hook, and the id must ALSO be on screen: the
    # manifest naming the analysis is the reader-facing claim this act is about.
    analysis_id = page.locator(loc.MANIFEST).first.get_attribute("data-analysis-id") or ""
    body = _text(stage)
    if not analysis_id.startswith("an-") or analysis_id not in body:
        raise ActFailed("the manifest did not name the analysis on screen")
    stage.state["analysis_id"] = analysis_id

    manifest = _ok(stage.get(f"/v1/analyses/{analysis_id}"), "read the manifest").json()
    filenames = [d["filename"] for d in manifest["documents"]]
    if sorted(filenames) != [
        "flowserve-covenant-position.txt",
        "flowserve-fy2025-financial-extract.pdf",
        "flowserve-fy2025-spread.csv",
    ]:
        raise ActFailed(f"the manifest does not name every file: {filenames}")
    if not all(d["sha256"] for d in manifest["documents"]):
        raise ActFailed("a document reached custody without a digest")
    if not manifest["retention_note"] or "deleted" not in manifest["retention_note"]:
        raise ActFailed(f"the manifest does not say when the evidence goes: {manifest}")
    if "available until" not in page.locator(loc.RETENTION).first.inner_text():
        raise ActFailed("the retention note is not on screen")
    stage.state["manifest"] = manifest
    stage.cue(
        Point(
            "The evidence is in custody. The manifest is the receipt.",
            "Every file by name, its SHA-256 digest, its page count, and the date it is deleted.",
        ),
        Point("Nothing downstream can cite a document that is not on this list."),
        look_at=f"the manifest, and the retention line: {manifest['retention_note']}",
    )


# --------------------------------------------------------------------------- #
# 3. Figures nobody has vouched for
# --------------------------------------------------------------------------- #
def act_extraction_is_a_proposal(stage: Stage) -> None:
    page = stage.page
    body = _text(stage)
    if "Not yet anybody's figures" not in body:
        raise ActFailed("the candidate is not labelled as a proposal")

    candidate = _ok(
        stage.get(f"/v1/analyses/{stage.analysis_id}/spreads"), "read the spreads"
    ).json()["candidate"]
    provenances = {item["provenance"] for item in candidate["items"]}
    if provenances != {"extracted"}:
        raise ActFailed(f"a candidate item is not merely extracted: {provenances}")
    if not all(item["quote"] and item["document_id"] for item in candidate["items"]):
        raise ActFailed("a proposed figure does not say where it was read")

    # The quote a reviewer checks the figure against, opened from the row itself.
    page.locator(loc.SHOW_QUOTE).first.click()
    if page.locator(loc.OPEN_SOURCE).count() == 0:
        raise ActFailed("the quote does not link back to the document it came from")
    stage.state["candidate"] = candidate
    stage.cue(
        Point(
            f"{len(candidate['items'])} figures read off the documents.",
            "Every row shows the sentence it was read from, with a link to the page it is on.",
        ),
        Point(
            "Nothing has been computed from them yet.",
            "The product's own types refuse to put an extracted figure into a ratio.",
        ),
        Point("The only way out of this panel is a person confirming it."),
        look_at="the amber panel, and the quote opened beside the number it explains",
    )


# --------------------------------------------------------------------------- #
# 4. Becoming the person who stands behind them
# --------------------------------------------------------------------------- #
def act_confirm_the_spread(stage: Stage) -> None:
    page = stage.page
    _spread_row(stage, fx.REJECTED_CODE).locator(loc.verdict("reject")).check()
    adjusted_row = _spread_row(stage, fx.ADJUSTED_CODE)
    adjusted_row.locator(loc.verdict("adjust")).check()
    adjusted_row.locator(loc.ADJUSTED_VALUE).fill(str(fx.ADJUSTED_TO))
    adjusted_row.locator(loc.ADJUSTMENT_REASON).fill(fx.ADJUSTMENT_REASON)
    stage.cue(
        Point(
            f"REJECT the cash line of USD {fx.REJECTED_VALUE:,.1f}m.",
            "This bank measures leverage on gross debt. A credit policy decision, not a "
            "correction to the filing.",
        ),
        Point(
            f"ADJUST EBITDA from USD {fx.ADJUSTED_FROM:,.1f}m to "
            f"USD {fx.ADJUSTED_TO:,.1f}m, with a reason.",
            f"Declining the add-back of USD {fx.REALIGNMENT_CHARGES:,.1f}m of realignment "
            "charges that have recurred three years running.",
        ),
        Point(
            "Both numbers are kept.",
            "The adjustment sits beside the borrower's original, never over it.",
        ),
        look_at="the struck-through cash row, and EBITDA with the reason beside it, before "
        "anything is confirmed",
    )

    page.locator(loc.CONFIRM).click()
    confirmed_line = page.locator(loc.SPREAD_CONFIRMED)
    confirmed_line.wait_for(timeout=60_000)

    spread = _ok(stage.get(f"/v1/analyses/{stage.analysis_id}/spreads"), "read the spreads").json()[
        "confirmed"
    ]
    if not spread or not spread.get("confirmed_by"):
        raise ActFailed("the confirmed spread carries no confirmer")
    if spread["confirmed_by"] != stage.state.get("actor"):
        raise ActFailed(
            f"the confirmation is attributed to {spread['confirmed_by']!r}, "
            f"not to the signed-in analyst {stage.state.get('actor')!r}"
        )
    codes = {item["code"]: item for item in spread["items"]}
    if fx.REJECTED_CODE in codes:
        raise ActFailed("a rejected line survived into the confirmed spread")
    adjusted = codes.get(fx.ADJUSTED_CODE)
    if adjusted is None or adjusted["value"] != fx.ADJUSTED_TO:
        raise ActFailed(f"the adjustment did not take: {adjusted}")
    # An adjusted figure is the ANALYST'S, not the document's, and the provenance says so
    # while the citation still points at the page the original came from.
    if adjusted.get("provenance") != "user_entered":
        raise ActFailed(
            f"an adjusted figure is attributed to the document rather than to the person "
            f"who changed it: {adjusted.get('provenance')!r}"
        )
    if not adjusted.get("citations"):
        raise ActFailed("the adjusted figure lost the page its original was read from")
    if confirmed_line.get_attribute("data-confirmed-by") != spread["confirmed_by"]:
        raise ActFailed("the confirmation on screen names somebody the service did not record")
    stage.state["spread"] = spread
    stage.cue(
        Point(f"Confirmed by {spread['confirmed_by']}."),
        Point(
            "That name is the verified identity behind the session.",
            "Not a field this browser filled in, and not editable from it.",
        ),
        Point("From here every engine computes from figures a named person accepted."),
        look_at="the green 'Confirmed by' line",
    )


# --------------------------------------------------------------------------- #
# 5. The memo
# --------------------------------------------------------------------------- #
def act_build_the_memo(stage: Stage) -> None:
    _fill_request(stage)
    stage.cue(
        Point(
            f"The ask: a new USD {FACILITY_AMOUNT:.0f}m term facility over "
            f"{FACILITY_TENOR} months.",
            "With its purpose, its repayment source and its security.",
        ),
        Point(
            "Stated before the memo is written, not after.",
            "Without the ask the memo would comment on a borrower rather than assess a "
            "credit. Those are different documents.",
        ),
        look_at="the completed ask, before Build is pressed",
    )
    _build(stage)

    body = _text(stage)
    if loc.REVIEW_BANNER not in body:
        raise ActFailed("the maker-checker banner is not on the memo")
    for selector in loc.ALWAYS_PRESENT:
        if stage.page.locator(selector).count() != 1:
            raise ActFailed(f"the memo does not show the {selector} section")

    memo = _ok(
        stage.post(f"/v1/analyses/{stage.analysis_id}/build", {"request": _request_body()}),
        "read the memo back",
    ).json()
    if not memo.get("requires_human_review"):
        raise ActFailed("a memo was produced that does not require human review")
    if not memo.get("citations"):
        raise ActFailed("the memo carries no citations")
    # Grounded in the borrower's OWN evidence, never in the built-in fictional corpus.
    uploaded = {d["id"] for d in memo["manifest"]["documents"]}
    cited = {c["source_id"] for c in memo["citations"]}
    if not cited or not cited <= uploaded:
        raise ActFailed(f"the memo cites something nobody uploaded: {cited - uploaded}")
    stage.state["memo"] = memo
    stage.cue(
        Point(
            "The ratios were computed BEFORE a word was drafted.",
            "Redact, screen, retrieve from the borrower's own evidence, compute, then write "
            "prose around numbers the bank calculated.",
        ),
        Point(
            f"{len(memo['citations'])} citations, every one a document in this credit file.",
            "Nothing is cited that nobody in this room uploaded.",
        ),
        Point(
            "The human-review banner is unconditional.",
            "No configuration produces a memo without it.",
        ),
        look_at="the amber human-review banner, then scroll the sections a committee reads",
    )


def _request_body(kind: str = "new_facility", tenor: int = FACILITY_TENOR) -> dict:
    return {
        "kind": kind,
        "loan_type": "ci_term",
        "facilities": [
            {
                "id": "fac-1",
                "facility_type": "term_loan",
                "amount": FACILITY_AMOUNT,
                "currency": "USD",
                "tenor_months": tenor,
                "purpose": FACILITY_PURPOSE,
                "repayment_source": REPAYMENT_SOURCE,
                "security": FACILITY_SECURITY,
            }
        ],
        "purpose": FACILITY_PURPOSE,
        "total_amount": FACILITY_AMOUNT,
    }


# --------------------------------------------------------------------------- #
# 6. The arithmetic the model cannot soften
# --------------------------------------------------------------------------- #
def act_the_breach_stands(stage: Stage) -> None:
    """The beat the whole demo is built around, and every number in it is filed.

    The borrower reports 1.64x and full compliance. The engine computes 3.18x and a
    breach. Neither is wrong: the borrower nets its cash and adds back its realignment
    charges, and this bank does neither. What the product does is refuse to pick one
    quietly.
    """
    memo = stage.memo
    covenants = {c["type"]: c for c in memo["covenants"]}
    leverage = covenants.get("leverage")
    if leverage is None:
        raise ActFailed("no leverage covenant was extracted")

    expected = fx.gross_leverage()
    if abs(leverage["current_value"] - expected) > 1e-9:
        raise ActFailed(
            f"the covenant was tested against {leverage['current_value']}, not against the "
            f"{expected:.4f} the confirmed spread computes"
        )
    if leverage["status"] != "breach":
        raise ActFailed(
            f"leverage {expected:.2f}x against <= {leverage['threshold']}x is not a breach"
        )
    reported = leverage.get("reported_value")
    if reported is None or abs(reported - leverage["current_value"]) < 1e-9:
        raise ActFailed(
            "the evidence and the engine agree, so this act proves nothing about which "
            "one the product trusts"
        )
    if abs(reported - fx.REPORTED_NET_LEVERAGE) > 0.01:
        raise ActFailed(
            f"the memo reports the borrower's figure as {reported}, not the "
            f"{fx.REPORTED_NET_LEVERAGE}x its own filing states"
        )

    # Thin headroom is its own answer, distinct from compliant. Here it falls out of the
    # filed figures rather than being arranged: 2.03x against a 2.00x floor.
    liquidity = covenants.get("current_ratio")
    if liquidity is None or liquidity["status"] != "at_risk":
        raise ActFailed(
            f"the current ratio passes by {abs(fx.current_ratio() - fx.MIN_CURRENT_RATIO) / fx.MIN_CURRENT_RATIO:.1%} "
            f"and should be flagged at risk, saw {liquidity}"
        )
    # And a covenant that is simply met, because a demo where everything fails is as
    # untrue as one where nothing does.
    dscr = covenants.get("dscr")
    if dscr is None or dscr["status"] != "compliant":
        raise ActFailed(f"DSCR of {fx.dscr():.2f}x against 1.25x should be met, saw {dscr}")

    statuses = stage.page.locator(loc.covenant("leverage")).evaluate_all(
        "cards => cards.map((card) => card.dataset.status)"
    )
    if "breach" not in statuses:
        raise ActFailed(f"the breach is not visible on screen: leverage shows {statuses}")


# --------------------------------------------------------------------------- #
# 7. It refuses to compute what it cannot
# --------------------------------------------------------------------------- #
def act_uncomputable_ratios(stage: Stage) -> None:
    memo = stage.memo
    skipped = [r for r in memo["ratios"] if r["value"] is None]
    if not skipped:
        raise ActFailed("every ratio computed, so nothing demonstrates the refusal")
    for ratio in skipped:
        if not ratio["reason_missing"]:
            raise ActFailed(f"{ratio['formula_id']} was skipped without saying why")
    computed = [r for r in memo["ratios"] if r["value"] is not None]
    if not computed:
        raise ActFailed("no ratio computed at all")
    for ratio in computed:
        if not ratio["definition"]:
            raise ActFailed(f"{ratio['formula_id']} states a number without its formula")


# --------------------------------------------------------------------------- #
# 8. The bank's own policy, and the grade it proposes
# --------------------------------------------------------------------------- #
def act_policy_and_rating(stage: Stage) -> None:
    memo = stage.memo
    if not memo["policy_version"]:
        raise ActFailed("the memo does not say which policy it was measured against")
    exceptions = {e["rule_id"]: e for e in memo["policy_exceptions"]}
    breach = exceptions.get("LEV-01")
    if breach is None:
        raise ActFailed(
            f"leverage of {fx.gross_leverage():.2f}x raised no policy exception: {list(exceptions)}"
        )
    if not breach["waiver_authority"]:
        raise ActFailed("an exception nobody can waive is not actionable")
    if abs(breach["measured"] - fx.gross_leverage()) > 1e-9:
        raise ActFailed("the exception was measured against something other than the engine")

    rating = memo.get("rating")
    if rating is None or not rating["obligor_grade"]:
        raise ActFailed("the scorecard proposed no grade")
    if not rating["drivers"]:
        raise ActFailed("a grade was proposed without saying what drove it")
    if rating["provenance"] != "computed":
        raise ActFailed("the grade is not the scorecard's arithmetic")

    for selector in (loc.SECTION_POLICY, loc.SECTION_RATING):
        if stage.page.locator(selector).count() != 1:
            raise ActFailed(f"the {selector} section is not on screen")
    rule_on_screen = stage.page.locator(loc.policy_rule(breach["rule_id"]))
    if rule_on_screen.count() == 0 or breach["rule_id"] not in rule_on_screen.first.inner_text():
        raise ActFailed("the breached rule is not named on screen")


# --------------------------------------------------------------------------- #
# 9. The reconciliations a credit file is expected to survive
# --------------------------------------------------------------------------- #
def act_reconciliation(stage: Stage) -> None:
    memo = stage.memo
    findings = memo["tie_out"]
    if not findings:
        raise ActFailed("no reconciliation ran")
    certificate = [f for f in findings if f["check"] == "certificate_agrees"]
    if not certificate:
        raise ActFailed(
            f"the borrower reports {fx.REPORTED_NET_LEVERAGE}x where the engine computes "
            f"{fx.gross_leverage():.2f}x and nothing flagged the disagreement"
        )
    for finding in certificate:
        if finding["expected"] == finding["actual"]:
            raise ActFailed("a reconciliation was raised on figures that agree")
    if stage.page.locator(loc.SECTION_TIE_OUT).count() != 1:
        raise ActFailed("the reconciliation findings are not on screen")


# --------------------------------------------------------------------------- #
# 10. The group, and who it could not include
# --------------------------------------------------------------------------- #
def act_the_group(stage: Stage) -> None:
    """Two real subsidiaries, neither of which the bank holds statements for.

    Both come from Exhibit 21.1 of the same 10-K. Neither files separately, so a lender to
    the parent genuinely cannot consolidate them, which is the point. The memo names them
    as entities it could not include rather than totalling without them, because "we did
    not look" is a weaker claim than a total that quietly omits a 100%-owned subsidiary and
    a 40%-held affiliate.

    No intercompany elimination is entered, and that is deliberate. Flowserve discloses a
    real one -- USD 10.6m of intersegment sales -- but the borrower's spread is already
    consolidated and net of it, so recording it again would deduct it twice. Inventing a
    different one to exercise the feature is exactly the fabrication this demo removed.
    """
    page = stage.page
    page.locator(loc.GROUP_ENTITY).fill(fx.SUBSIDIARY_NAME)
    page.locator(loc.GROUP_ROLE).select_option(label="Subsidiary")
    page.locator(loc.ADD_TO_GROUP).click()

    page.locator(loc.GROUP_ENTITY).fill(fx.AFFILIATE_NAME)
    page.locator(loc.GROUP_ROLE).select_option(label="Affiliate")
    page.locator(loc.ADD_TO_GROUP).click()
    stage.cue(
        Point(
            "Two real subsidiaries, out of Exhibit 21 of the same filing.",
            f"{fx.SUBSIDIARY_NAME} in {fx.SUBSIDIARY_JURISDICTION}, wholly owned. "
            f"{fx.AFFILIATE_NAME} in {fx.AFFILIATE_JURISDICTION}, 40% held.",
        ),
        Point(
            "Both rows are blank, and stay blank.",
            "Neither files separately, so a lender to the parent holds no standalone "
            "statements for either. The ordinary case, not the awkward one.",
        ),
        Point("Watch what the consolidation does with an entity it has no figures for."),
        look_at="the two entity rows, entirely blank, before the rebuild",
    )

    _build(stage)

    memo = _ok(
        stage.post(f"/v1/analyses/{stage.analysis_id}/build", _group_body()),
        "rebuild with the group",
    ).json()
    gcf = memo.get("global_cash_flow")
    if gcf is None:
        raise ActFailed("no global cash flow was assembled for a group")
    if gcf["complete"]:
        raise ActFailed("the cash flow claims completeness while two entities filed nothing")
    missing = gcf["entities_without_figures"]
    for name in (fx.SUBSIDIARY_NAME, fx.AFFILIATE_NAME):
        if name not in missing:
            raise ActFailed(f"an entity nobody filed for is not named: {name} not in {missing}")
    revenue = next((line for line in gcf["lines"] if line["code"] == "revenue"), None)
    if revenue is None or not revenue["contributions"]:
        raise ActFailed("the consolidated revenue does not show who contributed it")
    stage.state["group_memo"] = memo

    notice = stage.page.locator(loc.GCF_INCOMPLETE)
    if notice.count() != 1 or fx.SUBSIDIARY_NAME not in notice.inner_text():
        raise ActFailed("the entity the consolidation could not include is not on screen")
    stage.cue(
        Point(
            "The cash flow does not claim to be complete, and names exactly who is missing.",
            "'We hold no accounts for the Singapore subsidiary' is a weaker claim than a "
            "total, and a truer one. A total that quietly omits a wholly-owned subsidiary "
            "reads as though it contributes nothing.",
        ),
        Point(
            "Note what is NOT here: no invented intercompany elimination.",
            f"Flowserve discloses a real one, USD "
            f"{fx.DISCLOSED_INTERSEGMENT_ELIMINATION}m between its two divisions, and it is "
            "already inside the consolidated revenue. Recording it again would deduct it "
            "twice.",
        ),
        look_at="the incomplete notice naming both entities, and the borrower's own contribution",
    )


def _group_body() -> dict:
    """The group as the build endpoint takes it: two entities, and no figures for either.

    ``entity_spreads`` is empty on purpose. The borrower's own confirmed spread is added by
    the service, so the consolidation has something to total; these two contribute nothing
    and are reported as entities it could not include.
    """
    return {
        "request": _request_body(),
        "related_entities": [
            {
                "id": "flowserve-pte-ltd",
                "name": fx.SUBSIDIARY_NAME,
                "role": "subsidiary",
                "jurisdiction": fx.SUBSIDIARY_JURISDICTION,
            },
            {
                "id": "arabian-seals",
                "name": fx.AFFILIATE_NAME,
                "role": "affiliate",
                "jurisdiction": fx.AFFILIATE_JURISDICTION,
            },
        ],
        "entity_spreads": {},
        "eliminations": [],
    }


# --------------------------------------------------------------------------- #
# 11. How far it can fall
# --------------------------------------------------------------------------- #
def act_stress(stage: Stage) -> None:
    memo = stage.state.get("group_memo") or stage.memo
    scenarios = memo.get("scenarios") or []
    if not scenarios:
        raise ActFailed("no stress scenario was run")
    for scenario in scenarios:
        if scenario["stressed_value"] is None:
            raise ActFailed(f"{scenario['scenario_id']} reports no stressed value")
        # A missing break-even is an ANSWER, not a gap: it means the borrower absorbs
        # every severity worth modelling. What would be wrong is a scenario that fails
        # and still reports no break-even, because then the number is missing exactly
        # where a committee needs it.
        if scenario.get("breaks_at") is None and not scenario["passes"]:
            raise ActFailed(
                f"{scenario['scenario_id']} fails and still reports no break-even, which "
                "is the half a committee can actually judge"
            )
    if all(s.get("breaks_at") is None for s in scenarios):
        raise ActFailed("no scenario reports a break-even, so there is nothing to point at")
    combined = next((s for s in scenarios if s["scenario_id"] == "combined"), None)
    single = next((s for s in scenarios if s["scenario_id"] != "combined"), None)
    if combined and single and combined["stressed_value"] > single["stressed_value"]:
        raise ActFailed("the combined shock bites less hard than a single one")


# --------------------------------------------------------------------------- #
# 12. The checker
# --------------------------------------------------------------------------- #
def act_the_checker(stage: Stage) -> None:
    page = stage.page
    analysis_id = stage.analysis_id

    # The analyst rewrites the summary in the console's own editor.
    page.locator(loc.AMEND_SECTION).select_option("summary")
    page.locator(loc.AMEND_TEXT).fill(REVISED_SUMMARY)
    page.locator(loc.AMEND_REASON).fill("The drafted summary understated the breach.")
    page.locator(loc.AMEND_NOTE).fill("Rewritten to lead with the covenant position.")
    page.locator(loc.AMEND).click()
    page.locator(loc.revisions_numbering(2)).wait_for(timeout=30_000)

    chain = _ok(stage.get(f"/v1/analyses/{analysis_id}/revisions"), "read the revisions").json()
    amended = chain["revisions"][-1]["revision"]
    if amended < 2:
        raise ActFailed("an edit did not open a new revision")
    if REVISED_SUMMARY not in _text(stage):
        raise ActFailed("the edited summary is not the one on screen")
    stage.cue(
        Point(f"The analyst rewrites the summary to lead with the breach (revision {amended})."),
        Point(
            "The draft nobody touched is still there.",
            "And so is the reason this revision was written, in the author's own words.",
        ),
        look_at=f"revision {amended}, with its reason and note",
    )

    # The approver objects, as themselves.
    _as_persona(stage, APPROVER)
    page.locator(loc.COMMENT_SECTION).select_option("summary")
    page.locator(loc.COMMENT_BODY).fill("Say who is being asked to waive this.")
    page.locator(loc.ADD_COMMENT).click()
    page.locator(f'{loc.COMMENTS}[data-open-count="1"]').wait_for(timeout=30_000)

    thread = _ok(stage.get(f"/v1/analyses/{analysis_id}/comments"), "list the comments").json()
    comment = thread["comments"][-1]
    if comment["revision"] != amended:
        raise ActFailed("the comment is not anchored to the text its author read")
    if "@" not in comment["author"]:
        raise ActFailed("an unattributed comment")
    if page.locator(loc.comment_row(comment["id"])).count() != 1:
        raise ActFailed("the comment the service recorded is not on screen")
    stage.cue(
        Point("The approver objects."),
        Point(
            f"The comment is anchored to revision {comment['revision']}: the exact text they read.",
            "Not to the section, and not to the memo: to the words that were in front of "
            "them when they wrote it.",
        ),
        look_at=f"the comment by {comment['author']}, anchored to revision {comment['revision']}",
    )

    # The analyst answers it, and the comment goes stale rather than away.
    _as_persona(stage, ANALYST)
    page.locator(loc.AMEND_SECTION).select_option("summary")
    page.locator(loc.AMEND_TEXT).fill(ANSWERED_SUMMARY)
    page.locator(loc.AMEND_REASON).fill("Answering the checker.")
    page.locator(loc.AMEND_NOTE).fill("Named the waiver authority.")
    page.locator(loc.AMEND).click()
    page.locator(loc.revisions_numbering(3)).wait_for(timeout=30_000)
    page.locator(f'{loc.comment_row(comment["id"])}[data-stale="true"]').wait_for(timeout=30_000)

    listing = _ok(stage.get(f"/v1/analyses/{analysis_id}/comments"), "list the comments").json()
    if not [c for c in listing["comments"] if c["stale"]]:
        raise ActFailed(
            "editing the text underneath a comment did not flag it; a comment that lapsed "
            "because the text moved was lost, not answered"
        )
    if listing["open_count"] != 1:
        raise ActFailed("the edit closed the comment instead of flagging it")
    stage.cue(
        Point("The analyst edits again, and the comment does not close."),
        Point(
            f"It is flagged stale, and stays open ({listing['open_count']} open).",
            "A comment that lapsed because the text moved underneath it was lost, not "
            "answered, and the difference matters to whoever signs this.",
        ),
        look_at=f"the comment marked stale, with {listing['open_count']} still open",
    )

    # And the approver closes it, by name and with what was done about it.
    _as_persona(stage, APPROVER)
    row = page.locator(loc.comment_row(comment["id"]))
    row.locator(loc.RESOLUTION).fill("Named the Regional Credit Committee in the summary.")
    row.locator(loc.RESOLVE).click()
    page.locator(f'{loc.comment_row(comment["id"])}[data-open="false"]').wait_for(timeout=30_000)

    closed = _ok(stage.get(f"/v1/analyses/{analysis_id}/comments"), "list the comments").json()
    resolved = next(c for c in closed["comments"] if c["id"] == comment["id"])
    if "@" not in (resolved.get("resolved_by") or ""):
        raise ActFailed("the resolution does not name the person who made it")

    revisions = _ok(stage.get(f"/v1/analyses/{analysis_id}/revisions"), "read revisions").json()
    if not revisions["chain_intact"]:
        raise ActFailed(f"the revision chain is broken: {revisions['chain_detail']}")
    if len(revisions["revisions"]) < 3:
        raise ActFailed("the chain does not start at the draft nobody touched")
    if page.locator(f'{loc.REVISIONS}[data-chain-intact="true"]').count() != 1:
        raise ActFailed("the console does not report the chain it just extended as intact")
    stage.state["revisions"] = revisions
    stage.cue(
        Point(
            f"Resolved by {resolved.get('resolved_by')}: a person, named.",
            "Not the software deciding it had been dealt with.",
        ),
        Point(
            f"The chain of {len(revisions['revisions'])} revisions verifies.",
            "Every version from the machine's draft to this one, each linked to the last, "
            "none of them quietly rewritten.",
        ),
        look_at="the resolution and the intact revision chain",
    )


# --------------------------------------------------------------------------- #
# 13. Figures are not editable prose
# --------------------------------------------------------------------------- #
def act_figures_are_not_prose(stage: Stage) -> None:
    # The console offers exactly the sections the service accepts, and it ASKS which those
    # are rather than keeping a list that can drift out of agreement with the refusal.
    offered = stage.page.eval_on_selector_all(
        f"{loc.AMEND_SECTION} option", "options => options.map((option) => option.value)"
    )
    editable = _ok(
        stage.get(f"/v1/analyses/{stage.analysis_id}/revisions"), "read the revisions"
    ).json()["editable_sections"]
    if sorted(offered) != sorted(editable):
        raise ActFailed(f"the editor offers {offered}; the service accepts {editable}")
    if "ratios" in offered:
        raise ActFailed("the console offers to type over a computed section")

    # And the refusal holds for a caller that never goes through the console.
    response = stage.patch(
        f"/v1/analyses/{stage.analysis_id}/memo",
        {
            "sections": {"ratios": "Leverage is 2.0x."},
            "reason": "Trying to type over the arithmetic.",
            "note": "This must be refused.",
        },
    )
    if response.ok:
        raise ActFailed("a computed section was editable by hand")
    detail = response.text()
    if "editable" not in detail:
        raise ActFailed(f"the refusal does not explain itself: {detail[:200]}")


# --------------------------------------------------------------------------- #
# 14. Public context, for the analyst only
# --------------------------------------------------------------------------- #
SECTOR_QUERY = "manufacturing sector outlook"


def act_public_context(stage: Stage) -> None:
    """The one place the product reaches the open web, and the one it may not reach.

    Worth showing precisely because the fence is counter-intuitive: the search runs, the
    analyst reads it, and none of it can enter the memo. Google's Service Specific Terms
    section 20(k) permit Grounded Results to be displayed only to the End User who
    submitted the prompt, and a memo is read by a checker, a committee and later an
    examiner.

    Offline the adapter is a fixture that says so in every title. Under ``live`` the same
    switch reaches real Grounding with Google Search. The act asserts the fence either way,
    because the fence is the claim.
    """
    page = stage.page
    page.locator(loc.RESEARCH_QUERY).fill(SECTOR_QUERY)
    stage.cue(
        Point(
            "An analyst wants sector context, and would otherwise open a browser for it.",
            "Running it inside the console means the question and its answer are at least logged.",
        ),
        Point(
            "Offline every row is labelled a fixture.",
            "Under the live profile this same switch reaches Grounding with Google Search "
            "against Vertex.",
        ),
        look_at="the search box, before the query runs",
    )
    page.locator(loc.RESEARCH).click()
    page.locator(loc.RESEARCH_FENCE).wait_for(timeout=60_000)

    found = _ok(
        stage.get(f"/v1/analyses/{stage.analysis_id}/research?query={SECTOR_QUERY}"),
        "search the public web",
    ).json()
    if found["found_nothing"] or not found["evidence"]:
        raise ActFailed("the search returned nothing, so the fence demonstrates nothing")
    for item in found["evidence"]:
        if item["provenance"] != "web_grounded":
            raise ActFailed(f"a web result is not marked as web-grounded: {item}")
        # The fence, at the wire: no number on it for any engine to reach for.
        numeric = [key for key, value in item.items() if isinstance(value, (int, float))]
        if numeric:
            raise ActFailed(f"a web result carries a figure an engine could read: {numeric}")
    if not found["search_suggestions"]:
        raise ActFailed(
            "the search suggestions were dropped; Google requires them rendered verbatim "
            "beside grounded results, so losing them is a licence breach that looks tidy"
        )

    # And now the half that matters: none of it reached the memo.
    memo = stage.state.get("group_memo") or stage.memo
    forbidden = {"market_context", "web_evidence", "research", "web_citations"}
    if forbidden & set(memo):
        raise ActFailed(f"the memo has a field web context could occupy: {forbidden & set(memo)}")
    cited = {c["source_id"] for c in memo["citations"]}
    uploaded = {d["id"] for d in memo["manifest"]["documents"]}
    if not cited <= uploaded:
        raise ActFailed(f"the memo cites something that is not an uploaded document: {cited}")
    stage.cue(
        Point(
            f"{len(found['evidence'])} results, with the suggestion chips Google requires "
            "beside them.",
            "The licence requires them rendered verbatim; dropping them is a breach that "
            "looks tidy.",
        ),
        Point(
            "Not one of them is in the memo, the pack or the review payload.",
            "There is no field on a memo a search result could occupy, and nothing here "
            "holds a number a ratio could read.",
        ),
        Point(
            "To use one of these facts, the analyst types the figure into the spread and "
            "cites the URL.",
            "Which makes it theirs, under their name, like every other figure.",
        ),
        look_at="the results, then the line saying none of it is in the memo",
    )


# --------------------------------------------------------------------------- #
# 15. The committee pack
# --------------------------------------------------------------------------- #
def act_committee_pack(stage: Stage) -> None:
    page = stage.page
    analysis_id = stage.analysis_id
    offered = page.eval_on_selector_all(
        f"{loc.EXPORT_FORMAT} option", "options => options.map((option) => option.value)"
    )
    for wanted in ("docx", "html", "json"):
        if wanted not in offered:
            raise ActFailed(f"this deployment offers {offered}, which a committee cannot use")
    if "pdf" in offered:
        # Advertised rather than assumed: the console offers what the service says it can
        # produce, so there is no button here that fails when it is pressed.
        raise ActFailed("the console offers a format this deployment cannot produce")

    docx = _download(stage, "docx")
    if docx[:2] != b"PK":
        raise ActFailed("the exported .docx is not a document Word can open")

    pack = _download(stage, "html").decode("utf-8")
    # The regression this act exists for: a pack that dropped the policy breaches and the
    # failed reconciliations while still looking complete.
    for required in ("LEV-01", "Decision support, not a credit decision"):
        if required not in pack:
            raise ActFailed(f"the committee pack does not carry {required!r}")
    if "certificate" not in pack.lower():
        raise ActFailed("the committee pack does not carry the reconciliation findings")

    # The memo as the service stores it, which is the only form a LATER analysis can read
    # back when it has to say what changed since this one.
    wire = json.loads(_download(stage, "json").decode("utf-8"))
    if not any(e["rule_id"] == "LEV-01" for e in wire["policy_exceptions"]):
        raise ActFailed("the memo's own form dropped the exception the pack shows")

    refused = stage.post(f"/v1/analyses/{analysis_id}/export?fmt=pdf")
    if refused.ok:
        raise ActFailed("a format this deployment cannot produce was not refused")
    if "cannot export" not in refused.text():
        raise ActFailed("the refusal does not say what it can produce instead")

    # Put it on screen: the pack is the deliverable, and a demo that only asserts bytes has
    # not shown anybody the thing they asked for. The console page is kept, because the acts
    # after this one still drive it.
    pack_page = page.context.new_page()
    pack_page.set_content(pack)
    stage.state["console_page"] = page
    stage.page = pack_page
    stage.cue(
        Point(
            "This is what leaves the building: the same pack, as a Word document.",
            "Downloaded from the console, which is how a committee actually gets it.",
        ),
        Point(
            "Standing sentence first, then the policy exceptions and the failed reconciliations.",
            "A pack once dropped the last two while still looking complete. That is the "
            "regression this act exists for.",
        ),
        Point(
            "PDF, which this deployment cannot produce, is not even offered.",
            "And is refused rather than quietly substituted if something asks for it anyway.",
        ),
        look_at="the standing sentence, then LEV-01 and the certificate reconciliation in the pack",
    )


# --------------------------------------------------------------------------- #
# 16. Is this even bankable
# --------------------------------------------------------------------------- #
def act_pre_screen_knockout(stage: Stage) -> None:
    memo = _ok(
        stage.post(
            f"/v1/analyses/{stage.analysis_id}/build",
            {"request": _request_body(kind="pre_screen", tenor=KNOCKOUT_TENOR)},
        ),
        "run a pre-screen",
    ).json()
    rules = {e["rule_id"] for e in memo["policy_exceptions"]}
    if "TEN-01" not in rules:
        raise ActFailed(f"a {KNOCKOUT_TENOR}-month tenor tripped no knockout: {rules}")
    if memo.get("rating") is not None:
        raise ActFailed(
            "a pre-screen proposed a grade; grading a borrower off a thin package puts a "
            "number in front of a committee the package cannot support"
        )


# --------------------------------------------------------------------------- #
# 17. What it will not do
# --------------------------------------------------------------------------- #
def act_refusals(stage: Stage) -> None:
    # A page of its own, and act 15 left the rendered pack on screen in another. The deal's
    # console page is kept aside rather than reloaded: it holds the memo, the revision chain
    # and the delete that act 18 presses, and a reload here would lose all three.
    deal = _console_page(stage)
    refusals = deal.context.new_page()
    stage.state["console_page"] = deal
    stage.page = refusals
    page = refusals
    page.goto(stage.ui_base, wait_until="load")
    page.locator(loc.BORROWER).fill(fx.BORROWER_NAME)
    _build(stage, timeout=30_000)
    refusal = page.locator(loc.ERROR)
    if refusal.count() != 1 or "Add the borrower's documents" not in refusal.inner_text():
        raise ActFailed("building with an empty credit file did not refuse and say what to add")
    stage.cue(
        Point("Build with an empty credit file: it refuses, and says what to add."),
        Point(
            "It does not produce a thinner memo off a name alone.",
            "That is the failure mode worth naming, because a thin memo looks like a memo.",
        ),
        look_at="the inline refusal naming what is missing",
    )

    # And a request that tries to talk to the model rather than about the borrower.
    page.locator(loc.BORROWER).fill(f"{fx.BORROWER_NAME} {fx.INJECTION_PHRASE}")
    _upload_files(stage)
    _fill_request(stage)
    stage.cue(
        Point(
            "Now an instruction to the model, hidden in the borrower's name.",
            "Where a real one would arrive: inside a document somebody sent the bank.",
        ),
        Point("The request is otherwise complete and perfectly ordinary."),
        look_at=f"the borrower field, ending '{fx.INJECTION_PHRASE}'",
    )
    _build(stage)
    if page.locator(loc.GUARDRAIL_BLOCKED).count() != 1:
        raise ActFailed("an injection attempt produced a memo instead of a refusal")
    stage.cue(
        Point("Blocked by the guardrail, before any retrieval and before any drafting."),
        Point(
            "Screened on the redacted case summary.",
            "The same thing the model would have been shown. Nothing reached the model at all.",
        ),
        look_at="the amber guardrail notice",
    )


# --------------------------------------------------------------------------- #
# 18. The evidence goes away
# --------------------------------------------------------------------------- #
def act_evidence_goes_away(stage: Stage) -> None:
    analysis_id = stage.analysis_id
    stranger = stage.get(f"/v1/analyses/{analysis_id}", persona=OTHER_TENANT)
    if stranger.ok:
        raise ActFailed("another bank's user could read this analysis")
    if stranger.status != 404:
        raise ActFailed(
            f"a forbidden analysis answered {stranger.status}; absent and forbidden must be "
            "the same answer, or the status confirms the analysis exists"
        )
    if not stage.get(f"/v1/analyses/{analysis_id}", persona=AUDITOR).ok:
        raise ActFailed("the bank's own auditor could not read the analysis")
    stage.cue(
        Point(
            f"Another bank's user asks for this analysis and gets {stranger.status}.",
            "The same answer they would get for one that does not exist. A 403 would have "
            "confirmed it exists, which is itself a disclosure.",
        ),
        Point("The bank's own auditor reads it fine."),
        Point("Now the analyst deletes the credit file."),
        look_at="the two answers: 404 to the stranger, 200 to the auditor",
    )

    # Back to the deal's console, where the analyst presses it themselves: two presses, because
    # this is the one irreversible thing in the product.
    page = _console_page(stage)
    page.locator(loc.DELETE_ANALYSIS).click()
    page.locator(loc.CONFIRM_DELETE).click()
    page.locator(loc.DELETED).wait_for(timeout=30_000)
    if stage.get(f"/v1/analyses/{analysis_id}").status != 404:
        raise ActFailed("the analysis survived its own deletion")
    gone = stage.post(f"/v1/analyses/{analysis_id}/export?fmt=html")
    if gone.ok:
        raise ActFailed("the memo outlived the evidence it was built from")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _spread_row(stage: Stage, code: str) -> Any:
    """The review row proposing ``code`` for the demo's period, named by what it is."""
    candidate = stage.state.get("candidate")
    if not candidate:
        raise ActFailed("no candidate spread has been extracted")
    row = stage.page.locator(loc.spread_row(code, fx.PERIOD))
    if row.count() != 1:
        codes = [item["code"] for item in candidate["items"]]
        raise ActFailed(f"the extractor proposed no {code!r} row to act on: {codes}")
    return row


ACTS: tuple[Act, ...] = (
    Act(
        "Who is asking",
        (
            Point(
                "A credit analyst signs in.",
                "Four seeded people across two different banks. The demo has more than one "
                "tenant in it from the first screen.",
            ),
            Point(
                "Their verified identity becomes the audit actor on the memo.",
                "Never anything the browser claims about itself. Confirmations, comments "
                "and resolutions are all attributed to it.",
            ),
            Point("Identity also decides which borrowers this person may retrieve evidence for."),
        ),
        act_identity,
        point_at="the persona picker: four seeded people, in two different banks",
    ),
    Act(
        "The credit file",
        (
            Point(
                "The analyst brings the deal's documents.",
                "Audited statements, their own spread, and the quarterly covenant certificate.",
            ),
            Point(
                "Each is labelled with what it is, and the date it speaks to.",
                "The service cannot tell last year's management accounts from yesterday's, "
                "and will not guess.",
            ),
            Point(
                "The manifest is the receipt for what the bank now holds.",
                "Every file by name, its digest and page count, and the date the evidence "
                "is deleted.",
            ),
        ),
        act_credit_file,
        point_at="the manifest: every file, its digest and page count, and the date the "
        "evidence is deleted",
    ),
    Act(
        "Figures nobody has vouched for",
        (
            Point("The extractor reads the figures off those documents."),
            Point(
                "Every row shows the quote it came from, and links to the page.",
                "Anyone in the room can check a figure against the filing without leaving "
                "the screen.",
            ),
            Point(
                "None of it computes anything yet. This is a proposal.",
                "The product's own types refuse to calculate a ratio from an extracted figure.",
            ),
        ),
        act_extraction_is_a_proposal,
        point_at="the amber panel titled 'Not yet anybody's figures', and a quote opened "
        "beside its source page",
    ),
    Act(
        "Becoming the person who stands behind them",
        (
            Point("The analyst keeps most rows, rejects one, and adjusts capex with a reason."),
            Point(
                "Confirming carries their name.",
                "From here the engines compute from figures a named person accepted.",
            ),
            Point(
                "Both the original and the adjustment are kept.",
                "The bank's figure sits beside the borrower's, never over it.",
            ),
        ),
        act_confirm_the_spread,
        point_at="the green 'Confirmed by' line naming the analyst",
    ),
    Act(
        "The memo",
        (
            Point(
                "Build.",
                "The pipeline redacts, screens, and retrieves the borrower's own evidence "
                "before anything is written.",
            ),
            Point(
                "The ratios are computed BEFORE drafting.",
                "The narrative is then written around numbers the bank calculated, not the "
                "other way round.",
            ),
            Point("Every section carries citations."),
            Point(
                "The memo is marked for human review whatever it says.",
                "Decision support, not a credit decision. No configuration removes the banner.",
            ),
        ),
        act_build_the_memo,
        point_at="the amber human-review banner, then the sections a committee reads",
    ),
    Act(
        "Same filing, two answers",
        (
            Point("Flowserve's own filing: net leverage 1.64x, in compliance with every covenant."),
            Point("The bank's engine: 3.18x, and the covenant BREACHES."),
            Point(
                "Both are right.",
                "The borrower nets its cash and adds back its realignment charges, and this "
                "bank does neither. Every one of those numbers is in the 10-K.",
            ),
            Point("The model drafts prose. It never decides compliance."),
            Point(
                "Current ratio 2.03x against a 2.00x floor: AT RISK, not green.",
                "Thin headroom is its own answer, distinct from compliant. It falls out of "
                "the filed figures rather than being arranged.",
            ),
        ),
        act_the_breach_stands,
        point_at="the covenant table: the status pills, and the computed value beside the "
        "one the evidence reported",
    ),
    Act(
        "It refuses to compute what it cannot",
        (
            Point("Four of the nine catalogue ratios could not be computed."),
            Point(
                "Each one says which line was missing.",
                "A quick ratio quietly omitted reads as though nobody thought liquidity "
                "worth stating. An estimated one is worse.",
            ),
        ),
        act_uncomputable_ratios,
        point_at="the ratio rows with no number, each naming the line it needed",
    ),
    Act(
        "The bank's own policy",
        (
            Point(
                "The limits are the bank's own, from an uploaded versioned pack.",
                "The memo names the version it was measured against.",
            ),
            Point(
                "The exception is a sentence a committee can act on.",
                "Your policy requires 3.00x, this measures 3.18x, and the Regional Credit "
                "Committee can waive it.",
            ),
            Point(
                "The scorecard proposes a grade and shows every driver.",
                "Proposed, never assigned.",
            ),
        ),
        act_policy_and_rating,
        point_at="rule LEV-01 with its waiver authority, and the grade's drivers",
    ),
    Act(
        "The reconciliations",
        (
            Point(
                "The borrower's filing says 1.64x and every covenant met. The engine says 3.18x."
            ),
            Point("The memo reports the disagreement rather than picking a winner quietly."),
            Point(
                "The cause is not an error in either figure.",
                "Cash netting and an EBITDA add-back. That is the conversation the credit "
                "officer needs to have, surfaced instead of buried.",
            ),
        ),
        act_reconciliation,
        point_at="the reconciliation finding naming both figures",
    ),
    Act(
        "The group",
        (
            Point("Lending is to a group, not a company."),
            Point(
                "Two real subsidiaries, declared from Exhibit 21 of the same filing.",
                "One wholly owned in Singapore, one 40% held in Saudi Arabia.",
            ),
            Point(
                "Neither files separately, so the bank has statements for neither.",
                "Which is the ordinary case rather than the awkward one.",
            ),
            Point(
                "The consolidated cash flow NAMES both entities it could not include.",
                "Rather than totalling as though they contribute nothing.",
            ),
        ),
        act_the_group,
        point_at="the 'Incomplete' notice naming both subsidiaries",
    ),
    Act(
        "How far it can fall",
        (
            Point(
                "Every scenario reports the break-even, not just the shocked value.",
                "A committee cannot judge whether a 15% earnings decline is the right test "
                "for this sector. They can judge 'it breaks at 10%'.",
            ),
        ),
        act_stress,
        point_at="the break-even column",
    ),
    Act(
        "The checker",
        (
            Point("The analyst rewrites the summary to lead with the breach."),
            Point("The approver objects, against the exact text they read."),
            Point(
                "The analyst edits again. The comment goes stale, not closed.",
                "A comment that lapsed when the text moved underneath it was lost, not answered.",
            ),
            Point("The approver resolves it, by name, and the revision chain verifies."),
        ),
        act_the_checker,
        point_at="the revision chain, and the comment that went stale instead of away",
    ),
    Act(
        "Figures are not editable prose",
        (
            Point("The prose is editable. The ratios are not."),
            Point("No number reaches a committee that no formula produced."),
        ),
        act_figures_are_not_prose,
        point_at="the refusal, which names the sections that ARE editable",
    ),
    Act(
        "Public context, for the analyst only",
        (
            Point(
                "The analyst searches the open web for sector context, from inside the console.",
                "The one place this product reaches the public web, so the question and "
                "its answer are at least logged.",
            ),
            Point(
                "None of it enters the memo, the pack or the review payload.",
                "Google's licence permits grounded results to be shown only to the person "
                "who ran the query, and a memo is read by a checker, a committee and later "
                "an examiner.",
            ),
            Point(
                "The memo has no field one could occupy.",
                "And nothing here carries a figure an engine could read.",
            ),
        ),
        act_public_context,
        point_at="the results with their suggestion chips, then the line saying none of it "
        "is in the memo",
    ),
    Act(
        "The committee pack",
        (
            Point(
                "The pack leaves the application as a Word document a committee circulates.",
                "The standing sentence first, then the policy exceptions and the failed "
                "reconciliations.",
            ),
            Point(
                "It once dropped the last two while still looking complete.",
                "Which is why the pack's contents are asserted here rather than eyeballed.",
            ),
            Point("A format this deployment cannot produce is refused, not quietly substituted."),
        ),
        act_committee_pack,
        point_at="the rendered pack: the standing sentence, then LEV-01 and the reconciliation",
    ),
    Act(
        "Is this even bankable",
        (
            Point("A pre-screen answers in a minute, off a thin package."),
            Point(
                "Ninety-six months trips the one knockout no appetite overrides.",
                "The policy pack reserves knockouts for exactly that: rules no waiver "
                "authority can reach.",
            ),
            Point(
                "No grade is proposed.",
                "The package cannot support one, and a grade off a thin package puts a "
                "number in front of a committee that the evidence does not carry.",
            ),
        ),
        act_pre_screen_knockout,
        point_at="the TEN-01 knockout, and the absent rating",
    ),
    Act(
        "What it will not do",
        (
            Point("Build with an empty credit file: it refuses, and says what to add."),
            Point(
                "Hide an instruction to the model in the borrower's name: the guardrail blocks it.",
                "Before any retrieval and before any drafting.",
            ),
            Point(
                "Neither produces a thinner memo.",
                "That is the failure mode worth naming, because a thin memo looks like a memo.",
            ),
        ),
        act_refusals,
        point_at="the inline refusal, then the amber guardrail notice",
    ),
    Act(
        "The evidence goes away",
        (
            Point(
                "Another bank's user gets the same answer for an analysis that exists as "
                "for one that does not.",
                "A 403 would confirm it exists, which is itself a disclosure.",
            ),
            Point("The bank's own auditor can read it."),
            Point(
                "The analyst deletes it, and the memo dies with the evidence.",
                "The retention promise kept immediately, rather than in fifteen days.",
            ),
        ),
        act_evidence_goes_away,
        point_at="the 404 that does not confirm the analysis exists",
    ),
)


def act_titles() -> list[str]:
    return [act.title for act in ACTS]


if __name__ == "__main__":  # pragma: no cover - a convenience for the docs
    print(json.dumps(act_titles(), indent=2))
