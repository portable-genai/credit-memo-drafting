"""Unit tests for the credit-memo sub-services and the deterministic invariants.

Covers:
* CovenantService: extraction + deterministic status (LLM never sets compliance).
* RiskFlagService: grounded, cited flags.
* PeerCompService: arithmetic median/percentile (no invented peers).
* The covenant-status comparison itself (the single auditable calculation).

All tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

import pytest
from tests.conftest import FakeLLM, FakePeerData, FakeTracer
from tests.fixtures import sample_cases

from credit_memo.domain import _grounded as g
from credit_memo.domain.covenant_service import CovenantService
from credit_memo.domain.models import (
    CovenantOperator,
    CovenantStatus,
    PeerMetric,
)
from credit_memo.domain.peer_comp_service import PeerCompService
from credit_memo.domain.risk_flag_service import RiskFlagService

ACTOR = "officer@bank.test"
BORROWER = sample_cases.ENTITY_BORROWER
PASSAGES = list(sample_cases.SAMPLE_PASSAGES)


# --------------------------------------------------------------------------- #
# Covenant status is a deterministic comparison, not an LLM verdict.
# --------------------------------------------------------------------------- #
def test_covenant_status_max_leverage_compliant():
    # 2.5x net leverage against a 3.0x max => COMPLIANT (with headroom).
    status = g.covenant_status(2.5, 3.0, CovenantOperator.LE)
    assert status is CovenantStatus.COMPLIANT


def test_covenant_status_max_leverage_breach():
    # 3.4x net leverage against a 3.0x max => BREACH.
    status = g.covenant_status(3.4, 3.0, CovenantOperator.LE)
    assert status is CovenantStatus.BREACH


def test_covenant_status_min_dscr_breach():
    # 1.10x DSCR against a 1.25x min => BREACH.
    status = g.covenant_status(1.10, 1.25, CovenantOperator.GE)
    assert status is CovenantStatus.BREACH


def test_covenant_status_thin_headroom_is_at_risk():
    # 2.95x against a 3.0x max passes but within the 5 percent headroom band => AT_RISK.
    status = g.covenant_status(2.95, 3.0, CovenantOperator.LE)
    assert status is CovenantStatus.AT_RISK


def test_covenant_status_missing_current_value_is_at_risk():
    status = g.covenant_status(None, 3.0, CovenantOperator.LE)
    assert status is CovenantStatus.AT_RISK


def test_covenant_status_policy_override_changes_boundary():
    assert (
        g.covenant_status(2.90, 3.0, CovenantOperator.LE, at_risk_band=0.02)
        is CovenantStatus.COMPLIANT
    )
    assert (
        g.covenant_status(2.90, 3.0, CovenantOperator.LE, at_risk_band=0.05)
        is CovenantStatus.AT_RISK
    )


def test_covenant_service_extracts_and_tests_status():
    service = CovenantService(llm=FakeLLM(), tracer=FakeTracer())
    covenants = service.extract(BORROWER, PASSAGES, ACTOR)
    assert covenants
    by_type = {c.type.value: c for c in covenants}
    # The fake emits a leverage covenant (2.5x <= 3.0x) and a DSCR covenant (1.40 >= 1.25).
    assert by_type["leverage"].status is CovenantStatus.COMPLIANT
    assert by_type["dscr"].status is CovenantStatus.COMPLIANT
    for c in covenants:
        assert c.citations, "every covenant must carry a citation"
        for cit in c.citations:
            assert cit.page is not None


def test_covenant_service_breach_when_value_exceeds_threshold():
    # A model that reports a breaching current value must yield BREACH deterministically.
    class BreachLLM(FakeLLM):
        def _body_for_schema(self, schema):  # type: ignore[no-untyped-def]
            from tests.conftest import _schema_properties

            props = _schema_properties(schema)
            if "items" in props and "threshold" in str(schema):
                return {
                    "items": [
                        {
                            "type": "leverage",
                            "description": "Maximum net leverage covenant.",
                            "threshold": 3.0,
                            "operator": "<=",
                            "current_value": 3.6,
                            "period": "Q4",
                            "used_source_ids": [sample_cases.PRIMARY_SOURCE_ID],
                        }
                    ]
                }
            return super()._body_for_schema(schema)

    service = CovenantService(llm=BreachLLM(), tracer=FakeTracer())
    covenants = service.extract(BORROWER, PASSAGES, ACTOR)
    assert covenants[0].status is CovenantStatus.BREACH


# --------------------------------------------------------------------------- #
# Risk flags are grounded and cited.
# --------------------------------------------------------------------------- #
def test_risk_flag_service_returns_cited_flags():
    service = RiskFlagService(llm=FakeLLM(), tracer=FakeTracer())
    flags = service.flag(BORROWER, PASSAGES, ACTOR)
    assert flags
    for f in flags:
        assert f.detail
        assert f.citations


# --------------------------------------------------------------------------- #
# Peer comparison: arithmetic median/percentile, no invented peers.
# --------------------------------------------------------------------------- #
def test_peer_comp_computes_median_and_percentile():
    """The arithmetic, derived from whatever peer set the adapter supplies.

    Deliberately not pinned to particular peer values. This asserts that the median and
    the delta follow from the peers actually returned; pinning the numbers made it a test
    of the fixture table, and it failed the moment those peers became real companies
    without anything about the calculation having changed.
    """
    from statistics import median

    from credit_memo.domain.models import FinancialMetric

    service = PeerCompService(peer_data=FakePeerData(), tracer=FakeTracer())
    borrower_value = 2.5
    metrics = (
        FinancialMetric(name="leverage", value=borrower_value, period="FY2025", currency="x"),
    )
    comparisons = service.compare(BORROWER, metrics, ACTOR)
    assert len(comparisons) == 1
    cmp = comparisons[0]

    expected_median = median(p.value for p in cmp.peers)
    assert cmp.peer_median == pytest.approx(expected_median)
    assert cmp.delta_to_median == pytest.approx(borrower_value - expected_median)
    assert 0.0 <= cmp.percentile <= 1.0


def test_peer_comp_skips_metric_without_peers():
    from credit_memo.domain.models import FinancialMetric

    service = PeerCompService(peer_data=FakePeerData(by_metric={}), tracer=FakeTracer())
    metrics = (FinancialMetric(name="leverage", value=2.5),)
    assert service.compare(BORROWER, metrics, ACTOR) == ()


def test_peer_comp_defensive_when_peer_data_raises():
    from credit_memo.domain.models import Borrower, FinancialMetric

    class BoomPeerData:
        def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
            raise RuntimeError("bigquery unavailable")

    service = PeerCompService(peer_data=BoomPeerData(), tracer=FakeTracer())
    metrics = (FinancialMetric(name="leverage", value=2.5),)
    assert service.compare(BORROWER, metrics, ACTOR) == ()


def test_agent_memo_service_uses_configured_covenant_policy(monkeypatch):
    """The ADK surface must use the same bank-owned policy as the API composition root."""
    from dataclasses import replace

    from credit_memo.agent import tools
    from credit_memo.config import PolicySettings, Settings, build_container

    settings = replace(Settings.load(), policy=PolicySettings(covenant_at_risk_band=0.17))
    captured = {}

    class StubService:
        def build(self, memo_input, actor):  # type: ignore[no-untyped-def]
            captured["band"] = self.band
            return {"actor": actor, "borrower": memo_input.borrower.id}

    def fake_build(container):  # type: ignore[no-untyped-def]
        service = StubService()
        service.band = container.settings.policy.covenant_at_risk_band
        return service

    monkeypatch.setattr("credit_memo.api.deps.build_credit_memo_service", fake_build)
    monkeypatch.setattr(tools, "_container", lambda _settings: build_container(settings))
    tools.build_credit_memo("Policy Corp", settings=settings)
    assert captured["band"] == 0.17
