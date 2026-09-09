# How the credit-memo assistant is evaluated

Read this page if you decide what this service is allowed to say. The metrics, the bars, the
corpora and the narrative floor below are generated from the artifacts that actually gate the
build, so they cannot drift from what runs: `make evals-doc-check` fails the build when this page
and those artifacts disagree.

## How to run it

```sh
make eval              # the deterministic half, offline, no credentials
make eval-narrative    # the judged half, offline by default, no model server
make eval-adversarial  # the same gate against a fabricating model; a PASS here is the bug
make evals-doc-check   # this page is still true
```

`make check` runs all four on every change.

## Two kinds of scoring, and why both

Most of what matters in a credit memo is decided by deterministic code and is scored by rules:
whether the ratio engine reproduces its own arithmetic, whether the covenant status is the one a
reviewer computed, whether every citation resolves to a passage that was actually retrieved,
whether any identifier survived into the memo or the audit trail. Those are questions with
answers, and a judge would only add noise to them.

They leave a gap, and it is the one output a credit officer actually reads. A memo can reproduce
every ratio, get every covenant right, cite every source, mask every identifier, and still bury
the covenant position, assert a certainty the evidence does not carry, or read as a decision the
committee has not taken. Deciding that is a judgement, so it is judged, and the judge is held to
the same standard as everything else here: it must be shown able to fail before anything it
certifies is believed.

The judged half runs offline by default, so it is inside the gate with no model server and no
credentials. A real model judge is opt-in on the command line and never from the environment: a
gate whose scorer a stray variable could swap is not a gate.

## What is measured, and against what bar

Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the
runner reads it from there. There is no dict of thresholds in the runner any more: a
metric scored with no reviewed bar fails the build, and so does a bar that names no
metric, which is the direction that rots quietly because it rots toward looking well
governed.

The third column is the denominator rule, and it applies only where a score is a
FRACTION over scored positives: such a threshold `t` tolerates a single miss only over
at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no
headroom, so a bigger corpus would not change what it means. Each rubric declares which
it is rather than the rule being guessed from the number.

| Metric | Bar | Denominator | What it measures |
|---|---|---|---|
| `citation_accuracy` | 1 | all or nothing | Per-case correctness of the citation set: no citation outside the retrieved or derived evidence (filings, credit-policy passages, peer data). Averaged over the dataset. |
| `covenant_accuracy` | 1 | all or nothing | The deterministically-computed covenant status (COMPLIANT, AT_RISK, BREACH) matches the expected status for the golden case. |
| `groundedness` | 0.8 | a rate; needs 5 positives | Fraction of the credit memo's claim-bearing sentences that are supported by a cited evidence source. A memo with claims but no citations scores 0. |
| `pii_safety` | 0.99 | all or nothing | No unredacted borrower PII (NRIC, email) survives into the memo or the audit records. A single leak drops the whole metric below 0.99. |
| `ratio_reproducibility` | 1 | all or nothing | Every expected ratio is present in the memo, has a value, and equals the figure the golden case states. Absent, valueless and moved are three distinct failures and all score zero. |
| `research_isolation` | 1 | all or nothing | Nothing retrieved from the public web can reach a calculation, a memo field or the committee pack. Structural absence, not filtering. |
| `revision_integrity` | 1 | all or nothing | A two-revision chain verifies when intact and fails when an earlier revision's content is altered. Both halves, because only the second one is a guarantee. |
| `spread_accuracy` | 0.9 | a rate; needs 10 positives | Fraction of the line items the golden case names, per period, that appear in the confirmed spread with the value a reviewer read off the filing. |
| `tie_out_precision` | 1 | all or nothing | Reconciliations fire on the cases a reviewer marked as failing, and stay silent on the files a reviewer marked clean. The false alarm is scored, not only the miss. |

Scored over 6 golden cases.

## What is exercised

- **6 golden borrowers** in `eval/datasets/golden_cases.jsonl`, carrying
  8 expected covenant statuses, 12 spread line items across periods and
  9 expected ratio figures. Every expectation is a reviewer's, read off the
  source; none is derived from the engine, because an oracle computed from the thing
  under test agrees with it by construction and measures nothing.
- **4 of them plant a raw identifier**, so the leak metric has a target it could
  miss. A corpus that plants nothing scores a vacuous 1.0.
- **3 judged memo narratives** in
  `eval/datasets/narrative_golden.jsonl`, each written once per profile with the band it
  is expected to land in. A profile that quietly got BETTER fails too, because a band
  nobody predicted is a change nobody reviewed.
- **An adversarial run** (`make eval-adversarial`) drives the same gate with a
  fabricating model, where a PASS is the bug.

## Where the narrative floor comes from

`config/quality-floors.toml` is owned by model risk. A **floor** refuses: below it a
profile must not serve this vertical, which is not the same as serving it worse. A
**target** is full quality. Between the two is DEGRADED, the band a portability claim
describes in adjectives and which nothing measured until there was a floor.

| Vertical | Floor | Target | Why |
|---|---|---|---|
| `doc2-credit-memo` | 0.65 | 0.88 | A memo a credit officer reads before signing, and a committee reads after. A weak narrative here is not caught by a reviewer downstream: the reviewer IS the reader. |

## How a metric is prevented from being decoration

Four rules, each closing a way a gate reports a confident number over something it did not
measure. They are enforced by `eval/run_eval.py` itself, not by review:

1. **The bars are read from the rubrics, in both directions.** There is no `THRESHOLDS` dict any
   more. What was here before was both a dict and a loader that overlaid the rubrics on top of
   it, silently falling back to the dict when PyYAML was missing: two homes for one number, with
   a silent path that used the one nobody reviews.
2. **Every metric's red case runs as the first statement of the scored run.** Five of the nine
   metrics had never been shown able to fail anywhere, and four of those five sit at exactly
   1.00, which is the same shape a scorer that silently became a constant produces. Two of them
   score a MECHANISM rather than a memo, so their red case substitutes the collaborator the
   scorer trusts: a revision service that certifies a tampered chain, and a memo type carrying
   the market-context field the research fence exists to refuse.
3. **The corpus must be able to express its own bars.** Three bars could not, and were
   arithmetically identical to 1.0 while reading as though they had headroom:
   `citation_accuracy` and `covenant_accuracy` at 0.90, and `tie_out_precision` at 0.95. They now
   say 1.0, which is what they always meant.
4. **The leak scan reads what the service persisted.** Building a string in the eval and scanning
   that would score the redactor against itself, over text the service never produced.

## What is NOT measured here

Naming this is part of the page, because an unmeasured claim that goes unmentioned reads as a
measured one.

- **A real model's words.** Every metric above scores a deterministic core against a deterministic
  fake model adapter, so `groundedness` and `citation_accuracy` are measurements of the
  VALIDATOR rather than of a model's restraint: they would stay green through a model swap, a
  prompt regression or a context-window truncation. The adversarial run is the partial answer,
  and it is one-sided: it proves the gate catches a fabricator, not that a real model does not
  fabricate.
- **Retrieval quality.** The knowledge base's recall is not scored separately from what the memo
  did with what it returned, so a knowledge base that silently stopped returning the right filing
  would still produce a clean citation set.
- **Production traffic.** Everything here is a golden set. Nothing samples live requests.
