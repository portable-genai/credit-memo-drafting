"""Domain exceptions for the Credit-Memo / Underwriting Assistant (system B2).

Pure-Python exception hierarchy raised by the orchestration services. The domain
layer never imports Google Cloud, ADK, or any framework: these errors let callers
(API, CLI, the Agent Runtime adapter) react to domain-level failures without
coupling to any vendor SDK error type.
"""

from __future__ import annotations


class CreditMemoError(Exception):
    """Base class for all domain-level errors raised by B2 services."""


class BorrowerAccessDeniedError(CreditMemoError):
    """Raised when a verified principal is not entitled to a borrower's evidence (HTTP 403).

    Object-level authorization: the borrower id arrives in the request body, but the
    entitlement decision is made server-side against the verified Principal (see
    ``domain/entitlements.py``), never from a client-supplied field. Raised rather than
    returning an empty result so the caller cannot distinguish "not entitled" from "no
    evidence" by timing or shape, and so the denial is auditable.
    """


class GuardrailBlockedError(CreditMemoError):
    """Raised/flagged when the A1 guardrail blocks an input or output.

    Because the memo handles borrower financial/PII data (rule R1), a blocked unsafe
    request must never yield a partial memo: the orchestrator raises this rather than
    assembling a CreditMemo from screened-out content.
    """


class RetrievalEmptyError(CreditMemoError):
    """Raised when the governed RAG store (A2) returns no grounding passages.

    A credit memo must be grounded in the borrower's own filings and the credit
    policy/sector context; an empty retrieval after ingestion is treated as a hard
    error so a memo is never built on no evidence.
    """


class GroundingDisabledError(CreditMemoError):
    """Raised when public-web grounding is requested but switched off.

    Grounding is gated by ``grounding_enabled`` (SPEC §2). Callers that explicitly
    require web grounding can raise this rather than silently skipping it.
    """
