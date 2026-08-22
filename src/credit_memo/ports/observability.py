"""Observability ports — the A5 (audit/trace) and A4 (eval gate) concerns.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit (rule
R2), **Cloud Trace via OpenTelemetry** for the reasoning-loop traces (message content
capture OFF so borrower PII never reaches a span), and the **Gen AI evaluation
service** plus the **A4 promotion gate** for model-risk (rule R5).

Two of the three ports below are re-exported, not declared. ``ObservabilityTracerPort`` (with
its :class:`~hex_service_kit.observability.TokenUsage`) lives in ``hex-service-kit`` and
``EvaluationGatePort`` (with its :class:`~agent_eval_kit.report.EvalReport`) lives in
``agent-eval-kit``, because sixteen repositories had each hand-copied them and by the time
anyone compared the copies they disagreed: one had dropped the eval port entirely, two had
dropped its ``gate`` method, which is the half that can refuse a promotion. A Protocol copied
into N repositories is N Protocols.

``AuditSinkPort`` stays declared here on purpose: it is typed in this repo's own vocabulary
(:class:`~credit_memo.domain.models.AuditEvent`, which carries the memo's citations and
borrower-scoped metadata), so it is not a shared shape and re-exporting it would mean pushing a
domain type into the commons to satisfy an annotation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort as EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort as ObservabilityTracerPort
from hex_service_kit.observability import TokenUsage as TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable, already-redacted audit record (WORM)."""
        ...


__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
