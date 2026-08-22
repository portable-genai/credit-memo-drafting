"""On-prem placeholder for ``EvaluationGatePort`` — the sovereign target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed/platform
profiles this port binds to the Gen AI evaluation service / the A4 gate; switching
``profile`` to ``onprem`` rebinds it here. The adapter constructs cleanly with **no
external dependencies** and structurally satisfies the same Protocol as the managed
adapter, so the contract tests prove interface parity. Porting B2 on-premise is *only* a
matter of filling these bodies in: the domain orchestration and service callers do not
change.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import EvalReport

_MESSAGE = (
    "On-prem EvaluationGatePort adapter is a migration placeholder; implement against "
    "your on-premise eval platform. Core domain logic is unchanged."
)


class OnPremEvalAdapter:
    """Placeholder evaluation-gate adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, dataset_path: str) -> EvalReport:
        raise NotImplementedError(_MESSAGE)

    def gate(self, target: str) -> bool:
        raise NotImplementedError(_MESSAGE)
