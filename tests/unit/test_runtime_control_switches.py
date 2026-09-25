"""The cheap runtime controls each have a switch, default on, and behave as a user expects.

The fleet's runtime-control contract (2026-09-24): the guardrail, PII redaction and review
routing are each switched by one environment variable read in three states; off binds a
disabled adapter and says so at startup; on under a networked profile refuses to boot without
the configuration it needs; every caller that hands a memo to the router reports what happened
to the hand-off; and a memo built from a case that redaction changed says so.

Review routing here used to be an opt-in flag that DEFAULTED OFF and made the container return
``None``. It is now ``CREDIT_MEMO_REVIEW_ROUTING``, on unless a deployment says otherwise, and
the old variable is gone rather than kept as an alias.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from credit_memo.adapters.controls import (
    DisabledGuardrail,
    DisabledRedaction,
    DisabledReviewRouter,
    DisclosingRedaction,
    RecordingReviewRouter,
    ReviewRouting,
)
from credit_memo.adapters.gcp.dlp_redaction import DlpRedactionAdapter
from credit_memo.adapters.local.redaction import LocalRegexRedactionAdapter
from credit_memo.adapters.local.review_router import LocalReviewRouter
from credit_memo.agent import tools as agent_tools
from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.cli.main import app as cli_app
from credit_memo.config import (
    GUARDRAIL_ENV,
    HUMAN_REVIEW_IAP_AUDIENCE_ENV,
    HUMAN_REVIEW_URL_ENV,
    PII_REDACTION_ENV,
    REVIEW_ROUTING_ENV,
    AnalysisBundleSettings,
    Container,
    ControlSwitches,
    LocalSettings,
    Settings,
    build_container,
    warn_switched_off,
)
from credit_memo.envread import ConfiguredEmptyError
from credit_memo.mcp.server import build_handlers

_SWITCHES = (GUARDRAIL_ENV, PII_REDACTION_ENV, REVIEW_ROUTING_ENV)
_PROFILE_ENV = "CREDIT_MEMO_PROFILE"
_BORROWER = "Acme Manufacturing Pte Ltd (FICTIONAL)"
_LOOPBACK = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *_SWITCHES,
        HUMAN_REVIEW_URL_ENV,
        HUMAN_REVIEW_IAP_AUDIENCE_ENV,
        "CREDIT_MEMO_REVIEW_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_PROFILE_ENV, "local")


def _local(controls: ControlSwitches | None = None) -> Settings:
    """The shipped local bindings, with ephemeral stores and the controls under test."""
    return replace(
        Settings.load("config/settings.yaml"),
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        analysis_bundle=AnalysisBundleSettings(root=tempfile.mkdtemp(prefix="cm-switches-")),
        controls=controls or ControlSwitches(),
    )


# --------------------------------------------------------------------------- #
# Three states, and the old opt-in is gone
# --------------------------------------------------------------------------- #
def test_every_control_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(True, True, True)


def test_review_routing_is_on_by_default_and_binds_the_profile_router() -> None:
    assert isinstance(Container(_local()).review_router, LocalReviewRouter)


def test_the_retired_opt_in_flag_no_longer_decides_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDIT_MEMO_REVIEW_ENABLED", "false")
    assert Settings.load().controls.review_routing is True
    assert isinstance(Container(_local()).review_router, LocalReviewRouter)


@pytest.mark.parametrize("name", _SWITCHES)
def test_a_control_switched_off_is_off(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "false")
    assert Settings.load().controls.switched_off() == (name,)


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError, match=name):
        Settings.load()


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "sometimes")
    with pytest.raises(ValueError, match=name):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled adapter, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_adapters() -> None:
    container = Container(_local(ControlSwitches(False, False, False)))
    assert isinstance(container.guardrail, DisabledGuardrail)
    assert isinstance(container.redaction, DisabledRedaction)
    assert isinstance(container.review_router, DisabledReviewRouter)


def test_on_binds_the_profile_adapters() -> None:
    container = Container(_local())
    assert not isinstance(container.guardrail, DisabledGuardrail)
    assert not isinstance(container.redaction, DisabledRedaction)
    assert not isinstance(container.review_router, DisabledReviewRouter)


def test_a_process_with_a_control_off_says_so_once(caplog: pytest.LogCaptureFixture) -> None:
    warn_switched_off.cache_clear()
    settings = _local(ControlSwitches(review_routing=False))
    with caplog.at_level(logging.WARNING, logger="credit_memo.config"):
        build_container(settings)
        build_container(settings)
    assert len([r for r in caplog.records if REVIEW_ROUTING_ENV in r.getMessage()]) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under a networked profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_routing_on_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, profile)
    with pytest.raises(ConfiguredEmptyError, match=HUMAN_REVIEW_URL_ENV):
        Settings.load()


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    monkeypatch.setenv(HUMAN_REVIEW_IAP_AUDIENCE_ENV, "123456789-abc.apps.googleusercontent.com")
    assert Settings.load().controls.review_routing is True


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.review_routing is False


def test_the_local_profile_needs_no_console() -> None:
    assert Settings.load().controls.review_routing is True


def test_the_model_armor_guardrail_on_without_a_template_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    monkeypatch.setenv(HUMAN_REVIEW_IAP_AUDIENCE_ENV, "123456789-abc.apps.googleusercontent.com")
    shipped = Path("config/settings.yaml").read_text(encoding="utf-8")
    emptied = shipped.replace("template_id: credit-memo-guardrail", 'template_id: ""')
    assert emptied != shipped
    path = tmp_path / "settings.yaml"
    path.write_text(emptied, encoding="utf-8")
    with pytest.raises(ConfiguredEmptyError, match=GUARDRAIL_ENV):
        Settings.load(path)
    monkeypatch.setenv(GUARDRAIL_ENV, "false")
    assert Settings.load(path).controls.guardrail is False


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, memo: object, *, maker: str, tenant: str = "") -> None:
        return None


class _Refusing:
    def route(self, memo: object, *, maker: str, tenant: str = "") -> None:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    assert RecordingReviewRouter(_Accepting()).outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    routed.route(object(), maker="m")  # type: ignore[arg-type]
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(Settings()))
    off.route(object(), maker="m")  # type: ignore[arg-type]
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="credit_memo.adapters.controls"):
        failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Through every caller: the analyst sees what the controls did
# --------------------------------------------------------------------------- #
@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, Container]:
    holder = {"container": Container(_local())}
    monkeypatch.setattr(deps, "get_container", lambda: holder["container"])
    return holder


def _memo(name: str = _BORROWER) -> dict[str, Any]:
    body = {
        "borrower": {
            "id": "borr-acme-mfg",
            "name": name,
            "sector": "manufacturing",
            "jurisdiction": "SG",
        },
        "documents": [],
    }
    response = TestClient(app, client=_LOOPBACK).post("/v1/credit-memo", json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_a_memo_says_it_was_routed_and_the_case_unchanged(served: dict[str, Container]) -> None:
    body = _memo()
    assert body["requires_human_review"] is True
    assert body["review_routing"] == "routed"
    assert body["input_redacted"] is False


def test_a_memo_discloses_that_the_case_was_masked(served: dict[str, Container]) -> None:
    assert _memo(f"{_BORROWER} c/o jane.tan@example.com")["input_redacted"] is True


def test_a_memo_says_routing_is_off_when_it_is(served: dict[str, Container]) -> None:
    served["container"] = Container(_local(ControlSwitches(review_routing=False)))
    body = _memo()
    assert body["review_routing"] == "off"
    assert body["requires_human_review"] is True


def test_a_memo_says_the_hand_off_failed_instead_of_hiding_it(
    served: dict[str, Container],
) -> None:
    served["container"].__dict__["review_router"] = _Refusing()
    assert _memo()["review_routing"] == "failed"


def test_the_agent_tools_report_the_hand_off() -> None:
    off = _local(ControlSwitches(review_routing=False))
    memo = agent_tools.build_credit_memo(_BORROWER, "manufacturing", "SG", settings=off)
    assert memo["review_routing"] == "off"
    flags = agent_tools.flag_risks(_BORROWER, "manufacturing", "SG", settings=_local())
    assert flags["review_routing"] == "routed"
    assert "risk_flags" in flags


def test_the_mcp_tools_report_the_hand_off(served: dict[str, Container]) -> None:
    served["container"].__dict__["review_router"] = _Refusing()
    handlers = build_handlers("mcp:test")
    arguments = {"borrower_name": _BORROWER, "sector": "manufacturing", "jurisdiction": "SG"}
    assert handlers["build_credit_memo"](**arguments)["review_routing"] == "failed"
    covenants = handlers["extract_covenants"](**arguments)
    assert covenants["review_routing"] == "failed"
    assert "covenants" in covenants


def test_the_cli_states_the_hand_off_in_plain_words(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_DB", ":memory:")
    monkeypatch.setenv("CREDIT_MEMO_LOCAL_AUDIT", ":memory:")
    result = CliRunner().invoke(cli_app, ["build", _BORROWER, "-s", "manufacturing", "-j", "SG"])
    assert result.exit_code == 0, result.output
    assert "Review routing: off" in result.output
    assert "not queued for review" in result.output


def test_the_disclosure_wrapper_notices_only_a_change() -> None:
    wrapper = DisclosingRedaction(LocalRegexRedactionAdapter(_local()))
    wrapper.redact("Credit memo for borrower Acme Manufacturing Pte Ltd")
    assert wrapper.changed is False
    wrapper.redact("contact jane.tan@example.com")
    assert wrapper.changed is True


# --------------------------------------------------------------------------- #
# Redaction tuned against false positives
# --------------------------------------------------------------------------- #
_BENIGN = (
    "Credit memo for borrower Tan Holdings Pte Ltd (id=b-001, sector=manufacturing)",
    "Facility of SGD 85000000 term loan, DSCR covenant 1.25x tested quarterly",
    "Revolving credit facility of HKD 60000000 guaranteed by the sponsor",
    "Account balance 98765432.10 as at 2025-12-31 per the audited accounts",
    "Net debt of S$ 91234567 at FY2025 under MAS Notice 612",
    "Annual review as at 2026-03-31; rating moved from 5 to 6 on the 10-point scale",
    "Revenue USD 90,000,000 and EBITDA of 12.5m; leverage 3.2x",
)


@pytest.mark.parametrize("text", _BENIGN)
def test_benign_credit_text_passes_the_redactor_unchanged(text: str) -> None:
    assert LocalRegexRedactionAdapter(_local()).redact(text).text == text


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("NRIC S1234567D on file", "[SG_NRIC_FIN]"),
        ("write to jane.tan@example.com", "[EMAIL_ADDRESS]"),
        ("call +65 9123 4567 today", "[PHONE_NUMBER]"),
        ("call 91234567 today", "[SG_PHONE]"),
        ("call 9123 4567.", "[SG_PHONE]"),
    ],
)
def test_true_personal_data_is_still_masked(text: str, masked: str) -> None:
    assert masked in LocalRegexRedactionAdapter(_local()).redact(text).text


def test_the_inline_dlp_config_is_tuned_against_false_positives() -> None:
    adapter = DlpRedactionAdapter(_local())
    inspect = adapter._inline_inspect_config()
    assert inspect["min_likelihood"] == "LIKELY"
    assert all(c["likelihood"] == "VERY_LIKELY" for c in inspect["custom_info_types"])
    exclusion = inspect["rule_set"][0]
    assert exclusion["info_types"] == [{"name": "PERSON_NAME"}]
    assert "Pte" in exclusion["rules"][0]["exclusion_rule"]["regex"]["pattern"]
    transformation = adapter._inline_deidentify_config()["info_type_transformations"][
        "transformations"
    ][0]
    assert transformation["primitive_transformation"] == {"replace_with_info_type_config": {}}


def test_the_terraform_dlp_template_carries_the_same_tuning() -> None:
    dlp_tf = Path("infra/terraform/dlp.tf").read_text(encoding="utf-8")
    assert 'min_likelihood = "LIKELY"' in dlp_tf
    assert '"POSSIBLE"' not in dlp_tf
    assert "exclusion_rule" in dlp_tf
    assert "Pte" in dlp_tf
