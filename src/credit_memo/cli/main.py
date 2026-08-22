"""``credit-memo`` — the Typer CLI for the B2 Credit-Memo / Underwriting Assistant.

This is a thin presentation layer over the domain services. It owns no business logic:
every command builds the wiring from :func:`credit_memo.config.build_container` and the
factory functions in :mod:`credit_memo.api.deps`, invokes one domain service, and
pretty-prints the cited result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. the ``[project.scripts]`` entry point, or
  ``--help``) must never pull in FastAPI, uvicorn, the Google Cloud SDKs, or even the
  domain services. All of those are imported *lazily inside command bodies*, so the
  on-prem/test profile (which installs no Google Cloud SDK) can still load the CLI.
* **Profile-aware.** ``CREDIT_MEMO_PROFILE`` selects the adapter stack. The ``onprem``
  profile binds placeholder adapters that raise ``NotImplementedError``; when a command
  trips one, the CLI fails clearly (exit code 2) with a message that names the migration
  target.
* **Citations are first-class.** Every artifact is printed with source-and-page
  provenance, because a credit memo a credit officer cannot trace is worthless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import Container
    from ..domain.models import Citation, Covenant, CreditMemo, RiskFlag

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "B2 Credit-Memo / Underwriting Assistant — cited credit memos from a borrower's "
        "financial statements and filings, on the Gemini Enterprise Agent Platform "
        "(region asia-southeast1). Decision support, not a credit decision."
    ),
)

_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1
_CLI_ACTOR = "cli:operator"


def _container() -> Container:
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (credit_memo.api.deps) are unavailable: {exc}", code=_RUNTIME_EXIT
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors."""
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(f"'{action}' has no adapter wired for profile '{profile}': {exc}", code=_PROFILE_EXIT)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _fmt_citation(c: Citation) -> str:
    page = f" p.{c.page}" if c.page is not None else ""
    st = c.source_type.value if hasattr(c.source_type, "value") else str(c.source_type)
    url = f" — {c.url}" if c.url else ""
    return f"[{c.source_id}, {st}{page}]{url}"


def _echo_citations(citations: tuple[Citation, ...], indent: str = "  ") -> None:
    if not citations:
        typer.secho(f"{indent}(no citations)", fg=typer.colors.YELLOW)
        return
    typer.secho(f"{indent}Citations:", bold=True)
    for c in citations:
        typer.echo(f"{indent}  - {_fmt_citation(c)}")


def _echo_review_banner(requires_review: bool) -> None:
    if requires_review:
        typer.secho(
            "  [HUMAN REVIEW REQUIRED] maker-checker gate (P-06) — decision support only; "
            "a credit officer must review before relying on this memo.",
            fg=typer.colors.YELLOW,
            bold=True,
        )


def _print_covenants(covenants: tuple[Covenant, ...], indent: str = "  ") -> None:
    if not covenants:
        return
    typer.secho(f"{indent}Covenants:", bold=True)
    for cov in covenants:
        current = "n/a" if cov.current_value is None else f"{cov.current_value}"
        typer.echo(
            f"{indent}  - [{cov.status.value.upper()}] {cov.type.value}: "
            f"current {current} {cov.operator.value} {cov.threshold}"
        )


def _print_risk_flags(flags: tuple[RiskFlag, ...], indent: str = "  ") -> None:
    if not flags:
        return
    typer.secho(f"{indent}Risk flags:", bold=True)
    for f in flags:
        typer.echo(f"{indent}  - ({f.category.value}/{f.severity.value}) {f.detail}")


def _print_memo(memo: CreditMemo) -> None:
    typer.secho(f"Credit memo — {memo.borrower.name}", bold=True, fg=typer.colors.GREEN)
    _echo_review_banner(memo.requires_human_review)
    typer.echo("")
    typer.secho("  Summary:", bold=True)
    typer.echo(f"    {memo.summary}")
    if memo.financial_metrics:
        typer.secho("  Financial metrics:", bold=True)
        for x in memo.financial_metrics:
            typer.echo(f"    - {x.name}: {x.value} {x.currency} ({x.period})")
    _print_covenants(memo.covenants)
    _print_risk_flags(memo.risk_flags)
    if memo.peer_comparison:
        typer.secho("  Peer comparison:", bold=True)
        for p in memo.peer_comparison:
            typer.echo(
                f"    - {p.metric}: borrower {p.borrower_value} vs peer median "
                f"{p.peer_median} (p{int(p.percentile * 100)})"
            )
    typer.secho("  Recommendation rationale:", bold=True)
    typer.echo(f"    {memo.recommendation_rationale}")
    _echo_citations(memo.citations)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def build(
    borrower: str = typer.Argument(..., help="The borrower (obligor) name to assess."),
    sector: str = typer.Option("", "--sector", "-s", help="The borrower's sector."),
    jurisdiction: str = typer.Option("", "--jurisdiction", "-j", help="ISO-ish country code."),
) -> None:
    """Build a full cited credit memo for a borrower."""

    def _do() -> CreditMemo:
        from ..domain.models import Borrower, MemoInput

        svc = _deps().build_credit_memo_service(_container())
        b = Borrower(
            id=borrower.lower().replace(" ", "-"),
            name=borrower,
            sector=sector,
            jurisdiction=jurisdiction,
        )
        return svc.build(MemoInput(borrower=b), actor=_CLI_ACTOR)

    memo = _run("build", _do)
    _print_memo(memo)


@app.command()
def covenants(
    borrower: str = typer.Argument(..., help="The borrower name to extract covenants for."),
    sector: str = typer.Option("", "--sector", "-s", help="The borrower's sector."),
) -> None:
    """Extract covenants (with a tested compliance status) for a borrower."""

    def _do() -> tuple[Covenant, ...]:
        from ..domain import _grounded as g
        from ..domain.models import Borrower

        container = _container()
        b = Borrower(id=borrower.lower().replace(" ", "-"), name=borrower, sector=sector)
        passages = g.retrieve_passages(
            container.knowledge_base,
            f"financial covenants and thresholds for {b.name}",
            acl_principals=(f"borrower:{b.id}",),
            top_k=container.settings.knowledge_base.top_k,
        )
        return _deps().build_covenant_service(container).extract(b, passages, actor=_CLI_ACTOR)

    covs = _run("covenants", _do)
    typer.secho(f"Covenants ({len(covs)})", bold=True, fg=typer.colors.GREEN)
    _print_covenants(covs)


@app.command(name="risk-flags")
def risk_flags(
    borrower: str = typer.Argument(..., help="The borrower name to flag risks for."),
    sector: str = typer.Option("", "--sector", "-s", help="The borrower's sector."),
) -> None:
    """Identify credit risk flags for a borrower."""

    def _do() -> tuple[RiskFlag, ...]:
        from ..domain import _grounded as g
        from ..domain.models import Borrower

        container = _container()
        b = Borrower(id=borrower.lower().replace(" ", "-"), name=borrower, sector=sector)
        passages = g.retrieve_passages(
            container.knowledge_base,
            f"credit risks and sector context for {b.name}",
            acl_principals=(f"borrower:{b.id}",),
            top_k=container.settings.knowledge_base.top_k,
        )
        return _deps().build_risk_flag_service(container).flag(b, passages, actor=_CLI_ACTOR)

    flags = _run("risk-flags", _do)
    typer.secho(f"Risk flags ({len(flags)})", bold=True, fg=typer.colors.GREEN)
    _print_risk_flags(flags)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8093, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card, MCP, and REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "credit_memo.api.deps does not expose create_app(); cannot start the server.",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving credit-memo-drafting on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "credit_memo.api.deps:create_app", factory=True, host=host, port=port, reload=reload
        )

    _run("serve", _do)


@app.command()
def eval(  # noqa: A001 - "eval" is the documented command name
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Path to the golden eval dataset (defaults to the bundled set).",
    ),
) -> None:
    """Run the A4 promotion eval gate (groundedness / covenant / citations / pii_safety)."""

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    if code == 0:
        typer.secho("eval gate: PASS", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("eval gate: FAIL", fg=typer.colors.RED, bold=True)
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
