"""API-level tests for server-verified identity (the client-asserted actor is gone).

The FastAPI routes resolve a verified ``Principal`` via the ``IdentityPort`` (local
persona adapter in the ``local`` profile), never a request-body ``actor``. These tests
drive the app with an in-memory :class:`Container` (recording local adapters + the real
local persona identity adapter) injected by monkeypatching ``deps.get_container`` (which
is ``lru_cache``-wrapped), so nothing mutates the process environment.

They assert:
* an unknown ``X-Dev-Persona`` is a hard 401,
* the default (and header-selected) persona becomes the audit actor, and
* the verified user's entitlement principals reach the governed-retrieval ACL query.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import (
    RecordingAudit,
    RecordingExtraction,
    RecordingKnowledgeBase,
    RecordingLLM,
    RecordingPeerData,
    RecordingRedaction,
    RecordingTracer,
    _settings,
)

from credit_memo.adapters.local.analysis_bundle import LocalAnalysisBundleAdapter
from credit_memo.adapters.local.guardrail import LocalHeuristicGuardrailAdapter
from credit_memo.adapters.local.identity import LocalPersonaIdentityAdapter
from credit_memo.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from credit_memo.adapters.local.policy_pack import LocalYamlPolicyPackAdapter
from credit_memo.adapters.local.review_router import LocalReviewRouter
from credit_memo.api import deps
from credit_memo.api.app import app
from credit_memo.config import Container
from credit_memo.domain.identity import Principal
from credit_memo.domain.models import Citation, RetrievedPassage, SourceType


class _RecordingContainer(Container):
    """A Container whose ports are the recording local adapters (shared instances)."""

    def __init__(self) -> None:
        settings = _settings()
        super().__init__(settings)
        self.knowledge_base = RecordingKnowledgeBase(settings)  # type: ignore[assignment]
        self.audit = RecordingAudit(settings)  # type: ignore[assignment]
        self.extraction = RecordingExtraction(settings)  # type: ignore[assignment]
        self.peer_data = RecordingPeerData(settings)  # type: ignore[assignment]
        self.llm = RecordingLLM(settings)  # type: ignore[assignment]
        self.guardrail = LocalHeuristicGuardrailAdapter(settings)  # type: ignore[assignment]
        self.redaction = RecordingRedaction(settings)  # type: ignore[assignment]
        self.tracer = RecordingTracer(settings)  # type: ignore[assignment]
        self.identity = LocalPersonaIdentityAdapter(settings)  # type: ignore[assignment]
        self.review_router = LocalReviewRouter(settings)  # type: ignore[assignment]
        self.analysis_bundle = LocalAnalysisBundleAdapter(settings)  # type: ignore[assignment]
        self.policy_pack = LocalYamlPolicyPackAdapter(settings)  # type: ignore[assignment]


@pytest.fixture
def container() -> _RecordingContainer:
    return _RecordingContainer()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, container: _RecordingContainer) -> TestClient:
    # deps.get_container is lru_cached; inject the in-memory container instead of mutating
    # the environment. Patch both deps and the security module's reference.
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=("127.0.0.1", 50000))


_BODY = {
    "borrower": {
        "id": "borr-acme-mfg",
        "name": "Acme Manufacturing Pte Ltd (FICTIONAL)",
        "sector": "manufacturing",
        "jurisdiction": "SG",
    },
    "documents": [],
}


def test_unknown_persona_is_401(client: TestClient) -> None:
    res = client.post("/v1/credit-memo", json=_BODY, headers={"X-Dev-Persona": "does-not-exist"})
    assert res.status_code == 401


def test_default_persona_is_audit_actor(client: TestClient, container: _RecordingContainer) -> None:
    # No persona header -> the default (analyst) persona; even a body 'actor' is ignored.
    res = client.post("/v1/credit-memo", json={**_BODY, "actor": "attacker@evil.example"})
    assert res.status_code == 200
    actors = {e.actor for e in container.audit.events}
    assert actors == {"demo.analyst@bank.example"}
    assert "attacker@evil.example" not in actors


def test_selected_persona_is_audit_actor(
    client: TestClient, container: _RecordingContainer
) -> None:
    res = client.post("/v1/credit-memo", json=_BODY, headers={"X-Dev-Persona": "auditor"})
    assert res.status_code == 200
    assert {e.actor for e in container.audit.events} == {"demo.auditor@bank.example"}


def test_verified_principals_reach_governed_retrieval(
    client: TestClient, container: _RecordingContainer
) -> None:
    res = client.post("/v1/credit-memo", json=_BODY, headers={"X-Dev-Persona": "analyst"})
    assert res.status_code == 200
    assert container.knowledge_base.queries, "no governed-retrieval query was recorded"
    acls = set(container.knowledge_base.queries[0].acl_principals)
    # Both the borrower ACL tag and the verified user's entitlement principals are present.
    assert "borrower:borr-acme-mfg" in acls
    assert "group:credit-analyst" in acls


def test_personas_endpoint_lists_seeded_personas(client: TestClient) -> None:
    res = client.get("/v1/personas")
    assert res.status_code == 200
    ids = {p["id"] for p in res.json()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


# --------------------------------------------------------------------------- #
# C2 fix: subset / fail-closed governed-retrieval ACL + server-verified tenant.
#
# The old ``_acl_ok`` failed OPEN (empty principals => allow-all, and ANY-match tag
# widening), so any authenticated caller could name any borrower id in the request body
# and receive that borrower's tagged evidence. The fix makes the KB ACL subset-based and
# fail-closed, and threads the SERVER-VERIFIED tenant (from the IdentityPort, never the
# body) into retrieval as a ``tenant:<t>`` principal, partitioning evidence across tenants.
# --------------------------------------------------------------------------- #
_CROSS_TENANT_TAGS = ("borrower:acme-cross", "tenant:demo-bank")

_CROSS_TENANT_BODY = {
    "borrower": {
        "id": "acme-cross",
        "name": "Acme Cross Holdings Pte Ltd (FICTIONAL)",
        "sector": "manufacturing",
        "jurisdiction": "SG",
    },
    "documents": [],
}


def _tenant_passage() -> RetrievedPassage:
    """A borrower passage scoped to a single tenant (``borrower:`` AND ``tenant:`` tags)."""
    text = (
        "Acme Cross Holdings Pte Ltd (FICTIONAL) FY2025 audited financial statements: "
        "revenue USD 120m, EBITDA USD 24m, net leverage 2.5x against a 3.0x covenant, "
        "DSCR 1.4x tested quarterly."
    )
    return RetrievedPassage(
        text=text,
        citation=Citation(
            source_id="doc-acme-cross-financials",
            source_type=SourceType.FILING,
            title="Acme Cross FY2025 Financial Statements (FICTIONAL)",
            url="https://example.test/acme-cross",
            page=3,
            snippet=text[:120],
            score=0.9,
        ),
        score=0.9,
        acl_tags=_CROSS_TENANT_TAGS,
    )


def _untagged_passage() -> RetrievedPassage:
    """An untagged passage (public reference data), visible to any caller."""
    text = "Manufacturing sector credit policy: concentration risk over 25 percent of revenue."
    return RetrievedPassage(
        text=text,
        citation=Citation(
            source_id="policy-public",
            source_type=SourceType.POLICY,
            title="Public Credit Policy (FICTIONAL)",
            page=1,
            snippet=text[:120],
            score=0.5,
        ),
        score=0.5,
    )


def test_acl_ok_is_subset_and_fail_closed() -> None:
    """The KB ACL is subset (all-of), fail-closed: no empty-principal or any-match widening."""
    ok = LocalFtsKnowledgeBaseAdapter._acl_ok
    tagged = _tenant_passage()  # tags: borrower:acme-cross, tenant:demo-bank

    # Caller holding EVERY tag (plus extra entitlement groups) sees the passage.
    assert ok(tagged, {"borrower:acme-cross", "tenant:demo-bank", "group:credit-analyst"}) is True
    # Cross-tenant caller: same borrower id, WRONG tenant -> denied (no any-match widening).
    assert ok(tagged, {"borrower:acme-cross", "tenant:other-bank"}) is False
    # Borrower tag alone (missing the tenant tag) -> denied (subset, not intersection).
    assert ok(tagged, {"borrower:acme-cross"}) is False
    # Empty principals see nothing tagged -> no fail-open allow-all.
    assert ok(tagged, set()) is False
    # An untagged passage stays public reference data (visible even to empty principals).
    assert ok(_untagged_passage(), set()) is True


class _RealKbContainer(_RecordingContainer):
    """A container whose ``knowledge_base`` is the REAL local FTS5 adapter (enforces ACL).

    ``_RecordingContainer``'s recording KB deliberately bypasses ACL filtering to keep the
    shared fixtures visible, so a cross-tenant denial cannot be observed through it. This
    subclass swaps in the production :class:`LocalFtsKnowledgeBaseAdapter` seeded with a
    single tenant-scoped borrower passage, so retrieval is governed by the real
    subset/fail-closed ACL end to end. All other ports stay the recording local adapters.
    """

    def __init__(self) -> None:
        super().__init__()
        kb = LocalFtsKnowledgeBaseAdapter(self.settings)
        kb.seed([_tenant_passage()])  # replace the self-seed with ONLY the tenant-scoped row
        self.knowledge_base = kb  # type: ignore[assignment]


@pytest.fixture
def real_kb_container() -> _RealKbContainer:
    return _RealKbContainer()


@pytest.fixture
def real_kb_client(
    monkeypatch: pytest.MonkeyPatch, real_kb_container: _RealKbContainer
) -> TestClient:
    monkeypatch.setattr(deps, "get_container", lambda: real_kb_container)
    return TestClient(app, client=("127.0.0.1", 50000))


def test_same_tenant_persona_retrieves_borrower_evidence(real_kb_client: TestClient) -> None:
    # demo-bank analyst for borrower acme-cross: the verified tenant matches the evidence
    # tag, so the tenant-scoped passage is retrieved and the memo grounds (200).
    res = real_kb_client.post(
        "/v1/credit-memo", json=_CROSS_TENANT_BODY, headers={"X-Dev-Persona": "analyst"}
    )
    assert res.status_code == 200


def test_cross_tenant_persona_is_denied_borrower_evidence(real_kb_client: TestClient) -> None:
    # other-bank persona requesting the SAME guessed borrower id: it lacks tenant:demo-bank,
    # so the subset/fail-closed ACL filters the tenant-scoped evidence out. Retrieval is
    # empty -> RetrievalEmptyError -> ungrounded (HTTP 422). Under the OLD fail-open _acl_ok
    # the borrower tag alone matched (any-match) and this returned 200 -> the C2 leak.
    res = real_kb_client.post(
        "/v1/credit-memo", json=_CROSS_TENANT_BODY, headers={"X-Dev-Persona": "other-tenant"}
    )
    assert res.status_code == 422


# --------------------------------------------------------------------------- #
# Per-borrower least privilege (domain/entitlements.py) wired into every route.
#
# The rules themselves are unit-tested in test_entitlements.py; these prove the ROUTES
# actually consult them and answer 403. Every SEEDED persona holds a credit role, so the
# denial cannot be reached through the persona picker: this stubs the IdentityPort with a
# verified-but-unentitled principal, which is what a real IdP would hand back for, say, an
# HR user who authenticated fine but has no business reading a borrower's file.
# --------------------------------------------------------------------------- #
class _NoRolesIdentity:
    """An IdentityPort stub: authentication succeeds, entitlement does not."""

    def __init__(self, settings: object) -> None:
        self._settings = settings

    def resolve(self, ctx: object) -> Principal:
        return Principal(
            subject="viewer@bank.example",
            principals=("group:hr",),
            tenant="demo-bank",
            source="test-stub",
        )


class _NoRolesContainer(_RealKbContainer):
    def __init__(self) -> None:
        super().__init__()
        self.identity = _NoRolesIdentity(self.settings)  # type: ignore[assignment]


@pytest.fixture
def no_roles_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    container = _NoRolesContainer()
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize("route", ["/v1/credit-memo", "/v1/covenants", "/v1/risk-flags"])
def test_unentitled_principal_is_403_on_every_borrower_route(
    no_roles_client: TestClient, route: str
) -> None:
    # 403, not 422: the caller is refused before any retrieval, so "not entitled" is never
    # reported as "no evidence". Before the entitlements gate, borrower:<id> was minted from
    # the request body for anyone authenticated and this returned a memo.
    res = no_roles_client.post(route, json=_CROSS_TENANT_BODY)
    assert res.status_code == 403
    assert "not entitled" in res.json()["detail"]


def test_entitled_in_tenant_persona_still_succeeds(real_kb_client: TestClient) -> None:
    # The gate must not have broken the happy path: an entitled analyst still gets a memo.
    res = real_kb_client.post(
        "/v1/credit-memo", json=_CROSS_TENANT_BODY, headers={"X-Dev-Persona": "analyst"}
    )
    assert res.status_code == 200
