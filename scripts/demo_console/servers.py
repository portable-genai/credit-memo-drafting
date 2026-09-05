"""Start the two processes the demo drives: the API, and the BUILT console.

The console is deliberately started with ``next start``, never ``next dev``. This is not a
preference: ``next dev`` compiles with ``eval`` and opens an HMR websocket, so it needs CSP
relaxations a deployment must never carry, and they are emitted only outside production
(``ui/lib/csp.mjs``). A demo that shows the dev server is showing a configuration that
never ships. If the build is missing this module says so and names the command, rather than
quietly falling back to the thing it just refused.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from credit_memo.envread import setting_or_default

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "ui"

#: The console's API base is inlined at BUILD time (``ui/lib/api.ts``), so the port the
#: console talks to is fixed by whoever ran ``next build`` and cannot be moved at start-up.
#: Both processes therefore take the documented default ports or nothing.
# Three-state reads, not ``os.environ.get(name, default)``. An emptied variable expressed
# an intent that names nothing, and inheriting the default for it is the defect
# ``tests/unit/test_three_state_env_reads.py`` exists to catch. A port decides what gets
# served where, so it is not one of the posture-free knobs that test exempts.
API_PORT = int(setting_or_default("DEMO_API_PORT", "8093"))
UI_PORT = int(setting_or_default("DEMO_UI_PORT", "3000"))
API_BASE = f"http://127.0.0.1:{API_PORT}"
#: The origin the BROWSER uses. Deliberately ``localhost`` rather than the loopback IP:
#: it must match the console's own build-time default and the API's dev CORS allowlist,
#: and ``127.0.0.1`` is a different origin to a browser than ``localhost`` is.
API_BASE_FOR_BROWSER = f"http://localhost:{API_PORT}"
UI_BASE = f"http://localhost:{UI_PORT}"

#: The bank's policy pack. Named EXPLICITLY rather than left to the adapter's default so
#: the demo can say which pack produced the exceptions on screen. It is the shipped
#: example, whose limits are plausible and invented — which is the act's whole point: the
#: numbers belong to the bank, and a deployment that ships with this file is reporting
#: borrowers against a policy nobody wrote.
POLICY_PACK = REPO_ROOT / "config" / "policy_pack.example.yaml"

_READY_TIMEOUT = float(setting_or_default("DEMO_READY_TIMEOUT", "90"))

#: Where the run's evidence and the two server logs go. Resolved here rather than in
#: ``evidence`` because the servers start before any act does, and both modules must agree
#: on one directory. Three-state: an emptied DEMO_OUT_DIR would otherwise resolve to the
#: repo's own out/demo, writing where the operator said not to.
OUT_DIR = Path(setting_or_default("DEMO_OUT_DIR", str(REPO_ROOT / "out" / "demo")))
LOG_DIR = OUT_DIR / "logs"


def _log_file(name: str):
    """Open a fresh log for one server.

    The servers' own output does not belong in the presenter's terminal: a library's
    "invalid pdf header" chatter — harmless, and emitted every time the extractor is handed
    a CSV — lands in the middle of the sentence the presenter is reading aloud. It is not
    discarded, though: it goes to a file, and :func:`wait_for` reads the tail of it back
    into the error when a server fails to come up, which is the only moment anybody wants
    it.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return (LOG_DIR / name).open("w", encoding="utf-8", errors="replace")


def _tail(log: Path, lines: int = 15) -> str:
    try:
        recent = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return ""
    body = "\n".join(f"    {line}" for line in recent if line.strip())
    return f"\nThe last of {log}:\n{body}" if body else ""


class DemoServerError(RuntimeError):
    """A process the demo needs could not be started, with the remedy in the message."""


def api_env(analysis_root: Path) -> dict[str, str]:
    """The environment the demo API runs under: local profile, nothing durable on disk.

    ``CREDIT_MEMO_PROFILE`` is set DELIBERATELY rather than inherited. The seeded dev
    personas grant the credit-analyst and credit-approver entitlements with no
    authentication at all, and ``LocalPersonaIdentityAdapter`` refuses to construct unless
    a profile was actually chosen, so an unset variable fails closed instead of serving an
    underwriting assistant with dev approvers.
    """
    env = dict(os.environ)
    env.update(
        {
            "CREDIT_MEMO_PROFILE": "local",
            "CREDIT_MEMO_LOCAL_DB": ":memory:",
            "CREDIT_MEMO_LOCAL_AUDIT": ":memory:",
            "CREDIT_MEMO_ANALYSIS_ROOT": str(analysis_root),
            "CREDIT_MEMO_POLICY_PACK": str(POLICY_PACK),
            # The public-context act needs the port bound. Under `local` that is the
            # fixture adapter, which answers on SECTOR and labels every row a fixture on
            # its face; under `live` the same switch reaches real Google Search grounding.
            "CREDIT_MEMO_RESEARCH_ENABLED": "1",
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_for(
    url: str,
    timeout: float = _READY_TIMEOUT,
    process: subprocess.Popen | None = None,
    log: Path | None = None,
):
    """Poll ``url`` until it answers, failing early if the process died first."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise DemoServerError(
                f"the process serving {url} exited with code {process.returncode} "
                f"before it was ready" + (_tail(log) if log else "")
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise DemoServerError(
        f"{url} was not ready within {timeout:.0f}s (last error: {last})"
        + (_tail(log) if log else "")
    )


@contextmanager
def api_server(analysis_root: Path) -> Iterator[str]:
    """The FastAPI service on :data:`API_PORT`, for the life of the block."""
    if not port_is_free(API_PORT):
        raise DemoServerError(
            f"port {API_PORT} is already in use. Stop whatever is on it (a `make run-api`?) "
            f"or set DEMO_API_PORT — but note the console's API base is baked in at build "
            f"time, so moving the port needs a rebuild of the console too."
        )
    analysis_root.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / "api.log"
    stream = _log_file("api.log")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [
            # THIS interpreter, not whatever "python" resolves to on PATH. A demo run
            # that silently reached a different interpreter would fail with an import
            # error about uvicorn rather than about the interpreter, which is a long way
            # from the actual cause.
            sys.executable,
            "-m",
            "uvicorn",
            "credit_memo.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=api_env(analysis_root),
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for(f"{API_BASE}/healthz", process=process, log=log)
        yield API_BASE
    finally:
        _stop(process)
        stream.close()


@contextmanager
def console_server() -> Iterator[str]:
    """The BUILT Next.js console on :data:`UI_PORT`."""
    if not (UI_DIR / ".next").is_dir():
        raise DemoServerError(
            "the console has not been built, and this demo runs what ships rather than the "
            "dev server. Build it first:\n"
            "  npm ci --prefix ui\n"
            f"  NEXT_PUBLIC_API_BASE={API_BASE_FOR_BROWSER} "
            "NEXT_TELEMETRY_DISABLED=1 npm --prefix ui run build"
        )
    if shutil.which("npm") is None:
        raise DemoServerError("npm is not on PATH, so the console cannot be served")
    if not port_is_free(UI_PORT):
        raise DemoServerError(f"port {UI_PORT} is already in use; stop what is on it first")

    env = dict(os.environ)
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    # Required, not merely tidy. ``ui/lib/api.ts`` falls back to this exact origin when the
    # variable is UNSET, but ``ui/lib/csp.mjs`` adds an origin to ``connect-src`` only when
    # it IS set — so an unset console ships a page whose own default API call its own CSP
    # then blocks, with the failure visible only in the browser console. Setting it here
    # makes the two halves agree; the mismatch itself is reported in docs/demo-use-cases.md.
    env["NEXT_PUBLIC_API_BASE"] = API_BASE_FOR_BROWSER
    log = LOG_DIR / "console.log"
    stream = _log_file("console.log")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["npm", "run", "start", "--", "--port", str(UI_PORT)],
        cwd=UI_DIR,
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for(UI_BASE, process=process, log=log)
        yield UI_BASE
    finally:
        _stop(process)
        stream.close()


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged child
        process.kill()
        process.wait(timeout=5)
