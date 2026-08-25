"""Render the merged indirect taxonomy as a browsable hierarchy, offline.

    python pipeline/taxonomy_chart.py

Reads the newest MERGED workbook in output/Taxonomy/ and writes an HTML file beside it. Read-only:
no database is opened, and no file other than its own output is touched.

The five levels and nothing else, per Sameer 2026-08-12 - no line counts, no client counts. This is
the shape of the taxonomy, not a measurement of it.

WHY A COLUMN OUTLINE RATHER THAN A TREE. The first version was a collapsing tree, which reads well
at branch level and badly at line level: to compare two categories you had to hold their ancestry in
your head. Every category is now ONE ROW with Level 2, 3 and 4 in aligned columns, and a repeated
value is dimmed rather than restated - the same thing Excel does when you turn off repeated item
labels. The eye follows the indent, and any two rows can be compared directly.

REPEATED LEVELS ARE FOLDED BY DEFAULT. Most categories carry a Level 4 that is a verbatim copy of
Level 3, because every path is padded so no level is ever blank. That is correct in the taxonomy and
noise in a table - 'Bank Charges | Bank Charges' says nothing twice. Folded for display, restored by
a toggle, so the padding is never hidden, only folded.

Self-contained: no CDN, no fonts, no network. It opens from the file system.
"""
import html
import os
import sys
from collections import OrderedDict

OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "output", "Taxonomy")


def newest_merged(outdir):
    cands = [os.path.join(outdir, f) for f in os.listdir(outdir)
             if "MERGED" in f and f.lower().endswith(".xlsx") and not f.startswith("~$")]
    if not cands:
        sys.exit("No MERGED .xlsx in output/Taxonomy/ - run merge_taxonomy.py --emit first.")
    return max(cands, key=os.path.getmtime)


def load(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).active
    hdr = [str(c.value or "").strip() for c in ws[1]]
    cols = [hdr.index(f"LEVEL_{i}") for i in range(5)]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        segs = [str(row[c]).strip() if row[c] is not None else "" for c in cols]
        if any(segs):
            out.append(segs)
    return out


def group(rows):
    """{(L0, L1): [[L2, L3, L4], ...]} in sorted order."""
    g = OrderedDict()
    for l0, l1, l2, l3, l4 in sorted(rows, key=lambda r: [x.lower() for x in r]):
        g.setdefault((l0, l1), []).append([l2, l3, l4])
    return g


def cells(levels, prev, fold):
    """One row's three cells: '' where the level repeats its parent (padding) or the row above."""
    out, seen = [], None
    for i, v in enumerate(levels):
        if fold and v and v == seen:
            out.append(("pad", v))                 # repeats its own parent - the padding
        elif v and prev and i < len(prev) and v == prev[i] and all(
                levels[j] == prev[j] for j in range(i)):
            out.append(("rep", v))                 # same as the row above, at the same place
        else:
            out.append(("", v))
        if v:
            seen = v
    return out


CSS = """
*{box-sizing:border-box}
:root{--bg:#fff;--fg:#191919;--dim:#8b8b8b;--faint:#c8c8c8;--line:#e6e6e6;--hi:#f0f6ff;
      --accent:#0b57a4;--band:#fafafa;--head:#fff}
@media (prefers-color-scheme:dark){
 :root{--bg:#131313;--fg:#e9e9e9;--dim:#8a8a8a;--faint:#4a4a4a;--line:#2a2a2a;--hi:#16283d;
       --accent:#74b3ff;--band:#181818;--head:#131313}}
:root[data-theme=light]{--bg:#fff;--fg:#191919;--dim:#8b8b8b;--faint:#c8c8c8;--line:#e6e6e6;
      --hi:#f0f6ff;--accent:#0b57a4;--band:#fafafa;--head:#fff}
:root[data-theme=dark]{--bg:#131313;--fg:#e9e9e9;--dim:#8a8a8a;--faint:#4a4a4a;--line:#2a2a2a;
      --hi:#16283d;--accent:#74b3ff;--band:#181818;--head:#131313}
body{margin:0;background:var(--bg);color:var(--fg);
     font:13.5px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{position:sticky;top:0;z-index:30;background:var(--head);border-bottom:1px solid var(--line);
       padding:14px 22px 11px}
h1{margin:0;font-size:16px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:12px;margin-top:2px}
.bar{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=search]{flex:1 1 240px;min-width:180px;padding:7px 10px;border:1px solid var(--line);
     border-radius:6px;font:inherit;background:var(--bg);color:var(--fg)}
button,label.tog{padding:6px 11px;border:1px solid var(--line);background:var(--bg);
     border-radius:6px;font:inherit;font-size:12.5px;cursor:pointer;color:var(--fg)}
label.tog{display:inline-flex;align-items:center;gap:6px}
button:hover{background:var(--band)}
.wrap{display:flex;align-items:flex-start}
nav{position:sticky;top:104px;flex:0 0 236px;max-height:calc(100vh - 116px);overflow:auto;
    padding:14px 8px 40px 18px;border-right:1px solid var(--line)}
nav a{display:flex;justify-content:space-between;gap:8px;padding:4px 8px;border-radius:5px;
    color:var(--fg);text-decoration:none;font-size:12.5px}
nav a:hover{background:var(--band)}
nav a .c{color:var(--dim);font-variant-numeric:tabular-nums;font-size:11px}
nav .grp{margin:12px 0 4px 8px;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
    color:var(--dim)}
main{flex:1 1 auto;min-width:0;padding:0 22px 120px}
section{scroll-margin-top:116px}
h2{position:sticky;top:104px;z-index:20;margin:0;padding:14px 4px 7px;background:var(--head);
   font-size:14px;letter-spacing:-.01em;border-bottom:1px solid var(--line)}
h2 .c{color:var(--dim);font-weight:400;font-size:11.5px;margin-left:8px}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th{text-align:left;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--dim);
   font-weight:600;padding:8px 8px 5px;border-bottom:1px solid var(--line)}
td{padding:3px 8px;border-bottom:1px solid var(--line);vertical-align:top;
   overflow-wrap:anywhere}
tr:hover td{background:var(--hi)}
col.c2{width:27%}col.c3{width:31%}col.c4{width:31%}
td.l2{font-weight:600}
td.l3{color:var(--fg)}
td.l4{color:var(--fg)}
.rep{color:var(--faint)}
.pad{color:var(--faint);font-style:italic}
.hidepad .pad{visibility:hidden}
.hide{display:none}
mark{background:#ffe27a;color:#000;padding:0 1px;border-radius:2px}
footer{color:var(--dim);font-size:11.5px;padding:0 22px 40px}
@media(max-width:860px){nav{display:none}}
"""

JS = """
const q=document.getElementById('q'), body=document.body;
const secs=[...document.querySelectorAll('section')];
document.getElementById('pad').addEventListener('change',e=>{
  body.classList.toggle('hidepad',!e.target.checked);});
document.getElementById('theme').onclick=()=>{
  const r=document.documentElement;
  const now=r.dataset.theme||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  r.dataset.theme=now==='dark'?'light':'dark';};
function filter(){
  const s=q.value.trim().toLowerCase();
  document.querySelectorAll('mark').forEach(m=>{const t=m.textContent;m.replaceWith(t);});
  secs.forEach(sec=>{
    let hits=0;
    sec.querySelectorAll('tbody tr').forEach(tr=>{
      const txt=(tr.dataset.t||'');
      const ok=!s||txt.includes(s);
      tr.classList.toggle('hide',!ok);
      if(ok){hits++;
        if(s)[...tr.cells].forEach(td=>{
          const t=td.textContent,i=t.toLowerCase().indexOf(s);
          if(i>=0)td.innerHTML=t.slice(0,i)+'<mark>'+t.slice(i,i+s.length)+'</mark>'+t.slice(i+s.length);
        });}
    });
    const secHit=hits>0||(s&&sec.dataset.b.includes(s));
    sec.classList.toggle('hide',!secHit);
    const link=document.querySelector('nav a[href="#'+sec.id+'"]');
    if(link)link.classList.toggle('hide',!secHit);
  });
}
q.addEventListener('input',filter);
document.addEventListener('keydown',e=>{
  if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();}
  if(e.key==='Escape'){q.value='';filter();q.blur();}});
"""


def main():
    src = newest_merged(OUTDIR)
    rows = load(src)
    groups = group(rows)
    stamp = os.path.basename(src).replace("Indirect Taxonomy - MERGED - ", "").replace(".xlsx", "")

    nav, secs, last_l0 = [], [], None
    for i, ((l0, l1), items) in enumerate(groups.items()):
        sid = f"s{i}"
        if l0 != last_l0:
            nav.append(f'<div class="grp">{html.escape(l0)}</div>')
            last_l0 = l0
        nav.append(f'<a href="#{sid}"><span>{html.escape(l1)}</span>'
                   f'<span class="c">{len(items)}</span></a>')

        trs, prev = [], None
        for lv in items:
            cs = cells(lv, prev, fold=True)
            prev = lv
            tds = "".join(
                f'<td class="l{n + 2} {cls}">{html.escape(v)}</td>'
                for n, (cls, v) in enumerate(cs))
            key = html.escape(" ".join(x for x in lv if x).lower())
            trs.append(f'<tr data-t="{key}">{tds}</tr>')

        secs.append(
            f'<section id="{sid}" data-b="{html.escape(l1.lower())}">'
            f'<h2>{html.escape(l1)}<span class="c">{html.escape(l0)}'
            f' &middot; {len(items)} categories</span></h2>'
            f'<table><colgroup><col class="c2"><col class="c3"><col class="c4"></colgroup>'
            f'<thead><tr><th>Level 2</th><th>Level 3</th><th>Level 4</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></section>')

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Indirect taxonomy &mdash; {html.escape(stamp)}</title>
<style>{CSS}</style></head><body class="hidepad">
<header>
  <h1>Indirect taxonomy</h1>
  <div class="sub">{len(rows)} categories &middot; {len(groups)} Level&nbsp;1 branches &middot;
    Level&nbsp;0 is the scope gate &middot; {html.escape(os.path.basename(src))}</div>
  <div class="bar">
    <input type="search" id="q" placeholder="Filter &mdash; press / to jump here" autocomplete="off">
    <label class="tog"><input type="checkbox" id="pad"> show repeated levels</label>
    <button id="theme">Light / dark</button>
  </div>
</header>
<div class="wrap">
  <nav>{"".join(nav)}</nav>
  <main>{"".join(secs)}</main>
</div>
<footer>Levels 2&ndash;4 only; Level&nbsp;1 is the section heading and Level&nbsp;0 the scope gate.
A greyed value repeats the row above or the level before it &mdash; tick
<em>show repeated levels</em> to see every level exactly as stored.</footer>
<script>{JS}</script></body></html>"""

    out = os.path.join(OUTDIR, f"Indirect Taxonomy - HIERARCHY - {stamp}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"  read   : {os.path.basename(src)}  ({len(rows)} categories, {len(groups)} branches)")
    print(f"  WRITTEN: {out}")


if __name__ == "__main__":
    main()
