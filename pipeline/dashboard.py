"""Indirect QA — the manager dashboard. One screen, four cards, no drill-down.

    python pipeline/dashboard.py

Reads the pilot database (SELECT only, nothing is written to it) and writes a self-contained HTML
file to program/. Opens from the file system: no CDN, no fonts, no network, same house style as
taxonomy_chart.py.

WHO IT IS FOR. Internal managers, decided by Sameer 2026-08-18. It answers two questions and
deliberately no others: HOW FAR THROUGH ARE WE, and WHERE ARE THE ISSUES AND HOW MANY. Anything
that needs a click belongs in the analyst queue, not here.

THE SHAPE COMES FROM THE MSD APP, Assets/Screenshot of app msd.png, which Sameer sent as the level
to aim at: a card per client, a couple of headline pills, a stacked proportion bar, and a footer of
raw counts. His words: "we can keep measurable parameters without overcomplicating anything."

  their card                        ours
  BLUESCOPE / 129,616 Raw Vendors   Northern Health / 875,018 in-scope lines
  pills Compaction / Enriched       judged % / needs-an-analyst % / 3of3 %
  stacked COUNT bar                 stacked count bar, segmented by the six NIM_ACTION values
  footer Matched 127,854/129,616    judged N / N in scope
  one shared legend                 the six NIM_ACTION values with their meanings

WHY THERE IS NO SPEND BAR, THOUGH THEIR APP HAS ONE. Their spend is all positive so a stacked
proportion bar works. OURS IS SIGNED - Melbourne carries a -$5,625,000,000 line, and Northern is
$2.97bn signed against $53.9bn absolute. A stacked proportion bar CANNOT DRAW A NEGATIVE SEGMENT,
and quietly driving it off absolute would look identical while breaking the standing rule that spend
is reported exactly as the data holds it. Decided by Sameer 2026-08-18: signed figures beside each
action, no bar. Nothing netted, nothing absolute-valued, a negative reads as negative.

FOUR THINGS THIS FILE REFUSES TO DO, each one a trap something else already fell into:

  1. It reads NIM_* - the live three-model jury - and never the older Claude `verdict` columns.
     Two verdict layers coexist in qa_line. state_audit.py reported only the old one until
     2026-08-18 and closed with "no accuracy figure is quotable" long after that stopped being
     true. Mixing the layers on one screen is how that happens again.
  2. It does NOT count 'Out of scope' as an error. Those lines are a scope finding, not a defect -
     action_classify.py says so in the value's own description - and folding them in inflates every
     error rate on the page.
  3. It does NOT compute a "% with a destination". NIM_SUGGESTED_KEY is NULL BY DESIGN on a
     Correct verdict, so that ratio undercounts by exactly the lines we got right. This trap has
     already produced one false regression (RUN_LOG Finding 96).
  4. It does NOT touch qa_rule.ERROR_RATE, which is computed from Claude's OLD verdict layer
     (judge.py:684-691) and would silently mix layers on a page about the new one.

AND IT STATES ITS OWN SAMPLE. Every percentage here rests on 500 judged lines per hospital drawn
RULE-LED, not as a spread sample - 0.07% of the in-scope population. Those are PILOT figures, not
hospital figures, and the banner says so at the top of the page rather than in a footnote. The
whole "provisional figures" section of TRACKER.md exists because that distinction got lost once.
"""
import html
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg                                    # noqa: E402
from db import connect_qa                           # noqa: E402

OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "program")

# The six NIM_ACTION values, in the order a manager reads them: settled first, then the things that
# need someone, then the things nobody can act on. Colours are semantic - 'Out of scope' is
# deliberately NEUTRAL grey-blue and never red, because it is not an error.
ACTIONS = [
    ("No change",      "#3f9d54", "Filed correctly and completely. Nothing for anyone to do"),
    ("Re-mapped",      "#3d7fc1", "Correct, but we moved the category. Bulk-approvable - a migration, not a decision"),
    ("Incomplete",     "#d99a2b", "Never finished categorising. A gap, not an error - we filled in the detail"),
    ("Miscategorised", "#c9453d", "Wrong branch, and we say where it belongs. THIS is the analyst queue"),
    ("Needs evidence", "#8b8b8b", "We cannot act - the evidence did not settle it, or we know it is wrong but not where"),
    ("Out of scope",   "#7a8fa6", "Not an indirect line at all. A scope finding - NOT counted as an error"),
]
ERROR_ACTIONS = ("Miscategorised",)          # what "needs an analyst" means. Nothing else.


def fetch(qcur):
    """Everything the page needs, in three scans. Per client, from the live jury layer only."""
    qcur.execute("""SELECT client_code,
                           COUNT(*),
                           SUM(CASE WHEN nim_verdict IS NOT NULL THEN 1 ELSE 0 END),
                           SUM(CASE WHEN nim_agreement = '3of3' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN nim_models_responded < 3 THEN 1 ELSE 0 END),
                           COUNT(DISTINCT subject_key),
                           COUNT(DISTINCT supplier_name)
                    FROM qa_line GROUP BY client_code ORDER BY client_code""")
    base = {r[0]: dict(loaded=r[1], judged=r[2], three=r[3], hollow=r[4] or 0,
                       subjects=r[5], vendors=r[6]) for r in qcur.fetchall()}

    # Signed spend, exactly as held - no threshold, no netting, no absolute value. Line counts sit
    # beside it on the page so a reader can see when a spend figure rests on a handful of rows.
    qcur.execute("""SELECT client_code, nim_action, COUNT(*), SUM(CAST(spend AS float))
                    FROM qa_line GROUP BY client_code, nim_action""")
    for cc, act, n, spend in qcur.fetchall():
        base.setdefault(cc, {}).setdefault("acts", {})[act or "(none)"] = (n, spend or 0.0)

    # The denominator that makes this a PROGRESS page rather than a pilot report: the client's full
    # in-scope population, recorded at load time. LINES_LOADED is what this run actually took.
    #
    # THE DENOMINATOR IS AN AS-AT, NOT A CONSTANT, AND THE PAGE SAYS SO.
    # qa_run.LINES_IN_SCOPE was measured when the pilot was LOADED. Summed it gives 2,764,531;
    # CLAUDE.md quotes 2,767,046, measured six days later on 2026-08-11. The delta is +2,515
    # (0.09%) and the cause is that the client databases change during working hours - the ground
    # moved, the numbers did not drift. That is precisely why every run records an as-at.
    # Reconciling the two silently would hide a real property of the source; the page carries the
    # load date instead, so a reader can see which snapshot the percentage is against.
    #
    qcur.execute("""SELECT client_code, MAX(lines_in_scope), MAX(lines_loaded), MAX(loaded_at)
                    FROM qa_run GROUP BY client_code""")
    for cc, insc, loaded, at in qcur.fetchall():
        if cc in base:
            base[cc]["in_scope"] = insc or 0
            base[cc]["run_loaded"] = loaded or 0
            base[cc]["as_at"] = at
    return base


def money(v):
    """Signed, plain, and never abbreviated into a shape that hides a minus sign."""
    return ("-$" if v < 0 else "$") + "{:,.0f}".format(abs(v))


def card(cc, d):
    try:
        name = clientcfg.display_name(clientcfg.load_config(cc), cc)
    except Exception:                       # a client whose config moved should not kill the page
        name = cc.replace("_", " ").title()

    acts = d.get("acts", {})
    judged = d["judged"] or 0
    in_scope = d.get("in_scope", 0)
    needs = sum(acts.get(a, (0, 0))[0] for a in ERROR_ACTIONS)

    pills = [
        ("judged", "{:.2f}%".format(100.0 * judged / in_scope) if in_scope else "-"),
        ("needs an analyst", "{:.1f}%".format(100.0 * needs / judged) if judged else "-"),
        ("jury 3of3", "{:.1f}%".format(100.0 * d["three"] / judged) if judged else "-"),
    ]
    badges = [("lines", d["loaded"]), ("subjects", d["subjects"]), ("vendors", d["vendors"])]

    segs, rows = [], []
    for label, colour, _ in ACTIONS:
        n, spend = acts.get(label, (0, 0.0))
        if not n:
            continue
        segs.append('<i style="width:{:.4f}%;background:{}" title="{} - {:,} lines"></i>'.format(
            100.0 * n / judged if judged else 0, colour, html.escape(label), n))
        rows.append(
            '<tr><td><b style="background:{}"></b>{}</td><td class="n">{:,}</td>'
            '<td class="n">{:.1f}%</td><td class="n money">{}</td></tr>'.format(
                colour, html.escape(label), n, 100.0 * n / judged if judged else 0, money(spend)))

    hollow = ('<div class="warn">{} line(s) judged by fewer than 3 models</div>'.format(d["hollow"])
              if d["hollow"] else "")

    return """<article class="card">
  <h2>{name}</h2>
  <div class="sub">{insc} lines in scope</div>
  <div class="pills">{pills}</div>
  <div class="badges">{badges}</div>
  <div class="blab">Judged lines, by what should happen to them</div>
  <div class="stack">{segs}</div>
  <table class="brk">{rows}</table>
  {hollow}
  <div class="foot">judged <b>{judged:,}</b> of {insc} in scope &nbsp;·&nbsp; needs an analyst <b>{needs:,}</b></div>
</article>""".format(
        name=html.escape(name), insc="{:,}".format(in_scope) if in_scope else "unknown",
        pills="".join('<span class="pill">{} <b>{}</b></span>'.format(html.escape(k), v) for k, v in pills),
        badges="".join('<span class="badge">{} <b>{:,}</b></span>'.format(html.escape(k), v) for k, v in badges),
        segs="".join(segs), rows="".join(rows), hollow=hollow, judged=judged, needs=needs)


CSS = """
*{box-sizing:border-box}
:root{--bg:#fff;--fg:#191919;--dim:#8b8b8b;--line:#e6e6e6;--accent:#0b57a4;--card:#fff;
      --band:#fafafa;--warnbg:#fff6e6;--warnfg:#8a5a00}
@media (prefers-color-scheme:dark){
 :root{--bg:#131313;--fg:#e9e9e9;--dim:#8a8a8a;--line:#2a2a2a;--accent:#74b3ff;--card:#181818;
       --band:#161616;--warnbg:#332a14;--warnfg:#e8c47a}}
:root[data-theme=light]{--bg:#fff;--fg:#191919;--dim:#8b8b8b;--line:#e6e6e6;--accent:#0b57a4;
      --card:#fff;--band:#fafafa;--warnbg:#fff6e6;--warnfg:#8a5a00}
:root[data-theme=dark]{--bg:#131313;--fg:#e9e9e9;--dim:#8a8a8a;--line:#2a2a2a;--accent:#74b3ff;
      --card:#181818;--band:#161616;--warnbg:#332a14;--warnfg:#e8c47a}
body{margin:0;background:var(--bg);color:var(--fg);
     font:13.5px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{padding:16px 22px 12px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:16px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:12px;margin-top:2px}
button{padding:6px 11px;border:1px solid var(--line);background:var(--bg);border-radius:6px;
     font:inherit;font-size:12.5px;cursor:pointer;color:var(--fg)}
.banner{margin:14px 22px 0;padding:10px 13px;background:var(--warnbg);color:var(--warnfg);
     border-radius:7px;font-size:12.5px;line-height:1.5}
.prog{margin:14px 22px 0;padding:13px;border:1px solid var(--line);border-radius:9px;
     background:var(--band)}
.prog .big{font-size:22px;font-weight:600;letter-spacing:-.02em}
.pbar{height:9px;border-radius:5px;background:var(--line);overflow:hidden;margin-top:9px}
.pbar i{display:block;height:100%;background:var(--accent)}
.legend{margin:16px 22px 0;display:flex;gap:7px 16px;flex-wrap:wrap;font-size:12px;color:var(--dim)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend b{width:10px;height:10px;border-radius:3px;display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;padding:16px 22px 26px}
.card{border:1px solid var(--line);border-radius:9px;padding:14px;background:var(--card)}
.card h2{margin:0;font-size:14.5px}
.pills{margin-top:9px;display:flex;gap:6px;flex-wrap:wrap}
.pill{border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:11.5px;color:var(--dim)}
.pill b{color:var(--fg)}
.badges{margin-top:7px;display:flex;gap:6px;flex-wrap:wrap}
.badge{background:var(--band);border-radius:6px;padding:3px 8px;font-size:11.5px;color:var(--dim)}
.badge b{color:var(--fg)}
.blab{margin-top:13px;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.stack{display:flex;height:11px;border-radius:5px;overflow:hidden;margin-top:5px;background:var(--line)}
.stack i{display:block}
.brk{width:100%;border-collapse:collapse;margin-top:9px;font-size:12px}
.brk td{padding:2.5px 0;border-bottom:1px solid var(--line)}
.brk tr:last-child td{border-bottom:0}
.brk b{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:7px}
.brk .n{text-align:right;color:var(--dim);white-space:nowrap;padding-left:10px}
.brk .money{font-variant-numeric:tabular-nums}
.warn{margin-top:9px;padding:6px 9px;background:var(--warnbg);color:var(--warnfg);border-radius:6px;
     font-size:11.5px}
.foot{margin-top:10px;padding-top:9px;border-top:1px solid var(--line);font-size:12px;color:var(--dim)}
footer{padding:0 22px 30px;color:var(--dim);font-size:11.5px;line-height:1.6;max-width:900px}
"""

JS = """
var r=document.documentElement;
document.getElementById('t').onclick=function(){
  var d=r.getAttribute('data-theme');
  if(!d){d=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';}
  r.setAttribute('data-theme', d==='dark'?'light':'dark');
};
"""


def main():
    qa = connect_qa(pilot=True)
    qcur = qa.cursor()

    # One run_id or every figure on the page double-counts. Same assertion as six other scripts.
    qcur.execute("SELECT COUNT(DISTINCT run_id) FROM qa_line")
    nrun = qcur.fetchone()[0]
    if nrun != 1:
        raise SystemExit("\n  STOP - {} run_ids in qa_line. Every figure on this page would "
                         "double-count.\n".format(nrun))

    data = fetch(qcur)
    qa.close()
    if not data:
        raise SystemExit("no rows in qa_line")

    judged = sum(d["judged"] or 0 for d in data.values())
    in_scope = sum(d.get("in_scope", 0) for d in data.values())
    pct = 100.0 * judged / in_scope if in_scope else 0
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    ats = [d["as_at"] for d in data.values() if d.get("as_at")]
    as_at = min(ats).strftime("%Y-%m-%d") if ats else "unknown"

    page = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Indirect QA — programme dashboard</title>
<style>{css}</style>
<header>
  <div style="display:flex;justify-content:space-between;align-items:start;gap:14px">
    <div><h1>Indirect QA — programme dashboard</h1>
    <div class=sub>Non-clinical spend categorisation QA · four hospitals · generated {stamp}</div></div>
    <button id=t>theme</button>
  </div>
</header>

<div class=banner><b>These are PILOT figures, not hospital figures.</b> Every percentage below rests
on {judged:,} judged lines drawn <b>rule-led</b> from {in_scope:,} in scope — {pct:.2f}%, and
<b>not a spread sample</b>. They show what the judge does, not how accurate a hospital is. Nothing on
this page is cleared to leave the building.</div>

<div class=prog>
  <div class=big>{judged:,} <span style="font-weight:400;color:var(--dim);font-size:14px">of {in_scope:,} in-scope lines judged</span></div>
  <div class=pbar><i style="width:{pct:.4f}%"></i></div>
  <div class=sub style="margin-top:7px">{pct:.2f}% complete · at the measured 124 lines/min this is
  ~15.5 days of continuous judging once production runs</div>
  <div class=sub style="margin-top:5px">Denominator measured <b>as at {as_at}</b>, when the pilot
  was loaded. The source grew by <b>2,515 lines (0.09%)</b> in the six days to 2026-08-11 &mdash;
  client databases change during working hours, so this is a snapshot, not a constant.</div>
</div>

<div class=legend>{legend}</div>
<div class=grid>{cards}</div>

<footer>
<b>What this page counts, and what it deliberately does not.</b>
&ldquo;Needs an analyst&rdquo; is <b>Miscategorised</b> only — a line in the wrong branch where we can
say where it belongs. <b>Out of scope</b> is a scope finding and is <b>never counted as an error</b>.
<b>Re-mapped</b> is a migration we caused, not a hospital mistake, and is bulk-approvable.
<b>Incomplete</b> is a gap, not an error.<br><br>
Figures come from the live three-model jury (<code>NIM_*</code>), never the older single-model
layer. Spend is <b>signed, exactly as the data holds it</b> — no threshold, no netting, no absolute
values — and is shown as figures rather than a bar because a stacked proportion bar cannot draw a
negative segment. Line counts sit beside every spend figure so you can see when one rests on a
handful of rows.<br><br>
Generated by <code>pipeline/dashboard.py</code>, read-only. Current state and what is gated on whom:
<code>TRACKER.md</code>.
</footer>
<script>{js}</script>
</html>""".format(
        css=CSS, js=JS, stamp=stamp, judged=judged, in_scope=in_scope, pct=pct, as_at=as_at,
        legend="".join('<span><b style="background:{}"></b>{} — {}</span>'.format(
            c, html.escape(l), html.escape(desc)) for l, c, desc in ACTIONS),
        cards="".join(card(cc, data[cc]) for cc in sorted(data)))

    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    out = os.path.join(OUTDIR, "Indirect QA Dashboard - {}.html".format(
        datetime.now().strftime("%Y-%m-%d")))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)

    print("clients: {}   judged {:,} of {:,} in scope ({:.2f}%)".format(
        len(data), judged, in_scope, pct))
    for cc in sorted(data):
        d = data[cc]
        needs = sum(d.get("acts", {}).get(a, (0, 0))[0] for a in ERROR_ACTIONS)
        print("  {:20} judged {:>6,} / {:>9,}   needs an analyst {:>4,}".format(
            cc, d["judged"] or 0, d.get("in_scope", 0), needs))
    print("\nWRITTEN: " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
