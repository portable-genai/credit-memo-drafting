# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the `credit_memo` package name, the `credit-memo` CLI entry
point, the `CREDIT_MEMO_` env prefix, and the `credit-memo-drafting` resource ids in one pass
(preview with `--dry-run`, apply with `--yes`). Then recreate the venv, `pip install -e ".[dev]"`,
and run `make lint test eval`. The script does the mechanical rename; the human decisions
(region, IdP, PII pack, risk policy, fixtures, eval golden set) are the checklist in
`ADOPTING.md`.

### If five banks fork this, how does each take upstream security fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING sec. 2): upstream owns
the vertical-neutral machinery, `ports/`, `tests/contract/`, the eval harness mechanics and CI;
you own `config/settings.yaml` values, fixtures, `adapters/onprem/*`, UI theming, and the eval
golden set. Rebase your adopter-owned changes onto each release rather than merging `main`
continuously, and merge conflicts stay in files you were told to expect.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list, and the contract test fails loudly if you miss part of it: define
the `@runtime_checkable` Protocol under `ports/`, re-export it from `ports/__init__.py`,
implement one adapter per profile (at least `local` and `onprem`), bind all of them in
`config/settings.yaml`, add the port to the parity map (`PORT_PROTOCOLS`), add a
`cached_property` on the `Container`, and wire it in `api/deps.py`. Full instructions in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) ("Adding a port or adapter").

### How do I change the taxonomy (covenant types, risk categories, doc types)?

They are `StrEnum`s and the engines are typed on `str`, so members ARE their wire values and you
extend the vocabulary without editing engine code. To replace the taxonomy wholesale for a
different vertical, edit the enums in `domain/models.py` and the label maps in the UI. Serialized
JSON values are the enum strings.

### How do I retune the risk / covenant policy without touching code?

Today the one tunable engine number, the covenant thin-headroom band `_AT_RISK_BAND = 0.05` in
`domain/_grounded.py`, is a module-level constant (the practices audit records this as gap B4:
there is not yet a `policy:` settings section or `from_policy` constructor). When you own the
numbers your credit function cares about (the at-risk band, escalation thresholds, peer-set
rules), lift them into `config/settings.yaml` and thread them through a `domain/policy.py`
dataclass rather than hard-coding them, and pin them with an override test.

### Does the CI run for my fork out of the box?

Yes. CI (`ruff check` + `ruff format --check` + `mypy` + `pytest -m 'not integration'`) and the
eval gate (`python eval/run_eval.py`) both run on the `local` profile
(`CREDIT_MEMO_PROFILE=local`) with **no cloud credentials and no org secrets**, so a fork's build
is green immediately. You add secrets only when you wire the `gcp` / `platform` profiles. Note
the eval gate measures the *reference* vertical until you rebuild the golden set
(`eval/datasets/golden_cases.jsonl`); that is an explicit adoption step, not a silent pass.

### Will the demo rot after I diverge?

Be aware of the one open caveat here (practices audit gap F2): there is currently **no demo
self-test** (no `demo-selftest` target, no CI demo job, no `data-*` panel hooks in
`render_credit_memo_ui.py`), so a broken demo step would not fail CI today. If you rely on the
walkthrough for stakeholder presentations, add a headless self-test as an early hardening step;
the offline `make demo` and `make demo-server` themselves run without cloud or an API key.
