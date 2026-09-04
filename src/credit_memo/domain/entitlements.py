"""Server-side borrower entitlements: who may read a borrower's evidence, decided here.

The retrieval ACL for a borrower is NEVER derived from a client-supplied identifier alone.
A request names a borrower id, but the ``borrower:<id>`` retrieval principal is granted only
after :func:`may_access_borrower` passes against the VERIFIED
:class:`~credit_memo.domain.identity.Principal` (resolved by the IdentityPort, never
client-asserted).

This closes the second half of the object-level authorization gap. The first half, tenant
isolation, is already closed: evidence is tagged ``tenant:<t>`` at ingest and the
subset/fail-closed KB ACL requires a reader to hold that tag, so a guessed borrower id
cannot cross a tenant boundary. What that alone does NOT give is least privilege WITHIN a
tenant: any authenticated caller could name any borrower id in their own tenant and have
``borrower:<id>`` minted for them on the spot, because the tag was built from the request
body rather than checked against the caller. This module makes that grant conditional, which
is the parity ``cdd-sow-research`` (cdd-sow-research) already had via ``domain/entitlements.py``.

Access model (deliberately simple, override per deployment):

* an explicit ``borrower:<id>`` entitlement on the principal always grants access
  (fine-grained grants provisioned by the IdP / entitlement system); otherwise
* membership of one of the ``borrower_access_roles`` grants access to borrowers, and tenant
  isolation is still enforced by the ``tenant:<tenant>`` tag at retrieval time.

Pure stdlib; raising :class:`BorrowerAccessDeniedError` maps to HTTP 403 at the API layer.
"""

from __future__ import annotations

from .errors import BorrowerAccessDeniedError
from .identity import Principal


def borrower_acl(borrower_id: str, tenant: str = "") -> tuple[str, ...]:
    """The ACL tags a borrower's evidence carries in the knowledge base.

    Always ``borrower:<id>``; plus ``tenant:<t>`` when the caller carries a tenant. The KB's
    subset match then requires a reader to hold every tag, so a borrower id alone never
    crosses a tenant boundary. Without a tenant the tag set is just the borrower id, which
    preserves the CLI/agent (single-tenant, untagged-seed) path.
    """
    if tenant:
        return (f"borrower:{borrower_id}", f"tenant:{tenant}")
    return (f"borrower:{borrower_id}",)


#: Roles whose members may work on borrowers (within their own tenant). Deployments with
#: finer-grained needs provision explicit ``borrower:<id>`` entitlements instead.
DEFAULT_BORROWER_ACCESS_ROLES: frozenset[str] = frozenset(
    {"group:credit-analyst", "group:credit-approver", "group:audit"}
)


def may_access_borrower(
    principal: Principal,
    borrower_id: str,
    roles: frozenset[str] = DEFAULT_BORROWER_ACCESS_ROLES,
) -> bool:
    """True when the verified principal is entitled to the borrower's evidence."""
    if f"borrower:{borrower_id}" in principal.principals:
        return True
    return any(p in roles for p in principal.principals)


def borrower_scope(
    principal: Principal,
    borrower_id: str,
    roles: frozenset[str] = DEFAULT_BORROWER_ACCESS_ROLES,
) -> tuple[str, ...]:
    """The retrieval ACL principals for ``borrower_id``, derived entirely server-side.

    Returns the principal's own entitlements plus ``tenant:<tenant>`` (when the principal
    carries a tenant) plus ``borrower:<borrower_id>``; raises
    :class:`BorrowerAccessDeniedError` when the principal is not entitled to the borrower.
    The knowledge-base ACL match is subset-based, so evidence tagged with another tenant
    stays invisible even though the ``borrower:<id>`` principal is present.
    """
    if not may_access_borrower(principal, borrower_id, roles):
        raise BorrowerAccessDeniedError(
            f"{principal.actor} is not entitled to borrower {borrower_id!r} "
            "(no explicit borrower grant and no borrower-access role)"
        )
    scope: list[str] = list(principal.principals)
    if principal.tenant:
        scope.append(f"tenant:{principal.tenant}")
    scope.append(f"borrower:{borrower_id}")
    return tuple(scope)
