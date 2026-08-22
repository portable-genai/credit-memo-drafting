"""Safety ports — the A1 Guardrail Gateway concerns, expressed as interfaces (rule R1).

Primary GCP adapters: **Model Armor** (prompt-injection / jailbreak / RAI / malicious
URL screening via ``sanitizeUserPrompt`` / ``sanitizeModelResponse`` on the regional
host) and **Sensitive Data Protection / DLP** (``deidentifyContent``) for GA-grade PII
redaction before any model call or audit write (P-04, minimise data to the model).

B2 ships interchangeable adapters behind each port: a direct-GCP adapter (so the memo
assistant runs standalone), a ``platform`` HTTP client that delegates to the shared
``agent-guardrail-gateway`` service when deployed inside the platform, and an
on-prem placeholder.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Direction, GuardrailVerdict, RedactionResult


@runtime_checkable
class GuardrailPort(Protocol):
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound memo text; may sanitise in place."""
        ...


@runtime_checkable
class PIIRedactionPort(Protocol):
    def redact(self, text: str) -> RedactionResult:
        """De-identify PII so the result is safe to send to a model or audit sink."""
        ...
