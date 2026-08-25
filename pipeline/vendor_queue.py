"""vendor_queue.py - build THE RUNNING ORDER for the judging run. Stage 3.

WHAT THIS IS. 2,786,018 in-scope lines at ~50 lines/min is ~40 days of judging, so something has
to decide what gets judged FIRST. This builds that list: one row per (client, vendor), ranked by
signed spend, largest first.

WHAT IT IS NOT. It is NOT a prediction about where the miscategorisation is. Sameer, 2026-08-25:
"we dont know where the miscategorising is thats our assumption the judge will decide." An earlier
draft of this work proposed measuring whether big spend correlates with errors BEFORE building the
queue - that was the wrong question. The order decides which findings are worth ACTING ON, not
where the errors are. A wrong category on $943m of ATO spend matters more than a wrong category on
$4, whatever the error rate turns out to be.

THE RULES THIS OBEYS, each one earned:

  SIGNED, not absolute. Settled 2026-08-21 on the full population. Absolute ranks GE Healthcare
  ($50.7bn absolute against $9.4m signed - offsetting credits) FIRST, above the ATO's $943m of
  real spend, presenting a bookkeeping artefact as our largest finding. SPEND_ABSOLUTE is carried
  BESIDE the ranking as a data-quality signal and is never ranked on.

  SPEND AS THE DATA HOLDS IT. No threshold, no netting, no outlier guard, no absolute values in
  the ranking. Nothing is ever excluded from this table: a flagged vendor is ROUTED, not filtered,
  and appears with its figures exactly as held.

  SUPPLIER_NAME VERBATIM. Never trimmed, cased, normalised or de-duplicated. It is grouped on the
  raw column - the value an account manager pastes into their own system.

  BLANK VENDOR NAMES ARE IN THE QUEUE. Sameer, 2026-08-25: "i prefer those lines in que, where its
  a blank vendorr". Raised with him first, because ranked by signed spend they land at #2 in
  Northern (3,387 lines, $608,419,571) and #1 in Western (ONE line, $47,111,582). He ruled they
  stay. HAS_NO_EVIDENCE marks the subset the judge cannot resolve - no vendor AND no usable
  description - so an Uncertain verdict there is a PREDICTED outcome sitting on the row, not a
  surprise discovered after the run.

  A VENDOR IS JUDGED WHOLE, which is what the rank is FOR. It also bounds the judge's memory:
  emit_batch materialises its whole selection at 616 B/unit, so a whole client is ~0.51 GB for
  Melbourne and a single vendor is a few MB.

  NOTHING IS READ BACK FROM THIS TABLE. Every column is recomputed from qa_line on each build,
  QUEUE_STATUS included. That is deliberate: on 2026-08-17 merge_taxonomy read its own output back
  as a fifth hospital and compounded on every cycle. A queue that remembered its own progress would
  be the same defect wearing a different name. qa_line is the authority on what has been judged.
"""
import argparse
import sys
import time

from db import load_env, connect_qa, assert_writable_qa_database

# A vendor whose ABSOLUTE spend exceeds its signed spend by this much is offsetting credits and
# debits rather than spending money. GE Healthcare Australia is 5,402x. FLAGGED, never filtered -
# it stays in the queue at its ranked position with its figures exactly as held.
DIVERGENCE_FLAG_AT = 100.0
# ⚠️ THE FLAG IS NOT PERFECTLY REPRODUCIBLE AT THE BOUNDARY, and that is stated rather than left to
# be discovered. Measured 2026-08-25: two consecutive builds of the SAME unchanged 2,786,018 rows
# reported `divergent` as 3,651 lines and then 3,653. qa_line had not moved. The cause is that
# SUM() over millions of floats under a parallel plan does not add in a fixed order, so a vendor
# sitting near the cut wobbles in its last digits and crosses it - 2 vendors sit between 95x and
# 105x today, the closest at 101.0x on 3 lines.
#
# LEFT AS IT IS, deliberately. The flag ROUTES and excludes nothing, so a borderline vendor moving
# in or out costs nothing; DIVERGENCE itself is carried as a number and is what anyone should read.
# It is the same weakness the plan already names for MSD_COHERENCE_CUT - a hard cut on a continuous
# value - and the honest handling is the same: keep the number, treat the label as a convenience.


def build(qa, cur, run_id):
    """Recompute the whole queue for one run_id. Returns (rows written, seconds)."""
    t0 = time.time()

    # ONE SCAN. Every aggregate the queue needs comes out of a single pass over qa_line - the
    # "merge scans" lesson from 2026-07-30, when profiling ran two full passes for figures
    # obtainable in one.
    #
    # VENDOR_KEY is the same construction as UNIT_KEY / SUBJECT_KEY: SHA2_256 of the parts,
    # truncated to 20. Deterministic, so a rebuild gives a vendor the SAME key. It must never be
    # an identity column - that is what orphaned the answer key on 2026-08-20.
    #
    # ISNULL(SUPPLIER_NAME,'') means a NULL name and an EMPTY name would hash alike. Measured
    # 2026-08-25 on production: empty is ZERO on all four clients, so there is nothing to collide
    # today. check() re-measures it every build rather than trusting this comment.
    cur.execute("""
        SELECT CLIENT_CODE,
               SUPPLIER_NAME,
               LEFT(CONVERT(char(64), HASHBYTES('SHA2_256',
                    ISNULL(CLIENT_CODE,'') + '|' + ISNULL(SUPPLIER_NAME,'')), 2), 20) AS VENDOR_KEY,
               COUNT(*)                                                     AS LINES_TOTAL,
               SUM(CASE WHEN NIM_VERDICT IS NULL THEN 1 ELSE 0 END)         AS LINES_UNJUDGED,
               COUNT(DISTINCT SUBJECT_KEY)                                  AS SUBJECTS,
               SUM(SPEND)                                                   AS SPEND_SIGNED,
               SUM(ABS(SPEND))                                              AS SPEND_ABSOLUTE,
               -- no vendor name AND no usable description = no evidence exists on the line, so
               -- the hierarchy resolves it to Uncertain. Stated in advance, on the row.
               SUM(CASE WHEN SUPPLIER_NAME IS NULL
                         AND ISNULL(DESCRIPTION_USABLE,'N') <> 'Y' THEN 1 ELSE 0 END)
                                                                            AS HAS_NO_EVIDENCE
        FROM qa_line
        WHERE RUN_ID = ?
        GROUP BY CLIENT_CODE, SUPPLIER_NAME
    """, run_id)
    raw = cur.fetchall()
    if not raw:
        raise SystemExit("\n  STOP - no lines in qa_line for run_id %s\n" % run_id)

    # Rank WITHIN each client. VENDOR_KEY breaks ties so the order is reproducible: without a
    # deterministic tiebreak two vendors on identical spend would swap places between builds and
    # every recorded position would quietly mean something else.
    by_client = {}
    for r in raw:
        by_client.setdefault(r[0], []).append(r)

    rows, built_at = [], time.strftime("%Y-%m-%d %H:%M:%S")
    for client in sorted(by_client):
        ranked = sorted(by_client[client], key=lambda r: (-(r[6] or 0.0), r[2]))
        for rank, r in enumerate(ranked, start=1):
            signed, absolute = (r[6] or 0.0), (r[7] or 0.0)
            divergence = (absolute / abs(signed)) if signed else None
            flag = None
            if r[1] is None:
                flag = "no_vendor_name"
            elif divergence is not None and divergence >= DIVERGENCE_FLAG_AT:
                flag = "divergent"
            # DERIVED from qa_line every build, never read back from this table.
            unjudged, total = r[4], r[3]
            status = "done" if unjudged == 0 else ("pending" if unjudged == total else "in_progress")
            rows.append([run_id, client, r[2], r[1], rank, total, unjudged, r[5],
                         signed, absolute, divergence, flag, r[8], status, built_at])

    # GLOBAL_RANK - the same rows ordered across ALL FOUR HOSPITALS AT ONCE. Sameer, 2026-08-25:
    # "cant we start juding largest supplier spend first? irrespective of the hospitals".
    # Same tiebreak as the per-client rank, so both orders are reproducible.
    # ⚠️ The judged unit is UNCHANGED - still (client, vendor), still judged inside that client's
    # own taxonomy. A global ORDER never means a shared candidate list.
    for gr, row in enumerate(sorted(rows, key=lambda x: (-(x[8] or 0.0), x[2])), start=1):
        row.append(gr)

    # REPLACE this run's queue, and commit the delete with the insert. A half-replaced queue is a
    # partial generation - the failure this project has already paid for once, when a killed
    # rebuild left two run_ids in qa_line and every figure taken from it double-counted.
    cur.execute("DELETE FROM qa_vendor_queue WHERE RUN_ID = ?", run_id)
    cur.fast_executemany = True
    cur.executemany("""
        INSERT INTO qa_vendor_queue
          (RUN_ID, CLIENT_CODE, VENDOR_KEY, SUPPLIER_NAME, VENDOR_RANK, LINES_TOTAL,
           LINES_UNJUDGED, SUBJECTS, SPEND_SIGNED, SPEND_ABSOLUTE, DIVERGENCE,
           DATA_QUALITY_FLAG, HAS_NO_EVIDENCE, QUEUE_STATUS, BUILT_AT, GLOBAL_RANK)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    qa.commit()
    return len(rows), time.time() - t0


def check(cur, run_id):
    """Prove the queue against qa_line - OUTSIDE its own arithmetic.

    A self-consistency check cannot see a contaminated input: on 2026-08-17 `line conservation`
    printed OK on every run of a taxonomy that had merged with itself, because in = out + dropped
    was perfectly true of an input that was already wrong. So every check here compares the queue
    against QA_LINE, never against another column of the queue.
    """
    ok = True
    print("\n=== CHECKS - the queue measured against qa_line, not against itself ===")

    cur.execute("""SELECT (SELECT COUNT(*) FROM qa_line WHERE RUN_ID=?),
                          (SELECT SUM(LINES_TOTAL) FROM qa_vendor_queue WHERE RUN_ID=?)""",
                run_id, run_id)
    lines, queued = cur.fetchone()
    if lines != queued:
        ok = False
    print("  lines      qa_line %12s   queue %12s   %s"
          % ("{:,}".format(lines), "{:,}".format(queued or 0),
             "OK" if lines == queued else "** MISMATCH **"))

    cur.execute("""SELECT (SELECT SUM(SPEND) FROM qa_line WHERE RUN_ID=?),
                          (SELECT SUM(SPEND_SIGNED) FROM qa_vendor_queue WHERE RUN_ID=?)""",
                run_id, run_id)
    ls, qs = cur.fetchone()
    # float addition is not associative, so an exact match is not the right test. A cent on
    # billions is arithmetic; a dollar is a bug.
    delta = abs((ls or 0) - (qs or 0))
    if delta >= 1.0:
        ok = False
    print("  spend      qa_line %12s   queue %12s   delta %.4f  %s"
          % ("{:,.0f}".format(ls or 0), "{:,.0f}".format(qs or 0), delta,
             "OK" if delta < 1.0 else "** MISMATCH **"))

    # THE GRAIN IS (CLIENT, VENDOR), NOT VENDOR. The first version of this check compared the
    # queue against COUNT(DISTINCT SUPPLIER_NAME) and failed 583 vs 643 on the pilot - because a
    # vendor trading with two hospitals is ONE distinct name and legitimately TWO queue rows. The
    # build was right and the check was wrong, which is the same class of error as the taxonomy
    # matcher that reported 55.6%: a comparison that looks correct and is measuring the wrong
    # thing. SELECT DISTINCT keeps NULL as a value, so no-vendor rows need no adjustment.
    cur.execute("""SELECT (SELECT COUNT(*) FROM
                             (SELECT DISTINCT CLIENT_CODE, SUPPLIER_NAME
                                FROM qa_line WHERE RUN_ID=?) d),
                          (SELECT COUNT(*) FROM qa_vendor_queue WHERE RUN_ID=?)""", run_id, run_id)
    dn, qn = cur.fetchone()
    cur.execute("""SELECT COUNT(*) FROM qa_vendor_queue
                   WHERE RUN_ID=? AND SUPPLIER_NAME IS NULL""", run_id)
    nulls = cur.fetchone()[0]
    if qn != dn:
        ok = False
    print("  vendors    client+name %8s   queue %12s   (%d no-vendor rows)  %s"
          % ("{:,}".format(dn), "{:,}".format(qn), nulls,
             "OK" if qn == dn else "** MISMATCH **"))

    # the one collision this design could have: a NULL name and an EMPTY name hash alike
    cur.execute("SELECT COUNT(*) FROM qa_line WHERE RUN_ID=? AND SUPPLIER_NAME = ''", run_id)
    empties = cur.fetchone()[0]
    if empties:
        ok = False
    print("  empty names in qa_line: %9s   %s"
          % ("{:,}".format(empties),
             "OK" if empties == 0 else "** empty names would share the no-vendor key **"))

    cur.execute("""SELECT COUNT(*) FROM (SELECT CLIENT_CODE, VENDOR_RANK FROM qa_vendor_queue
                   WHERE RUN_ID=? GROUP BY CLIENT_CODE, VENDOR_RANK HAVING COUNT(*)>1) d""", run_id)
    dupes = cur.fetchone()[0]
    if dupes:
        ok = False
    print("  rank is unique per client: %d duplicates   %s"
          % (dupes, "OK" if dupes == 0 else "** DUPLICATE RANKS **"))

    # GLOBAL_RANK must be a complete 1..N with no gaps and no repeats. A gap means a vendor is
    # never reached by a global run; a repeat means two vendors claim one position and which gets
    # judged first is undefined.
    cur.execute("""SELECT COUNT(*), COUNT(DISTINCT GLOBAL_RANK), MIN(GLOBAL_RANK),
                          MAX(GLOBAL_RANK), SUM(CASE WHEN GLOBAL_RANK IS NULL THEN 1 ELSE 0 END)
                   FROM qa_vendor_queue WHERE RUN_ID=?""", run_id)
    n, distinct, lo, hi, nulls = cur.fetchone()
    good = (nulls == 0 and distinct == n and lo == 1 and hi == n)
    if not good:
        ok = False
    print("  GLOBAL_RANK 1..%s, no gaps or repeats: %s"
          % ("{:,}".format(n), "OK" if good else
             "** %s nulls, %s distinct of %s, range %s-%s **" % (nulls, distinct, n, lo, hi)))
    return ok


def report(cur, run_id):
    print("\n=== THE RUNNING ORDER - run %s ===" % run_id)
    cur.execute("""SELECT CLIENT_CODE, COUNT(*), SUM(LINES_TOTAL), SUM(SPEND_SIGNED)
                   FROM qa_vendor_queue WHERE RUN_ID=? GROUP BY CLIENT_CODE ORDER BY 1""", run_id)
    print("  %-20s%9s%12s%18s" % ("client", "vendors", "lines", "signed spend"))
    for r in cur.fetchall():
        print("  %-20s%9s%12s%18s"
              % (r[0], "{:,}".format(r[1]), "{:,}".format(r[2]), "{:,.0f}".format(r[3] or 0)))

    # ⚠️ % of signed spend CAN EXCEED 100 and that is not a fault. Spend is signed and as-is, so
    # credits below the top 100 subtract from the client total while the top 100 does not carry
    # them. Northern reads 100.8% on the pilot. Left exactly as computed - correcting it would
    # mean netting or absolute values, which the standing rule forbids.
    print("\n  -- what the TOP 100 vendors cover: the 'stop and look' slice --")
    print("  %-20s%12s%10s%17s" % ("client", "lines", "% lines", "% signed spend"))
    cur.execute("SELECT DISTINCT CLIENT_CODE FROM qa_vendor_queue WHERE RUN_ID=? ORDER BY 1", run_id)
    for (c,) in cur.fetchall():
        cur.execute("""SELECT SUM(LINES_TOTAL), SUM(SPEND_SIGNED) FROM qa_vendor_queue
                       WHERE RUN_ID=? AND CLIENT_CODE=?""", run_id, c)
        tl, ts = cur.fetchone()
        cur.execute("""SELECT SUM(LINES_TOTAL), SUM(SPEND_SIGNED) FROM qa_vendor_queue
                       WHERE RUN_ID=? AND CLIENT_CODE=? AND VENDOR_RANK<=100""", run_id, c)
        hl, hs = cur.fetchone()
        print("  %-20s%12s%9.1f%%%16.1f%%"
              % (c, "{:,}".format(hl or 0), 100.0 * (hl or 0) / tl,
                 100.0 * (hs or 0) / (ts if ts else 1)))

    print("\n  -- the top of each client's queue --")
    cur.execute("SELECT DISTINCT CLIENT_CODE FROM qa_vendor_queue WHERE RUN_ID=? ORDER BY 1", run_id)
    for (c,) in cur.fetchall():
        cur.execute("""SELECT TOP 3 VENDOR_RANK, SUPPLIER_NAME, LINES_TOTAL, SPEND_SIGNED,
                              DATA_QUALITY_FLAG, HAS_NO_EVIDENCE
                       FROM qa_vendor_queue WHERE RUN_ID=? AND CLIENT_CODE=?
                       ORDER BY VENDOR_RANK""", run_id, c)
        print("  %s" % c)
        for r in cur.fetchall():
            name = "(no vendor name)" if r[1] is None else r[1]
            flag = "  [%s]" % r[4] if r[4] else ""
            noev = "  no-evidence lines: {:,}".format(r[5]) if r[5] else ""
            print("    #%-3d %-42s %8s lines %16s%s%s"
                  % (r[0], name[:42], "{:,}".format(r[2]), "{:,.0f}".format(r[3] or 0), flag, noev))

    # THE GLOBAL ORDER - what `--queue` uses when no --client is given.
    print("\n  -- the GLOBAL top 10, ignoring hospital (largest signed spend anywhere first) --")
    cur.execute("""SELECT TOP 10 GLOBAL_RANK, CLIENT_CODE, SUPPLIER_NAME, LINES_TOTAL, SPEND_SIGNED
                   FROM qa_vendor_queue WHERE RUN_ID=? ORDER BY GLOBAL_RANK""", run_id)
    for r in cur.fetchall():
        name = "(no vendor name)" if r[2] is None else r[2]
        print("    %-4d %-18s %-34s %8s lines %16s"
              % (r[0], r[1], name[:34], "{:,}".format(r[3]), "{:,.0f}".format(r[4] or 0)))

    # ⚠️ A GLOBAL ORDER UNDER-SERVES THE SMALLEST HOSPITAL EARLY, and that is a decision for the
    # day the run is stopped, not a fault. Printed so it is visible rather than discovered.
    print("\n  -- % of EACH hospital's signed spend covered at each GLOBAL cut-off."
          "  A global order under-serves the SMALLEST hospital early --")
    cur.execute("SELECT DISTINCT CLIENT_CODE FROM qa_vendor_queue WHERE RUN_ID=? ORDER BY 1", run_id)
    clients = [c for (c,) in cur.fetchall()]
    print("  %-10s" % "cut" + "".join("%12s" % c[:11] for c in clients))
    for cut in (100, 250, 500, 1000, 2000):
        cells = []
        for c in clients:
            cur.execute("""SELECT SUM(SPEND_SIGNED) FROM qa_vendor_queue
                           WHERE RUN_ID=? AND CLIENT_CODE=?""", run_id, c)
            tot = cur.fetchone()[0] or 0
            cur.execute("""SELECT SUM(SPEND_SIGNED) FROM qa_vendor_queue
                           WHERE RUN_ID=? AND CLIENT_CODE=? AND GLOBAL_RANK<=?""", run_id, c, cut)
            got = cur.fetchone()[0] or 0
            cells.append("%11.1f%%" % (100.0 * got / tot if tot else 0.0))
        print("  top %-6d" % cut + "".join(cells))

    cur.execute("""SELECT DATA_QUALITY_FLAG, COUNT(*), SUM(LINES_TOTAL), SUM(SPEND_SIGNED)
                   FROM qa_vendor_queue WHERE RUN_ID=? AND DATA_QUALITY_FLAG IS NOT NULL
                   GROUP BY DATA_QUALITY_FLAG ORDER BY 1""", run_id)
    flagged = cur.fetchall()
    print("\n  -- data-quality flags. ROUTING, never a filter: every one is still IN the queue --")
    if not flagged:
        print("     (none)")
    for r in flagged:
        print("     %-18s %5d vendors  %10s lines  %18s"
              % (r[0], r[1], "{:,}".format(r[2]), "{:,.0f}".format(r[3] or 0)))


def main():
    ap = argparse.ArgumentParser(description="Build the vendor spend queue - the judging order")
    ap.add_argument("--production", action="store_true",
                    help="target QA_DATABASE instead of the pilot. Must be asked for on purpose")
    ap.add_argument("--run-id", default=None, help="defaults to the newest run in qa_run")
    ap.add_argument("--report", action="store_true", help="report only, build nothing")
    args = ap.parse_args()

    env = load_env()
    qa = connect_qa(production=args.production, env=env)
    cur = qa.cursor()
    cur.execute("SELECT DB_NAME()")
    live = cur.fetchone()[0]
    assert_writable_qa_database(live, args.production, env)

    run_id = args.run_id
    if not run_id:
        cur.execute("SELECT TOP 1 run_id FROM qa_run ORDER BY loaded_at DESC")
        row = cur.fetchone()
        if not row:
            raise SystemExit("\n  STOP - qa_run is empty; nothing to build a queue for\n")
        run_id = row[0]

    # ONE run_id is expected. More than one means an aborted generation is still in the table and
    # every figure taken from it double-counts.
    cur.execute("SELECT COUNT(DISTINCT run_id) FROM qa_line")
    n = cur.fetchone()[0]
    if n != 1:
        print("  ** %d run_ids in qa_line - expected exactly 1. The queue is built for %s only **"
              % (n, run_id))

    print("vendor queue on %s  (%s)   run %s"
          % (live, "PRODUCTION" if args.production else "pilot", run_id))

    if not args.report:
        written, el = build(qa, cur, run_id)
        print("  built %s vendor rows in %.1fs" % ("{:,}".format(written), el))

    ok = check(cur, run_id)
    report(cur, run_id)
    qa.close()
    print("\n" + ("ALL CHECKS PASS" if ok else "** CHECKS FAILED - see above **"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
