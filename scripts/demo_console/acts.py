"""The demo, as an ordered list of acts. One deal, walked through the real product.

Each act is a business beat a credit audience recognises, and each one ASSERTS what it
claims on screen. That pairing is the point of the module: the walkthrough a presenter
shows and the suite CI runs are the same fifteen functions, so a capability that quietly
stops being reachable breaks the build instead of surprising somebody in front of a room.

Every expectation is recomputed from the running application — covenant status from the
threshold and the operator, ratios from the confirmed spread, the peer percentile from the
peer table. Nothing here matches a sentence the product happens to render today.

Three acts have no console UI and are driven over the API in the same run: the committee
pack, the reviewer's comment thread, and deleting the borrower's evidence. They are here
because a credit audience asks for exactly those three; that they are unreachable from the
console is a product gap, recorded in docs/demo-use-cases.md, not a reason to hide them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import fixtures as fx
from . import locators as loc

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
    beat: Callable[[str, str], None] | None = None

    # -- The presenter --------------------------------------------------- #
    def cue(self, say: str, look_at: str = "") -> None:
        """Hold here: say ``say``, point at ``look_at``, and wait for the presenter.

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
            self.beat(say, look_at)

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
    narration: str
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
    stage.page.get_by_label(loc.DOCUMENTS_INPUT, exact=True).set_input_files(
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
        stage.page.get_by_label(f"Document kind for {filename}", exact=True).select_option(
            label=label
        )
        stage.page.get_by_label(f"Date {filename} speaks to", exact=True).fill(fx.PERIOD_ENDED)


def _fill_request(stage: Stage, kind: str = "New facility", tenor: int = FACILITY_TENOR) -> None:
    page = stage.page
    loc.choose(page, "Memo kind", kind)
    loc.choose(page, "Loan type", "C&I term / working capital")
    loc.choose(page, "Facility type", "term loan")
    page.get_by_label("Amount (USD, millions)", exact=True).fill(str(FACILITY_AMOUNT))
    page.get_by_label("Tenor (months)", exact=True).fill(str(tenor))
    page.get_by_label("Primary repayment source", exact=True).fill(REPAYMENT_SOURCE)
    page.get_by_label("Purpose").fill(FACILITY_PURPOSE)
    page.get_by_label("Security", exact=True).fill(FACILITY_SECURITY)


def _build(stage: Stage, timeout: int = 60_000) -> None:
    """Press Build and wait for either the memo or a refusal to appear."""
    loc.button(stage.page, loc.BUILD).click()
    stage.page.wait_for_function(
        "() => !document.body.innerText.includes('Building...')", timeout=timeout
    )


def _ok(response: Any, what: str) -> Any:
    if not response.ok:
        raise ActFailed(f"could not {what}: HTTP {response.status} {response.text()[:300]}")
    return response


def _text(stage: Stage) -> str:
    return str(stage.page.inner_text("body"))


# --------------------------------------------------------------------------- #
# 1. Who is asking
# --------------------------------------------------------------------------- #
def act_identity(stage: Stage) -> None:
    page = stage.page
    page.goto(stage.ui_base, wait_until="load")
    # The picker is filled by a fetch the page makes after it hydrates, so waiting for the
    # OPTIONS rather than for the control is the difference between reading the personas
    # and reading an empty select that is about to be filled.
    # Not exact: the label wraps its own hint text, so an exact match finds nothing. And
    # the options arrive from a fetch the page makes after it hydrates, so waiting for the
    # OPTIONS rather than the control is the difference between reading the personas and
    # reading an empty select that is about to be filled.
    picker = page.get_by_label(loc.PERSONA)
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
    page.get_by_label(loc.BORROWER, exact=True).fill(fx.BORROWER_NAME)
    page.get_by_label(loc.SECTOR, exact=True).fill(fx.SECTOR)
    page.get_by_label(loc.JURISDICTION, exact=True).fill(fx.JURISDICTION)
    _upload_files(stage)
    stage.cue(
        "Three documents, and everything in them is checkable: an extract of Flowserve's "
        "FY2025 Form 10-K, the analyst's own spread of it, and the covenant position. Each "
        "is labelled with what it is and the date it speaks to, because the service cannot "
        "tell last year's management accounts from yesterday's and will not guess. The "
        "accession number is on every page, so anyone in the room can open the filing.",
        "the three rows, each with its own kind and as-of date, before anything is read",
    )

    # Opening the analysis is what puts the evidence in custody, and the console does it
    # on the first step that needs it. Extract is that step.
    loc.button(page, loc.EXTRACT).click()
    page.wait_for_selector("text=Not yet anybody's figures", timeout=60_000)

    # The console does not surface the analysis id as data, so recover it from the
    # manifest the page rendered. That is not a workaround: the manifest naming the
    # analysis on screen IS the reader-facing claim this act is about.
    body = _text(stage)
    if "an-" not in body:
        raise ActFailed("the manifest did not name the analysis on screen")
    analysis_id = next(word for word in body.split() if word.startswith("an-"))
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
    if "available until" not in body:
        raise ActFailed("the retention note is not on screen")
    stage.state["manifest"] = manifest
    stage.cue(
        "The evidence is now in custody, and the manifest is the receipt: every file by "
        "name, its SHA-256 digest, its page count, and the date it is deleted. Nothing "
        "downstream can cite a document that is not on this list.",
        f"the manifest, and the retention line: {manifest['retention_note']}",
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
    page.get_by_role("button", name="Show the quote").first.click()
    if "Open" not in _text(stage):
        raise ActFailed("the quote does not link back to the document it came from")
    stage.state["candidate"] = candidate
    stage.cue(
        f"The extractor read {len(candidate['items'])} figures, and every row shows the "
        "sentence it read them from with a link to the page. Nothing has been computed. "
        "The product's own types refuse to put an extracted figure into a ratio — the only "
        "way out of this panel is a person confirming it.",
        "the amber panel, and the quote opened beside the number it explains",
    )


# --------------------------------------------------------------------------- #
# 4. Becoming the person who stands behind them
# --------------------------------------------------------------------------- #
def act_confirm_the_spread(stage: Stage) -> None:
    page = stage.page
    page.get_by_role("radio", name="reject").nth(_row_index(stage, fx.REJECTED_CODE)).check()
    adjust_row = _row_index(stage, fx.ADJUSTED_CODE)
    page.get_by_role("radio", name="adjust").nth(adjust_row).check()
    line = loc.SPREAD_LINE_LABELS[fx.ADJUSTED_CODE]
    page.get_by_label(f"Adjusted value for {line}, {fx.PERIOD}", exact=True).fill(
        str(fx.ADJUSTED_TO)
    )
    page.get_by_label(f"Reason for adjusting {line}, {fx.PERIOD}", exact=True).fill(
        fx.ADJUSTMENT_REASON
    )
    stage.cue(
        f"Two decisions, and both are the bank's credit policy rather than a correction. "
        f"The analyst REJECTS the cash line of USD {fx.REJECTED_VALUE:,.1f}m, because this "
        f"bank measures leverage on gross debt. And it ADJUSTS EBITDA from the borrower's "
        f"USD {fx.ADJUSTED_FROM:,.1f}m to USD {fx.ADJUSTED_TO:,.1f}m, declining the "
        f"add-back of USD {fx.REALIGNMENT_CHARGES:,.1f}m of realignment charges that have "
        "recurred three years running. Both numbers are kept: the adjustment sits beside "
        "the original, never over it.",
        "the struck-through cash row, and EBITDA with the reason beside it, before "
        "anything is confirmed",
    )

    loc.button(page, loc.CONFIRM).click()
    page.wait_for_selector("text=Confirmed by", timeout=60_000)

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
    stage.state["spread"] = spread
    stage.cue(
        f"Confirmed by {spread['confirmed_by']}. Note where that name came from: the "
        "verified identity behind the session, not a field this browser filled in. From "
        "here every engine computes from figures a named person accepted.",
        "the green 'Confirmed by' line",
    )


# --------------------------------------------------------------------------- #
# 5. The memo
# --------------------------------------------------------------------------- #
def act_build_the_memo(stage: Stage) -> None:
    _fill_request(stage)
    stage.cue(
        f"The ask, stated before the memo is written: a new USD {FACILITY_AMOUNT:.0f} "
        f"million term facility over {FACILITY_TENOR} months, its purpose, its repayment "
        "source and its security. Without it the memo would comment on a borrower rather "
        "than assess a credit — those are different documents.",
        "the completed ask, before Build is pressed",
    )
    _build(stage)

    body = _text(stage)
    if loc.REVIEW_BANNER not in body:
        raise ActFailed("the maker-checker banner is not on the memo")
    for heading in loc.ALWAYS_PRESENT:
        if loc.section(stage.page, heading).count() != 1:
            raise ActFailed(f"the memo does not show the {heading!r} section")

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
        "The pipeline redacted the case, screened it, retrieved from the borrower's own "
        "evidence, computed the ratios BEFORE drafting a word, and then wrote prose around "
        f"numbers the bank calculated. {len(memo['citations'])} citations, every one of "
        "them a document in this credit file. And the banner at the top is unconditional: "
        "no configuration produces a memo without it.",
        "the amber human-review banner, then scroll the sections a committee reads",
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

    # Thin headroom is its own answer, distinct from compliant — and here it falls out of
    # the filed figures rather than being arranged: 2.03x against a 2.00x floor.
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

    body = _text(stage)
    if "breach" not in body.lower():
        raise ActFailed("the breach is not visible on screen")


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

    body = _text(stage)
    for heading in (loc.SECTION_POLICY, loc.SECTION_RATING):
        if loc.section(stage.page, heading).count() != 1:
            raise ActFailed(f"the {heading!r} section is not on screen")
    if breach["rule_id"] not in body:
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
    if loc.section(stage.page, loc.SECTION_TIE_OUT).count() != 1:
        raise ActFailed("the reconciliation findings are not on screen")


# --------------------------------------------------------------------------- #
# 10. The group, and who it could not include
# --------------------------------------------------------------------------- #
def act_the_group(stage: Stage) -> None:
    """Two real subsidiaries, neither of which the bank holds statements for.

    Both come from Exhibit 21.1 of the same 10-K. Neither files separately, so a lender to
    the parent genuinely cannot consolidate them — which is the point. The memo names them
    as entities it could not include rather than totalling without them, because "we did
    not look" is a weaker claim than a total that quietly omits a 100%-owned subsidiary and
    a 40%-held affiliate.

    No intercompany elimination is entered, and that is deliberate. Flowserve discloses a
    real one -- USD 10.6m of intersegment sales -- but the borrower's spread is already
    consolidated and net of it, so recording it again would deduct it twice. Inventing a
    different one to exercise the feature is exactly the fabrication this demo removed.
    """
    page = stage.page
    page.get_by_label("Entity", exact=True).fill(fx.SUBSIDIARY_NAME)
    loc.choose(page, "Role", "Subsidiary")
    loc.button(page, loc.ADD_TO_GROUP).click()

    page.get_by_label("Entity", exact=True).fill(fx.AFFILIATE_NAME)
    loc.choose(page, "Role", "Affiliate")
    loc.button(page, loc.ADD_TO_GROUP).click()
    stage.cue(
        f"Two real subsidiaries out of Exhibit 21 of the same filing: {fx.SUBSIDIARY_NAME} "
        f"in {fx.SUBSIDIARY_JURISDICTION}, wholly owned, and {fx.AFFILIATE_NAME} in "
        f"{fx.AFFILIATE_JURISDICTION}, 40% held. Both rows are blank, because a lender to "
        "the parent holds no standalone statements for either. Watch what the "
        "consolidation does with an entity it has no figures for.",
        "the two entity rows, entirely blank, before the rebuild",
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

    body = _text(stage)
    if fx.SUBSIDIARY_NAME not in body:
        raise ActFailed("the entity the consolidation could not include is not on screen")
    stage.cue(
        "The cash flow does not claim to be complete, and it names exactly who is missing. "
        "'We hold no accounts for the Singapore subsidiary' is a weaker claim than a total, "
        "and a truer one: the total that quietly omits a wholly-owned subsidiary reads as "
        "though it contributes nothing. Note what is NOT here — no invented intercompany "
        "elimination. Flowserve discloses a real one, USD 10.6m between its two divisions, "
        "and it is already inside the consolidated revenue, so recording it again would "
        "deduct it twice.",
        "the incomplete notice naming both entities, and the borrower's own contribution",
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
    analysis_id = stage.analysis_id
    amended = _ok(
        stage.patch(
            f"/v1/analyses/{analysis_id}/memo",
            {
                "sections": {
                    "summary": (
                        "Revised by the analyst: leverage of 3.18x breaches the 3.00x covenant "
                        "and the exception needs Regional Credit Committee waiver."
                    )
                },
                "reason": "The drafted summary understated the breach.",
                "note": "Rewritten to lead with the covenant position.",
            },
        ),
        "amend the memo",
    ).json()
    if amended["revision"] < 2:
        raise ActFailed("an edit did not open a new revision")
    stage.cue(
        f"The analyst rewrites the summary to lead with the breach. That is revision "
        f"{amended['revision']}: the draft nobody touched is still there, and so is the "
        "reason this one was written.",
        f"revision {amended['revision']}, with its reason and note",
    )

    comment = _ok(
        stage.post(
            f"/v1/analyses/{analysis_id}/comments",
            {"section": "summary", "body": "Say who is being asked to waive this."},
            persona=APPROVER,
        ),
        "leave a comment",
    ).json()
    if comment["revision"] != amended["revision"]:
        raise ActFailed("the comment is not anchored to the text its author read")
    if "@" not in comment["author"]:
        raise ActFailed("an unattributed comment")
    stage.cue(
        f"The approver objects, and the comment is anchored to revision {comment['revision']} "
        "— the exact text they read. Not to the section, and not to the memo: to the "
        "words that were in front of them.",
        f"the comment by {comment['author']}, anchored to revision {comment['revision']}",
    )

    _ok(
        stage.patch(
            f"/v1/analyses/{analysis_id}/memo",
            {
                "sections": {
                    "summary": (
                        "Revised again: the Regional Credit Committee is the waiver authority "
                        "for the leverage exception."
                    )
                },
                "reason": "Answering the checker.",
                "note": "Named the waiver authority.",
            },
        ),
        "amend again",
    )
    listing = _ok(stage.get(f"/v1/analyses/{analysis_id}/comments"), "list comments").json()
    flagged = [c for c in listing["comments"] if c["stale"]]
    if not flagged:
        raise ActFailed(
            "editing the text underneath a comment did not flag it; a comment that lapsed "
            "because the text moved was lost, not answered"
        )
    if listing["open_count"] != 1:
        raise ActFailed("the edit closed the comment instead of flagging it")
    stage.cue(
        "The analyst edits again — and the comment does not close. It is flagged stale, "
        "and it stays open. A comment that lapsed because the text moved underneath it was "
        "lost, not answered, and the difference matters to whoever signs this.",
        f"the comment marked stale, with {listing['open_count']} still open",
    )

    resolved = _ok(
        stage.post(
            f"/v1/analyses/{analysis_id}/comments/{comment['id']}/resolve",
            {"resolution": "Named the Regional Credit Committee in the summary."},
            persona=APPROVER,
        ),
        "resolve the comment",
    ).json()
    if "@" not in (resolved.get("resolved_by") or ""):
        raise ActFailed("the resolution does not name the person who made it")

    revisions = _ok(stage.get(f"/v1/analyses/{analysis_id}/revisions"), "read revisions").json()
    if not revisions["chain_intact"]:
        raise ActFailed(f"the revision chain is broken: {revisions['chain_detail']}")
    if len(revisions["revisions"]) < 3:
        raise ActFailed("the chain does not start at the draft nobody touched")
    stage.state["revisions"] = revisions
    stage.cue(
        f"Resolved by {resolved.get('resolved_by')} — a person, named, not the software "
        f"deciding it had been dealt with. And the chain of {len(revisions['revisions'])} "
        "revisions verifies: every version from the machine's draft to this one, each "
        "linked to the last, none of them quietly rewritten.",
        "the resolution and the intact revision chain",
    )


# --------------------------------------------------------------------------- #
# 13. Figures are not editable prose
# --------------------------------------------------------------------------- #
def act_figures_are_not_prose(stage: Stage) -> None:
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
    """The one place the product reaches the open web — and the one it may not reach.

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
    page.get_by_label("Search the public web", exact=True).fill(SECTOR_QUERY)
    stage.cue(
        "An analyst wants sector context, and would otherwise open a browser for it. This "
        "runs the search from inside the console so the question and its answer are at "
        "least logged. Offline every row is labelled a fixture; under the live profile "
        "this is Grounding with Google Search against Vertex.",
        "the search box, before the query runs",
    )
    loc.button(page, "Search public context").click()
    page.wait_for_selector("text=None of the above is in the memo", timeout=60_000)

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
        f"{len(found['evidence'])} results, with the suggestion chips Google requires "
        "rendered beside them. And not one of them is in the memo: there is no field on a "
        "memo a search result could occupy, the export carries none, and nothing here "
        "holds a number a ratio could read. To use one of these facts, the analyst types "
        "the figure into the spread and cites the URL — which makes it theirs.",
        "the results, then the line saying none of it is in the memo",
    )


# --------------------------------------------------------------------------- #
# 15. The committee pack
# --------------------------------------------------------------------------- #
def act_committee_pack(stage: Stage) -> None:
    analysis_id = stage.analysis_id
    formats = _ok(
        stage.get(f"/v1/analyses/{analysis_id}/export/formats"), "list export formats"
    ).json()["formats"]
    if "docx" not in formats or "html" not in formats:
        raise ActFailed(f"this deployment produces {formats}, which a committee cannot use")

    docx = _ok(stage.post(f"/v1/analyses/{analysis_id}/export?fmt=docx"), "export a docx")
    if docx.body()[:2] != b"PK":
        raise ActFailed("the exported .docx is not a document Word can open")

    html = _ok(stage.post(f"/v1/analyses/{analysis_id}/export?fmt=html"), "export the pack")
    pack = html.body().decode("utf-8")
    # The regression this act exists for: a pack that dropped the policy breaches and the
    # failed reconciliations while still looking complete.
    for required in ("LEV-01", "Decision support, not a credit decision"):
        if required not in pack:
            raise ActFailed(f"the committee pack does not carry {required!r}")
    if "certificate" not in pack.lower():
        raise ActFailed("the committee pack does not carry the reconciliation findings")

    refused = stage.post(f"/v1/analyses/{analysis_id}/export?fmt=pdf")
    if refused.ok:
        raise ActFailed("a format this deployment cannot produce was not refused")
    if "cannot export" not in refused.text():
        raise ActFailed("the refusal does not say what it can produce instead")

    # Put it on screen: the pack is the deliverable, and a demo that only asserts bytes
    # has not shown anybody the thing they asked for. It replaces the stage's page for the
    # rest of the run so the act's own screenshot is OF THE PACK — a frame of the console
    # behind it would be evidence of the wrong thing.
    pack_page = stage.page.context.new_page()
    pack_page.set_content(pack)
    stage.state["console_page"] = stage.page
    stage.page = pack_page
    stage.cue(
        "This is what leaves the building — the same pack as a Word document, which is how "
        "a committee actually circulates it. The standing sentence is first. Then the "
        "policy exceptions and the failed reconciliations, which a pack once dropped while "
        "still looking complete. And PDF, which this deployment cannot produce, is refused "
        "rather than quietly substituted with something else.",
        "the standing sentence, then LEV-01 and the certificate reconciliation in the pack",
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
    # Back to the console: act 14 left the committee pack on screen.
    console = stage.state.pop("console_page", None)
    if console is not None:
        stage.page.close()
        stage.page = console
    page = stage.page
    page.goto(stage.ui_base, wait_until="load")
    page.get_by_label(loc.BORROWER, exact=True).fill(fx.BORROWER_NAME)
    loc.button(page, loc.BUILD).click()
    page.wait_for_selector("text=Add the borrower's documents", timeout=30_000)
    stage.cue(
        "Build with an empty credit file and it refuses, and says what to add. It does not "
        "produce a thinner memo off a name alone — which is the failure mode worth naming, "
        "because a thin memo looks like a memo.",
        "the inline refusal naming what is missing",
    )

    # And a request that tries to talk to the model rather than about the borrower.
    page.get_by_label(loc.BORROWER, exact=True).fill(f"{fx.BORROWER_NAME} {fx.INJECTION_PHRASE}")
    _upload_files(stage)
    _fill_request(stage)
    stage.cue(
        "Now an instruction to the model, hidden in the borrower's name where a real one "
        "would arrive — inside a document somebody sent the bank. The request is otherwise "
        "complete and perfectly ordinary.",
        f"the borrower field, ending '{fx.INJECTION_PHRASE}'",
    )
    _build(stage)
    body = _text(stage)
    if loc.BLOCKED_BANNER not in body:
        raise ActFailed("an injection attempt produced a memo instead of a refusal")
    stage.cue(
        "Blocked by the guardrail, before any retrieval and before any drafting. Note what "
        "it was screened on: the redacted case summary, which is the same thing the model "
        "would have been shown. Nothing reached the model at all.",
        "the amber guardrail notice",
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
        f"Another bank's user asks for this analysis and gets {stranger.status} — the same "
        "answer they would get for one that does not exist. A 403 would have confirmed it "
        "exists, which is itself a disclosure. The bank's own auditor reads it fine. Now "
        "the analyst deletes the credit file.",
        "the two answers: 404 to the stranger, 200 to the auditor",
    )

    deleted = stage.delete(f"/v1/analyses/{analysis_id}")
    if deleted.status != 204:
        raise ActFailed(f"delete answered {deleted.status}")
    if stage.get(f"/v1/analyses/{analysis_id}").status != 404:
        raise ActFailed("the analysis survived its own deletion")
    gone = stage.post(f"/v1/analyses/{analysis_id}/export?fmt=html")
    if gone.ok:
        raise ActFailed("the memo outlived the evidence it was built from")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _row_index(stage: Stage, code: str) -> int:
    """Which row of the review table holds ``code``, in the order it is rendered."""
    candidate = stage.state.get("candidate")
    if not candidate:
        raise ActFailed("no candidate spread has been extracted")
    codes = [item["code"] for item in candidate["items"]]
    if code not in codes:
        raise ActFailed(f"the extractor proposed no {code!r} row to act on: {codes}")
    return codes.index(code)


ACTS: tuple[Act, ...] = (
    Act(
        "Who is asking",
        "A credit analyst signs in. Everything that follows — the audit actor on the memo, "
        "and which borrowers this person may retrieve evidence for — comes from the verified "
        "identity, never from anything the browser claims about itself.",
        act_identity,
        point_at="the persona picker: four seeded people, in two different banks",
    ),
    Act(
        "The credit file",
        "The analyst brings the deal's documents: audited statements, their own spread, and "
        "the quarterly covenant certificate. Each one is labelled with what it is and the "
        "date it speaks to, because the service cannot tell last year's management accounts "
        "from yesterday's and will not guess.",
        act_credit_file,
        point_at="the manifest: every file, its digest and page count, and the date the "
        "evidence is deleted",
    ),
    Act(
        "Figures nobody has vouched for",
        "The extractor reads the figures off those documents. Every row shows the quote it "
        "came from and links to the page. None of it computes anything yet: this is a "
        "proposal, and the product's own types refuse to calculate a ratio from it.",
        act_extraction_is_a_proposal,
        point_at="the amber panel titled 'Not yet anybody's figures', and a quote opened "
        "beside its source page",
    ),
    Act(
        "Becoming the person who stands behind them",
        "The analyst keeps most rows, rejects one, and adjusts capex with a reason. "
        "Confirming carries their name. From here the engines compute from figures a named "
        "person accepted, and both the original and the adjustment are kept.",
        act_confirm_the_spread,
        point_at="the green 'Confirmed by' line naming the analyst",
    ),
    Act(
        "The memo",
        "Build. The pipeline redacts, screens, retrieves the borrower's own evidence, "
        "computes the ratios BEFORE drafting, then writes the narrative around numbers the "
        "bank calculated. Every section carries citations, and the memo is marked for human "
        "review whatever it says.",
        act_build_the_memo,
        point_at="the amber human-review banner, then the sections a committee reads",
    ),
    Act(
        "Same filing, two answers",
        "Flowserve's own filing says it is in compliance with every covenant, and reports "
        "net leverage of 1.64x. The engine computes 3.18x from the figures the analyst "
        "confirmed, and the covenant BREACHES. Both are right: the borrower nets its cash "
        "and adds back its realignment charges, and this bank does neither. The model "
        "drafts prose; it never decides compliance. And the current ratio passes at 2.03x "
        "against a 2.00x floor — inside the thin-headroom band, so AT RISK rather than "
        "green. Every one of those numbers is in the 10-K.",
        act_the_breach_stands,
        point_at="the covenant table: the status pills, and the computed value beside the "
        "one the evidence reported",
    ),
    Act(
        "It refuses to compute what it cannot",
        "Four of the nine catalogue ratios could not be computed, and each says which line "
        "was missing. A quick ratio quietly omitted reads as though nobody thought liquidity "
        "worth stating; an estimated one is worse.",
        act_uncomputable_ratios,
        point_at="the ratio rows with no number, each naming the line it needed",
    ),
    Act(
        "The bank's own policy",
        "The limits are the bank's, from an uploaded versioned pack, and the memo names the "
        "version. That is what makes the exception a sentence a committee can act on: your "
        "policy requires 3.00x, this measures 3.18x, and the Regional Credit Committee can "
        "waive it. The scorecard proposes a grade and shows every driver — proposed, never "
        "assigned.",
        act_policy_and_rating,
        point_at="rule LEV-01 with its waiver authority, and the grade's drivers",
    ),
    Act(
        "The reconciliations",
        "The borrower's filing says net leverage is 1.64x and every covenant is met. The "
        "engine computes 3.18x. The memo reports the disagreement rather than picking a "
        "winner quietly, and the cause is not an error in either figure: it is cash "
        "netting and an EBITDA add-back. That is the conversation the credit officer needs "
        "to have, surfaced instead of buried.",
        act_reconciliation,
        point_at="the reconciliation finding naming both figures",
    ),
    Act(
        "The group",
        "Lending is to a group, not a company. The analyst declares two real subsidiaries "
        "from Exhibit 21 of the same filing — one wholly owned in Singapore, one 40% held "
        "in Saudi Arabia. Neither files separately, so the bank has no statements for "
        "either, which is the ordinary case rather than the awkward one. The consolidated "
        "cash flow shows the borrower's contribution and NAMES both entities it could not "
        "include, rather than totalling as though they contribute nothing.",
        act_the_group,
        point_at="the 'Incomplete' notice naming both subsidiaries",
    ),
    Act(
        "How far it can fall",
        "A committee cannot judge whether a 15% earnings decline is the right test for this "
        "sector. They can judge 'it breaks at 10%'. Every scenario reports the break-even, "
        "not just the shocked value.",
        act_stress,
        point_at="the break-even column",
    ),
    Act(
        "The checker",
        "The analyst rewrites the summary to lead with the breach. The approver objects "
        "against the exact text they read. The analyst edits again — and the comment is "
        "flagged as stale rather than closed, because a comment that lapsed when the text "
        "moved was lost, not answered. The approver resolves it, by name, and the revision "
        "chain verifies.",
        act_the_checker,
        point_at="the revision chain, and the comment that went stale instead of away",
    ),
    Act(
        "Figures are not editable prose",
        "The prose is editable. The ratios are not. No number reaches a committee that no "
        "formula produced.",
        act_figures_are_not_prose,
        point_at="the refusal, which names the sections that ARE editable",
    ),
    Act(
        "Public context, for the analyst only",
        "The one place this product reaches the open web, and the one place its output may "
        "not travel. The analyst searches for sector context and reads what comes back. "
        "None of it enters the memo, the pack or the review payload — Google's licence "
        "permits grounded results to be shown only to the person who ran the query, and a "
        "memo is read by a checker, a committee and later an examiner. The memo has no "
        "field one could occupy, and nothing here carries a figure an engine could read.",
        act_public_context,
        point_at="the results with their suggestion chips, then the line saying none of it "
        "is in the memo",
    ),
    Act(
        "The committee pack",
        "The pack leaves the application as a Word document a committee circulates, carrying "
        "the standing sentence first, the policy exceptions and the failed reconciliations. "
        "It once dropped the last two while still looking complete. A format this deployment "
        "cannot produce is refused rather than quietly substituted.",
        act_committee_pack,
        point_at="the rendered pack: the standing sentence, then LEV-01 and the reconciliation",
    ),
    Act(
        "Is this even bankable",
        "A pre-screen answers in a minute off a thin package. Ninety-six months trips the "
        "one knockout the policy pack reserves for rules no appetite overrides, and no grade "
        "is proposed, because the package cannot support one.",
        act_pre_screen_knockout,
        point_at="the TEN-01 knockout, and the absent rating",
    ),
    Act(
        "What it will not do",
        "Build with an empty credit file and it refuses and says what to add. Put an "
        "instruction to the model into the borrower's name and the guardrail blocks the "
        "request before any retrieval or drafting. Neither produces a thinner memo.",
        act_refusals,
        point_at="the inline refusal, then the amber guardrail notice",
    ),
    Act(
        "The evidence goes away",
        "Another bank's user gets the same answer for an analysis that exists as for one "
        "that does not. The bank's own auditor can read it. And when the analyst deletes it, "
        "the memo dies with the evidence it was built from — the retention promise, kept "
        "immediately rather than in fifteen days.",
        act_evidence_goes_away,
        point_at="the 404 that does not confirm the analysis exists",
    ),
)


def act_titles() -> list[str]:
    return [act.title for act in ACTS]


if __name__ == "__main__":  # pragma: no cover - a convenience for the docs
    print(json.dumps(act_titles(), indent=2))
