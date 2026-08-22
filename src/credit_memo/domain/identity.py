"""Identity value objects for server-side, verified principals.

The assistant never trusts a client-asserted ``actor`` or ACL. A :class:`Principal` is
resolved server-side by an :class:`~credit_memo.ports.identity.IdentityPort` adapter
(local dev persona, GCP IAP-verified assertion, or an on-prem client IdP) from the inbound
transport context, and becomes the audit actor plus the entitlement principals fed into
governed retrieval (non-repudiation under MAS TRM / CPS 234).

**Nothing is declared here.** Every name below is re-exported from
:mod:`hex_service_kit.identity`, which is pure standard library and imports no web framework
and no cloud SDK, so the domain stays framework-free exactly as it did when these classes were
copied into this file. The copies were byte-identical to the commons originals, which is the
whole argument for deleting them: a value type duplicated across sixteen repositories is
sixteen types that agree only until somebody edits one.
"""

from __future__ import annotations

from hex_service_kit.identity import ANONYMOUS as ANONYMOUS
from hex_service_kit.identity import IdentityError as IdentityError
from hex_service_kit.identity import Principal as Principal
from hex_service_kit.identity import RequestContext as RequestContext

__all__ = ["ANONYMOUS", "IdentityError", "Principal", "RequestContext"]
