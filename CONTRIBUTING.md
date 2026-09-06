# Contributing to `credit-memo-drafting` Credit-Memo / Underwriting Assistant

Thanks for your interest. This is an engineering-portfolio reference repo; contributions
that keep the hexagonal discipline intact are welcome.

## Ground rules

1. **Keep the domain pure.** `src/credit_memo/domain/` imports only the standard library.
   No `google-cloud-*`, ADK, FastAPI, httpx or pydantic in the domain.
2. **GCP imports are lazy.** In `adapters/gcp/*`, every google-cloud / genai / adk import
   lives inside a method or under `TYPE_CHECKING`, never at module top level. The on-prem
   and test profiles must import every module with no Google Cloud SDK installed.
3. **Adapters take one argument.** Every adapter constructor is `__init__(self, settings:
   Settings) -> None`.
4. **Cite everything; gate consequential outputs.** New artifacts carry `Citation`s, are
   audited, and pass through the maker-checker policy.
5. **Covenant status stays deterministic.** Compliance is decided only in
   `_grounded.covenant_status`; never let the model set it.

## Local workflow

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export CREDIT_MEMO_PROFILE=onprem

make fmt      # ruff format + ruff check --fix
make lint     # ruff check + ruff format --check + mypy
make test     # pytest -m 'not integration'
make eval     # the `model-quality-gate` promotion gate
```

The mandatory gate (must be green before a PR):

```bash
ruff check src tests
ruff format --check src tests
pytest -m 'not integration' -q
```

`mypy src` and `python eval/run_eval.py` should also pass.

## Adding a port or adapter

1. Add the `Protocol` to `ports/` and re-export it from `ports/__init__.py`.
2. Add a `gcp` adapter (lazy imports), a `platform` client if a sibling service owns it,
   and an `onprem` placeholder that raises `NotImplementedError`.
3. Bind all three in `config/settings.yaml` and add a `cached_property` to the `Container`.
4. Extend `tests/contract/test_port_parity.py` `PORT_PROTOCOLS` and add unit tests with a
   fake in `tests/conftest.py`.

## Style

- `from __future__ import annotations`, full type hints, ruff line-length 100, target
  py312, ruff lint select `["E","F","I","UP","B","SIM"]`.
- Markdown: minimise em-dashes; validate any mermaid before committing.
- Do not name third-party OSS products in the on-prem stubs.

## Adding an adapter or sub-service

For a new adapter, update the typed port in `src/credit_memo/ports/`, add `local`, `gcp` or
`platform`, and `onprem` bindings as applicable, update `config/settings.yaml`, export the
adapter, and extend `tests/contract/test_port_parity.py` so the settings and Protocol sets
remain equal. For a new sub-service, add the pure service under `domain/`, re-export it from
`domain/services.py`, wire it only in `api/deps.py`, add one test per deterministic finding
and boundary, add eval coverage, expose the output in the audit/demo view, and update SPEC,
ARCHITECTURE, COMPLIANCE, the runbook, model card, and changelog.
