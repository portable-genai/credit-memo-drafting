# B2 Credit-Memo / Underwriting Assistant — developer Makefile.
#
# The default dev/test/lint targets run under the LOCAL profile: a WORKING offline
# stack (SQLite FTS5 + a deterministic LLM) that needs NO Google Cloud SDK and runs the
# whole memo pipeline end to end. Override PROFILE=gcp for the managed stack, or
# PROFILE=onprem to exercise the fail-fast migration placeholders.

PYTHON      ?= python3
PYTHON      := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))
PIP         ?= pip
PROFILE     ?= local
SRC         := src/credit_memo
TESTS       := tests
API_APP     := credit_memo.api.app:app
API_HOST    ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT    ?= 8093
UI_DIR      := ui
TF_DIR      := infra/terraform

export CREDIT_MEMO_PROFILE := $(PROFILE)

.DEFAULT_GOAL := help
.PHONY: help install install-demo install-gcp lock fmt lint test check memo demo demo-server demo-selftest eval run-api run-ui \
	demo-browser ui-install ui-check tf-plan clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev tooling (NO GCP SDK — local/test profile).
	$(PIP) install -e ".[dev]"

install-demo: ## Install the pinned headless-browser extra, then fetch its browser binary.
	$(PIP) install -e ".[dev,demo]"
	$(PYTHON) -m playwright install chromium

install-gcp: ## Install with the managed-stack extra (google-adk, genai, documentai, ...).
	$(PIP) install -e ".[gcp,dev]"

lock: ## Recompile every lockfile from pyproject.toml and restore the tag = commit headers.
	$(PYTHON) scripts/lock.py

fmt: ## Auto-format and auto-fix lint issues.
	ruff format $(SRC) $(TESTS) eval
	ruff check --fix $(SRC) $(TESTS) eval

lint: ## Lint (ruff) and type-check (mypy).
	ruff check $(SRC) $(TESTS) eval scripts/demo_selftest.py scripts/portability_demo.py \
		scripts/render_credit_memo_ui.py
	ruff format --check $(SRC) $(TESTS) eval scripts/demo_selftest.py scripts/portability_demo.py \
		scripts/render_credit_memo_ui.py
	mypy $(SRC)

test: ## Run unit + contract tests on the local profile (no GCP SDK required).
	CREDIT_MEMO_PROFILE=local pytest -m 'not integration' -q

portability: ## Execute the bounded offline/profile portability proof.
	PYTHONPATH=src $(PYTHON) scripts/portability_demo.py

plugin: ## Render the Agent Plugins 1.0.0 directory from this repo's own declarations.
	python scripts/render_plugin.py --dest dist/plugin

mcp-serve: ## Serve the governed tool catalog over MCP 2026-07-28 (stdio; needs [gcp]).
	python -m credit_memo.mcp

check: lint test eval demo-selftest portability plugin ## Run the full offline quality gate (no node, no cloud).

demo-selftest: ## Prove the served presenter states and evidence hooks cannot rot silently.
	PYTHONPATH=src:scripts $(PYTHON) scripts/demo_selftest.py

demo-browser: ## Drive the SERVED demo through pinned headless Chromium (needs the [demo] extra).
	CREDIT_MEMO_PROFILE=local $(PYTHON) -m pytest $(TESTS)/browser -q -rs

memo: ## End-to-end smoke: build a cited memo offline under the local profile.
	CREDIT_MEMO_PROFILE=local credit-memo build "Acme Manufacturing Pte Ltd" \
		--sector manufacturing --jurisdiction SG

demo: ## Offline demo: build a cited memo + write JSON + render static audit-first HTML.
	PYTHONPATH=src $(PYTHON) scripts/credit_memo_demo.py credit_memo_demo.json
	PYTHONPATH=src $(PYTHON) scripts/render_credit_memo_ui.py credit_memo_demo.json ./out
	@echo "open ./out/memo.html and ./out/sources.html - or: make demo-server"

demo-server: ## Live presenter-controlled demo server (offline) on :8094.
	PYTHONPATH=src $(PYTHON) scripts/credit_memo_demo_server.py

eval: ## Run the A4 eval gate (groundedness / covenant / citations / pii_safety).
	$(PYTHON) eval/run_eval.py

run-api: ## Run the FastAPI service (PROFILE=$(PROFILE)).
	uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT) --reload

run-ui: ## Run the React / Next.js UI (dev server).
	cd $(UI_DIR) && npm install && npm run dev

ui-install: ## Install the console's locked dependencies.
	npm ci --prefix $(UI_DIR)

ui-check: ## Console gate: types, policy tests, build, then hydration against the BUILT server.
	npm --prefix $(UI_DIR) run lint
	npm --prefix $(UI_DIR) test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(UI_DIR) run build
	npm --prefix $(UI_DIR) run assert-hydratable

tf-plan: ## Terraform plan for the asia-southeast1 infrastructure.
	cd $(TF_DIR) && terraform init -input=false && terraform plan

clean: ## Remove caches and build artefacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
