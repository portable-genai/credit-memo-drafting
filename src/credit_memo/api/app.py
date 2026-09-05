"""FastAPI application for the B2 Credit-Memo / Underwriting Assistant.

Exposes the credit-memo endpoints (full memo, covenant extraction, risk-flag
identification) plus health and the A2A AgentCard at ``/.well-known/agent-card.json``.
The React/Next.js UI and the CLI consume this surface.

Design constraints:

* **Import-safe.** Building the :class:`~credit_memo.config.Container` is deferred to
  request time via the ``deps`` factories, so importing this module (or ``app``) never
  touches Google Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **Guardrail blocks are not 500s.** A :class:`GuardrailBlockedError` from a service is
  translated to an HTTP 200 carrying an explicit blocked envelope flagged for human
  review, never a 500.
* **Region pinned** to ``asia-southeast1`` (Singapore) for data residency (SPEC §2).

Run locally with ``python -m credit_memo.api.app`` (uvicorn on :8093).
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from hex_service_kit import cors_allowlist, resolve_bind_host
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import end_user_auth_kind
from ..domain import _grounded as g
from ..domain import entitlements
from ..domain import models as m
from ..domain.errors import (
    AnalysisNotFoundError,
    BorrowerAccessDeniedError,
    GuardrailBlockedError,
    RetrievalEmptyError,
)
from ..domain.services import CreditMemoService
from ..envread import boolean_setting, read_env_setting, setting_or_default
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AgentCardModel,
    AnalysisBuildRequest,
    AnalysisManifestModel,
    CovenantListResponse,
    CovenantRequest,
    CreditMemoRequest,
    CreditMemoResponse,
    DocumentUploadResponse,
    HealthResponse,
    RiskFlagListResponse,
    RiskFlagRequest,
    to_domain_memo,
)
from .security import CurrentPrincipal

_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Embedding-surface controls. In secure/embedded mode the agent is served same-origin via
# the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone dev
# case, CREDIT_MEMO_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# CREDIT_MEMO_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins
# permitted to iframe the assistant UI.
_CORS_ORIGINS_ENV = "CREDIT_MEMO_CORS_ORIGINS"
_FRAME_ANCESTORS_ENV = "CREDIT_MEMO_FRAME_ANCESTORS"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a sandboxed iframe presents a null origin,
#: so ``frame-ancestors null`` admits framing from a document whose own origin the browser has
#: already decided not to trust, and a null CORS origin trusts the same document WITH
#: credentials. ``'*'`` is the quoted form CSP also honours and ``*.*`` is the subdomain
#: wildcard; both carry an asterisk, and both are named here so the set reads as the complete
#: refusal rather than as a list of leftovers. Matching is exact, so ``https://nullify.example``
#: remains a perfectly good origin. The same four are refused in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: list[str] | tuple[str, ...], setting: str) -> None:
    """An origin policy naming everybody is not an allowlist, so refuse to boot with one.

    "never ``*``" was written in the comment above and enforced nowhere, which is the same
    as unenforced: the shared ``cors_allowlist`` docstring promises it never returns ``*``
    while its set-and-valid branch returns exactly what the operator wrote. ``*`` in the CORS
    allowlist trusts every origin WITH credentials, and in frame-ancestors it lets any page
    on the internet frame the console and drive it as the signed-in user. The rule catches a
    wildcard hiding inside an origin too (``https://*.example``): a legitimate origin has no
    ``*`` anywhere in it, so this refuses no configuration a deployment could correctly hold.

    The asterisk test alone was not the whole rule. ``null`` carries no asterisk, so it passed
    both allowlists and reached ``CORSMiddleware`` and the CSP directive verbatim: see
    :data:`_WILDCARD_TOKENS`. The two halves are a UNION, and the union is what
    ``ui/lib/csp.mjs`` already enforced for the document a browser actually frames, so until
    now the two surfaces disagreed about what an origin policy may hold.
    """
    offending = [origin for origin in origins if "*" in origin or origin in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{setting} origin policy must never contain a wildcard, got {offending}. "
            "Name each permitted origin in full."
        )


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``CREDIT_MEMO_FRAME_ANCESTORS``; an emptied value REFUSES framing.

    Unset keeps the shipped ``'self'``. A value naming no origin would emit the
    header ``Content-Security-Policy: frame-ancestors`` with an empty directive, which is a
    CSP parse error, so browsers dropped the directive and the clickjacking restriction went
    with it (and the ``'self'`` branch below was skipped at the same moment, so the
    X-Frame-Options backstop went too).

    A read that folds set-and-empty into unset and hands both ``'self'`` stops the valueless
    directive, but it also silently overrides the operator: emptying an
    allowlist is an expressed intent and it means "nobody may frame this", which CSP spells
    ``'none'``, not "same origin may". Unset and set-and-empty are different answers, so they
    get different results, the same way every other edge variable in the fleet resolves.
    """
    if raw is None:
        return "'self'"
    ancestors = raw.split()
    _refuse_wildcard(ancestors, _FRAME_ANCESTORS_ENV)
    return " ".join(ancestors) or "'none'"


_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV).raw)


def _frame_options(frame_ancestors: str) -> str:
    """The X-Frame-Options equivalent of ``frame_ancestors``, or "" where none exists.

    X-Frame-Options is the pre-CSP header, and browsers that understand frame-ancestors
    ignore it, so it is only a backstop for the ones that do not. It can express exactly two
    of the three states: ``'self'`` is SAMEORIGIN and ``'none'`` is DENY. It cannot express an
    allowlist (ALLOW-FROM was never widely implemented and is gone), so a named parent origin
    gets no backstop rather than a DENY that would break the embed it was configured for.
    """
    if frame_ancestors == "'self'":
        return "SAMEORIGIN"
    if frame_ancestors == "'none'":
        return "DENY"
    return ""


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*"; the localhost dev fallback applies ONLY under a
    DELIBERATELY chosen local profile (shared hex-service-kit rule).

    Keyed off ``exposure_profile`` rather than the raw profile: granting cross-origin
    credentialed access to localhost is a relaxation, so a run that never named a profile
    must not look like ``local`` here and gets an empty allowlist instead.

    The CONFIGURED value is judged by :func:`_refuse_wildcard` before the kit is called, and
    that ordering is the point rather than an accident. ``cors_allowlist`` now refuses a
    wildcard itself, raising ``InsecureCorsError``, so whichever of the two runs first is the
    one that decides which message an operator reads. This repo owns the rule: it names the
    variable, and its union covers the behavioural tokens as well as the asterisk. Running it
    first keeps it the single authority and leaves the kit an unreachable backstop on the
    configured path. The trailing call still guards the RESOLVED list, which under the unset
    default is a value the operator never wrote.
    """
    setting = read_env_setting(_CORS_ORIGINS_ENV)
    if setting.has_value:
        _refuse_wildcard(
            [origin.strip() for origin in setting.value.split(",") if origin.strip()],
            _CORS_ORIGINS_ENV,
        )
    resolved = cors_allowlist(
        deps.get_settings().profile_choice.exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )
    _refuse_wildcard(resolved, _CORS_ORIGINS_ENV)
    return resolved


app = FastAPI(
    title="B2 Credit-Memo / Underwriting Assistant",
    version="0.1.0",
    description=(
        "Grounded underwriting assistant that turns a borrower's financial statements and "
        "filings into a cited credit memo (financial analysis, covenants with a "
        "deterministic compliance status, risk flags, and peer comparisons), with a full "
        "audit trail, on the Gemini Enterprise Agent Platform. Decision support, not a "
        "credit decision. Region asia-southeast1."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the assistant)."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if deps.get_settings().profile in {"gcp", "platform"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    frame_options = _frame_options(_FRAME_ANCESTORS)
    if frame_options:
        response.headers["X-Frame-Options"] = frame_options
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every end-user route answers 401; but
#      /healthz and the agent card would still answer a stranger, and a deployment in that
#      state has no business being reachable at all. It is also the one case where a settings
#      file that bound a verifying adapter must NOT buy the relaxation: unset is not consent,
#      whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote (client-asserted)
#      and the on-premises placeholder resolves nobody at all (unimplemented); neither
#      authenticates anyone, so neither may switch this off. Note that the seeded adapter is
#      bound under `live` as well as `local`, which a rule keyed on the profile string would
#      have missed.
_END_USER_AUTHENTICATED = deps.get_settings().profile_explicit and end_user_auth_kind() == VERIFIED

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as
# `local`; this widens the same rule to every posture that cannot authenticate an end user, so
# the start-up bound in `main()` and the request-time guard agree instead of one binding every
# interface while the other refuses every caller on it. Without this, `live` would bind
# 0.0.0.0 while the guard refused every peer that reached it.
_BIND_PROFILE = (
    deps.get_settings().profile_choice.bind_profile if _END_USER_AUTHENTICATED else "local"
)

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the APP
# OBJECT, not to `main()`: the Dockerfile CMD is
# `uvicorn credit_memo.api.app:app --host 0.0.0.0 --port ${PORT}`, so a guard reachable only
# from `main()` never runs in a shipped process and the seeded personas would be served to the
# LAN.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="CREDIT_MEMO_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().profile_choice.exposure_profile,
)


def _blocked_response(detail: str, reason: str) -> JSONResponse:
    """A 200 JSON body for a guardrail-blocked request (flagged for human review)."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "blocked": True,
            "requires_human_review": True,
            "detail": detail,
            "reason": reason or "blocked",
        },
    )


def _denied_response(exc: BorrowerAccessDeniedError) -> JSONResponse:
    """403 for a failed server-side borrower entitlement check (never a data leak)."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


def _ungrounded_response(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": detail},
    )


# --------------------------------------------------------------------------- #
# Borrower documents (the audience-data path)
# --------------------------------------------------------------------------- #
# A private borrower has no EDGAR record, so its evidence must be brought to the demo:
# an uploaded financial statement goes through the same extract -> governed FTS ingest
# (borrower + tenant ACL) path as pipeline filings, and the next memo build for that
# borrower retrieves it.
_UPLOAD_MAX_BYTES = 20 * 1024 * 1024  # one document per upload
_UPLOAD_TEMPLATE = (
    "field,required,example,notes\n"
    "file,yes,acme-2025-audited-financials.pdf,PDF or plain text; one document per upload\n"
    "borrower_id,yes,acme-manufacturing-pte-ltd,Lowercase borrower id "
    "(the UI derives it from the borrower name)\n"
    "title,yes,Acme 2025 Audited Financial Statements,Shown in citations\n"
    "doc_type,no,financial_statement,financial_statement | filing | loan_agreement | "
    "covenant_certificate | other\n"
)


@app.get("/v1/documents/template", tags=["documents"], response_class=Response)
def document_upload_template() -> Response:
    """The upload contract as a downloadable CSV (one row per form field)."""
    return Response(
        content=_UPLOAD_TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="borrower-upload-template.csv"'},
    )


@app.post(
    "/v1/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["documents"],
)
async def upload_borrower_document(
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File(description="The borrower document (PDF or text)")],
    borrower_id: Annotated[str, Form(min_length=1, max_length=120)],
    title: Annotated[str, Form(min_length=3, max_length=200)],
    doc_type: Annotated[str, Form()] = "financial_statement",
) -> DocumentUploadResponse | JSONResponse:
    """Ingest one borrower document into the governed evidence store."""
    # Same object-level authorization as the memo build: the borrower ACL comes from the
    # VERIFIED principal, never from the request body alone.
    try:
        entitlements.borrower_scope(principal, borrower_id)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    try:
        kind = m.DocType(doc_type)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": f"unknown doc_type {doc_type!r}"},
        )
    content = await file.read(_UPLOAD_MAX_BYTES + 1)
    if len(content) > _UPLOAD_MAX_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": f"document exceeds the {_UPLOAD_MAX_BYTES} byte limit"},
        )
    if not content:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "uploaded file is empty"},
        )

    document_id = f"upload-{borrower_id}-{_slug(title)}"
    filing = m.Filing(
        id=document_id,
        doc_type=kind,
        uri=f"upload://{document_id}",
        title=title.strip(),
    )
    acl_tags = entitlements.borrower_acl(borrower_id, principal.tenant)
    container = deps.get_container()
    result = container.knowledge_base.ingest(filing, content, acl_tags)
    if not result.ok or result.chunks == 0:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": f"no indexable text found: {result.detail}"},
        )
    return DocumentUploadResponse(
        document_id=result.document_id,
        borrower_id=borrower_id,
        chunks=result.chunks,
        detail=result.detail,
    )


def _header_filename(name: str) -> str:
    """A filename safe to put in a header, with its extension intact.

    ``_slug`` was the wrong tool here: it lowercases and replaces every non-alphanumeric
    run with a hyphen, so ``acme-fs.txt`` became ``acme-fs-txt`` and the browser lost the
    only hint it had about how to display the file. This strips the characters that would
    break the header (quotes, control characters, path separators) and keeps the rest.
    """
    cleaned = "".join(c for c in name if c.isprintable() and c not in '"\\/\r\n').strip()
    return cleaned[:120] or "document"


def _slug(text: str) -> str:
    import re as _re

    return _re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


# --------------------------------------------------------------------------- #
# Analyses (the stateless intake path)
# --------------------------------------------------------------------------- #
# An analysis is one question, the files uploaded to answer it, and the memo built from
# them. It expires on a schedule the console prints. There is no document library here
# and no memo of record: a user brings the evidence each time, which is what makes them
# responsible for its freshness and able to see exactly what was used.
_ANALYSIS_STAGES = (
    "received",
    "extracted",
    "retrieved",
    "computed",
    "drafted",
    "assembled",
)


def _new_analysis_id() -> str:
    import uuid

    return f"an-{uuid.uuid4().hex[:20]}"


@app.post("/v1/analyses", response_model=AnalysisManifestModel, status_code=201, tags=["analyses"])
async def open_analysis(
    principal: CurrentPrincipal,
    borrower_id: Annotated[str, Form(min_length=1, max_length=120)],
    files: Annotated[list[UploadFile], File(description="The credit file for this analysis")],
    doc_types: Annotated[str, Form()] = "",
    declared_as_of: Annotated[str, Form()] = "",
) -> AnalysisManifestModel | JSONResponse:
    """Open an analysis and put its evidence in custody for the retention window.

    ``doc_types`` and ``declared_as_of`` are comma-separated and positional against
    ``files``. ``declared_as_of`` is the uploader's own statement of how current each
    document is: the service cannot tell a management account printed yesterday from one
    printed last year, and inventing a date would put a freshness claim in the memo that
    nobody made.
    """
    try:
        entitlements.borrower_scope(principal, borrower_id)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)

    container = deps.get_container()
    limits = container.settings.analysis_bundle
    if len(files) > limits.max_documents:
        return _ungrounded_response(
            f"an analysis takes at most {limits.max_documents} documents; {len(files)} were sent"
        )

    kinds = [k.strip() for k in doc_types.split(",")] if doc_types else []
    as_of = [d.strip() for d in declared_as_of.split(",")] if declared_as_of else []
    # The bundle is tagged by TENANT, not by borrower. A borrower tag here would be
    # unreadable: a later request knows the analysis id but not yet whose analysis it is,
    # so it could not hold the tag needed to read the manifest that would tell it. The
    # analysis id is an unguessable capability, the tenant tag stops it crossing a bank,
    # and borrower entitlement is checked explicitly on every route against the borrower
    # the manifest actually names.
    acl_tags = _tenant_tags(principal)
    acl_principals = _analysis_principals(principal)

    analysis_id = _new_analysis_id()
    bundle = container.analysis_bundle
    bundle.create(analysis_id, borrower_id, acl_tags, created_by=principal.actor)

    for index, upload in enumerate(files):
        content = await upload.read(limits.max_upload_bytes + 1)
        if len(content) > limits.max_upload_bytes:
            bundle.delete(analysis_id, acl_principals)
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "detail": (
                        f"{upload.filename!r} exceeds the {limits.max_upload_bytes} byte limit"
                    )
                },
            )
        if not content:
            continue
        raw_kind = kinds[index] if index < len(kinds) else ""
        try:
            kind = m.DocType(raw_kind) if raw_kind else m.DocType.OTHER
        except ValueError:
            bundle.delete(analysis_id, acl_principals)
            return _ungrounded_response(f"unknown doc_type {raw_kind!r}")
        bundle.put_document(
            analysis_id,
            content,
            filename=upload.filename or f"document-{index + 1}",
            doc_type=kind,
            acl_principals=acl_principals,
            mime_type=upload.content_type or "",
            declared_as_of=as_of[index] if index < len(as_of) else "",
            uploaded_by=principal.actor,
        )

    manifest = bundle.manifest(analysis_id, acl_principals)
    if not manifest.documents:
        bundle.delete(analysis_id, acl_principals)
        return _ungrounded_response(
            "no readable document was uploaded; a memo is only ever built on evidence you supply"
        )
    _audit_artifact(
        container,
        action="open_analysis",
        actor=principal.actor,
        prompt=f"analysis {analysis_id} for borrower {borrower_id}",
        response=f"documents={manifest.document_count}",
    )
    return AnalysisManifestModel.from_domain(manifest)


@app.get("/v1/analyses/{analysis_id}", response_model=AnalysisManifestModel, tags=["analyses"])
def read_analysis(
    analysis_id: str, principal: CurrentPrincipal
) -> AnalysisManifestModel | JSONResponse:
    """What this analysis was given, and until when it can be reopened."""
    container = deps.get_container()
    try:
        manifest = container.analysis_bundle.manifest(analysis_id, _analysis_principals(principal))
    except AnalysisNotFoundError as exc:
        return _analysis_gone(exc)
    return AnalysisManifestModel.from_domain(manifest)


@app.get("/v1/analyses/{analysis_id}/documents/{document_id}", tags=["analyses"])
def read_analysis_document(
    analysis_id: str, document_id: str, principal: CurrentPrincipal
) -> Response:
    """Serve one uploaded file back, inline, so a citation can open the page it names.

    ``Content-Disposition: inline`` on purpose: the console appends ``#page=N`` and the
    browser's own viewer scrolls there. An attachment would download the file instead,
    which is not what "click the citation" means.
    """
    container = deps.get_container()
    principals = _analysis_principals(principal)
    try:
        manifest = _read_analysis(analysis_id, principal)
        content = container.analysis_bundle.get_document(analysis_id, document_id, principals)
    except AnalysisNotFoundError as exc:
        return _analysis_gone(exc)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    record = next((d for d in manifest.documents if d.id == document_id), None)
    return Response(
        content=content,
        media_type=(record.mime_type if record else "") or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'inline; filename="{_header_filename(record.filename if record else document_id)}"'
            )
        },
    )


@app.delete("/v1/analyses/{analysis_id}", status_code=204, tags=["analyses"])
def delete_analysis(analysis_id: str, principal: CurrentPrincipal) -> Response:
    """Delete the analysis now, rather than waiting for the retention window."""
    container = deps.get_container()
    # Already gone is the outcome the caller asked for, so deleting twice is not an error.
    with contextlib.suppress(AnalysisNotFoundError):
        container.analysis_bundle.delete(analysis_id, _analysis_principals(principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/v1/analyses/{analysis_id}/build", response_model=CreditMemoResponse, tags=["analyses"])
def build_analysis_memo(
    analysis_id: str,
    body: AnalysisBuildRequest,
    principal: CurrentPrincipal,
    service: Annotated[CreditMemoService, Depends(deps.get_credit_memo_service)],
) -> JSONResponse | CreditMemoResponse:
    """Build the memo from the evidence already in this analysis.

    The borrower comes from the bundle, not the body: the caller cannot point a build at
    one analysis and claim it is about a different borrower.
    """
    container = deps.get_container()
    principals = _analysis_principals(principal)
    try:
        manifest = _read_analysis(analysis_id, principal)
    except AnalysisNotFoundError as exc:
        return _analysis_gone(exc)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)

    try:
        memo_input = m.MemoInput(
            borrower=m.Borrower(id=manifest.borrower_id, name=manifest.borrower_id),
            request=body.request.to_domain() if body.request is not None else None,
            spreads=tuple(s.to_domain(manifest.borrower_id) for s in body.spreads),
            analysis_id=analysis_id,
        )
    except ValueError as exc:
        return _ungrounded_response(str(exc))

    try:
        memo = service.build(
            memo_input,
            principal.actor,
            principals=principal.principals,
            tenant=principal.tenant,
        )
    except GuardrailBlockedError as exc:
        return _blocked_response(
            "This credit-memo request was blocked by the safety guardrail and routed for review.",
            str(exc),
        )
    except RetrievalEmptyError as exc:
        return _ungrounded_response(f"No borrower evidence available to ground the memo: {exc}")

    response = CreditMemoResponse.from_domain(memo)
    # The memo lives in the bundle with the evidence it was built from, and dies with it.
    with contextlib.suppress(Exception):
        container.analysis_bundle.put_artifact(
            analysis_id, "memo", response.model_dump(mode="json"), principals
        )
    return response


@app.post("/v1/analyses/{analysis_id}/export", tags=["analyses"])
def export_analysis_memo(
    analysis_id: str, principal: CurrentPrincipal, fmt: str = "docx"
) -> Response:
    """The committee pack, in a format that can leave the application.

    Reads the memo the build stored in the bundle rather than rebuilding it: the pack a
    committee receives must be the memo that was reviewed, not a fresh one that might
    differ because a model was asked again.
    """
    container = deps.get_container()
    principals = _analysis_principals(principal)
    try:
        _read_analysis(analysis_id, principal)
        stored = container.analysis_bundle.get_artifact(analysis_id, "memo", principals)
    except AnalysisNotFoundError as exc:
        return _analysis_gone(exc)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    if stored is None:
        return _ungrounded_response("this analysis has no memo yet; build one before exporting it")

    try:
        payload, content_type = container.export.export(
            to_domain_memo(CreditMemoResponse.model_validate(stored)), fmt
        )
    except ValueError as exc:
        return _ungrounded_response(str(exc))
    except NotImplementedError as exc:
        return _ungrounded_response(str(exc))

    filename = f"credit-memo-{_slug(analysis_id)}.{fmt}"
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/v1/analyses/{analysis_id}/export/formats", tags=["analyses"])
def export_formats(analysis_id: str, principal: CurrentPrincipal) -> Any:
    """Which formats this deployment can actually produce.

    Advertised rather than assumed: the SDK-free profile makes DOCX and HTML and says so,
    instead of offering a PDF button that fails when pressed.
    """
    try:
        _read_analysis(analysis_id, principal)
    except AnalysisNotFoundError as exc:
        return _analysis_gone(exc)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    return {"formats": list(deps.get_container().export.formats())}


def _tenant_tags(principal: Any) -> tuple[str, ...]:
    """The tags an analysis bundle carries. Empty for a single-tenant deployment."""
    return (f"tenant:{principal.tenant}",) if principal.tenant else ()


def _analysis_principals(principal: Any) -> tuple[str, ...]:
    """What this caller holds when reading a bundle: their principals plus their tenant."""
    return (*principal.principals, *_tenant_tags(principal))


def _read_analysis(analysis_id: str, principal: Any) -> Any:
    """The manifest, after checking this caller may read THIS borrower.

    Two checks, in this order and not the other. The tenant tag on the bundle decides
    whether the caller can see the analysis at all; the entitlement check then decides
    whether they may read the borrower it turns out to be about. In this order a caller
    from another bank learns nothing, while a caller from the right bank who is not
    entitled to this borrower gets an honest 403 rather than a confusing 404.

    The bundle is tagged by tenant rather than by borrower for the same reason. A borrower
    tag would be unreadable: a request knows the analysis id but not yet whose analysis it
    is, so it could not hold the tag needed to read the manifest that would tell it.
    """
    manifest = deps.get_container().analysis_bundle.manifest(
        analysis_id, _analysis_principals(principal)
    )
    entitlements.borrower_scope(principal, manifest.borrower_id)
    return manifest


def _analysis_gone(exc: AnalysisNotFoundError) -> JSONResponse:
    """404 for absent, expired, or not-readable alike, so ids cannot be probed."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Artifact endpoints
# --------------------------------------------------------------------------- #
@app.post("/v1/credit-memo", response_model=CreditMemoResponse, tags=["artifacts"])
def build_credit_memo(
    request: CreditMemoRequest,
    principal: CurrentPrincipal,
    service: Annotated[CreditMemoService, Depends(deps.get_credit_memo_service)],
) -> JSONResponse | CreditMemoResponse:
    """Build a full cited credit memo for a borrower and its filings."""
    # The domain refuses a spread holding a figure no engine may read (an unconfirmed
    # extraction, say). That refusal is about what the CALLER sent, so it is a 422 with
    # the domain's own sentence, never a 500 the caller cannot act on.
    try:
        memo_input = request.to_memo_input()
    except ValueError as exc:
        return _ungrounded_response(str(exc))
    # Object-level authorization: the borrower ACL principal is granted server-side from the
    # VERIFIED principal, never from the request body's borrower id alone.
    try:
        entitlements.borrower_scope(principal, memo_input.borrower.id)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    try:
        memo = service.build(
            memo_input,
            principal.actor,
            principals=principal.principals,
            tenant=principal.tenant,
        )
    except GuardrailBlockedError as exc:
        return _blocked_response(
            "This credit-memo request was blocked by the safety guardrail and routed for review.",
            str(exc),
        )
    except RetrievalEmptyError as exc:
        return _ungrounded_response(f"No borrower evidence available to ground the memo: {exc}")
    return CreditMemoResponse.from_domain(memo)


@app.post("/v1/covenants", response_model=CovenantListResponse, tags=["artifacts"])
def extract_covenants(
    request: CovenantRequest, principal: CurrentPrincipal
) -> JSONResponse | CovenantListResponse:
    """Extract covenants (with a deterministic tested status) for a borrower."""
    container = deps.get_container()
    memo_input = request.to_memo_input()
    borrower = memo_input.borrower
    # Object-level authorization, both halves. The entitlement check decides server-side
    # whether this verified caller may read THIS borrower at all (least privilege within the
    # tenant); the tenant tag on the evidence then keeps the subset/fail-closed KB ACL inside
    # the caller's tenant. Neither the borrower id nor the tenant comes from the request body.
    try:
        scope = entitlements.borrower_scope(principal, borrower.id)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    acl_tags = entitlements.borrower_acl(borrower.id, principal.tenant)

    # Ingest the supplied filings into the governed RAG store (best-effort), then ground.
    for document in memo_input.documents:
        try:
            container.knowledge_base.ingest(document, b"", acl_tags)
        except Exception:  # noqa: BLE001 - ingestion is best-effort; retrieval is the gate
            continue
    passages = g.retrieve_passages(
        container.knowledge_base,
        f"financial covenants and thresholds for {borrower.name}",
        acl_principals=scope,
        top_k=container.settings.knowledge_base.top_k,
    )
    if not passages:
        return _ungrounded_response("No evidence available to ground covenant extraction.")
    service = deps.build_covenant_service(container)
    span = container.tracer.span(
        "credit_memo.covenants", action="extract_covenants", actor=principal.actor
    )
    with span if span is not None else nullcontext():
        covenants = service.extract(borrower, passages, principal.actor)
    _audit_artifact(
        container,
        action="extract_covenants",
        actor=principal.actor,
        prompt=f"covenant extraction for borrower {borrower.id}",
        response=(
            f"covenants={len(covenants)}; "
            f"breaches={sum(1 for c in covenants if c.status is m.CovenantStatus.BREACH)}"
        ),
        citations=tuple(c for cov in covenants for c in cov.citations),
    )
    return CovenantListResponse.from_domain(borrower.id, covenants)


@app.post("/v1/risk-flags", response_model=RiskFlagListResponse, tags=["artifacts"])
def flag_risks(
    request: RiskFlagRequest, principal: CurrentPrincipal
) -> JSONResponse | RiskFlagListResponse:
    """Identify credit risk flags for a borrower."""
    container = deps.get_container()
    memo_input = request.to_memo_input()
    borrower = memo_input.borrower
    # Object-level authorization, both halves: see the covenants route above.
    try:
        scope = entitlements.borrower_scope(principal, borrower.id)
    except BorrowerAccessDeniedError as exc:
        return _denied_response(exc)
    acl_tags = entitlements.borrower_acl(borrower.id, principal.tenant)

    for document in memo_input.documents:
        try:
            container.knowledge_base.ingest(document, b"", acl_tags)
        except Exception:  # noqa: BLE001 - ingestion is best-effort; retrieval is the gate
            continue
    passages = g.retrieve_passages(
        container.knowledge_base,
        f"credit risks and sector context for {borrower.name}",
        acl_principals=scope,
        top_k=container.settings.knowledge_base.top_k,
    )
    if not passages:
        return _ungrounded_response("No evidence available to ground risk-flag identification.")
    service = deps.build_risk_flag_service(container)
    span = container.tracer.span(
        "credit_memo.risk_flags", action="flag_risks", actor=principal.actor
    )
    with span if span is not None else nullcontext():
        flags = service.flag(borrower, passages, principal.actor)
    _audit_artifact(
        container,
        action="flag_risks",
        actor=principal.actor,
        prompt=f"risk-flag identification for borrower {borrower.id}",
        response=f"risk_flags={len(flags)}",
        citations=tuple(c for flag in flags for c in flag.citations),
    )
    return RiskFlagListResponse.from_domain(borrower.id, flags)


def _audit_artifact(
    container: Any,
    action: str,
    actor: str,
    prompt: str,
    response: str,
    citations: tuple[m.Citation, ...] = (),
) -> None:
    """Record one artifact build. On a managed profile, a lost record is a failed request.

    Swallowing the write keeps a demo alive and leaves a regulated deployment with an
    artifact nobody can prove was produced. ``local`` still degrades (the append-only
    file may be read-only in a sandbox); ``gcp`` and ``platform`` raise, because there
    the audit sink IS the record of what the bank did.
    """
    event = m.AuditEvent(
        action=action,
        actor=actor,
        decision=m.Decision.ESCALATED,
        redacted_prompt=prompt,
        redacted_response=response,
        citations=citations,
        metadata={"direction": "output", "requires_human_review": "true"},
    )
    try:
        container.audit.record(event)
    except Exception:
        if deps.get_settings().profile in {"gcp", "platform"}:
            raise
        return


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness/readiness probe. Reports the active profile and pinned region."""
    settings = deps.get_settings()
    return HealthResponse(
        status="ok",
        profile=settings.profile,
        runtime=settings.runtime,
        generator_model=settings.generator_model,
        region=settings.region,
    )


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list.
    """
    identity = deps.get_container().identity
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this agent's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    return AgentCardModel.from_domain(build_agent_card(deps.get_settings()))


def main() -> None:
    """Run the API locally with uvicorn (Cloud Run / Agent Runtime use this app object)."""
    import uvicorn

    uvicorn.run(
        "credit_memo.api.app:app",
        # Fail-closed bind (shared hex-service-kit rule): the no-auth local
        # profile binds loopback unless CREDIT_MEMO_ALLOW_INSECURE_DEMO=1; secure profiles keep
        # 0.0.0.0 (container-local; ingress is fronted by the platform). Keyed off
        # ``_BIND_PROFILE``, which fails closed in the OPPOSITE direction to the CORS
        # relaxation above: here ``local`` is the restrictive case, so an unconsented run, and
        # any run whose identity binding cannot verify an end user, must look like ``local``
        # and stay on loopback. That is the same value the request-time guard was built with,
        # so the two cannot disagree.
        host=resolve_bind_host(
            _BIND_PROFILE,
            host_env="CREDIT_MEMO_API_HOST",
            insecure_demo_env="CREDIT_MEMO_ALLOW_INSECURE_DEMO",
        ),
        port=int(setting_or_default("PORT", "8093")),
        reload=boolean_setting("CREDIT_MEMO_API_RELOAD"),
    )


if __name__ == "__main__":
    main()
