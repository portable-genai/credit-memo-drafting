"""Object-level authorization: server-side borrower entitlements (per-borrower least privilege).

The C2 control closes tenant isolation: evidence is tagged ``borrower:<id>`` AND ``tenant:<t>``,
and the knowledge-base ACL match is subset-based and fail-closed, so a caller in another
tenant gets ZERO passages for a borrower id they merely guessed
(``test_api_identity.test_acl_ok_is_subset_and_fail_closed`` pins that).

What it does NOT close, and what these tests cover, is least privilege WITHIN a tenant: minting
the ``borrower:<id>`` principal from the request body for anyone who asks lets any authenticated
in-tenant caller name any borrower. ``domain/entitlements.py`` makes that grant conditional on
the VERIFIED principal, which is the parity ``cdd-sow-research`` (Doc1) holds.
"""

from __future__ import annotations

import pytest

from credit_memo.domain import entitlements
from credit_memo.domain.errors import BorrowerAccessDeniedError
from credit_memo.domain.identity import Principal
from credit_memo.domain.memo_service import CreditMemoService

ANALYST = Principal(
    subject="demo.analyst@bank.example",
    principals=("group:credit-analyst", "group:risk"),
    tenant="demo-bank",
)
OTHER_TENANT = Principal(
    subject="user@other-tenant.example",
    principals=("group:credit-analyst",),
    tenant="other-bank",
)
NO_ROLES = Principal(subject="viewer@bank.example", principals=("group:hr",), tenant="demo-bank")
EXPLICIT_GRANT = Principal(
    subject="temp@bank.example", principals=("borrower:acme",), tenant="demo-bank"
)


# --------------------------------------------------------------------------- #
# Entitlement rules
# --------------------------------------------------------------------------- #
def test_borrower_access_roles_and_explicit_grants() -> None:
    assert entitlements.may_access_borrower(ANALYST, "acme") is True
    assert entitlements.may_access_borrower(EXPLICIT_GRANT, "acme") is True
    # An explicit grant is scoped to ITS borrower and does not generalise to another.
    assert entitlements.may_access_borrower(EXPLICIT_GRANT, "zeta") is False
    # A verified, authenticated in-tenant caller with no credit role is still denied: this
    # is the least-privilege half the tenant partition alone never enforced.
    assert entitlements.may_access_borrower(NO_ROLES, "acme") is False


def test_borrower_scope_denies_unentitled_principal() -> None:
    with pytest.raises(BorrowerAccessDeniedError):
        entitlements.borrower_scope(NO_ROLES, "acme")


def test_borrower_scope_contains_tenant_and_borrower_principals() -> None:
    scope = entitlements.borrower_scope(ANALYST, "acme")
    assert "borrower:acme" in scope
    assert "tenant:demo-bank" in scope
    assert set(ANALYST.principals) <= set(scope)


def test_borrower_scope_passes_role_check_but_keeps_the_tenant_partition() -> None:
    """A cross-tenant caller with the right ROLE is scoped, not granted.

    The two halves are independent and both required: the role check passes here (the
    other-bank analyst holds group:credit-analyst), so the scope is built, but it carries
    tenant:other-bank. The subset ACL then hides demo-bank's evidence. Entitlements decide
    WHETHER a caller may ask; the tenant tag decides WHAT they can see.
    """
    scope = entitlements.borrower_scope(OTHER_TENANT, "acme")
    assert "tenant:other-bank" in scope
    assert "tenant:demo-bank" not in scope


# --------------------------------------------------------------------------- #
# The ACL tags written at ingest are the tags a granted scope holds
# --------------------------------------------------------------------------- #
def test_borrower_acl_shape_with_and_without_tenant() -> None:
    assert entitlements.borrower_acl("acme", "demo-bank") == ("borrower:acme", "tenant:demo-bank")
    # No tenant (the CLI/agent single-tenant path): the borrower tag alone.
    assert entitlements.borrower_acl("acme") == ("borrower:acme",)


def test_service_ingest_tags_match_a_granted_scope() -> None:
    """What the service writes at ingest must be a subset of what a granted scope holds.

    The load-bearing invariant behind the single definition: the KB match is subset-based,
    so if the ingest tags and the entitlement scope ever drifted, evidence would be written
    carrying a tag no entitled reader could hold and the borrower's own analyst would silently
    retrieve nothing.
    """
    tags = CreditMemoService._acl_tags("acme", ANALYST.tenant)
    scope = entitlements.borrower_scope(ANALYST, "acme")
    assert set(tags) <= set(scope)
