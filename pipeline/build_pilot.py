"""Phase 0.5 loader - build the pilot: a stratified LINE-LEVEL sample, no grouping.

    python pipeline/build_pilot.py                    # 500 lines per client, 75% categorised
    python pipeline/build_pilot.py --lines 1000
    python pipeline/build_pilot.py northern_health

NO GROUPING. EVERY LINE IS JUDGED ON ITS OWN.
Standing instruction from Sameer, 2026-08-05, said three times: "i dont want to keep anything
grouped, im trying to give the team line level granularity ... let each line be on its own,
irrespective if the supplier and line item match."

This REPLACES the rule-led design (v3.9-v3.19), and the trade is worth stating plainly rather than
leaving for someone to discover:

  WHAT WAS LOST. The old loader chose rules and took every line of each, so a rule's error rate was
  a FACT - every line it touched had been judged. A stratified sample cannot do that: each rule's
  error rate is now an ESTIMATE. Nobody should quote a rule error rate from this run to a client.

  WHAT WAS GAINED. Line-level granularity end to end, and no possibility of one verdict being
  copied onto lines that differ in cost centre or GL account. Measured 2026-08-05 on the previous
  run: 29.1% of groups spanned more than one GL account and 41.4% more than one cost centre, and
  the judge saw only one of them. That evidence loss is gone.

  WHAT IT COSTS. Grouping was purely an economy - identical vendor + item + category is the same
  question, so it was asked once. Removing it multiplies judgements by the duplication factor:
  2,764,531 in-scope lines against 1,010,661 groups, so 2.74x at full scale. The full census needs
  an API key; this pilot is sized to what can be judged in-session.

THE SAMPLE. 500 lines per client: "at least 75% of the lines should have the category levels
present in them", the rest uncategorised, so the judge is tested on both. Drawn as two independent
draws, because the uncategorised share differs wildly per client - one draw would return whatever
the population happens to hold rather than the mix asked for.

Reads the client databases READ-ONLY. Writes to the pilot QA database only.
"""
import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg  # noqa: E402

# Rows pulled from the client and written to qa_line at a time. The value matters
# only for memory and log size, never for WHICH rows arrive - the query decides that.
BATCH = 20000
from db import connect_client, connect_qa, load_env  # noqa: E402
from smoke_test import (FIELDS, RULE_SRC, build_select, check_level_overflow,
                        out as out_name)  # noqa: E402

SCOPE_NOTE = ("INDIRECT (non-clinical) spend only. In scope = Category Level 0 is neither Clinical "
              "nor Inter-Hospital Spend; uncategorised lines are IN scope and flagged.")


def T(e):
    return f"LTRIM(RTRIM(CONVERT(nvarchar(400), {e})))"


def scope_counts(cfg, cur):
    """In-scope lines, split by whether Category Level 0 carries anything. ONE scan.

    Both numbers are needed before the sample is drawn: a client with fewer uncategorised lines
    than the quota asks for must have the shortfall made up from the categorised side, or the run
    silently returns fewer than 500 lines and nobody notices until the counts are read.
    """
    cols = clientcfg.column_map(cfg)
    tbl, c0 = clientcfg.source_table(cfg), cols["cat_l0"]
    excl = [v.strip() for v in
            set(clientcfg.clinical_exclusions(cfg)) | set(clientcfg.scope_exclusions(cfg))]
    notin = ", ".join(f"'{v}'" for v in excl) or "''"
    cur.execute(f"""SELECT COUNT(*),
            SUM(CASE WHEN NULLIF({T(f'v.[{c0}]')},'') IS NULL THEN 1 ELSE 0 END)
        FROM {tbl} v
        WHERE ({T(f'v.[{c0}]')} NOT IN ({notin}) OR v.[{c0}] IS NULL)""")
    total, blank = cur.fetchone()
    return total, (blank or 0), total - (blank or 0)


def plan_strata(n_lines, pct_categorised, n_cat_avail, n_blank_avail):
    """How many from each stratum, given what the client actually has.

    'At least 75%' is a FLOOR on the categorised share, not a target: if a client is short of
    uncategorised lines the balance goes to categorised, which only pushes the share further above
    the floor. It is never made up the other way round.
    """
    want_cat = -(-n_lines * pct_categorised // 100)          # ceiling, so 75% of 500 -> 375
    want_blank = n_lines - want_cat
    take_blank = min(want_blank, n_blank_avail)
    take_cat = min(n_lines - take_blank, n_cat_avail)
    return take_cat, take_blank


def rule_text(cfg, cur, ids):
    """Rule text, priority, tier - from EVERY configured rules table, primary first.

    A client's RuleIDs span more than one table. Western's PMML_Medical_Rules carries 20.7% of its
    in-scope lines and the config had dismissed it on its name; resolving against only the primary
    table produces a fix queue that comes back short and reads as "nothing to fix there".
    """
    out = {}
    if not ids:
        return out
    inlist = ", ".join("'" + r.replace("'", "''") + "'" for r in ids)
    for rt in clientcfg.rules_tables(cfg):
        bare = rt.replace("[", "").replace("]", "").split(".")[-1]
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?", bare)
        have = {c[0] for c in cur.fetchall()}
        pick = {}
        for internal, cands in RULE_SRC.items():
            hit = next((c for c in cands if c in have), None)
            pick[internal] = T(f"r.[{hit}]") if hit else "CAST(NULL AS nvarchar(400))"
        sel = ", ".join(f"{pick[f]} AS [{f}]" for f in RULE_SRC)
        cur.execute(f"SELECT {T('r.[RuleID]')} AS rid, {sel} FROM {rt} r "
                    f"WHERE {T('r.[RuleID]')} IN ({inlist})")
        for row in cur.fetchall():
            # primary table wins - setdefault, so a later table never overwrites it
            out.setdefault(row[0], (rt, dict(zip(RULE_SRC, row[1:]))))
    return out


def rule_impact(cfg, cur, ids):
    """Full-population impact of just the rules our sampled lines reference.

    Aggregate by rule FIRST and join the small result afterwards - joining a multi-million-row view
    to the rules table and then grouping timed out at 15 minutes on 2026-07-30.
    """
    if not ids:
        return {}
    cols = clientcfg.column_map(cfg)
    tbl, c0, rid = clientcfg.source_table(cfg), cols["cat_l0"], cols["rule_id"]
    sup, spend = cols["supplier"], cols["spend"]
    excl = [v.strip() for v in
            set(clientcfg.clinical_exclusions(cfg)) | set(clientcfg.scope_exclusions(cfg))]
    notin = ", ".join(f"'{v}'" for v in excl) or "''"
    inlist = ", ".join("'" + r.replace("'", "''") + "'" for r in ids)
    cur.execute(f"""SELECT {T(f'v.[{rid}]')}, COUNT(*), COUNT(DISTINCT {T(f'v.[{sup}]')}),
                           SUM(CAST(v.[{spend}] AS float))
        FROM {tbl} v
        WHERE ({T(f'v.[{c0}]')} NOT IN ({notin}) OR v.[{c0}] IS NULL)
          AND {T(f'v.[{rid}]')} IN ({inlist})
        GROUP BY {T(f'v.[{rid}]')}""")
    return {r[0]: {"lines": r[1], "vendors": r[2], "spend": r[3]} for r in cur.fetchall()}


def refuse_if_precious(qcur, where, params, what):
    """Refuse to DELETE qa_line rows that carry a VERDICT or a REVIEW. Nothing overrides this.

    🔒 THE GUARD KEYS ON THE VERDICT AND THE REVIEW, NEVER ON run_id. Sameer asked on 2026-08-21
    whether a run_id means the analyst has looked at a line. It does not, and the distinction is the
    whole point of this function: run_id is stamped at LOAD, so on the day it was asked all
    2,786,018 production lines carried one and NONE was judged or reviewed. Three independent
    states, and a guard on the wrong one protects nothing:

        RUN_ID          loaded. every line, always. says nothing.
        NIM_VERDICT     judged  - 15-37 days of compute
        REVIEW_STATUS   reviewed - a person's decision, and the ONE thing here that cannot be
                        regenerated at any price

    WHY IT EXISTS. The loader is generation-replacement: a new run purges the old one outright,
    which is correct for a pilot that rebuilds in 40 minutes and catastrophic for a monthly product
    whose rows carry weeks of compute and human decisions. The full incremental model (PLAN v3.57,
    stage 3b) replaces that. This is the guard that makes the gap survivable in the meantime.

    It refuses rather than skipping. A load that silently declined to delete would leave two
    generations and report success - the failure shape this project keeps finding.
    """
    qcur.execute(f"""SELECT COUNT(*),
            SUM(CASE WHEN NIM_VERDICT   IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN REVIEW_STATUS IS NOT NULL THEN 1 ELSE 0 END)
        FROM qa_line WHERE {where}""", *params)
    n, judged, reviewed = qcur.fetchone()
    judged, reviewed = judged or 0, reviewed or 0
    if not (judged or reviewed):
        return n
    raise SystemExit(
        f"\n  STOP - REFUSING to delete {what}.\n\n"
        f"    rows in scope of the delete : {n:,}\n"
        f"    carrying OUR VERDICT        : {judged:,}\n"
        f"    carrying an ANALYST REVIEW  : {reviewed:,}\n\n"
        "  A verdict is 15-37 days of compute. AN ANALYST REVIEW CANNOT BE REGENERATED AT ANY\n"
        "  PRICE - it is a person's decision and it exists nowhere else.\n\n"
        "  This loader replaces a whole generation, which is right for a pilot and wrong for a\n"
        "  monthly product. The incremental model (PLAN.md, stage 3b) is what makes a monthly\n"
        "  reload safe; it is not built yet. Until it is, a load that would destroy judged or\n"
        "  reviewed rows STOPS HERE.\n\n"
        "  If the intent really is to discard them, do it deliberately and explicitly in SQL,\n"
        "  having said so out loud first. There is no flag for it and that is on purpose.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=500, help="lines per client")
    ap.add_argument("--pct-categorised", type=int, default=75,
                    help="minimum %% of the sample carrying a Category Level 0")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--census", action="store_true",
                    help="EVERY in-scope line for the client, not a sample. The production load.")
    ap.add_argument("--production", action="store_true",
                    help="write to PI_Medical_QA_Indirect instead of the pilot")
    ap.add_argument("--dry-run", action="store_true",
                    help="read and count, write NOTHING. Times the read and proves the count.")
    ap.add_argument("clients", nargs="*")
    args = ap.parse_args()

    env = load_env()
    # The run_id says which database it belongs to. The first production load carried
    # "pilot-20260821T084059" INSIDE PI_Medical_QA_Indirect - a label asserting the opposite
    # of the truth, sitting on 671,200 rows and on every figure ever quoted from them. Third
    # instance of this defect in a week (apply_schema's "(pilot only)" banner, build_pilot's
    # "This is a SAMPLE" under a census). A label is read long after the person who wrote it
    # has stopped being available to correct it.
    run_id = args.run_id or (("prod-" if args.production else "pilot-")
                             + datetime.now().strftime("%Y%m%dT%H%M%S"))
    wanted = args.clients or clientcfg.list_clients()

    qa = connect_qa(pilot=not args.production, production=args.production, env=env)
    qcur = qa.cursor()
    qcur.execute("SELECT DB_NAME()")
    live = qcur.fetchone()[0]
    mode = "CENSUS - every in-scope line" if args.census else f"SAMPLE - {args.lines} lines/client"
    print(f"{'READING ONLY (--dry-run), nothing will be written' if args.dry_run else 'writing'} "
          f"to {live}  ({'PRODUCTION' if args.production else 'pilot'})   run_id = {run_id}")
    print(f"{mode}" + ("" if args.census else
                       f", >= {args.pct_categorised}% carrying a category"))
    print("EVERY LINE JUDGED ON ITS OWN - no grouping\n")

    # A superseded generation left in the table double-counts every figure taken from it, and has
    # done so once for real (2026-08-04).
    #
    # 2026-08-20: THE PURGE MOVED TO THE END OF THE RUN, and it destroyed the pilot before it did.
    # It used to sit HERE - before a single row had been read, deleting every run_id that was not
    # this invocation's freshly-minted one. Two things followed from that ordering, and both are
    # real rather than theoretical:
    #
    #   1. A --dry-run, whose banner says "nothing will be written", wiped 2,000 judged lines.
    #   2. ANY failure between the purge and the first successful write left the table EMPTY -
    #      the old generation deleted, the new one never arrived. Delete-then-attempt.
    #
    # It is now delete-AFTER-replace: the new run is written alongside the old one and the old one
    # is purged once every client has landed. If the load dies half way, the previous generation is
    # still there and the table simply holds two run_ids - which state_audit.py already reports as a
    # STOP. A visible, recoverable inconsistency beats a silent empty table.
    if args.dry_run:
        print("  --dry-run: no purge, no deletes, no inserts. Reading only.\n")
    else:
        # PRE-FLIGHT. The guard below would also catch this - but only AFTER a 20-minute load,
        # leaving two generations behind and the work wasted. Knowing before starting is the
        # inverse of the delete-then-attempt defect that emptied the pilot on 2026-08-20: find
        # out whether the run can legally finish BEFORE doing anything irreversible.
        qcur.execute("""SELECT RUN_ID,
                SUM(CASE WHEN NIM_VERDICT   IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN REVIEW_STATUS IS NOT NULL THEN 1 ELSE 0 END)
            FROM qa_line WHERE RUN_ID <> ? GROUP BY RUN_ID""", run_id)
        blocked = [(r[0], r[1] or 0, r[2] or 0) for r in qcur.fetchall() if (r[1] or 0) or (r[2] or 0)]
        if blocked:
            det = "\n".join(f"    {r:32} judged {j:>9,}   reviewed {v:>9,}" for r, j, v in blocked)
            raise SystemExit(
                f"\n  STOP before loading anything - a superseded run holds work this load would\n"
                f"  have to destroy at the end, and it would destroy it AFTER {'' if args.census else 'a '}"
                f"full load had already run.\n\n{det}\n\n"
                "  A verdict is 15-37 days of compute. AN ANALYST REVIEW CANNOT BE REGENERATED.\n\n"
                "  Pass --run-id <that run> to ADD to it instead of replacing it. That is the\n"
                "  right answer for a monthly refresh and is what the incremental model (PLAN.md\n"
                "  stage 3b) makes safe properly.\n")

    line_ins = (f"INSERT INTO qa_line ({', '.join(out_name(f) for f in FIELDS)}) "
                f"VALUES ({', '.join('?' * len(FIELDS))})")
    RULE_COLS = ["run_id", "client_code", "rule_id", "rules_table", "resolves",
                 "tests_description"] + list(RULE_SRC) + \
                ["lines_in_scope", "vendors_in_scope", "spend_in_scope"]
    rule_ins = (f"INSERT INTO qa_rule ({', '.join(RULE_COLS)}) "
                f"VALUES ({', '.join('?' * len(RULE_COLS))})")

    for k in wanted:
        cfg = clientcfg.load_config(k)
        if not cfg or clientcfg.missing_for_run(cfg):
            print(f"  {k:20} SKIPPED - config incomplete")
            continue
        cn = connect_client(k, env=env, timeout=60)
        cn.timeout = 3000
        cur = cn.cursor()

        tx_tbl = clientcfg.taxonomy_table(cfg)
        tx_cols = set()
        if tx_tbl:
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                        tx_tbl.replace("[", "").replace("]", "").split(".")[-1])
            tx_cols = {c[0] for c in cur.fetchall()}
        check_level_overflow(k, tx_cols)
        rule_cols = []
        for rt in clientcfg.rules_tables(cfg):
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                        rt.replace("[", "").replace("]", "").split(".")[-1])
            rule_cols.append((rt, {c[0] for c in cur.fetchall()}))

        print(f"  {k}")
        in_scope, n_blank, n_cat = scope_counts(cfg, cur)

        # Source-structure metadata is read BEFORE the main SELECT, not after. It used to sit
        # after fetchall(), which was harmless while the whole result was in memory; with the
        # result STREAMED it is not - the cursor is mid-result-set and cannot run another query.
        src_tbl = clientcfg.source_table(cfg)
        cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                    src_tbl.replace("[", "").replace("]", "").split(".")[-1])
        n_src_cols = cur.fetchone()[0]
        n_tx_rows = None
        if tx_tbl:
            cur.execute(f"SELECT COUNT(*) FROM {tx_tbl}")
            n_tx_rows = cur.fetchone()[0]
        n_rule_rows = 0
        for rt in clientcfg.rules_tables(cfg):
            cur.execute(f"SELECT COUNT(*) FROM {rt}")
            n_rule_rows += cur.fetchone()[0]

        if args.census:
            # THE PRODUCTION LOAD. Every in-scope line, and the expected count is the client's own
            # in-scope count measured moments ago on the same connection - an OUTSIDE-the-process
            # yardstick, not the loader's own arithmetic.
            take_cat = take_blank = None
            expected = in_scope
            print(f"     in scope {in_scope:,}  ({n_cat:,} categorised, {n_blank:,} uncategorised)")
            print(f"     CENSUS - loading all {in_scope:,}")
            note = ("LINE-LEVEL CENSUS, no grouping - every in-scope line judged on its own. "
                    "No TOP, no sampling, no vendor spread. Rule error rates from this run are "
                    "FACTS for this client, not estimates.")
            q = build_select(cfg, k, None, None, tx_cols, run_id, rule_cols, census=True)
        else:
            take_cat, take_blank = plan_strata(args.lines, args.pct_categorised, n_cat, n_blank)
            expected = take_cat + take_blank
            print(f"     in scope {in_scope:,}  ({n_cat:,} categorised, {n_blank:,} uncategorised)")
            print(f"     drawing {take_cat} categorised + {take_blank} uncategorised "
                  f"= {take_cat + take_blank}")
            if take_cat + take_blank < args.lines:
                print(f"     ** short of the {args.lines}-line target - the client does not hold "
                      f"enough in-scope lines **")
            note = (f"LINE-LEVEL sample, no grouping - every line judged on its own. {take_cat} "
                    f"lines carrying a Category Level 0 and {take_blank} uncategorised, drawn as "
                    f"two independent draws ordered by a hash of the line so the rows are chosen "
                    f"by the data and not by scan order. NOT a census: rule error rates from this "
                    f"run are ESTIMATES.")
            q = build_select(cfg, k, None, None, tx_cols, run_id, rule_cols,
                             strata=(take_cat, take_blank))

        # Clear this client's slot BEFORE the first batch lands. Streaming means rows are committed
        # as they arrive, so a delete afterwards would remove what was just written.
        if not args.dry_run:
            # Same generation, same client, being reloaded. Guarded: on a re-run after judging has
            # started this is the delete that would silently take the verdicts with it.
            refuse_if_precious(qcur, "RUN_ID=? AND CLIENT_CODE=?", (run_id, k),
                               f"{k}'s rows in run {run_id} before reloading them")
            qcur.execute("DELETE FROM qa_line WHERE RUN_ID=? AND CLIENT_CODE=?", run_id, k)
            qcur.execute("DELETE FROM qa_rule WHERE run_id=? AND client_code=?", run_id, k)
            qcur.execute("DELETE FROM qa_run  WHERE run_id=? AND client_code=?", run_id, k)
            qa.commit()

        # --- STREAM. Never fetchall() ------------------------------------------------------------
        # fetchall() over 2.77M rows x 84 columns does not fit in memory, and the failure arrives
        # only at full scale - it cannot happen on a 500-line sample. fetchmany() pulls from the
        # server as it goes, so peak memory is one batch regardless of population size.
        #
        # A commit per batch, deliberately: one transaction around a whole client is ~880k rows of
        # log that cannot be released until it closes. An interruption therefore leaves a PARTIAL
        # client, which is already the documented behaviour - state_audit.py reports it, and a
        # re-run clears the slot above and starts that client again.
        ridx = FIELDS.index("rule_id")
        ids = set()
        n_rows = 0
        t0 = time.time()
        cur.execute(q)
        while True:
            chunk = cur.fetchmany(BATCH)
            if not chunk:
                break
            for r in chunk:
                if r[ridx]:
                    ids.add(r[ridx])
            if not args.dry_run:
                qcur.fast_executemany = True
                qcur.executemany(line_ins, [tuple(r) for r in chunk])
                qcur.fast_executemany = False
                qa.commit()
            n_rows += len(chunk)
            el = time.time() - t0
            print(f"       {n_rows:>9,} / {expected:,}   {el / 60:>6.1f} min   "
                  f"{n_rows / el * 60:>8,.0f} lines/min", flush=True)
        el = time.time() - t0
        print(f"     read {n_rows:,} lines in {el / 60:.1f} min "
              f"({n_rows / el * 60:,.0f} lines/min)")

        ids = sorted(ids)
        # the fix queue: every rule these lines actually reference, with its FULL-population
        # impact - so an owner reading "this rule touches 1,591 lines" gets the real number, not
        # the number that happened to land in a 500-line sample.
        text = rule_text(cfg, cur, ids)
        impact = rule_impact(cfg, cur, ids)
        cn.close()

        rule_rows = []
        for r in ids:
            rt, t = text.get(r, (None, {}))
            fields = [t.get(f) for f in ("field_1", "field_2", "field_3")]
            tests = (None if not rt else
                     "Y" if any("DESCRIPTION" in (f or "").upper() for f in fields) else "N")
            im = impact.get(r, {})
            n_lines = im.get("lines")
            rule_rows.append(tuple(
                [run_id, k, r[:100], (rt or "(unresolved)")[:128], "Y" if rt else "N", tests]
                + [t.get(f) for f in RULE_SRC]
                + [n_lines, im.get("vendors"), im.get("spend")]))

        if args.dry_run:
            ok = "OK" if n_rows == expected else "** MISMATCH **"
            print(f"     DRY RUN - nothing written.  read {n_rows:,}  expected {expected:,}  {ok}")
            print(f"     {len(rule_rows)} rules would be written\n")
            continue

        qcur.executemany(rule_ins, rule_rows)

        qcur.execute("""INSERT INTO qa_run (run_id, client_code, loaded_at, source_table,
              source_columns, taxonomy_source, taxonomy_rows, taxonomy_columns, rules_tables,
              rules_rows, lines_in_scope, lines_loaded, selection_note, scope_note,
              judge_backend, judge_model, prompt_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            run_id, k, datetime.now(),
            f"{(cfg.get('source') or {}).get('database')}.{src_tbl}", n_src_cols,
            f"{(cfg.get('source') or {}).get('database')}.{tx_tbl}" if tx_tbl else None,
            n_tx_rows, len(tx_cols) or None, ", ".join(clientcfg.rules_tables(cfg)), n_rule_rows,
            in_scope, n_rows, note,
            SCOPE_NOTE, None, None, None)
        qa.commit()

        qcur.execute("""SELECT COUNT(*), SUM(CASE WHEN CATEGORY_LVL_0=? THEN 1 ELSE 0 END)
                        FROM qa_line WHERE RUN_ID=? AND CLIENT_CODE=?""",
                     clientcfg.LEVEL_UNCATEGORISED, run_id, k)
        got, got_blank = qcur.fetchone()
        # The check that matters, and it is deliberately NOT "did it finish without error".
        # `expected` came from the CLIENT's own scope count, measured on the client connection -
        # outside this process. A round number here would mean something silently capped the load.
        ok = "OK" if got == expected else f"** MISMATCH - expected {expected:,} **"
        print(f"     loaded {got:,} lines ({got - (got_blank or 0):,} categorised, "
              f"{got_blank or 0:,} uncategorised), {len(rule_rows)} rules   {ok}\n")
        if got != expected:
            raise SystemExit(
                f"\n  STOP - {k}: loaded {got:,} but the client holds {expected:,} in scope.\n"
                f"  A load that returns the wrong count and carries on is the failure mode this\n"
                f"  project keeps finding: it looks like success. Nothing further is run.\n")

    # ---- NOW the superseded generation goes, with the replacement already committed -------------
    if not args.dry_run:
        qcur.execute("SELECT DISTINCT RUN_ID FROM qa_line WHERE RUN_ID <> ?", run_id)
        old_runs = [r[0] for r in qcur.fetchall()]
        for o in old_runs:
            refuse_if_precious(qcur, "RUN_ID=?", (o,), f"superseded run {o}")
            for t in ("qa_line", "qa_rule", "qa_run"):
                qcur.execute(f"DELETE FROM {t} WHERE {'RUN_ID' if t=='qa_line' else 'run_id'}=?", o)
            print(f"  purged superseded run {o}  (replacement already committed)")
        if old_runs:
            qa.commit()
            print()

    print("=" * 84)
    qcur.execute("""SELECT r.client_code, r.lines_in_scope, r.lines_loaded,
                      (SELECT COUNT(*) FROM qa_rule q WHERE q.run_id=r.run_id
                                                        AND q.client_code=r.client_code)
                    FROM qa_run r WHERE r.run_id=? ORDER BY 1""", run_id)
    print(f"  {'client':20} {'rules':>6} {'lines loaded':>13} {'client in-scope':>16}")
    print("  " + "-" * 62)
    tl = 0
    for c, insc, loaded, nr in qcur.fetchall():
        tl += loaded or 0
        print(f"  {c:20} {nr:>6} {loaded:>13,} {insc:>16,}")
    print("  " + "-" * 62)
    print(f"  {'TOTAL':20} {'':>6} {tl:>13,}")
    print("\n  Every line is judged on its own. No grouping, at any stage.")
    # The closing line asserts what kind of run this WAS. It said "SAMPLE" unconditionally,
    # and printed that under a 671,200-line census on 2026-08-21 - a banner stating the
    # opposite of what happened, which is the same defect as apply_schema printing
    # "(pilot only)" while writing to production. Harmless to the data, corrosive to the
    # reader, and it is the reader who decides whether a figure can be quoted.
    print("  This is a CENSUS - every in-scope line. Rule error rates from it are FACTS\n"
          "  for this client, not estimates." if args.census else
          "  This is a SAMPLE - rule error rates from it are estimates, not facts.")
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
