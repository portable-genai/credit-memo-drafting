"""Fail-closed network defaults (C5).

Wired through the shared ``hex-service-kit`` rules; these tests prove THIS repo's wiring
(each red against the pre-adoption behaviour: unconditional 0.0.0.0 bind and a dev-origin
CORS fallback in every profile).
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from credit_memo.api import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def _origins_for_profile(
    monkeypatch: pytest.MonkeyPatch, profile: str, *, explicit: bool = True
) -> list[str]:
    monkeypatch.delenv("CREDIT_MEMO_CORS_ORIGINS", raising=False)
    settings = dataclasses.replace(
        app_module.deps.get_settings(), profile=profile, profile_explicit=explicit
    )
    monkeypatch.setattr(app_module.deps, "get_settings", lambda: settings)
    return app_module._cors_origins()


def test_cors_fallback_only_under_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _origins_for_profile(monkeypatch, "local") == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    assert _origins_for_profile(monkeypatch, "gcp") == []
    assert _origins_for_profile(monkeypatch, "platform") == []


def test_cors_fallback_needs_a_deliberate_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """An INHERITED local profile is not consent to trust localhost with credentials.

    Red before the three-state resolution: the dev-origin fallback keyed off the raw profile
    string, which an unset CREDIT_MEMO_PROFILE silently made ``local``.
    """
    assert _origins_for_profile(monkeypatch, "local", explicit=False) == []


def test_explicit_allowlist_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDIT_MEMO_CORS_ORIGINS", "https://tenant.example")
    assert app_module._cors_origins() == ["https://tenant.example"]


def test_local_profile_refuses_non_loopback_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    from hex_service_kit import InsecureBindError, resolve_bind_host

    monkeypatch.setenv("CREDIT_MEMO_API_HOST", "0.0.0.0")
    monkeypatch.delenv("CREDIT_MEMO_ALLOW_INSECURE_DEMO", raising=False)
    with pytest.raises(InsecureBindError):
        resolve_bind_host(
            "local",
            host_env="CREDIT_MEMO_API_HOST",
            insecure_demo_env="CREDIT_MEMO_ALLOW_INSECURE_DEMO",
        )


def test_frame_ancestors_keeps_the_shipped_default_when_unset() -> None:
    """Unset expresses no intent, so the shipped restrictive default stands."""
    assert app_module._frame_ancestors(None) == "'self'"


@pytest.mark.parametrize("value", ["", "   ", "\n\t "])
def test_an_emptied_frame_ancestors_refuses_framing_rather_than_dropping_the_directive(
    value: str,
) -> None:
    """A blank value must not emit a valueless CSP directive, which browsers discard.

    Red before the original three-state read: ``CREDIT_MEMO_FRAME_ANCESTORS=""`` produced
    the header ``Content-Security-Policy: frame-ancestors`` with no directive value, a CSP
    parse error, so the clickjacking control silently disappeared for a deployment whose
    template rendered the variable empty.

    Red again before this revision, which is what changed here. Folding set-and-empty into
    unset stopped the valueless header but answered ``'self'``, silently overriding the
    operator: emptying an allowlist is an expressed intent, and it means "nobody may frame
    this", which CSP spells ``'none'``. Unset and set-and-empty are different answers and
    now get different results, matching every other edge variable in the fleet.
    """
    assert app_module._frame_ancestors(value) == "'none'"


def test_frame_ancestors_honours_a_named_parent_origin() -> None:
    assert app_module._frame_ancestors("https://parent.example") == "https://parent.example"
    assert (
        app_module._frame_ancestors("  https://parent.example\n https://portal.example ")
        == "https://parent.example https://portal.example"
    )


def test_the_refusing_state_still_carries_a_legacy_clickjacking_backstop() -> None:
    """Red before: only ``'self'`` set X-Frame-Options, so the strictest state got nothing.

    A browser predating frame-ancestors had no clickjacking control on the very
    configuration that meant "nobody may frame this". A named parent origin correctly gets
    no header: X-Frame-Options cannot express an allowlist, and a DENY would break the
    embed the operator configured.
    """
    assert app_module._frame_options("'self'") == "SAMEORIGIN"
    assert app_module._frame_options("'none'") == "DENY"
    assert app_module._frame_options("https://parent.example") == ""


def test_the_emitted_headers_match_the_configured_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through the real middleware, not just the pure helpers.

    ``_FRAME_ANCESTORS`` is resolved once at import, so the emitted header is pinned to it;
    patch the module attribute to exercise each state against a live response.
    """
    expected = {
        "'self'": "SAMEORIGIN",
        "'none'": "DENY",
        "https://parent.example": None,
    }
    for ancestors, frame_options in expected.items():
        monkeypatch.setattr(app_module, "_FRAME_ANCESTORS", ancestors)
        with TestClient(app_module.app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/healthz")
        assert response.headers["content-security-policy"] == f"frame-ancestors {ancestors}"
        assert response.headers.get("x-frame-options") == frame_options
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in response.headers


def test_api_still_serves() -> None:
    client = TestClient(app_module.app, client=("127.0.0.1", 50000))
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_policy_band_refuses_out_of_range_values(value: float) -> None:
    from credit_memo.config import PolicySettings

    with pytest.raises(ValueError, match="between 0 and 1"):
        PolicySettings(covenant_at_risk_band=value)


# The wildcard refusal. Both origin policies documented "never *" and enforced it nowhere:
# `_cors_origins` delegates to `hex_service_kit.cors_allowlist`, whose docstring promises it
# "never returns *" while its set-and-valid branch returns exactly what the operator wrote,
# and `_frame_ancestors` joined the raw tokens. So `CREDIT_MEMO_CORS_ORIGINS=*` trusted every
# origin WITH credentials and `CREDIT_MEMO_FRAME_ANCESTORS=*` let any page frame the console.


def test_a_wildcard_cors_allowlist_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDIT_MEMO_CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._cors_origins()


def test_a_wildcard_hiding_inside_an_origin_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """``https://*.example`` is an allowlist of every subdomain, including one an attacker took."""
    monkeypatch.setenv("CREDIT_MEMO_CORS_ORIGINS", "https://tenant.example,https://*.example")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._cors_origins()


def test_a_wildcard_frame_ancestor_is_refused() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        app_module._frame_ancestors("*")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._frame_ancestors("'self' https://*.parent.example")


def test_a_legitimate_allowlist_and_the_three_states_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal adds ONE case. Unset, emptied and a named allowlist must all still hold."""
    assert app_module._frame_ancestors(None) == "'self'"
    assert app_module._frame_ancestors("") == "'none'"
    assert app_module._frame_ancestors("https://parent.example") == "https://parent.example"
    monkeypatch.setenv("CREDIT_MEMO_CORS_ORIGINS", "")
    assert app_module._cors_origins() == []
    monkeypatch.setenv("CREDIT_MEMO_CORS_ORIGINS", "https://tenant.example, https://other.example")
    assert app_module._cors_origins() == ["https://tenant.example", "https://other.example"]


@pytest.mark.parametrize("variable", ["CREDIT_MEMO_CORS_ORIGINS", "CREDIT_MEMO_FRAME_ANCESTORS"])
def test_a_wildcard_refuses_at_boot_and_not_on_some_later_request(variable: str) -> None:
    """Importing the app must fail, so a wildcard cannot reach a running service at all.

    A refusal raised on the first cross-origin request would leave the misconfiguration live
    until traffic found it, and a health check would have called the deployment good.
    """
    completed = subprocess.run(
        [sys.executable, "-c", "import credit_memo.api.app"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": "src", "CREDIT_MEMO_PROFILE": "local", variable: "*"},
        check=False,
        timeout=300,
    )
    assert completed.returncode != 0, f"the app imported with {variable}=*"
    assert "wildcard" in completed.stderr, completed.stderr
