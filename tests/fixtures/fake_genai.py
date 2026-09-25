"""A stand-in for the two ``google.genai`` names the Gemini adapters touch, with no SDK.

The offline gate has no ``google-genai``, and the adapters import it lazily inside the call, so
a test that wants to see what a managed adapter SENDS (which model, which config keys, whether a
search tool rode along) swaps these fakes in for the length of one test. ``monkeypatch`` puts
the real modules back, whether or not this machine has the SDK installed.

Nothing here answers like Gemini. It records the call and returns a response carrying one
grounding chunk, which is all the adapters read back.
"""

from __future__ import annotations

import importlib
import sys
import types as pytypes
from dataclasses import dataclass, field
from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest


class _ThinkingLevel(Enum):
    LOW = "LOW"
    HIGH = "HIGH"


def _record(name: str) -> Any:
    def build(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(kind=name, args=args, **kwargs)

    return build


@dataclass
class FakeGenai:
    """What the adapters sent: one entry per ``generate_content`` call."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    # ``types`` -------------------------------------------------------------------------
    def config(self, **kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    def types_module(self) -> pytypes.ModuleType:
        module = pytypes.ModuleType("google.genai.types")
        module.GenerateContentConfig = self.config  # type: ignore[attr-defined]
        module.Content = _record("Content")  # type: ignore[attr-defined]
        module.Part = SimpleNamespace(  # type: ignore[attr-defined]
            from_text=_record("Part.text"), from_bytes=_record("Part.bytes")
        )
        module.Tool = _record("Tool")  # type: ignore[attr-defined]
        module.GoogleSearch = _record("GoogleSearch")  # type: ignore[attr-defined]
        module.ThinkingConfig = _record("ThinkingConfig")  # type: ignore[attr-defined]
        module.ThinkingLevel = _ThinkingLevel  # type: ignore[attr-defined]
        return module

    # the client ------------------------------------------------------------------------
    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        if self.fail:
            raise RuntimeError("the managed model refused the call")
        self.calls.append({"model": model, "contents": contents, "config": config})
        web = SimpleNamespace(uri="https://example.invalid/sector", title="Sector", domain="x")
        metadata = SimpleNamespace(
            grounding_chunks=[SimpleNamespace(web=web)], search_entry_point=None
        )
        return SimpleNamespace(
            text='{"label": "ok"}',
            candidates=[
                SimpleNamespace(
                    finish_reason=SimpleNamespace(name="STOP"), grounding_metadata=metadata
                )
            ],
            usage_metadata=None,
            prompt_feedback=None,
        )

    @property
    def client(self) -> Any:
        return SimpleNamespace(models=SimpleNamespace(generate_content=self.generate_content))


def install(monkeypatch: pytest.MonkeyPatch) -> FakeGenai:
    """Make ``from google.genai import types`` (and ``from google import genai``) the fake."""
    fake = FakeGenai()
    genai = pytypes.ModuleType("google.genai")
    genai.types = fake.types_module()  # type: ignore[attr-defined]
    genai.Client = lambda **_: fake.client  # type: ignore[attr-defined]
    try:
        google = importlib.import_module("google")
    except ImportError:
        google = pytypes.ModuleType("google")
        google.__path__ = []  # a package, so ``google.genai`` resolves under it
        monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai.types)  # type: ignore[attr-defined]
    return fake
