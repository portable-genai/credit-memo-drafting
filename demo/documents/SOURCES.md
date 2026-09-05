# Where every figure in this demo comes from

The demo runs on a real, currently listed company so an audience can check the
output against the filing rather than take the software's word for it. Nothing in
this directory is invented. Where a document states something the bank decided
rather than something the company filed, it says so on its face.

## The borrower

**Flowserve Corporation** — NYSE: FLS, SEC CIK 0000030625, SIC 3561 (Pumps and
Pumping Equipment), incorporated in New York, fiscal year ending 31 December.

## The filing

| | |
|---|---|
| Form | 10-K for the fiscal year ended 31 December 2025 |
| Filed | 17 February 2026 |
| Accession | `0000030625-26-000003` |
| Primary document | `fls-20251231.htm` |
| Subsidiary list | Exhibit 21.1, `fls1231202510kex211.htm` |
| Filing index | https://www.sec.gov/Archives/edgar/data/30625/000003062526000003/0000030625-26-000003-index.htm |
| XBRL company facts | https://data.sec.gov/api/xbrl/companyfacts/CIK0000030625.json |
| Registrant profile | https://data.sec.gov/submissions/CIK0000030625.json |

Retrieved 5 September 2026. Every income-statement and balance-sheet figure in
`flowserve-fy2025-financial-extract.txt` and `flowserve-fy2025-spread.csv` is a
consolidated XBRL fact for the period ended **2025-12-31** — one period throughout,
which is not automatic: see `latest_annual_facts` in
`src/credit_memo/adapters/live/_edgar.py` for why.

## What the bank supplied, and the company did not

Part B of `flowserve-covenant-position.txt` — the proposed maximum leverage of
3.00x, minimum DSCR of 1.25x and minimum current ratio of 2.00x — are **this demo
bank's own proposed terms for a hypothetical new facility**. Flowserve has not
agreed them and does not disclose its actual covenant thresholds. The same is true
of the facility request the demo enters (amount, tenor, purpose, security) and of
`config/policy_pack.example.yaml`, whose limits are the bank's appetite.

So: the measurements are Flowserve's filed figures; the limits they are measured
against are ours. A policy exception raised in this demo is a statement about our
appetite, not an allegation about the company.

## Why the memo and the borrower disagree

They disagree on purpose, and the disagreement is real rather than staged:

* The borrower measures leverage **net** of its USD 760.2m of cash and **after
  adding back** USD 58.3m of realignment charges, and on that basis reports 1.64x
  and full compliance with its existing covenants.
* This bank measures leverage on **gross** debt and on statutory EBITDA, which gives
  3.18x.

Same filing, same figures, two definitions. The reconciliation section reports both
and names the cause instead of quietly picking one — which is the single most useful
thing the product does, and it could not be shown honestly with an invented borrower.

## What the demo deliberately does not do

It declares real subsidiaries from Exhibit 21.1 — `FLOWSERVE PTE. LTD.` (Singapore,
100%) and `ARABIAN SEALS COMPANY, LTD.` (Saudi Arabia, 40%) — as group members with
no figures, because a lender to the parent genuinely does not hold standalone
statements for them, and the memo naming them as entities the consolidation could
not include is the honest outcome.

It does **not** enter an intercompany elimination. Flowserve discloses a real one —
USD 10.6m of intersegment sales between its two divisions, quoted in the financial
extract — but the borrower's spread is already consolidated and net of it, so
recording it again would deduct it twice. Inventing a different one to demonstrate
the feature would be exactly the fabrication this rewrite removed.
