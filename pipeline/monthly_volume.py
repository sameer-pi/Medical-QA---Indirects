"""READ-ONLY. How many in-scope lines arrive per month, per hospital, and how variable is it.

Answers PLAN.md v3.55 change 318. Nothing is written anywhere. Client databases are read-only.

Two things this does NOT do, deliberately:
  - it does not divide the population by the date span. Sameer, 2026-08-20: "invoices dont arrive
    evenly, it all depends on the data we recieve". A mean would describe a month that never happens.
  - it does not trust the config's fill-rate comments. The null count is measured in the same scan.

Scope is taken from the SAME construction the loader uses (build_pilot.scope_counts) rather than
re-written here. A second definition of scope is a defect, not a convenience.
"""
import os, sys, statistics
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "pipeline")

import clientcfg, db
from build_pilot import T

DATE_FIELD = "posting_date"   # 100% on all four; invoice_date is 52% at SAH and can be backdated


def main():
    env = db.load_env()
    print("=" * 92)
    print("MONTHLY ARRIVAL VOLUME - in-scope indirect lines, by POSTING month.  READ-ONLY")
    print("=" * 92)

    grand = {}
    for key in sorted(clientcfg.list_clients()):
        cfg = clientcfg.load_config(key)
        clientcfg.assert_same_database(cfg, key)
        cols = clientcfg.column_map(cfg)
        tbl, c0 = clientcfg.source_table(cfg), cols["cat_l0"]
        dcol = cols.get(DATE_FIELD)
        if not dcol:
            print(f"\n  {key}: no {DATE_FIELD} configured - SKIPPED")
            continue

        excl = [v.strip() for v in
                set(clientcfg.clinical_exclusions(cfg)) | set(clientcfg.scope_exclusions(cfg))]
        notin = ", ".join(f"'{v}'" for v in excl) or "''"
        scope_where = f"({T(f'v.[{c0}]')} NOT IN ({notin}) OR v.[{c0}] IS NULL)"

        # ONE scan. Aggregate in SQL - never fetch lines and count them in Python.
        q = f"""SELECT CASE WHEN v.[{dcol}] IS NULL THEN '(no date)'
                            ELSE CONVERT(char(7), CAST(v.[{dcol}] AS date), 126) END AS ym,
                       COUNT(*)
                FROM {tbl} v
                WHERE {scope_where}
                GROUP BY CASE WHEN v.[{dcol}] IS NULL THEN '(no date)'
                              ELSE CONVERT(char(7), CAST(v.[{dcol}] AS date), 126) END
                ORDER BY 1"""

        with db.connect_client(key, env=env, timeout=600) as cx:
            cur = cx.cursor()
            cur.execute(q)
            rows = cur.fetchall()      # one row per month, not per line

        buckets = {r[0]: r[1] for r in rows}
        nodate = buckets.pop("(no date)", 0)
        total = sum(buckets.values()) + nodate
        months = sorted(buckets)
        counts = [buckets[m] for m in months]

        print(f"\n{'-' * 92}\n{key}   [{dcol}]")
        print(f"  in scope {total:>10,}     no posting date {nodate:>9,} "
              f"({nodate / total * 100:.1f}%)     months spanned {len(months)}")
        if not counts:
            print("  ** no dated lines - a monthly figure cannot be derived here **")
            continue

        # the last 12 dated months, which is what a monthly product actually lives in
        recent = months[-12:]
        rc = [buckets[m] for m in recent]
        print(f"  span {months[0]} -> {months[-1]}")
        print(f"  ALL dated months   min {min(counts):>9,}   median {int(statistics.median(counts)):>9,}"
              f"   max {max(counts):>9,}")
        print(f"  last 12 months     min {min(rc):>9,}   median {int(statistics.median(rc)):>9,}"
              f"   max {max(rc):>9,}")
        print("  last 12: " + "  ".join(f"{m[-2:]}:{buckets[m]:,}" for m in recent))
        grand[key] = {"recent": rc, "nodate": nodate, "total": total, "months": recent}

    # ---- combined, month by month, so the peak is a real month and not a sum of separate peaks
    print(f"\n{'=' * 92}\nALL FOUR HOSPITALS COMBINED - per calendar month\n{'=' * 92}")
    allm = sorted({m for g in grand.values() for m in g["months"]})
    tot_nodate = sum(g["nodate"] for g in grand.values())
    tot_all = sum(g["total"] for g in grand.values())
    per = []
    for m in allm:
        n = 0
        for k, g in grand.items():
            if m in g["months"]:
                n += g["recent"][g["months"].index(m)]
        per.append((m, n))
    for m, n in per:
        print(f"  {m}   {n:>10,}")
    if per:
        v = [n for _, n in per]
        print(f"\n  min {min(v):,}   median {int(statistics.median(v)):,}   max {max(v):,}"
              f"   over {len(v)} months")
        print(f"\n  ** The MAX is the number the design has to survive, not the median. **")
        print(f"  at 124 lines/min end-to-end:  median month = {statistics.median(v) / 124 / 60:.1f} h"
              f"   worst month = {max(v) / 124 / 60:.1f} h")
    print(f"\n  no posting date anywhere: {tot_nodate:,} of {tot_all:,} in-scope lines "
          f"({tot_nodate / tot_all * 100:.1f}%)")
    print("  ^ these carry no arrival month at all. Any monthly figure describes the REST.")


if __name__ == "__main__":
    main()
