"""Root ADK agent for the B2 Credit-Memo Assistant, hosted on Agent Runtime.

This is the agent the Gemini Enterprise Agent Platform **Agent Runtime** (ex-Agent
Engine) hosts. It wires together:

* the credit-memo domain-service :class:`FunctionTool` wrappers (``agent.tools``),
* the defense-in-depth model-boundary **callbacks** (redact + guardrail + audit;
  ``agent.callbacks``), and
* the reasoning model ``settings.models.reasoning`` (``gemini-3.5-flash``) at
  ``thinking=high`` (SPEC §3).

ADK convention is honoured two ways: the module exposes a ``root_agent`` attribute (what
ADK / ``adk web`` / Agent Runtime discover by default) **and** a
``build_root_agent(settings)`` factory for explicit, test-friendly construction.

Import safety (SPEC §4): ``google.adk`` is heavy and GCP-only. All ADK imports are
quarantined inside :func:`build_root_agent`, and the module-level ``root_agent`` is built
lazily via :class:`_LazyRootAgent` so merely importing this module never requires ADK (the
on-prem/test profile imports it cleanly).

Exposing over A2A: ``to_a2a(build_root_agent(settings))`` produces an A2A app that serves
``/.well-known/agent-card.json`` (see :func:`to_a2a_app` and ``agent.agent_card``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents import LlmAgent

ROOT_AGENT_NAME = "credit_memo_assistant"

_ROOT_INSTRUCTION = (
    "You are the B2 Credit-Memo and Underwriting Assistant for a commercial bank's credit "
    "team. You build cited credit memos from a borrower's financial statements and "
    "filings. You are decision SUPPORT for a credit officer, never a credit decision.\n\n"
    "Routing:\n"
    "- 'Build a credit memo for <borrower>' or a full underwriting request -> call "
    "build_credit_memo.\n"
    "- 'What are the risk flags for <borrower>?' -> call flag_risks.\n"
    "- 'How does <borrower> compare to peers?' -> call peer_compare.\n\n"
    "Rules:\n"
    "- Every figure, covenant and risk must carry a citation to its source (filing, "
    "policy, peer data). Never invent a number, a covenant threshold, or a citation.\n"
    "- Covenant compliance is computed deterministically; never assert a covenant is met "
    "or breached on your own, report the computed status.\n"
    "- A credit memo is consequential: always state that it requires human review "
    "(maker-checker) and is not a credit decision.\n"
    "- Do not request, repeat or store borrower personal data; it is redacted at the "
    "boundary and must not appear in your output."
)


def build_root_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the root ADK ``LlmAgent`` for the agent.

    Wires the credit-memo FunctionTools and the redact/guardrail/audit callbacks built
    from the DI container. The reasoning model runs at ``thinking=high`` (SPEC §3). All
    ADK imports are local to this function (SPEC §4).
    """
    settings = settings or Settings.load()

    from google.adk.agents import LlmAgent
    from google.genai import types

    from ..config import build_container
    from .callbacks import build_callbacks, configure_span_privacy
    from .tools import build_function_tools

    # Borrower PII must never land in trace spans (SPEC §3); set before anything runs.
    configure_span_privacy()

    container = build_container(settings)
    callbacks = build_callbacks(container)

    tools: list[Any] = list(build_function_tools())

    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )

    return LlmAgent(
        name=ROOT_AGENT_NAME,
        model=settings.models.reasoning,
        description=(
            "Credit-memo assistant: builds cited credit memos (financial analysis, "
            "covenants, risk flags, peer comparisons) from a borrower's filings."
        ),
        instruction=_ROOT_INSTRUCTION,
        tools=tools,
        generate_content_config=generate_content_config,
        before_model_callback=callbacks["before_model_callback"],
        after_model_callback=callbacks["after_model_callback"],
        after_agent_callback=callbacks["after_agent_callback"],
    )


def to_a2a_app(settings: Settings | None = None) -> Any:
    """Expose the root agent as an A2A app (serves ``/.well-known/agent-card.json``).

    Thin wrapper over ADK's ``to_a2a`` so peers can discover and call the agent over A2A
    v1.0 (SPEC §3/§6). ADK is imported lazily (SPEC §4).
    """
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    return to_a2a(build_root_agent(settings))


class _LazyRootAgent:
    """Lazy proxy so ``import root_agent`` never pulls in ADK.

    ADK discovers a module-level ``root_agent``. We expose that name without forcing ADK
    to be importable at module import time (on-prem/test profile, SPEC §4). The real
    ``LlmAgent`` is built on first attribute access and cached.
    """

    __slots__ = ("_agent",)

    def __init__(self) -> None:
        self._agent: LlmAgent | None = None

    def _resolve(self) -> LlmAgent:
        if self._agent is None:
            self._agent = build_root_agent()
        return self._agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "unbuilt" if self._agent is None else "built"
        return f"<LazyRootAgent {ROOT_AGENT_NAME} ({state})>"


# ADK convention: a module-level ``root_agent`` the runtime discovers. Lazy so importing
# this module is safe without ADK installed (SPEC §4).
root_agent = _LazyRootAgent()
