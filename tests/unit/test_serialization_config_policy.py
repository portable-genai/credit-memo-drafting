"""Unit tests for serialization, config wiring, and the review policy.

* ``to_jsonable`` round-trips the domain artifacts into JSON-safe Python.
* ``Settings.load`` reads config/settings.yaml and the onprem profile resolves.
* ``CreditReviewPolicy`` always requires review and escalates on breach/high severity.

No Google Cloud SDK is imported (the onprem profile binds placeholder adapters).
"""

from __future__ import annotations

import json
import os

from pii_kit import DEFAULT_JURISDICTIONS
from tests.fixtures import sample_cases

from credit_memo.config import Container, Settings, build_container
from credit_memo.domain.models import (
    Covenant,
    CovenantOperator,
    CovenantStatus,
    CovenantType,
    RiskCategory,
    RiskFlag,
    Severity,
)
from credit_memo.domain.review_policy import CreditReviewPolicy
from credit_memo.domain.serialization import citation_to_dict, to_jsonable

CONFIG_PATH = "config/settings.yaml"


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def test_to_jsonable_serialises_passage_with_enum_and_page():
    passage = sample_cases.PRIMARY_PASSAGE
    out = to_jsonable(passage)
    assert isinstance(out, dict)
    # Enum -> .value; nested Citation rendered as a dict; tuples -> lists.
    assert out["citation"]["source_type"] == "filing"
    assert out["citation"]["page"] == passage.citation.page
    # Round-trips through json without raising.
    assert json.loads(json.dumps(out))


def test_citation_to_dict_returns_dict():
    d = citation_to_dict(sample_cases.PRIMARY_PASSAGE.citation)
    assert isinstance(d, dict)
    assert d["source_id"] == sample_cases.PRIMARY_SOURCE_ID


def test_to_jsonable_covenant_status_enum():
    covenant = Covenant(
        type=CovenantType.LEVERAGE,
        description="Max net leverage.",
        threshold=3.0,
        operator=CovenantOperator.LE,
        current_value=2.5,
        status=CovenantStatus.COMPLIANT,
    )
    out = to_jsonable(covenant)
    assert out["type"] == "leverage"
    assert out["operator"] == "<="
    assert out["status"] == "compliant"


# --------------------------------------------------------------------------- #
# Config + container wiring (onprem profile, no GCP SDK).
# --------------------------------------------------------------------------- #
def test_settings_load_pins_region_and_reads_adapters():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "asia-southeast1"
    assert "peer_data" in settings.adapters
    assert "onprem" in settings.adapters["extraction"]


def test_settings_yaml_pii_kit_matches_the_shipped_default():
    """The YAML default and the pack's own default must not drift apart.

    ``config/settings.yaml`` restates the jurisdiction list for discoverability, so pin it
    to the shipped default (the shared ``pii-kit`` APAC reference set): the redactor, the DLP
    custom info types and the eval gate's leak check all key off that pack, and a settings file
    that quietly disagreed would change what is masked without changing what the gate checks.
    """
    settings = Settings.load(CONFIG_PATH)
    assert settings.pii.jurisdictions == DEFAULT_JURISDICTIONS


def test_pii_jurisdictions_env_override(monkeypatch):
    monkeypatch.setenv("CREDIT_MEMO_PII_JURISDICTIONS", "jp, au ")
    settings = Settings.load(CONFIG_PATH)
    # Upper-cased, whitespace-stripped, and a tuple regardless of where the value came from.
    assert settings.pii.jurisdictions == ("JP", "AU")


def test_container_binds_onprem_adapters_without_gcp_sdk():
    settings = Settings.load(CONFIG_PATH)
    onprem = Settings(
        project_id=settings.project_id,
        region=settings.region,
        profile="onprem",
        adapters=settings.adapters,
    )
    container = build_container(onprem)
    assert isinstance(container, Container)
    # Binding constructs the onprem placeholder cleanly (it only raises when *called*).
    assert container.extraction is not None
    assert container.peer_data is not None
    assert container.knowledge_base is not None


def test_profile_env_override(monkeypatch):
    monkeypatch.setenv("CREDIT_MEMO_PROFILE", "onprem")
    settings = Settings.load(CONFIG_PATH)
    assert settings.profile == "onprem"
    monkeypatch.delenv("CREDIT_MEMO_PROFILE", raising=False)
    os.environ.pop("CREDIT_MEMO_PROFILE", None)


# --------------------------------------------------------------------------- #
# Review policy (maker-checker, P-06).
# --------------------------------------------------------------------------- #
def test_memo_always_requires_review():
    assert CreditReviewPolicy().requires_review() is True


def test_breach_covenant_escalates():
    policy = CreditReviewPolicy()
    breach = Covenant(
        type=CovenantType.LEVERAGE,
        description="Max net leverage.",
        threshold=3.0,
        operator=CovenantOperator.LE,
        current_value=3.6,
        status=CovenantStatus.BREACH,
    )
    assert policy.escalates(covenants=(breach,)) is True


def test_high_severity_flag_escalates():
    policy = CreditReviewPolicy()
    flag = RiskFlag(
        category=RiskCategory.LIQUIDITY,
        severity=Severity.HIGH,
        detail="Tight liquidity.",
    )
    assert policy.escalates(risk_flags=(flag,)) is True


def test_low_severity_no_breach_does_not_escalate():
    policy = CreditReviewPolicy()
    compliant = Covenant(
        type=CovenantType.LEVERAGE,
        description="Max net leverage.",
        threshold=3.0,
        operator=CovenantOperator.LE,
        current_value=2.0,
        status=CovenantStatus.COMPLIANT,
    )
    flag = RiskFlag(category=RiskCategory.SECTOR, severity=Severity.LOW, detail="Minor.")
    assert policy.escalates(covenants=(compliant,), risk_flags=(flag,)) is False
