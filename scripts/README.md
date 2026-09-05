# Demo scripts - cited credit-memo build

All scripts are SDK-free and run against the in-process `local` stack (no Google Cloud,
no API key). They pin `CREDIT_MEMO_PROFILE=local` unless you have set it yourself. Run
them from the repo root with the domain package on the path:

```bash
export PYTHONPATH=src
```

| Script | What it does |
|--------|--------------|
| `credit_memo_demo.py` | Builds the cited credit memo for the synthetic borrower Acme Manufacturing end to end, prints a stage-by-stage summary, and writes the full memo as audit-view JSON. |
| `render_credit_memo_ui.py` | Renders that JSON into static audit-first HTML pages (the memo page + a sources/audit page) for screenshots. |
| `credit_memo_demo_server.py` | A **live, click-through** server that builds the *real* memo and reveals its cited sections one step per click, rendering the audit-first UI. |
| `credit_memo_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server: it narrates each step and waits for you to press Enter before performing it. |
| `credit_memo_console_walkthrough.py` | The **full business walkthrough**: one deal through the REAL console and service in eighteen acts, presenter-paced. Starts both servers itself. Prints what to say and waits for a key before each act and at the beats inside one; `--act NAME\|N` presents a single use case (its predecessors run silently first), `--list` names them all. Every act asserts what it shows, and the same acts run headless as `make demo-console`. See [`docs/demo-use-cases.md`](../docs/demo-use-cases.md). |
| `demo_console/` | The acts, fixtures, locators, server harness and evidence capture the walkthrough and `tests/browser/test_console_use_cases.py` share. Changing an act changes both. |

## Static artifacts (slides / screenshots)

```bash
python scripts/credit_memo_demo.py credit_memo_demo.json
python scripts/render_credit_memo_ui.py credit_memo_demo.json ./out   # ./out/memo.html, sources.html
```

Or simply `make demo` from the repo root (writes `credit_memo_demo.json` and `./out`).

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8094)
PYTHONPATH=src python scripts/credit_memo_demo_server.py

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/credit_memo_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Next** and spotlights the panel to look at. The six steps
are: memo built (summary) -> financial analysis -> covenants (deterministic status) ->
risk flags -> peer comparison -> maker-checker review gate.

You can also just open `http://localhost:8094` and click **Next** / **Restart** by hand -
the server holds the live memo, so the buttons drive the same real artifact. The
`/sources` route shows the input filings and every citation.

> The demo server runs on **:8094** so it never clashes with the FastAPI API on **:8093**.

Useful environment overrides for `credit_memo_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8094` | server base URL |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter - advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | - | explicit Chromium/Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |

The synthetic data is fictional and says so; the demo's credit file is a listed company's
published SEC filings (`demo/documents/SOURCES.md`). Neither is a real borrower of yours: do
not run against live borrower data without your own legal, security and model-risk
sign-off.
