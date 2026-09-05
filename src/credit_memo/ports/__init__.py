"""Ports — the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` so adapters need only structural conformance and
contract tests can verify any adapter (GCP, remote-platform, or on-prem placeholder)
satisfies the same contract.
"""

from .analysis_bundle import AnalysisBundlePort as AnalysisBundlePort
from .export import ExportPort as ExportPort
from .extraction import DocumentExtractionPort
from .generation import LLMPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import EndUserAuthUnavailableError, IdentityPort
from .knowledge_base import KnowledgeBaseClientPort
from .observability import (
    AuditSinkPort,
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .peer_data import PeerDataPort
from .policy_pack import PolicyPackPort as PolicyPackPort
from .review_router import ReviewRouterPort
from .safety import GuardrailPort, PIIRedactionPort
from .spread_extraction import SpreadExtractionPort as SpreadExtractionPort

__all__ = [
    "DocumentExtractionPort",
    "KnowledgeBaseClientPort",
    "PeerDataPort",
    "LLMPort",
    "GuardrailPort",
    "PIIRedactionPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "EvaluationGatePort",
    "TokenUsage",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "EndUserAuthUnavailableError",
    "ReviewRouterPort",
]
