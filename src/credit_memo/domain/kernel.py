"""Vertical-neutral domain kernel: the contracts a fork never edits.

This module is the **physical** kernel seam, not a re-export shim. It owns the
vertical-neutral machinery -- provenance and citations, the LLM envelope, safety
verdicts, the audit record, the evaluation report, agent-discovery cards and the
shared severity scale -- and it depends on **nothing** inside this package. In
particular it does not import :mod:`credit_memo.domain.models`; the dependency runs
the other way, so a fork can lift this module (and the ports typed against it) and
rewrite the vertical artifacts in ``models`` without touching a line here.

Like ``models`` it is standard-library only (plus the shared commons), with no
dependency on Google Cloud, ADK or FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_eval_kit.report import EvalMetricResult as EvalMetricResult
from agent_eval_kit.report import EvalReport as EvalReport
from hex_service_kit import StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single clock the domain uses)."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Retrieval & citation
# --------------------------------------------------------------------------- #
class SourceType(StrEnum):
    """Every citation names which kind of evidence it points to."""

    FILING = "filing"  # a borrower filing / financial-statement extract
    POLICY = "policy"  # a credit-policy / sector-context passage (via A2)
    PEER_DATA = "peer_data"  # a peer-comparison data point


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to every generated claim in the credit memo.

    A credit memo an officer cannot trace is worthless: every figure, covenant and
    risk statement must point back to its exact source filing, policy passage or peer
    data point (and page where known).
    """

    source_id: str
    source_type: SourceType
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    """A passage retrieved from the governed RAG store (A2) for a borrower."""

    text: str
    citation: Citation
    score: float = 0.0
    acl_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 10
    acl_principals: tuple[str, ...] = ()  # case ACL principals for governed retrieval
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebCitation:
    """Provenance for a public-web grounded fact (secondary, cross-border)."""

    title: str
    url: str
    snippet: str = ""


# --------------------------------------------------------------------------- #
# Generation (LLM)
# --------------------------------------------------------------------------- #
class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.0  # omitted at a call site means this value; it must not sample
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# ``TokenUsage`` is NOT declared here. It is re-exported from
# ``hex_service_kit.observability`` at the top of this module. Sixteen repositories had each
# hand-copied the same three int fields, which is a shared value type that had simply never been
# shared, and a copied type is a type that drifts the first time one copy is edited. Importing it
# means there is exactly one definition to change; ``tests/contract/test_port_parity.py`` asserts
# object IDENTITY with the commons class, which a look-alike copy cannot satisfy.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    web_citations: tuple[WebCitation, ...] = ()
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Safety (guardrail + PII redaction) — A1 Guardrail Gateway concerns (rule R1)
# --------------------------------------------------------------------------- #
class GuardrailCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    HATE = "hate"
    HARASSMENT = "harassment"
    SEXUAL = "sexual"
    DANGEROUS = "dangerous"
    OTHER = "other"


class Direction(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    category: GuardrailCategory
    confidence: str  # e.g. "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    # Text after any inline sanitisation the guardrail applied (may equal input).
    sanitized_text: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RedactionFinding:
    info_type: str  # e.g. "PERSON_NAME", "SG_NRIC_FIN", "IBAN_CODE"
    count: int = 1


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str  # de-identified text safe to send to the model / audit log
    findings: tuple[RedactionFinding, ...] = ()

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


# --------------------------------------------------------------------------- #
# Audit & observability — A5 Observability, Audit & FinOps concerns (rule R2)
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one credit-memo interaction.

    Prompt and response are stored **already redacted** (P-04): borrower PII is removed
    at the boundary before it is ever written to the audit sink or a trace span.
    """

    action: str  # "build_credit_memo" | "extract_covenants" | "flag_risks" | ...
    actor: str  # authenticated credit officer / service identity
    decision: Decision
    redacted_prompt: str
    redacted_response: str
    citations: tuple[Citation, ...] = ()
    resource: str = "credit-memo"
    trace_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Evaluation gate — A4 AI Quality & Model-Risk concerns (rule R5)
# --------------------------------------------------------------------------- #
# ``EvalMetricResult`` and ``EvalReport`` are NOT declared here either. They are re-exported from
# ``agent_eval_kit.report`` at the top of this module (the submodule, not the package root: the
# root pulls httpx in via the gate client, and this module promises to be stdlib-only).
#
# The commons ``EvalReport`` is a strict superset of a locally declared one: same
# ``dataset`` / ``results`` / ``n_examples``, same fail-closed ``passed`` rule
# (``n_examples > 0 and bool(results) and all(...)``, so a report that scored nothing still
# refuses to certify a promotion), plus the durable evidence fields a remote quality gate
# attaches (run id, dataset version and digest, evaluator, schema version, trace and correlation
# ids, artifact refs, attested). Every one of them is defaulted, so every existing construction
# call compiles unchanged, and the adapter returns the gate client's report with its evidence
# intact rather than rebuilding a thin local copy.


# --------------------------------------------------------------------------- #
# Governance — A3 Agent Registry & Governance concerns (A2A AgentCard, rule R4)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "credit-memo-drafting"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Knowledge-base ingestion (the borrower's governed RAG store IS A2)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class IngestResult:
    document_id: str
    chunks: int = 0
    status: str = "indexed"
    ok: bool = True
    detail: str = ""


# --------------------------------------------------------------------------- #
# Shared severity scale
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
