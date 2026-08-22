"""Render the audit-first credit-memo UI from the demo JSON into static HTML pages.

Server-side, dependency-free rendering of a ``CreditMemo`` (the memo page with its four
cited sections, plus a sources/audit page), faithful to the existing console palette
(ink / regblue, Panel, citation chips) used by ``ui/``. Used to produce screenshots /
slides from the synthetic testing data.

    PYTHONPATH=src python scripts/render_credit_memo_ui.py credit_memo_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

COV_COLOR = {
    "compliant": ("#ecfdf5", "#059669"),
    "at_risk": ("#fffbeb", "#d97706"),
    "breach": ("#fee2e2", "#b91c1c"),
}
SEV_COLOR = {
    "low": ("#eef2f7", "#546b8b"),
    "medium": ("#fef3c7", "#92400e"),
    "high": ("#ffedd5", "#c2410c"),
    "critical": ("#fee2e2", "#b91c1c"),
}
SRC_LABEL = {"filing": "FILING", "policy": "POLICY", "peer_data": "PEER"}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;
--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-600:#2945d6;--regblue-700:#2237ad;
--ok:#059669;--ok-bg:#ecfdf5;--warn:#d97706;--warn-bg:#fffbeb;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:880px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 16px}
.step{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--ink-200);background:#fff;color:var(--ink-500)}
.step.done{background:var(--regblue-50);border-color:var(--regblue-100);color:var(--regblue-700)}
.step.cur{background:var(--regblue-600);border-color:var(--regblue-600);color:#fff;font-weight:600}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-800);
display:flex;justify-content:space-between;align-items:center}
.panel>.body{padding:16px}
.statuspill{font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px}
.review{border:1px solid #fcd34d;background:var(--warn-bg);color:#92400e;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;margin-bottom:14px}
.summary{font-size:14px;line-height:1.6;color:var(--ink-800);margin:0}
/* metrics */
.metrics{display:flex;gap:10px;flex-wrap:wrap}
.metric{border:1px solid var(--ink-200);border-radius:9px;padding:9px 14px;background:var(--ink-50);min-width:120px}
.metric .k{font-size:11px;text-transform:uppercase;color:var(--ink-400)}
.metric .v{font-size:18px;font-variant-numeric:tabular-nums;color:var(--ink-800)}
.metric .p{font-size:11px;color:var(--ink-400)}
/* covenant table */
table.cov{width:100%;border-collapse:collapse;font-size:13px}
table.cov th,table.cov td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--ink-100)}
table.cov th{font-size:11px;text-transform:uppercase;color:var(--ink-400);font-weight:600}
table.cov td.num{font-variant-numeric:tabular-nums}
.covpill{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 8px;border-radius:5px}
/* risk + items */
.item{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--ink-100)}
.item:last-child{border-bottom:0}
.sev{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:5px;flex:none;margin-top:1px}
.item .txt{font-size:13px}
.item .cat{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--ink-500)}
/* peer bars */
.peer{margin-bottom:12px}
.peer .lbl{display:flex;justify-content:space-between;font-size:12px;color:var(--ink-500);margin-bottom:4px}
.peer .lbl b{color:var(--ink-800)}
.scale{position:relative;height:14px;border-radius:8px;background:var(--ink-100);border:1px solid var(--ink-200)}
.scale .med{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink-500)}
.scale .me{position:absolute;top:1px;height:10px;width:10px;border-radius:50%;background:var(--regblue-600);transform:translateX(-5px)}
/* chips */
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.chip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--ink-200);background:var(--ink-50);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--ink-700)}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:600;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.muted{color:var(--ink-400);font-size:12px}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
.navlinks{font-size:12px;margin:0 0 14px}
.navlinks a{color:var(--regblue-700);text-decoration:none;margin-right:10px}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def chip(c: dict) -> str:
    ty = SRC_LABEL.get(c.get("source_type", ""), c.get("source_type", ""))
    page = f" p.{c['page']}" if c.get("page") is not None else ""
    return (
        f'<span class="chip"><span class="ty">{esc(ty)}</span>'
        f'<span class="sr">{esc(c.get("source_id"))}{esc(page)}</span></span>'
    )


def chips(cites: list[dict]) -> str:
    if not cites:
        return ""
    return '<div class="chips">' + "".join(chip(c) for c in cites) + "</div>"


def steps_bar(cur: int) -> str:
    labels = ["Summary", "Financials", "Covenants", "Risk", "Peers", "Review"]
    out = []
    for i, lab in enumerate(labels):
        cls = "step"
        if i < cur:
            cls += " done"
        elif i == cur:
            cls += " cur"
        out.append(f'<span class="{cls}">{esc(lab)}</span>')
    return '<div class="steps">' + "".join(out) + "</div>"


def render_metrics(metrics: list[dict]) -> str:
    if not metrics:
        return '<p class="muted">No metrics normalised.</p>'
    cells = "".join(
        f'<div class="metric" data-metric="{esc(m["name"])}" '
        f'data-metric-value="{esc(m["value"])}">'
        f'<div class="k">{esc(m["name"])}</div>'
        f'<div class="v">{esc(m["value"])} {esc(m.get("currency", ""))}</div>'
        f'<div class="p">{esc(m.get("period", ""))}</div></div>'
        for m in metrics
    )
    return f'<div class="metrics" data-metric-count="{len(metrics)}">{cells}</div>'


def cov_pill(status: str) -> str:
    bg, fg = COV_COLOR.get(status, COV_COLOR["at_risk"])
    return f'<span class="covpill" style="background:{bg};color:{fg}">{esc(status)}</span>'


def sev_pill(sev: str) -> str:
    bg, fg = SEV_COLOR.get(sev, SEV_COLOR["low"])
    return f'<span class="sev" style="background:{bg};color:{fg}">{esc(sev)}</span>'


def render_covenants(covenants: list[dict]) -> str:
    if not covenants:
        return '<p class="muted">No covenants extracted.</p>'
    rows = []
    for c in covenants:
        cur = "n/a" if c.get("current_value") is None else c["current_value"]
        rows.append(
            f"<tr data-covenant='{esc(c['type'])}' data-covenant-status='{esc(c['status'])}' "
            f"data-covenant-current='{esc(cur)}'>"
            f"<td>{esc(c['type'])}</td>"
            f"<td>{cov_pill(c['status'])}</td>"
            f"<td class='num'>{esc(cur)}</td>"
            f"<td class='num'>{esc(c['operator'])} {esc(c['threshold'])}</td>"
            f"<td>{chips(c.get('citations', []))}</td></tr>"
        )
    breaches = sum(1 for c in covenants if c["status"] == "breach")
    return (
        f"<table class='cov' data-covenant-count='{len(covenants)}' "
        f"data-covenant-breaches='{breaches}'>"
        "<tr><th>Covenant</th><th>Status</th><th>Current</th>"
        "<th>Test</th><th>Source</th></tr>" + "".join(rows) + "</table>"
    )


def render_risk(flags: list[dict]) -> str:
    if not flags:
        return '<p class="muted">No risk flags raised.</p>'
    items = "".join(
        f'<div class="item" data-risk-severity="{esc(f["severity"])}" '
        f'data-risk-category="{esc(f["category"])}">{sev_pill(f["severity"])}'
        f'<div class="txt">{esc(f["detail"])} <span class="cat">[{esc(f["category"])}]</span>'
        f"{chips(f.get('citations', []))}</div></div>"
        for f in flags
    )
    return f"<div data-risk-count='{len(flags)}'>{items}</div>"


def render_peers(comparisons: list[dict]) -> str:
    if not comparisons:
        return '<p class="muted">No peer cohort available.</p>'
    out = []
    for p in comparisons:
        vals = [p["borrower_value"], p["peer_median"]] + [x["value"] for x in p.get("peers", [])]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        med_pct = (p["peer_median"] - lo) / span * 100
        me_pct = (p["borrower_value"] - lo) / span * 100
        out.append(
            f"<div class='peer' data-peer='{esc(p['metric'])}' "
            f"data-peer-percentile='{int(p['percentile'] * 100)}' "
            f"data-peer-borrower-value='{esc(p['borrower_value'])}'>"
            f"<div class='lbl'><span>{esc(p['metric'])}</span>"
            f"<span>borrower <b>{esc(p['borrower_value'])}</b> · median {esc(p['peer_median'])}"
            f" · p{int(p['percentile'] * 100)}</span></div>"
            f"<div class='scale'><div class='med' style='left:{med_pct:.0f}%'></div>"
            f"<div class='me' style='left:{me_pct:.0f}%'></div></div></div>"
        )
    return "".join(out)


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def slug(title: str) -> str:
    """Stable, styling-independent identifier for a result panel (F2 evidence hook)."""
    return "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")


def _section(title: str, inner: str, extra: str = "") -> str:
    return (
        f"<section class='panel' data-panel='{slug(title)}'>"
        f"<h2>{esc(title)}{extra}</h2>"
        f"<div class='body' data-panel-body='{slug(title)}'>{inner}</div></section>"
    )


def render_memo(data: dict, cur: int = 0) -> str:
    borrower = data["borrower"]
    breaches = sum(1 for c in data["covenants"] if c["status"] == "breach")
    header = (
        f"<div data-memo-borrower='{esc(borrower['id'])}' "
        f"data-memo-citations='{len(data.get('citations', []))}' "
        f"data-memo-breaches='{breaches}' "
        f"data-memo-review='{str(bool(data.get('requires_human_review'))).lower()}'></div>"
        f"<h1>Credit memo — {esc(borrower['name'])}</h1>"
        f"<p class='sub'>Borrower <b class='mono'>{esc(borrower['id'])}</b> · "
        f"{esc(borrower.get('sector') or 'sector n/a')} · "
        f"{esc(borrower.get('jurisdiction') or 'jurisdiction n/a')}</p>"
        "<p class='navlinks'><a href='memo.html'>Memo</a><a href='sources.html'>Sources &amp; audit</a></p>"
        + steps_bar(cur)
    )
    review = (
        "<div class='review'>HUMAN REVIEW REQUIRED — maker-checker gate (P-06). "
        "Decision support, not a credit decision. The assistant proposes; a credit officer "
        "disposes.</div>"
        if data.get("requires_human_review")
        else ""
    )
    body = (
        header
        + review
        + _section("Summary", f"<p class='summary'>{esc(data['summary'])}</p>")
        + _section("Financial analysis", render_metrics(data.get("financial_metrics", [])))
        + _section(
            "Covenants",
            render_covenants(data.get("covenants", [])),
            extra=(
                f"<span class='statuspill' style='background:#fee2e2;color:#b91c1c'>{breaches} breach</span>"
                if breaches
                else "<span class='statuspill' style='background:#ecfdf5;color:#059669'>all compliant</span>"
            ),
        )
        + _section("Risk assessment", render_risk(data.get("risk_flags", [])))
        + _section("Peer comparison", render_peers(data.get("peer_comparison", [])))
        + _section(
            "Recommendation rationale",
            f"<p class='summary'>{esc(data.get('recommendation_rationale', ''))}</p>",
        )
        + "<p class='foot'>Audit-first credit-memo view · synthetic fictional data · "
        "deterministic covenant/peer engine</p>"
    )
    return page(f"Credit memo — {borrower['name']}", body)


def render_sources(data: dict) -> str:
    borrower = data["borrower"]
    filings = data.get("filings", [])
    frows = "".join(
        f"<tr><td class='mono'>{esc(f['id'])}</td><td>{esc(f['doc_type'])}</td>"
        f"<td>{esc(f['title'])}</td></tr>"
        for f in filings
    )
    crows = "".join(
        f"<tr><td>{chip(c)}</td><td>{esc(c.get('title'))}</td>"
        f"<td class='mono'>{esc(c.get('page'))}</td></tr>"
        for c in data.get("citations", [])
    )
    body = (
        f"<h1>Sources &amp; audit — {esc(borrower['name'])}</h1>"
        f"<p class='sub'>Every claim in the memo traces to a source filing, credit-policy "
        f"passage or peer data point. Actor: <b class='mono'>{esc(data.get('actor'))}</b>.</p>"
        "<p class='navlinks'><a href='memo.html'>Memo</a><a href='sources.html'>Sources &amp; audit</a></p>"
        + _section(
            "Input filings (extracted + ingested under borrower ACL)",
            "<table class='cov'><tr><th>Doc id</th><th>Type</th><th>Title</th></tr>"
            + frows
            + "</table>",
        )
        + _section(
            "Citations (provenance for the memo claims)",
            "<table class='cov'><tr><th>Chip</th><th>Title</th><th>Page</th></tr>"
            + crows
            + "</table>",
            extra=f"<span class='muted'>{len(data.get('citations', []))} total</span>",
        )
        + "<p class='foot'>Audit-first credit-memo view · synthetic fictional data · "
        "PII redacted at the boundary before any model/index/audit call</p>"
    )
    return page(f"Sources — {borrower['name']}", body)


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fname, html_text in (
        ("memo.html", render_memo(data)),
        ("sources.html", render_sources(data)),
    ):
        p = out / fname
        p.write_text(html_text)
        written.append(p)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
