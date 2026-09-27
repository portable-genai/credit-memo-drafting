"""The remote guardrail gateway client allows ONLY on a literal JSON ``true``.

The parser this replaces was ``allowed=bool(body.get("allowed", False))``: the string
``"false"``, the number ``1`` and any non-empty object or list all became an allow. A gateway
bug, a proxy rewriting the body, or a schema drift on the gateway side would have opened the
screen rather than closed it.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from credit_memo.adapters.platform.remote_guardrail import (
    RemoteGuardrailAdapter,
    RemoteGuardrailError,
)
from credit_memo.config import Settings
from credit_memo.domain.models import Direction

TEXT = "Summarise the borrower's leverage covenant headroom."


def _parse(body: Any) -> Any:
    return RemoteGuardrailAdapter._parse_verdict(body, Direction.INPUT)


def test_literal_true_allows() -> None:
    assert _parse({"allowed": True, "sanitized_text": TEXT}).allowed is True


@pytest.mark.parametrize(
    "value",
    [False, None, "true", "false", "yes", 1, 1.0, 0, {"ok": True}, [True], "", []],
    ids=repr,
)
def test_anything_but_literal_true_blocks(value: Any) -> None:
    assert _parse({"allowed": value}).allowed is False


def test_a_missing_allowed_field_blocks() -> None:
    assert _parse({"reason": "ok"}).allowed is False


@pytest.mark.parametrize("body", [[{"allowed": True}], "true", True, None], ids=repr)
def test_a_body_that_is_not_an_object_raises(body: Any) -> None:
    with pytest.raises(RemoteGuardrailError):
        _parse(body)


def _serve(monkeypatch: pytest.MonkeyPatch, content: bytes, status: int = 200) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status,
            content=content,
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)


@pytest.mark.parametrize(
    "content",
    [b'{"allowed": "false"}', b'{"allowed": 1}', b'{"allowed": {"x": 1}}', b"{}"],
    ids=["string-false", "one", "object", "empty"],
)
def test_screen_blocks_on_a_non_boolean_wire_verdict(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    _serve(monkeypatch, content)
    verdict = RemoteGuardrailAdapter(Settings(profile="platform")).screen(TEXT, Direction.INPUT)
    assert verdict.allowed is False


def test_screen_allows_on_the_wire_literal_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b'{"allowed": true, "sanitized_text": "ok"}')
    verdict = RemoteGuardrailAdapter(Settings(profile="platform")).screen(TEXT, Direction.OUTPUT)
    assert verdict.allowed is True


def test_a_gateway_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b'{"allowed": true}', status=503)
    with pytest.raises(RemoteGuardrailError):
        RemoteGuardrailAdapter(Settings(profile="platform")).screen(TEXT, Direction.INPUT)
