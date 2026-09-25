"""Live web research (WebResearchPort): the OPTIONAL search leg of the laptop lane.

Under ``live`` the core model is local and this is the one leg that may call Gemini:
Grounding with Google Search, through the same
:class:`~credit_memo.adapters.gcp.gemini_web_research.GeminiWebResearchAdapter` the managed
profiles bind, with every fence that adapter carries (query hygiene, the per-analysis cap,
results shown only to the analyst who asked). The container builds it only while
``CREDIT_MEMO_RESEARCH_ENABLED`` is on, and that switch is off unless an operator sets it.

Switched on, it still has to be callable from this machine. When ``GOOGLE_CLOUD_PROJECT`` is
not set, the ``[gcp]`` extra is not installed, or Application Default Credentials do not
resolve, the app still starts and the memo core still runs: this leg reports itself
unavailable, logs why once, and every research call answers with that reason through the
route's existing "cannot run here" path (``NotImplementedError``), which the console shows
as it shows the on-prem placeholder's. Nothing is searched and nothing is billed.
"""

from __future__ import annotations

import logging
from typing import Any

from ...config import Settings
from ...domain.models import MarketContext

_log = logging.getLogger(__name__)

#: ``settings.project_id`` when ``GOOGLE_CLOUD_PROJECT`` is unset (config/settings.yaml).
_PLACEHOLDER_PROJECT = "your-gcp-project"


def _gemini_or_reason(settings: Settings) -> tuple[Any | None, str]:
    """Build the Gemini research delegate, or say why it cannot be built on this machine.

    Checks only what can be known locally: the project, the SDK, and that Application Default
    Credentials resolve. Nothing here calls Gemini or runs a billable query.
    """
    if not settings.project_id or settings.project_id == _PLACEHOLDER_PROJECT:
        return None, "GOOGLE_CLOUD_PROJECT is not set"
    try:
        import google.auth
        from google import genai  # noqa: F401 - presence check for the [gcp] extra
    except ImportError:
        return None, "the Gemini SDK is not installed (install the [gcp] extra)"
    try:
        google.auth.default()
    except Exception as exc:  # noqa: BLE001 - any failure means no usable credential
        return None, f"no Application Default Credentials ({type(exc).__name__})"
    from ..gcp.gemini_web_research import GeminiWebResearchAdapter

    return GeminiWebResearchAdapter(settings), ""


class LiveWebResearchAdapter:
    """Gemini web research when this machine can reach it; a named refusal when it cannot."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._delegate, reason = _gemini_or_reason(settings)
        self._reason = "" if self._delegate is not None else reason
        if self._delegate is None:
            _log.warning(
                "public-web research is switched on but unavailable: %s; memos are built "
                "without it",
                reason,
            )

    @property
    def available(self) -> bool:
        """Whether a research call can actually reach Gemini from this machine."""
        return self._delegate is not None

    @property
    def reason(self) -> str:
        """Why the leg is unavailable; empty when it is available."""
        return self._reason

    def research(
        self,
        query: str,
        purpose: str = "",
        max_results: int = 8,
    ) -> MarketContext | None:
        """Delegate to Gemini, or refuse with the reason this machine cannot search."""
        if self._delegate is None:
            raise NotImplementedError(
                "public-web research is switched on (CREDIT_MEMO_RESEARCH_ENABLED) but "
                f"unavailable on this machine: {self._reason}. The memo core runs without it."
            )
        result: MarketContext | None = self._delegate.research(query, purpose, max_results)
        return result
