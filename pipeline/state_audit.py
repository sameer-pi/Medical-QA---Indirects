"""Print the ACTUAL state of a QA database. Run this FIRST, every session.

    python pipeline/state_audit.py                # the pilot (the default)
    python pipeline/state_audit.py --production   # PI_Medical_QA_Indirect

Read-only. Nothing here writes, and it refuses any database that is not one of the two configured
QA targets - never a client database. An audit that silently reports on the WRONG database is worse
than one that fails, because its output looks like an answer.

Why it exists: this project has twice put a remembered figure into a sentence instead of a
measured one. `TRACKER.md` records the state as at the last session; run this and the numbers should
reproduce. If they do not, find out why before doing anything else - the most likely cause is a
second `run_id` in `qa_line`, and two generations in the table double-count every figure taken
from it.

  Corrected 2026-08-18: this docstring used to say `build_pilot.py` HAS NO superseded-run purge.
  It has one - build_pilot.py:164-172, added after the 2026-08-04 incident. The claim had been
  wrong here long enough to be read as fact, which is why a second run_id is worth investigating
  rather than assuming: if one appears now, the purge did not fire and THAT is the finding.

    python pipeline/state_audit.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import assert_writable_qa_database, connect, load_env, qa_database_names  # noqa: E402

# Recorded 2026-08-05 (line-level rebuild, RUN_LOG Finding 56). Drift here is a finding, not a nuisance.
EXPECTED = {
    # 7,184 since 2026-08-14: the locked merged taxonomy loaded under client_code
    # 'merged_indirect' - 350 categories (CL 1 / NC 332 / NP 17). The four hospitals' own
    # taxonomies stay exactly as they were; this sits BESIDE them, because the verdict is still
    # measured against the hospital's own buckets and only the SUGGESTION comes from the merged
    # tree. RUN_LOG Finding 85.
    # 7,186 since 2026-08-17: the merged taxonomy is 352 = the clean 350 plus Sameer's two adds,
    # NC-0348 Batteries (under General Office Supplies) and NC-0334 Cutlery (under Consumables &
    # Disposables). ~~7,199 / 365~~ - that generation was CONTAMINATED and has been withdrawn:
    # merge_taxonomy.load_nodes() had no client filter, so it read the previously-LOADED merged
    # taxonomy back out of qa_category as if it were a fifth hospital and merged the tree with
    # itself. 13 exact-duplicate leaves and 2M double-counted lines. Fixed in load_nodes;
    # RUN_LOG Finding 93. If this number ever jumps without a client's taxonomy changing, suspect
    # the same loop before anything else.
    # 7,187 since 2026-08-24: the merged taxonomy went 352 -> 353 (Refrigeration Paper).
    # RUN_LOG Finding 117. Expect this to move on every ruling - the drift flag is asking
    # "was this deliberate?", not "is this wrong".
    "qa_category": (19, 7187),
    # 54 since 2026-08-05: SUGGESTED_CATEGORY_LVL_0 added. A candidate path is five segments, and
    # taking four shifted every suggested level by one and dropped the leaf. Level 0 is not a
    # constant - 65 in-scope categories sit under Non-Procurement and two under Tail Spend.
    # 55 since 2026-08-06: REVIEW_NOTE added at the END, where it belongs - beside the other
    # REVIEW_* columns. The review workbook collects a free-text note and there was nowhere to
    # put it, so an ingest would have discarded reviewer input. No rebuild was needed here,
    # unlike SUGGESTED_CATEGORY_LVL_0, because the end IS this column's correct position.
    # 80 since 2026-08-14: 25 NIM_* columns for the three-model jury. COLUMNS, NOT ROWS - Sameer:
    # "our qa_line database can never have more than 2000 rows ... yes we can go with addtional
    # colums but not rows." One run per model would have been 8,000 rows. RUN_LOG Finding 86.
    # 81 since 2026-08-14: NIM_ACTION. The verdict says WHAT, the action says SO WHAT - it
    # separates "you misfiled this" from "we moved the category", which the verdict alone cannot
    # express because both answer "no". RUN_LOG Finding 87, JUDGING-RULES section 10.
    # 82 since 2026-08-17: NIM_DECIDED_BY, naming EVERY model that voted the winning verdict.
    # 83 since 2026-08-17: MSD_COHERENCE - the MSD's own read on whether the vendor's stated
    # business matches what it invoices for. FIVE values, Sameer's words: coherent | incoherent |
    # inconclusive | unevaluated | no match. A FLAG BESIDE THE VENDOR, NEVER A JUDGE INPUT.
    # Refreshed by msd_coherence.py; a SNAPSHOT of another team's live database.
    # 84 since 2026-08-18: NIM_MODELS_RESPONDED - how many of the three models actually
    # ANSWERED the line. A throttled model that exhausts its retries drops out SILENTLY and
    # the line is decided by a smaller jury, but `2of2` reads exactly like agreement. The
    # concurrency test measured 11 dropouts at 16 workers against 102 at 48. The data was
    # always in NIM_1/2/3_VERDICT; nothing surfaced it. RUN_LOG Finding 96.
    "qa_line": (84, 2000),
    # 360 since 2026-08-20, NOT 352. The pilot was rebuilt and drew a different 500 lines
    # per client, which touched 8 more rules. Explained and benign - RUN_LOG Finding 116 §8.
    # ⚠️ The rule-count expectation is a fact about THIS DRAW, not about the pipeline: any
    # future rebuild moves it again, and the right response is to establish the cause, not
    # to assume drift means damage. It flagged for three days before anyone asked why.
    "qa_rule": (31, 360),   # units_in_scope + lines_per_unit dropped
    "qa_run": (17, 4),      # units_loaded dropped
}
PROTOTYPE = ("zz_smoke_test", "zz_smoke_rule", "zz_smoke_run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--production", action="store_true",
                    help="audit QA_DATABASE instead of the pilot")
    args = ap.parse_args()

    env = load_env()
    # Read-only script, but it still refuses an unknown database: an audit that silently reports
    # on the WRONG database is worse than one that fails, because its output looks like an answer.
    pilot = qa_database_names(env)[bool(args.production)]
    assert_writable_qa_database(pilot, args.production, env)

    cn = connect(env=env, database=pilot, timeout=60)
    cn.timeout = 600
    cur = cn.cursor()
    print(f"database: {pilot}\n")

    print("=== TABLES ===")
    cur.execute("""SELECT t.name,
                          (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = t.object_id)
                   FROM sys.tables t ORDER BY t.name""")
    drift = []
    for name, ncols in cur.fetchall():
        cur.execute(f"SELECT COUNT(*) FROM [dbo].[{name}]")
        nrows = cur.fetchone()[0]
        note = ""
        if name in PROTOTYPE:
            note = "  <- PROTOTYPE, superseded. Do not analyse from this"
        elif name in EXPECTED and (ncols, nrows) != EXPECTED[name]:
            ec, er = EXPECTED[name]
            note = f"  <- DRIFT: recorded as {ec} cols / {er:,} rows"
            drift.append(name)
        print(f"  {name:22} {ncols:>3} cols  {nrows:>10,} rows{note}")

    print("\n=== RUNS (expect exactly one run_id in qa_line) ===")
    cur.execute("SELECT DISTINCT run_id FROM qa_line")
    runs = [r[0] for r in cur.fetchall()]
    for r in runs:
        print(f"  {r}")
    if len(runs) != 1:
        print(f"  ** STOP - {len(runs)} run_ids in qa_line. Figures taken from this table will "
              f"double-count.\n     Purge the superseded run before measuring anything. **")

    print("\n=== JUDGING PROGRESS - THE LIVE JUDGE (NIM 3-model jury) ===")
    # This block was added 2026-08-18. Until then this script reported ONLY the older Claude
    # `verdict` column and closed with "no accuracy figure is quotable" - which stopped being true
    # when the jury judged all 2,000 lines, and is the FIRST thing printed every session. Same
    # defect as PLAN.md's status section (RUN_LOG Finding 97): a status surface that nothing
    # measured against reality. Two verdict layers coexist in qa_line and a reader shown only one
    # of them draws the wrong conclusion about where the project is.
    cur.execute("""SELECT client_code, COUNT(*),
                          SUM(CASE WHEN nim_verdict IS NULL THEN 1 ELSE 0 END),
                          SUM(CASE WHEN nim_verdict = 'Correct'   THEN 1 ELSE 0 END),
                          SUM(CASE WHEN nim_verdict = 'Incorrect' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN nim_verdict = 'Uncertain' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN nim_models_responded < 3  THEN 1 ELSE 0 END)
                   FROM qa_line GROUP BY client_code ORDER BY client_code""")
    print(f"  {'client':20} {'lines':>7} {'unjudged':>9} {'Correct':>8} {'Incorrect':>10} "
          f"{'Uncertain':>10} {'jury<3':>8}")
    n_lines = n_unj = n_hollow = 0
    for r in cur.fetchall():
        print(f"  {r[0]:20} {r[1]:>7,} {r[2]:>9,} {r[3]:>8,} {r[4]:>10,} {r[5]:>10,} {r[6] or 0:>8,}")
        n_lines += r[1]; n_unj += r[2]; n_hollow += (r[6] or 0)
    print(f"  {'TOTAL':20} {n_lines:>7,} {n_unj:>9,} {'':>8} {'':>10} {'':>10} {n_hollow:>8,}")

    cur.execute("SELECT nim_action, COUNT(*) FROM qa_line GROUP BY nim_action ORDER BY 2 DESC")
    acts = cur.fetchall()
    if acts:
        print("\n  NIM_ACTION: " + " | ".join(f"{a or '(none)'} {n:,}" for a, n in acts))

    # 'jury<3' is a RATE check, not == 0 - an occasional dropout is normal, and the failure it
    # exists to catch is gradual (11 lines at 16 workers, 102 at 48). See RUN_LOG Finding 95.
    if n_lines:
        pct = 100.0 * n_hollow / n_lines
        flag = "OK" if pct <= 1.0 else "** ABOVE 1% - the jury is hollowing out, check --workers **"
        print(f"  jury health: {n_hollow} of {n_lines:,} lines judged by fewer than 3 models "
              f"({pct:.1f}%)  {flag}")

    print("\n=== JUDGING PROGRESS - CLAUDE's OLDER LAYER (superseded, kept for comparison) ===")
    cur.execute("""SELECT client_code, COUNT(*),
                          SUM(CASE WHEN verdict IS NULL THEN 1 ELSE 0 END),
                          SUM(CASE WHEN verdict = 'Correct' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN verdict = 'Incorrect' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN verdict = 'Uncertain' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN basis IS NOT NULL AND basis NOT LIKE 'deterministic%'
                                   THEN 1 ELSE 0 END)
                   FROM qa_line GROUP BY client_code ORDER BY client_code""")
    print(f"  {'client':20} {'lines':>7} {'unjudged':>9} {'Correct':>8} {'Incorrect':>10} "
          f"{'Uncertain':>10} {'model-judged':>13}")
    tot_units = tot_model = 0
    for r in cur.fetchall():
        print(f"  {r[0]:20} {r[1]:>7,} {r[2]:>9,} {r[3]:>8,} {r[4]:>10,} {r[5]:>10,} {r[6]:>13,}")
        tot_units += r[1]
        tot_model += r[6]
    print(f"  {'TOTAL':20} {tot_units:>7,} {'':>9} {'':>8} {'':>10} {'':>10} {tot_model:>13,}")
    print(f"\n  {tot_model} of {tot_units:,} lines carry a model verdict in THIS layer; the rest are "
          f"deterministic.\n  This is the OLD layer - it is not what the project runs on. Read the "
          f"jury table above.\n  Accuracy has still never been measured on a spread sample, so no "
          f"per-client figure\n  is client-facing regardless of layer. See TRACKER.md.")

    print("\n=== RULES ===")
    cur.execute("""SELECT client_code, COUNT(*), SUM(CASE WHEN lines_judged > 0 THEN 1 ELSE 0 END),
                          SUM(CAST(is_complete AS int))
                   FROM qa_rule GROUP BY client_code ORDER BY client_code""")
    print(f"  {'client':20} {'rules':>6} {'touched':>9} {'complete':>9}")
    for r in cur.fetchall():
        print(f"  {r[0]:20} {r[1]:>6,} {r[2] or 0:>9,} {r[3] or 0:>9,}")

    cn.close()
    if drift:
        print(f"\n** {len(drift)} table(s) drifted from the recorded state: {', '.join(drift)}")
        print("   That is a finding. Establish the cause before quoting any figure.")
    else:
        print("\nCompare against TRACKER.md's measured block - if they disagree, TRACKER.md is stale.")


if __name__ == "__main__":
    main()
