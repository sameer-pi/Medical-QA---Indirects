"""Cache every client's own category list into qa_category - THE CANDIDATE SET.

    python pipeline/load_taxonomy.py

This is the table that unblocks `suggested_cat_l1..l4`. Without it the pipeline can say "this is in
the wrong bucket" and cannot say which bucket it belongs in, which is half the deliverable.

WHY A TABLE AND NOT A COLUMN. Two structural shortcuts were tested on 2026-08-03 and both failed:

  the sibling set     of the 97 subjects where an identical vendor + identical item text received
                      two DIFFERENT categories, the alternative was a sibling on only 10.3%.
                      89.7% sat in a different Level-1 branch entirely. Errors are gross misfiles,
                      not near misses, so "the boxes next door" is the wrong shortlist.
  the vendor's own    71% of categorised vendors have only ever used ONE category, so their history
  history             offers no alternative - and that is exactly the dumping-ground case.

So the shortlist is the tree itself, narrowed by MEANING rather than by structure: pick the branch,
then pick the leaf within it. 50 branches and 1,449 leaves at Northern - 58 choices instead of
1,449, and small enough to hand a judge whole. Far too big to repeat on 875,000 lines, which is why
it lives here.

ISOLATION. Every row carries client_code (in the primary key) and taxonomy_source naming the
database and table it came from. The taxonomy keys COLLIDE across hospitals while meaning different
things - key 379 is Cheese at Melbourne and Facilities Management at Northern - so this table is
only safe read one client at a time. `candidates()` enforces that.

Reads the client databases READ-ONLY. Writes to the pilot QA database only.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg  # noqa: E402
from db import connect_client, connect_qa, load_env  # noqa: E402
from smoke_test import LEVELS, check_level_overflow  # noqa: E402

COLUMNS = ["CLIENT_CODE", "CATEGORY_KEY", "TAXONOMY_SOURCE",
           "CATEGORY_LVL_0", "CATEGORY_LVL_1", "CATEGORY_LVL_2", "CATEGORY_LVL_3", "CATEGORY_LVL_4",
           "PATH_FULL", "BRANCH", "LEAF", "PARENT_PATH", "DEPTH_DISTINCT", "SIBLING_COUNT",
           "CATEGORY_DESCRIPTION", "ADDRESSABLE", "IS_CLINICAL", "IN_SCOPE", "LINES_IN_SCOPE"]


def _t(v):
    """Trim on the way in. Sydney Adventist stores 'Clinical ' with a trailing space and SQL Server
    pads on comparison where Python does not - an untrimmed gate would let 524,923 clinical lines
    through a pandas-side filter silently."""
    return (v or "").strip() if isinstance(v, str) else v


def load_client(k, qcur, env):
    cfg = clientcfg.load_config(k)
    if not cfg or clientcfg.missing_for_run(cfg):
        print(f"  {k:20} SKIPPED - config incomplete")
        return 0
    tx_tbl = clientcfg.taxonomy_table(cfg)
    tx_key = clientcfg.taxonomy_join_column(cfg)
    if not tx_tbl or not tx_key:
        print(f"  {k:20} SKIPPED - no taxonomy configured")
        return 0
    db_name = ((cfg.get("source") or {}).get("database") or "?")
    source = f"{db_name}.{tx_tbl}"

    cn = connect_client(k, env=env, timeout=60)
    cn.timeout = 600
    cur = cn.cursor()
    bare = tx_tbl.replace("[", "").replace("]", "").split(".")[-1]
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?", bare)
    have = {c[0] for c in cur.fetchall()}
    check_level_overflow(k, have)

    lvl = [f"Category Level {i}" if f"Category Level {i}" in have else None for i in LEVELS]
    desc_col = "Category Description" if "Category Description" in have else None
    addr_col = "Category Adressable" if "Category Adressable" in have else None  # sic, all four
    pick = [f"[{tx_key}]"] + [f"[{c}]" if c else "NULL" for c in lvl] \
        + [f"[{desc_col}]" if desc_col else "NULL", f"[{addr_col}]" if addr_col else "NULL"]
    cur.execute(f"SELECT {', '.join(pick)} FROM {tx_tbl}")
    raw = cur.fetchall()

    # how much of the client's spend actually USES each category. A judge should not be offered a
    # category no line has ever landed in without knowing that; and a category carrying 200,000
    # lines is a different kind of suggestion from one carrying none.
    cols = clientcfg.column_map(cfg)
    usage = {}
    if "taxonomy_key" in cols:
        c0 = cols["cat_l0"]
        excl = ", ".join(f"'{v}'" for v in ["Clinical"] + list(clientcfg.scope_exclusions(cfg)))
        T = "LTRIM(RTRIM(CONVERT(nvarchar(80), v.[{}])))"
        cur.execute(f"""SELECT {T.format(cols['taxonomy_key'])}, COUNT(*) FROM {clientcfg.source_table(cfg)} v
            WHERE (LTRIM(RTRIM(CONVERT(nvarchar(400), v.[{c0}]))) NOT IN ({excl})
                   OR v.[{c0}] IS NULL)
            GROUP BY {T.format(cols['taxonomy_key'])}""")
        usage = {r[0]: r[1] for r in cur.fetchall() if r[0]}
    cn.close()

    rows, paths = [], {}
    for r in raw:
        key = _t(str(r[0])) if r[0] is not None else None
        if not key:
            continue
        levels = [_t(r[1 + i]) or None for i in range(len(LEVELS))]
        # DISTINCT depth, not populated depth. These taxonomies pad shallow categories by repeating
        # the leaf - 'Beverages > Beverages > Beverages' - so a category that looks five deep may
        # really be three, and the two measures disagree on 96.5% of Northern's rows.
        seen, distinct = set(), []
        for v in levels:
            if v and v not in seen:
                seen.add(v)
                distinct.append(v)
        depth = len(distinct)
        leaf = distinct[-1] if distinct else None
        parent = " > ".join(distinct[:-1]) if depth > 1 else None
        # The marker is conditional on LEVEL 0, exactly as it is on qa_line - not decided per level.
        # Level 0 empty means there is no path at all, so every level reads Uncategorised. Level 0
        # filled with a deeper level empty is a real category with a SHORT path, which is a different
        # thing and must not read as uncategorised. These paths become suggested_cat_l0..l4 verbatim,
        # so any drift between the two conventions would put the analyst's suggestion in a vocabulary
        # the assigned category does not use.
        marker = (clientcfg.LEVEL_UNCATEGORISED if not levels[0]
                  else clientcfg.LEVEL_NOT_USED)
        full = " > ".join(
            v if v else clientcfg.NO_SUCH_LEVEL.format(i) if lvl[i] is None
            else marker for i, v in enumerate(levels))
        l0 = levels[0]
        rows.append([k, key, source] + levels + [full, levels[1], leaf, parent, depth, None,
                    _t(r[1 + len(LEVELS)]) or None, _t(r[2 + len(LEVELS)]) or None,
                    1 if l0 == "Clinical" else 0,
                    0 if (l0 in ("Clinical",) or l0 in set(clientcfg.scope_exclusions(cfg))) else 1,
                    usage.get(key, 0)])
        paths.setdefault(parent, set()).add(leaf)

    for row in rows:
        row[13] = len(paths.get(row[11], ()))   # sibling_count, at the row's own real depth

    # de-duplicate on the primary key. Western has genuine duplicates - WH0001 and WH0002 carry
    # identical paths under different IDs - but a repeated ID would break the insert, so take the
    # first and report the count rather than failing.
    dedup, dupes = {}, 0
    for row in rows:
        if row[1] in dedup:
            dupes += 1
            continue
        dedup[row[1]] = row
    rows = list(dedup.values())

    qcur.execute("DELETE FROM qa_category WHERE client_code=?", k)
    qcur.fast_executemany = False
    qcur.executemany(
        f"INSERT INTO qa_category ({', '.join(COLUMNS)}) VALUES ({', '.join('?'*len(COLUMNS))})",
        [tuple(r) for r in rows])
    used = sum(1 for r in rows if (r[18] or 0) > 0)
    inscope = sum(1 for r in rows if r[17])
    print(f"  {k:20} {len(rows):>6,} categories  {inscope:>6,} in scope  {used:>6,} actually used"
          + (f"   ({dupes} duplicate keys dropped)" if dupes else ""))
    return len(rows)


# The merged indirect taxonomy is stored in qa_category under this sentinel rather than in a table
# of its own. Sameer, 2026-08-14: *"any writing into sql strictly do it in only qa_line like we were
# doing before"* - so no new tables. qa_category is the table the candidate set has always lived in,
# and the merged key (NC-0042) is globally unique, so a sentinel client cannot collide with a real
# one. The four client taxonomies stay exactly as they are: a line's EXISTING category is still
# judged against its own hospital's structure. Only the SUGGESTION comes from here.
MERGED_CLIENT = "merged_indirect"


def load_merged(qcur, path=None):
    """Load the locked merged taxonomy into qa_category as the SUGGESTION source.

    Reads the newest MERGED workbook and opens no database but the pilot. Idempotent - the
    sentinel's rows are deleted and rewritten, so a re-run cannot double-count.

    IN_SCOPE, and why `Clinical` is 0:
      NC / NP  ->  1, offered on every line.
      CL       ->  0, so it reaches the FULL-taxonomy list only - which is the uncategorised
                   lines, the exact case Sameer added it for (167 of the pilot's 500 uncategorised
                   lines are clinical). A categorised in-scope line is non-clinical by definition,
                   so offering the hand-off there would be an escape hatch on 1,500 lines that do
                   not need one. TRADE-OFF, stated rather than hidden: a categorised line that is
                   really clinical can no longer be called out. Flip this one value to change it.
    """
    from openpyxl import load_workbook
    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "output", "Taxonomy")
    if path is None:
        files = sorted(f for f in os.listdir(outdir)
                       if f.startswith("Indirect Taxonomy - MERGED - ") and f.endswith(".xlsx"))
        if not files:
            print("  no MERGED workbook found - run merge_taxonomy.py --emit first")
            return 0
        path = os.path.join(outdir, files[-1])
    src = os.path.basename(path)
    ws = load_workbook(path, data_only=True).active
    hdr = [str(c.value or "").strip() for c in ws[1]]
    ix = {h: hdr.index(h) for h in hdr}
    rows, seen = [], set()
    for r in ws.iter_rows(min_row=2, values_only=True):
        key = _t(r[ix["INDIRECT_KEY"]])
        if not key or key in seen:
            continue
        seen.add(key)
        lv = [_t(r[ix[f"LEVEL_{i}"]]) or "" for i in range(5)]
        full = _t(r[ix["FULL_PATH"]])
        # DISTINCT depth, not padded depth - the padding is display only.
        distinct = []
        for v in lv:
            if v and (not distinct or v != distinct[-1]):
                distinct.append(v)
        clinical = lv[0].upper() == "CLINICAL"
        rows.append((MERGED_CLIENT, key, src, *lv, full,
                     distinct[1] if len(distinct) > 1 else lv[0],   # BRANCH  = Level 1
                     distinct[-1],                                   # LEAF
                     " > ".join(distinct[:-1]) if len(distinct) > 1 else "",
                     len(distinct), 0,
                     # THE DEFINITION - what this category EXCLUDES, in Sameer's words. Empty on
                     # every category until 2026-08-24; judge.emit_batch has always sent it to the
                     # model as `definition`, so filling it in needs no change on the judge side.
                     (_t(r[ix["DEFINITION"]]) if "DEFINITION" in ix else None) or None,
                     "N" if lv[0].upper() == "NON-PROCUREMENT" else "Y",
                     1 if clinical else 0,
                     0 if clinical else 1,
                     int(r[ix["LINES"]] or 0)))
    qcur.execute("DELETE FROM qa_category WHERE client_code = ?", MERGED_CLIENT)
    qcur.fast_executemany = True
    qcur.executemany(
        f"INSERT INTO qa_category ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        rows)
    print(f"  {MERGED_CLIENT:20} {len(rows):>6,} categories from {src}")
    return len(rows)


def candidates(qcur, client_code, branch=None, in_scope_only=True, used_only=False):
    """The shortlist for one client. ALWAYS filtered by client_code - the keys collide.

    branch=None  -> the first step: every Level-1 branch, with how many leaves and lines each holds
    branch='X'   -> the second step: every leaf under that branch
    """
    where = ["client_code = ?"]
    args = [client_code]
    if in_scope_only:
        where.append("in_scope = 1")
    if used_only:
        where.append("lines_in_scope > 0")
    if branch is None:
        qcur.execute(f"""SELECT branch, COUNT(*), SUM(lines_in_scope)
            FROM qa_category WHERE {' AND '.join(where)} AND branch IS NOT NULL
            GROUP BY branch ORDER BY 3 DESC""", *args)
        return qcur.fetchall()
    where.append("branch = ?")
    args.append(branch)
    qcur.execute(f"""SELECT category_key, leaf, path_full, category_description, lines_in_scope
        FROM qa_category WHERE {' AND '.join(where)} ORDER BY lines_in_scope DESC""", *args)
    return qcur.fetchall()


def main():
    env = load_env()
    # --production added 2026-08-21. This script was pilot-only and its banner said so; the
    # production load needs the candidate set or the judge can say "wrong bucket" and not "which
    # bucket", which is half the deliverable. The banner now names the database it actually wrote
    # to - it used to print "(pilot only)" unconditionally, the same defect as apply_schema's
    # banner and build_pilot's "pilot-" run_id on production rows.
    production = "--production" in sys.argv
    qa = connect_qa(pilot=not production, production=production, env=env)
    qcur = qa.cursor()
    qcur.execute("SELECT DB_NAME()")
    print(f"writing to {qcur.fetchone()[0]}  "
          f"({'PRODUCTION' if production else 'pilot'})   "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    if "--merged-only" not in sys.argv:
        for k in clientcfg.list_clients():
            load_client(k, qcur, env)
            qa.commit()
    # The merged indirect taxonomy - the SUGGESTION source from PLAN v3.37 change 204.
    load_merged(qcur)
    qa.commit()

    print("\n" + "=" * 78)
    print("THE CANDIDATE SET - step 1: how many branches does a judge choose between?")
    print("=" * 78)
    for k in clientcfg.list_clients():
        br = candidates(qcur, k)
        if not br:
            continue
        qcur.execute("SELECT COUNT(*) FROM qa_category WHERE client_code=? AND in_scope=1", k)
        leaves = qcur.fetchone()[0]
        print(f"\n  {k}: {len(br)} branches, {leaves:,} in-scope categories")
        print(f"    -> a judge picks 1 of {len(br)}, then 1 of ~{leaves // max(len(br),1)}, "
              f"instead of 1 of {leaves:,}")
        for b, n, lines in br[:4]:
            print(f"       {str(b)[:44]:46} {n:>4} leaves  {(lines or 0):>9,} lines")
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
