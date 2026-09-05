"""Gemini LLM adapter (LLMPort).

Wraps the unified **Google GenAI SDK** (``google-genai``) against the **Gemini
Enterprise Agent Platform** (Vertex backend) in ``asia-southeast1`` (Singapore).
Reasoning uses ``gemini-3.5-flash`` (thinking=high) for memo synthesis, covenant
extraction and risk-flag identification; triage/classification uses
``gemini-3.5-flash``. Both are pinned from settings; the floating ADK default model
and ``gemini-2.0-flash`` are never used.

The adapter maps the domain :class:`LlmRequest` onto ``client.models.generate_content``
(system instruction, temperature, max-output-tokens, a :class:`ThinkingConfig` mapped
from ``request.thinking``, and structured-output config when a response schema is
supplied), and maps ``usage_metadata`` back onto :class:`TokenUsage`.

All Google Cloud / GenAI SDK imports are lazy so the on-prem / test profile imports this
module without ``google-genai`` installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse, ThinkingLevel, TokenUsage

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google import genai


_LOG = logging.getLogger(__name__)


class GeminiLLMAdapter:
    """Generate completions and triage labels via Gemini on the Agent Platform."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models = settings.models
        self._client: Any | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=self._settings.project_id,
                # MODEL location, not the compute region.
                location=self._settings.models.location,
            )
        return self._client

    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion for ``request`` using the configured model."""
        client = self._get_client()
        from google.genai import types

        model = request.model or self._models.reasoning
        contents = self._to_contents(request)
        config = self._build_config(request, types)

        response = client.models.generate_content(model=model, contents=contents, config=config)
        text = getattr(response, "text", "") or ""
        finish = self._finish_reason(response)
        if finish not in ("STOP", "None", ""):
            # A structured response that stopped for any other reason is unusable even when
            # it is long: MAX_TOKENS truncates the JSON mid-object, the defensive parser
            # reads nothing from it, and the service reports "no grounded memo could be
            # synthesised from the evidence" -- which describes the evidence rather than the
            # budget. Thinking is charged to the same budget as the answer, so this is the
            # failure a bigger prompt produces first.
            _LOG.warning(
                "%s finished as %s, not STOP: %d chars of text, usage=%s",
                model,
                finish,
                len(text),
                getattr(response, "usage_metadata", None),
            )
        if not text.strip():
            # An empty completion is indistinguishable, downstream, from a model that had
            # nothing to say: the parser returns {} and the service reports "no grounded
            # memo could be synthesised from the evidence", which reads as a judgement about
            # the evidence rather than as a truncated or blocked response. The reason the
            # API gives is the only thing that separates them, and it was being dropped, so
            # a deployed build produced that sentence with no way to find out why.
            _LOG.warning(
                "empty completion from %s: finish_reason=%s block_reason=%s usage=%s",
                model,
                self._finish_reason(response),
                self._block_reason(response),
                getattr(response, "usage_metadata", None),
            )
        return LlmResponse(
            text=text,
            usage=self._map_usage(getattr(response, "usage_metadata", None)),
            model=model,
        )

    @staticmethod
    def _finish_reason(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return "no-candidates"
        reason = getattr(candidates[0], "finish_reason", None)
        return getattr(reason, "name", None) or str(reason)

    @staticmethod
    def _block_reason(response: Any) -> str:
        feedback = getattr(response, "prompt_feedback", None)
        reason = getattr(feedback, "block_reason", None) if feedback else None
        return getattr(reason, "name", None) or str(reason)

    def classify(self, text: str, labels: list[str]) -> str:
        """Cheap single-label classification using the triage-tier model."""
        client = self._get_client()
        from google.genai import types

        prompt = (
            "Classify the text into exactly one of these labels: "
            f"{', '.join(labels)}.\n"
            "Reply with the single label only, no punctuation or explanation.\n\n"
            f"Text:\n{text}"
        )
        response = client.models.generate_content(
            model=self._models.triage,
            # One turn, passed as a Content rather than a one-element list: the SDK's
            # `contents` union accepts either, and a list of Content is not assignable to
            # a list of the union it declares (lists are invariant), which the newer
            # google-genai stubs now say out loud.
            contents=types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=16,
                thinking_config=types.ThinkingConfig(
                    thinking_level=self._thinking_level(ThinkingLevel.MINIMAL, types)
                ),
            ),
        )
        raw = (getattr(response, "text", "") or "").strip()
        return self._match_label(raw, labels)

    def _to_contents(self, request: LlmRequest) -> list[Any]:
        """Messages as text parts, with any attached documents on the first user turn.

        Documents ride with the prompt rather than as a separate turn because the model
        reads them as context for the instruction, not as a conversation. Sending the
        file rather than its text layer is what lets an answer name the page a figure sat
        on, which is the difference between a citation a reviewer can click and one they
        have to go looking for.
        """
        from google.genai import types

        document_parts = [
            types.Part.from_bytes(data=document.content, mime_type=document.mime_type)
            for document in request.documents
            if document.content
        ]

        contents: list[Any] = []
        for message in request.messages:
            role = "model" if message.role == "model" else "user"
            parts = [types.Part.from_text(text=message.content)]
            if document_parts and role == "user":
                parts = [*document_parts, *parts]
                document_parts = []  # attach once, to the first user turn
            contents.append(types.Content(role=role, parts=parts))
        if document_parts:
            # Documents with no message to attach to still have to be sent.
            contents.append(types.Content(role="user", parts=document_parts))
        return contents

    def _build_config(self, request: LlmRequest, types: Any) -> Any:
        kwargs: dict[str, Any] = {
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "thinking_config": types.ThinkingConfig(
                thinking_level=self._thinking_level(request.thinking, types)
            ),
        }
        if request.system_instruction:
            kwargs["system_instruction"] = request.system_instruction
        if request.response_schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = request.response_schema
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _thinking_level(level: ThinkingLevel, types: Any) -> Any:
        """Map the domain :class:`ThinkingLevel` to the SDK ``ThinkingLevel``.

        Gemini 3 exposes discrete thinking levels (``LOW`` / ``HIGH``); MEDIUM and above
        are treated as HIGH so credit reasoning runs at full depth.
        """
        mapping = {
            ThinkingLevel.MINIMAL: types.ThinkingLevel.LOW,
            ThinkingLevel.LOW: types.ThinkingLevel.LOW,
            ThinkingLevel.MEDIUM: types.ThinkingLevel.HIGH,
            ThinkingLevel.HIGH: types.ThinkingLevel.HIGH,
        }
        return mapping.get(level, types.ThinkingLevel.HIGH)

    @staticmethod
    def _map_usage(usage_metadata: Any) -> TokenUsage:
        if usage_metadata is None:
            return TokenUsage()
        return TokenUsage(
            input_tokens=int(getattr(usage_metadata, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage_metadata, "candidates_token_count", 0) or 0),
            thinking_tokens=int(getattr(usage_metadata, "thoughts_token_count", 0) or 0),
        )

    @staticmethod
    def _match_label(raw: str, labels: list[str]) -> str:
        if not labels:
            return raw
        lowered = raw.lower()
        for label in labels:
            if label.lower() == lowered:
                return label
        for label in labels:
            if label.lower() in lowered:
                return label
        return labels[0]
