"""The IAP negative matrix against a locally minted key: the REAL verifier, offline, no live GCP.

This service is deployed as an embedded application behind the journey portal's IAP edge, which
makes it one of the few in the fleet that receives a forwarded IAP assertion in production.
``test_iap_claim_half.py`` and ``test_iap_refusal_split.py`` prove the adapter's own half, but
the first replaces ``_verify`` with a stub and the second blocks the google-auth import, and the
verifier is the thing under suspicion: a suite that never runs it cannot show that the arguments
the adapter passes make ``google-auth`` REFUSE a wrong audience, an expired token or a signature
from the wrong key.

So this mints its own P-256 key, signs its own ES256 assertions with it (ES256 is what IAP signs
with), serves the public half from an in-process transport in the ``{kid: PEM}`` shape IAP's key
endpoint publishes, and runs the REAL ``google.oauth2.id_token.verify_token`` through the adapter
exactly as ``CREDIT_MEMO_PROFILE=gcp`` constructs it. The only thing faked is the HTTP fetch of
the key set, and the fake ASSERTS the URL requested is IAP's, so a verifier that fell back to
google-auth's OAuth2 key set fails here rather than verifying against keys IAP never signs with.

    cell                                   refused by
    -------------------------------------  -----------------------------------------------
    a correct assertion                    NOT refused: the control
    wrong or absent audience               google-auth, because audience= is passed
    expired, not yet valid, no exp/iat     google-auth
    impostor key (own kid, IAP's kid,      google-auth: unknown key id, or a signature
      no kid) and a tampered payload         that does not verify against IAP's key set
    malformed, alg none, HS256 confusion   the algorithm pin, before any cryptography
    a pin-passing token with a bad body    google-auth, as a refusal rather than a 500
    wrong or absent issuer                 this adapter, after a VALID signature
    no email, no sub                       this adapter, naming the missing claim
    absent, empty or blank header          this adapter, before anything is fetched
    unconfigured audience                  this adapter, 503, before anything is fetched
    emptied audience                       construction: no adapter exists to verify with

**Both transports, identically.** ``x-goog-*`` is Google's reserved namespace and the serverless
frontend strips it from a request entering this service, so the portal's broker forwards the
same assertion as ``x-portal-iap-assertion`` too. Every refusal above runs under BOTH names: a
header that bought a weaker check would be a second trust path, which is the defect this proves
absent. Precedence is covered as well: the edge-injected name wins when both are present, and a
bad assertion under it is refused rather than rescued by the other name.

**Machine callers.** This adapter has no machine-tenant setting. Its policy takes the tenant from
the ``hd`` claim alone, which a service account never carries, so a verified machine caller
resolves with NO tenant and, unless the deployment's group map names its domain, no role. That
is fail-closed twice over: ``may_access_borrower`` refuses a principal holding no role and no
borrower grant, and evidence ingested under a tenant carries a ``tenant:`` tag it cannot hold.
The cells assert that outcome through the entitlement check itself, not just the empty string.

WHY THIS MODULE MAY NOT SILENTLY SKIP. google-auth is in ``requirements-gcp.lock`` and not in
``requirements-dev.lock``, so the SDK-free ``make check`` cannot import it and skips this module.
Where the runtime lockfile IS installed, the hosted gate's ``offline-gate`` job names this file as
its ``iap_matrix_path``, sets ``CREDIT_MEMO_REQUIRE_IAP_MATRIX=1`` (the prefix comes from the
``CREDIT_MEMO_PROFILE=`` line in ``.env.example``) and fails if the run reports a skip. Under that
flag a missing google-auth is a hard ERROR, not a skip.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from credit_memo.adapters.gcp import iap_identity
from credit_memo.adapters.gcp.iap_identity import (
    IapAudienceUnconfiguredError,
    IapIdentityAdapter,
)
from credit_memo.config import Settings
from credit_memo.domain.entitlements import may_access_borrower
from credit_memo.domain.identity import IdentityError, Principal, RequestContext
from credit_memo.envread import ConfiguredEmptyError
from credit_memo.ports.identity import EndUserAuthUnavailableError

#: Set to "1" wherever google-auth IS installed, so absence becomes an error rather than a skip.
#: An exact-match read: unset, emptied and "0" all mean "not required", which fails closed for a
#: developer running the SDK-free gate and fails LOUD in the gate that installs the runtime lock.
_REQUIRE_ENV = "CREDIT_MEMO_REQUIRE_IAP_MATRIX"
_REQUIRED = os.environ.get(_REQUIRE_ENV) == "1"

try:  # noqa: SIM105 - the else branch is a skip, not a pass
    from google.auth import crypt as ga_crypt
    from google.auth import jwt as ga_jwt
    from google.auth.transport import requests as ga_requests
except ImportError as exc:  # pragma: no cover - exercised by whichever gate lacks the extra
    if _REQUIRED:
        raise RuntimeError(
            f"{_REQUIRE_ENV}=1 but google-auth is not importable, so the IAP negative matrix "
            "would have SKIPPED in a gate that exists to run it. Install the runtime lockfile "
            "(pip install -r requirements-gcp.lock) or stop setting the flag."
        ) from exc
    pytest.skip(
        f"google-auth is not installed (the SDK-free gate). Set {_REQUIRE_ENV}=1 where the "
        "runtime lockfile is installed to make this a hard failure instead.",
        allow_module_level=True,
    )

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError as exc:  # pragma: no cover - cryptography ships with the runtime lockfile
    if _REQUIRED:
        raise RuntimeError(
            f"{_REQUIRE_ENV}=1 but `cryptography` is not importable, so no key could be minted."
        ) from exc
    pytest.skip("cryptography is not installed", allow_module_level=True)


# The transport contract, written as LITERALS rather than imported from the adapter. The portal's
# broker and IAP itself send these exact strings; a rename on this side would be a deployment that
# silently stopped reading its identity, and importing the adapter's own constant would agree with
# the rename instead of catching it.
EDGE_HEADER = "x-goog-iap-jwt-assertion"
FORWARDED_HEADER = "x-portal-iap-assertion"
IAP_ISSUER = "https://cloud.google.com/iap"
IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"
BOTH_HEADERS = pytest.mark.parametrize(
    "header", [EDGE_HEADER, FORWARDED_HEADER], ids=["edge-injected", "host-forwarded"]
)

#: The deployment's variables, by the names the adapter reads; the portal's stack injects the
#: audience under exactly this name.
AUDIENCE_ENV = "CREDIT_MEMO_IAP_AUDIENCE"
GROUPS_ENV = "CREDIT_MEMO_IAP_GROUPS_JSON"

#: The IAP-protected resource this deployment verifies against. Obviously fictional.
AUDIENCE = "/projects/000000000000/global/backendServices/1111111111111111111"
#: A DIFFERENT protected resource: the audience an assertion minted for another service carries.
OTHER_AUDIENCE = "/projects/999999999999/global/backendServices/2222222222222222222"

SIGNING_KID = "iap-signing-key"
IMPOSTOR_KID = "impostor-key"

HUMAN = "analyst@bank.example"
HUMAN_SUB = "accounts.google.com:100000000000000000001"
MACHINE = "e2e-caller@fictional-project-000000.iam.gserviceaccount.com"
MACHINE_SUB = "accounts.google.com:100000000000000000002"


def test_the_literals_are_the_values_the_adapter_reads() -> None:
    """The literals above are only a contract if the adapter agrees with them today."""
    assert iap_identity._ASSERTION_HEADER == EDGE_HEADER
    assert iap_identity._PORTAL_ASSERTION_HEADER == FORWARDED_HEADER
    assert iap_identity._IAP_ISSUER == IAP_ISSUER
    assert iap_identity._IAP_KEYS_URL == IAP_KEYS_URL
    assert iap_identity._IAP_GROUPS_ENV == GROUPS_ENV


# --------------------------------------------------------------------------------------- #
# The harness: a minted key, a key set served in-process, and assertions signed like IAP's.
# --------------------------------------------------------------------------------------- #
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _mint_key() -> tuple[Any, str]:
    """A fresh P-256 keypair: the private key and its public half as PEM.

    Generated per module run. Nothing here is a secret and nothing is committed: a key on disk
    in a test is a key in every repository that copies the test.
    """
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, pem.decode("ascii")


def _signer(private_key: Any, kid: str | None) -> Any:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return ga_crypt.ES256Signer.from_string(pem, kid)


@pytest.fixture(scope="module")
def keys() -> dict[str, Any]:
    """IAP's signing key, and an impostor key that IAP's key set does not contain."""
    iap_private, iap_public_pem = _mint_key()
    impostor_private, _ = _mint_key()
    return {
        "iap": _signer(iap_private, SIGNING_KID),
        "impostor": _signer(impostor_private, IMPOSTOR_KID),
        # The forgeries that matter: the impostor claiming IAP's own key id, and claiming none.
        "impostor-as-iap": _signer(impostor_private, SIGNING_KID),
        "impostor-no-kid": _signer(impostor_private, None),
        "iap_public_pem": iap_public_pem,
        # The key set the fake transport serves: IAP's key only, in IAP's {kid: PEM} shape.
        "certs": {SIGNING_KID: iap_public_pem},
    }


class _CertsResponse:
    """What ``google.auth.transport.Request.__call__`` returns: a status and a body."""

    def __init__(self, payload: dict[str, str]) -> None:
        self.status = 200
        self.data = json.dumps(payload).encode("utf-8")
        self.headers: dict[str, str] = {}


@pytest.fixture()
def fetched(monkeypatch: pytest.MonkeyPatch, keys: dict[str, Any]) -> list[str]:
    """Serve the minted key set in-process, and record every URL the verifier asked for."""
    requested: list[str] = []

    class _Request:
        def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> _CertsResponse:
            requested.append(url)
            assert url == IAP_KEYS_URL, (
                f"the verifier fetched {url!r}, not IAP's key set. google-auth's default is the "
                "OAuth2 federated set, which signs tokens IAP never issued."
            )
            return _CertsResponse(keys["certs"])

    monkeypatch.setattr(ga_requests, "Request", _Request)
    return requested


@pytest.fixture(autouse=True)
def _deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deployment as the portal's stack configures it, and nothing inherited from a shell."""
    monkeypatch.setenv(AUDIENCE_ENV, AUDIENCE)
    monkeypatch.delenv(GROUPS_ENV, raising=False)


def _claims(
    *,
    audience: str | None = AUDIENCE,
    issuer: str | None = IAP_ISSUER,
    email: str | None = HUMAN,
    subject: str | None = HUMAN_SUB,
    hosted_domain: str | None = "bank.example",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    omit: tuple[str, ...] = (),
) -> dict[str, Any]:
    """One IAP-shaped claim set. ``None`` leaves a claim out; every knob is a cell."""
    now = issued_at or datetime.now(tz=UTC) - timedelta(seconds=30)
    exp = expires_at or (now + timedelta(minutes=10))
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "email": email,
        "hd": hosted_domain,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return {k: v for k, v in payload.items() if v is not None and k not in omit}


def _assertion(keys: dict[str, Any], *, signer: str = "iap", **claims: Any) -> str:
    token: bytes = ga_jwt.encode(keys[signer], _claims(**claims))
    return token.decode("ascii")


def _machine_assertion(keys: dict[str, Any], address: str = MACHINE) -> str:
    """A service account's assertion: its address as ``email`` and NO ``hd`` claim at all."""
    return _assertion(keys, email=address, subject=MACHINE_SUB, hosted_domain=None)


def _adapter() -> IapIdentityAdapter:
    """Constructed exactly as the gcp profile builds it: the audience is read from the env."""
    return IapIdentityAdapter(Settings(profile="gcp"))


def _resolve(assertion: str, header: str = EDGE_HEADER) -> Principal:
    return _adapter().resolve(RequestContext(headers={header: assertion}))


# --------------------------------------------------------------------------------------- #
# The control. Without a cell that SUCCEEDS, every refusal below is satisfied by an adapter
# that refuses everything, which is not a service.
# --------------------------------------------------------------------------------------- #
@BOTH_HEADERS
def test_a_correctly_minted_assertion_verifies_and_yields_the_principal(
    keys: dict[str, Any], fetched: list[str], header: str
) -> None:
    principal = _resolve(_assertion(keys), header)
    assert principal.subject == HUMAN
    assert principal.tenant == "bank.example"
    assert principal.principals == (f"user:{HUMAN}",)
    assert principal.assurance == "iap"
    assert principal.source == "gcp-iap"
    assert fetched == [IAP_KEYS_URL], "the verifier must fetch IAP's key set, once"


@BOTH_HEADERS
def test_the_reviewed_group_map_grants_a_verified_human_its_roles(
    keys: dict[str, Any], fetched: list[str], header: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GROUPS_ENV, json.dumps({"bank.example": ["group:credit-analyst"]}))
    principal = _resolve(_assertion(keys), header)
    assert principal.principals == (f"user:{HUMAN}", "group:credit-analyst")


# --------------------------------------------------------------------------------------- #
# Refused by google-auth, because the adapter passes audience= and certs_url=.
# --------------------------------------------------------------------------------------- #
@BOTH_HEADERS
@pytest.mark.parametrize(
    ("audience", "reason"),
    [
        (OTHER_AUDIENCE, f"Token has wrong audience {OTHER_AUDIENCE}"),
        (None, "Token has wrong audience None"),
    ],
    ids=["another-service", "no-aud-claim"],
)
def test_an_assertion_for_another_audience_is_refused_by_the_verifier(
    keys: dict[str, Any], fetched: list[str], header: str, audience: str | None, reason: str
) -> None:
    """THE defect. Signed by the right key, well formed, unexpired, and for somebody else.

    The reason is google-auth's own. This adapter ALSO compares the audience after
    verification, so a verifier that stopped receiving ``audience=`` would still refuse here --
    with a different reason. Matching google-auth's words is what keeps that regression red.
    """
    with pytest.raises(IdentityError, match=re.escape(f"verification failed: {reason}")):
        _resolve(_assertion(keys, audience=audience), header)
    assert fetched == [IAP_KEYS_URL]


@BOTH_HEADERS
@pytest.mark.parametrize(
    ("offset", "reason"),
    [(-timedelta(hours=2), "Token expired"), (timedelta(hours=2), "Token used too early")],
    ids=["expired", "not-yet-valid"],
)
def test_an_assertion_outside_its_lifetime_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str, offset: timedelta, reason: str
) -> None:
    issued = datetime.now(tz=UTC) + offset
    assertion = _assertion(keys, issued_at=issued, expires_at=issued + timedelta(minutes=10))
    with pytest.raises(IdentityError, match=re.escape(f"verification failed: {reason}")):
        _resolve(assertion, header)


@BOTH_HEADERS
@pytest.mark.parametrize("claim", ["exp", "iat"])
def test_an_assertion_with_no_lifetime_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str, claim: str
) -> None:
    """No ``exp`` is a credential that never stops working; google-auth refuses it outright."""
    reason = f"verification failed: Token does not contain required claim {claim}"
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(_assertion(keys, omit=(claim,)), header)


@BOTH_HEADERS
@pytest.mark.parametrize(
    ("signer", "reason"),
    [
        ("impostor", f"Certificate for key id {IMPOSTOR_KID} not found"),
        ("impostor-as-iap", "Could not verify token signature"),
        ("impostor-no-kid", "Could not verify token signature"),
    ],
    ids=["impostor-own-kid", "impostor-claims-iap-kid", "impostor-no-kid"],
)
def test_an_assertion_signed_by_a_key_iap_does_not_publish_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str, signer: str, reason: str
) -> None:
    """Correct claims, audience and issuer, signed by a key outside IAP's set.

    An impostor naming its OWN key id is refused at the key lookup, before any signature is
    checked. The two that reach the signature check are the forgeries that matter: one that
    claims IAP's key id, and one that names no key so every published key is tried.
    """
    with pytest.raises(IdentityError, match=re.escape(f"verification failed: {reason}")):
        _resolve(_assertion(keys, signer=signer), header)


@BOTH_HEADERS
def test_a_tampered_payload_under_a_genuine_signature_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str
) -> None:
    """IAP's own signature, over a DIFFERENT claim set than the one presented."""
    head, _body, signature = _assertion(keys).split(".")
    forged_body = _b64(json.dumps(_claims(email="attacker@bank.example")).encode())
    with pytest.raises(IdentityError, match="verification failed: Could not verify token"):
        _resolve(f"{head}.{forged_body}.{signature}", header)


# --------------------------------------------------------------------------------------- #
# Refused by the algorithm pin, before any cryptography, each with its OWN reason.
# --------------------------------------------------------------------------------------- #
def _unsigned() -> str:
    """``alg: none`` over a claim set that would otherwise be perfect."""
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{_b64(json.dumps(_claims()).encode())}."


def _hmac_keyed_with_the_public_key(keys: dict[str, Any]) -> str:
    """The HS256 confusion: an HMAC whose "secret" is IAP's PUBLIC key, which everybody has."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": SIGNING_KID}).encode())
    signing_input = f"{header}.{_b64(json.dumps(_claims()).encode())}"
    secret = keys["iap_public_pem"].encode("ascii")
    mac = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(mac)}"


@BOTH_HEADERS
@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (lambda keys: "not-a-jwt", "not a compact JWS or JWE"),
        (lambda keys: "eyJhbGciOiJFUzI1NiJ9", "not a compact JWS or JWE"),
        (lambda keys: "a.b.c", "not base64url-encoded JSON"),
        (lambda keys: "...", "not a compact JWS or JWE"),
        (lambda keys: _unsigned(), "alg 'none', which means it is UNSIGNED"),
        (
            _hmac_keyed_with_the_public_key,
            "signed with HS256, which is not in this deployment's pinned set",
        ),
    ],
    ids=["garbage", "one-segment", "three-bad-segments", "dots", "alg-none", "hs256-confusion"],
)
def test_a_malformed_or_unpinned_assertion_is_a_refusal_before_the_verifier(
    keys: dict[str, Any], fetched: list[str], header: str, build: Any, reason: str
) -> None:
    """Each cell asserts its OWN reason rather than a shared "verification failed".

    An unsigned token recognised as unsigned and a token rejected for being unparseable are
    different security properties, and a refusal that merely says "failed" cannot tell them
    apart. Nothing is fetched: the pin runs with no cryptography and no network.
    """
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(build(keys), header)
    assert fetched == []


@BOTH_HEADERS
def test_a_token_that_passes_the_pin_with_an_unreadable_body_is_still_a_refusal(
    keys: dict[str, Any], fetched: list[str], header: str
) -> None:
    """google-auth's parse error is a ``ValueError``; unwrapped it would be a bare 500."""
    head = _b64(json.dumps({"alg": "ES256", "typ": "JWT", "kid": SIGNING_KID}).encode())
    with pytest.raises(IdentityError, match="verification failed: Can't parse segment"):
        _resolve(f"{head}.{_b64(b'not json')}.{_b64(b'x' * 64)}", header)


# --------------------------------------------------------------------------------------- #
# Refused by this adapter AFTER a valid signature: verify_token checks no issuer and no identity.
# --------------------------------------------------------------------------------------- #
@BOTH_HEADERS
@pytest.mark.parametrize(
    ("issuer", "reason"),
    [
        ("https://accounts.google.com", "issued by a party this deployment does not accept"),
        (
            "https://securetoken.google.com/fictional-project-000000",
            "issued by a party this deployment does not accept",
        ),
        (None, "missing required claim(s): iss"),
    ],
    ids=["oauth2-issuer", "firebase-issuer", "no-issuer"],
)
def test_a_validly_signed_assertion_from_the_wrong_issuer_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str, issuer: str | None, reason: str
) -> None:
    """Right key, right audience, unexpired: ``verify_token`` returns these claims happily."""
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(_assertion(keys, issuer=issuer), header)
    assert fetched == [IAP_KEYS_URL], "refused AFTER a signature that verified"


@BOTH_HEADERS
@pytest.mark.parametrize(
    ("claim", "overrides"),
    [("email", {"email": None}), ("sub", {"subject": None}), ("email", {"email": "  "})],
    ids=["no-email", "no-sub", "blank-email"],
)
def test_a_validly_signed_assertion_naming_nobody_is_refused(
    keys: dict[str, Any], fetched: list[str], header: str, claim: str, overrides: dict[str, Any]
) -> None:
    """The refusal NAMES the claim, so a check that stopped reading one cannot hide."""
    reason = f"missing required claim(s): {claim}"
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(_assertion(keys, **overrides), header)


# --------------------------------------------------------------------------------------- #
# The transport: which name is read, and that neither can rescue the other.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {EDGE_HEADER: ""},
        {EDGE_HEADER: "   "},
        {FORWARDED_HEADER: ""},
        {FORWARDED_HEADER: "\t"},
        {EDGE_HEADER: " ", FORWARDED_HEADER: "\n"},
    ],
    ids=["none", "edge-empty", "edge-blank", "forwarded-empty", "forwarded-blank", "both-blank"],
)
def test_an_absent_or_blank_assertion_is_refused_before_anything_is_fetched(
    fetched: list[str], headers: dict[str, str]
) -> None:
    with pytest.raises(IdentityError, match="missing IAP assertion header") as caught:
        _adapter().resolve(RequestContext(headers=headers))
    assert EDGE_HEADER in str(caught.value) and FORWARDED_HEADER in str(caught.value)
    assert fetched == [], "nothing should have been fetched"


def test_a_bad_edge_assertion_is_not_rescued_by_a_good_forwarded_one(
    keys: dict[str, Any], fetched: list[str]
) -> None:
    """The fallback is for an ABSENT edge header, never for a failed one."""
    headers = {
        EDGE_HEADER: _assertion(keys, audience=OTHER_AUDIENCE),
        FORWARDED_HEADER: _assertion(keys),
    }
    with pytest.raises(IdentityError, match="Token has wrong audience"):
        _adapter().resolve(RequestContext(headers=headers))
    assert fetched == [IAP_KEYS_URL], "exactly one assertion was verified"


def test_the_edge_assertion_wins_and_the_forwarded_one_is_never_read(
    keys: dict[str, Any], fetched: list[str]
) -> None:
    """With both present, the principal is the edge's caller; the other value is not a vote."""
    headers = {
        EDGE_HEADER: _assertion(keys),
        FORWARDED_HEADER: _assertion(keys, email="someone.else@bank.example", subject="x:2"),
    }
    assert _adapter().resolve(RequestContext(headers=headers)).subject == HUMAN
    assert fetched == [IAP_KEYS_URL]


def test_header_names_are_matched_without_regard_to_case(
    keys: dict[str, Any], fetched: list[str]
) -> None:
    headers = {FORWARDED_HEADER.upper(): _assertion(keys)}
    assert _adapter().resolve(RequestContext(headers=headers)).subject == HUMAN


# --------------------------------------------------------------------------------------- #
# Machine callers: no machine-tenant setting exists here, so a service account gets no tenant.
# --------------------------------------------------------------------------------------- #
@BOTH_HEADERS
def test_a_service_account_authenticates_and_reaches_no_borrower(
    keys: dict[str, Any], fetched: list[str], header: str
) -> None:
    """Verified, named, and entitled to nothing: the fail-closed answer for an unmapped machine.

    IAP signed for it, so it is authenticated. The policy's tenant comes from ``hd`` alone and a
    service account carries none, so it holds no tenant; it holds no role either, so the
    entitlement check refuses it every borrower. Refusing it outright here would be a different
    product decision than the one this adapter's policy states.
    """
    principal = _resolve(_machine_assertion(keys), header)
    assert principal.subject == MACHINE
    assert principal.tenant == ""
    assert principal.principals == (f"user:{MACHINE}",)
    assert not may_access_borrower(principal, "borrower-000001")


def test_the_human_group_map_grants_a_machine_nothing(
    keys: dict[str, Any], fetched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A role reviewed for the sign-in domain does not leak to a machine outside it."""
    monkeypatch.setenv(GROUPS_ENV, json.dumps({"bank.example": ["group:credit-analyst"]}))
    principal = _resolve(_machine_assertion(keys), FORWARDED_HEADER)
    assert principal.principals == (f"user:{MACHINE}",)
    assert not may_access_borrower(principal, "borrower-000001")


def test_a_forged_machine_assertion_is_refused_by_the_verifier(
    keys: dict[str, Any], fetched: list[str]
) -> None:
    """A service account's address is worth nothing without IAP's signature over it."""
    forged = _assertion(
        keys, signer="impostor-as-iap", email=MACHINE, subject=MACHINE_SUB, hosted_domain=None
    )
    with pytest.raises(IdentityError, match="Could not verify token signature"):
        _resolve(forged, FORWARDED_HEADER)


# --------------------------------------------------------------------------------------- #
# The deployment's own failure: no audience means nobody, refused before anything is read.
# --------------------------------------------------------------------------------------- #
@BOTH_HEADERS
def test_an_unconfigured_audience_refuses_even_a_perfect_assertion(
    keys: dict[str, Any], fetched: list[str], header: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no verify-without-an-audience path to fall into, under either name."""
    monkeypatch.delenv(AUDIENCE_ENV, raising=False)
    reason = f"{AUDIENCE_ENV} is not configured"
    with pytest.raises(IapAudienceUnconfiguredError, match=re.escape(reason)) as caught:
        _resolve(_assertion(keys), header)
    assert isinstance(caught.value, EndUserAuthUnavailableError)
    assert caught.value.http_status == 503
    assert fetched == []


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "blank"])
def test_an_emptied_audience_refuses_to_build_the_adapter_at_all(
    fetched: list[str], value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three-state read, cashed: an emptied audience is a deployment that does not start.

    It never reaches ``verify_token`` as an empty expected audience, and never becomes the
    ``None`` that google-auth documents as "the audience is not verified".
    """
    monkeypatch.setenv(AUDIENCE_ENV, value)
    with pytest.raises(ConfiguredEmptyError, match=re.escape(f"{AUDIENCE_ENV} is set to an empty")):
        _adapter()
    assert fetched == []


# --------------------------------------------------------------------------------------- #
# The mutants: prove this matrix would FAIL if the protection were removed. A negative matrix
# nobody proved can go red is a green tick over an adapter that verifies nothing.
# --------------------------------------------------------------------------------------- #
def test_the_matrix_would_go_red_without_the_audience_argument(
    keys: dict[str, Any], fetched: list[str]
) -> None:
    """The defective call, reproduced: ``verify_token`` with no ``audience=``.

    ``certs_url`` is passed only because the fake transport is the only key server in this
    process; what is being demonstrated is the audience. The defective call accepts a token
    minted for a DIFFERENT protected resource, and the adapter refuses that same token under
    either header.
    """
    from google.oauth2 import id_token

    foreign = _assertion(keys, audience=OTHER_AUDIENCE)
    claims = id_token.verify_token(foreign, ga_requests.Request(), certs_url=IAP_KEYS_URL)
    assert claims["email"] == HUMAN, (
        "verify_token without audience= accepted an assertion minted for another service, which "
        "is the defect. If this ever stops being true, google-auth changed its default and the "
        "adapter's own audience check is what still holds."
    )
    for header in (EDGE_HEADER, FORWARDED_HEADER):
        with pytest.raises(IdentityError, match="Token has wrong audience"):
            _resolve(foreign, header)


def test_the_matrix_would_go_red_if_the_forwarded_header_bypassed_the_verifier(
    keys: dict[str, Any], fetched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the signature check, the claim half alone would admit a forged credit analyst.

    Decoded WITHOUT verification, an impostor's assertion for somebody in the reviewed domain
    becomes a principal holding that domain's role, and the entitlement check then opens every
    borrower to it: nothing after the verifier can tell it apart. So the forwarded-header cells
    above are only meaningful because the forwarded name reaches the same verifier, and the
    adapter refusing the very same token is that proof.
    """
    from hex_service_kit.federation import FederationPolicy, principal_from_iap_claims

    forged = _assertion(keys, signer="impostor-as-iap", email="attacker@bank.example")
    unverified = ga_jwt.decode(forged, verify=False)
    policy = FederationPolicy(
        tenant_from_hosted_domain=True, domain_groups={"bank.example": ("group:credit-analyst",)}
    )
    assert may_access_borrower(principal_from_iap_claims(unverified, policy), "borrower-000001")

    monkeypatch.setenv(GROUPS_ENV, json.dumps({"bank.example": ["group:credit-analyst"]}))
    with pytest.raises(IdentityError, match="Could not verify token signature"):
        _resolve(forged, FORWARDED_HEADER)
