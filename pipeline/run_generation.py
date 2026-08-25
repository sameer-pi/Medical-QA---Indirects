#!/usr/bin/env python
"""Run ONE complete judging generation: judge every client, classify, score, check invariants.

    python pipeline/run_generation.py --workers 12
    python pipeline/run_generation.py --workers 24 --dry-run     # print the plan, run nothing

WHY THIS EXISTS. Both full re-judges on 2026-08-17 were driven by a shell loop typed into a scratch
directory that gets cleaned up. The settings survived only because they were written into
`RUN_LOG.md`. **Reproducible-from-a-log is not the same as runnable**, and at full scale the
difference is a person retyping an eight-pass loop correctly at 2am.

🔒 THE ORDER IS NOT OPTIONAL, AND THAT IS THE REAL REASON THIS IS A SCRIPT RATHER THAN A HABIT.
`action_classify.py` MUST run after every judging pass. A re-judge rewrites `NIM_SUGGESTED_KEY` from
the consensus, which is `NULL` for a `Correct` verdict - so it CLEARS the crosswalk fill, and only a
re-classify restores it (PLAN v3.44 change 240). Get the order wrong and 113 `Re-mapped` rows
silently lose their destination: a defect Sameer found by reading the data, not by any check.

⚠️ IT DOES NOT CLEAR THE PREVIOUS GENERATION. Selection is `NIM_VERDICT IS NULL`, so this RESUMES by
default - an interrupted run continues exactly where it stopped, and a completed one is a no-op.
Clearing 2,000 verdicts is destructive and stays a deliberate, separate act (`--reset`), because
"a killed process is not a process that did nothing" applies twice over here.
"""
import argparse
import io
import os
import subprocess
import sys
import time

# 🔒 FORCE UTF-8 ON OUR OWN STREAMS, not just on the children.
#
# 2026-08-21: `--reset` cleared the NIM_* columns on 2,000 rows, COMMITTED, and then the process
# died on the very next line - a UnicodeEncodeError printing the ⚠️ in the message announcing the
# reset. The pilot was left with 2,000 rows and ZERO verdicts, and the judging never began.
#
# 🔑 The irony is the point: line 41 already sets PYTHONIOENCODING="utf-8" for every SUBPROCESS,
# so the children were safe and the parent was not. A guarantee applied to what you spawn is not a
# guarantee about yourself. Same defect fixed in score_answer_key.py on 2026-08-18 - fixed THERE,
# and nobody asked which other file printed an emoji.
#
# ⚠️ And note WHERE it landed: after the destructive UPDATE, before the work. Any crash in that
# window empties the pilot. The print is now safe, but the ordering is still delete-then-attempt.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clientcfg import list_clients  # noqa: E402
from db import connect_qa, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LOGDIR = os.path.join(os.path.dirname(HERE), "output", "logs")
LOG = None

# 🔒 A RUN THAT KEEPS NO LOG CANNOT BE DIAGNOSED AFTERWARDS, AND THIS ONE ALREADY WASN'T.
#
# 2026-08-24: 141 of 2,000 pilot lines were decided by fewer than three models. `ask_models` prints
# the exact exception for every failed request - "HTTP 429", "no response in 180s", a JSON parse
# error - and `sh` below CAPTURED all of it and then threw it away, printing six lines of tail only
# when the step exited non-zero. The passes exited ZERO. Every one of those 16 failures was
# explained, in text, in a variable, and discarded.
#
# 🔑 The mechanism was recoverable from the stored verdicts; the CAUSE was not, and that is the
# difference between "16 requests failed" and "16 requests failed BECAUSE". Three reproduction
# attempts at full concurrency then failed to trigger it at all - so the only evidence that would
# have settled it was the evidence we deleted.
#
# At 40 days this stops being an inconvenience: a run nobody can look back at cannot be trusted,
# and it cannot be resumed intelligently either.
class _Tee:
    """Console AND file. Not `> file`, because a run nobody can watch is its own problem."""

    def __init__(self, stream, fh):
        self._s, self._f = stream, fh

    def write(self, t):
        self._s.write(t)
        self._f.write(t)
        return len(t)

    def flush(self):
        self._s.flush()
        self._f.flush()

    def __getattr__(self, n):
        return getattr(self._s, n)


def sh(args, label):
    """Run a pipeline step, streaming nothing but its tail. Returns (ok, seconds).

    ⚠️ The tail is what reaches the CONSOLE. The whole of stdout and stderr goes to the log file,
    always, pass or fail - the failures that mattered on 2026-08-21 were inside a pass that exited
    zero, so keeping output only on a non-zero exit keeps exactly the wrong half.
    """
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([PY] + args, cwd=os.path.dirname(HERE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    dt = time.time() - t0
    if LOG:
        LOG.write(f"\n{'=' * 100}\n=== {label}   exit={p.returncode}   {dt / 60:.1f} min\n"
                  f"{'=' * 100}\n")
        LOG.write(p.stdout or "")
        LOG.write(p.stderr or "")
        LOG.flush()
    if p.returncode != 0:
        print(f"  ** FAILED: {label} (exit {p.returncode})", flush=True)
        print("     " + "\n     ".join((p.stdout or "").splitlines()[-6:]), flush=True)
        print("     " + "\n     ".join((p.stderr or "").splitlines()[-6:]), flush=True)
    return p.returncode == 0, dt, (p.stdout or "")


def invariants_rows(production=False):
    """Rows in qa_line, in whichever database this run is pointed at."""
    qa = connect_qa(pilot=not production, production=production, env=load_env())
    c = qa.cursor()
    c.execute("SELECT COUNT(*) FROM qa_line")
    n = c.fetchone()[0]
    qa.close()
    return n


def judged_count(production=False):
    """How many lines currently carry a jury verdict. Used to measure the rate on what was ACTUALLY
    judged, rather than on a constant."""
    qa = connect_qa(pilot=not production, production=production, env=load_env())
    c = qa.cursor()
    c.execute("SELECT COUNT(*) FROM qa_line WHERE NIM_VERDICT IS NOT NULL")
    n = c.fetchone()[0]
    qa.close()
    return n


def invariants(tag, production=False):
    """The checks that must hold before a figure from this table is worth quoting."""
    qa = connect_qa(pilot=not production, production=production, env=load_env())
    c = qa.cursor()
    out = {}
    c.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM qa_line")
    out["rows"], out["run_ids"] = c.fetchone()
    # 🔒 THE ROW COUNT IS MEASURED AGAINST qa_run, NEVER AGAINST THE LITERAL 2,000.
    #
    # 2,000 is a fact about the pilot. Production holds 2,786,018, so a hard `== 2000` here would
    # have FAILED every production generation - and the identical constant three lines further down
    # produced "judging rate ~514 lines/min, full-scale 3.7 days" on 2026-08-24 after a run that
    # judged 142 lines. Wrong by an order of magnitude, printed with the same confidence as a
    # measurement.
    #
    # 🔑 qa_run is written by the LOADER, so this stays an outside-the-process check - the property
    # that made it worth having. It is not the judge marking its own homework; it is the judged
    # table reconciled against what the load said it put there.
    c.execute("""SELECT SUM(LINES_LOADED) FROM qa_run
                 WHERE RUN_ID IN (SELECT DISTINCT run_id FROM qa_line)""")
    out["expected"] = c.fetchone()[0] or 0
    for k, q in (("unjudged", "SELECT COUNT(*) FROM qa_line WHERE NIM_VERDICT IS NULL"),
                 ("no_action", "SELECT COUNT(*) FROM qa_line WHERE NIM_ACTION IS NULL"),
                 ("gl_leak", """SELECT COUNT(*) FROM qa_line WHERE NIM_RATIONALE LIKE '%account name%'
                                OR NIM_RATIONALE LIKE '%cost centre%' OR NIM_RATIONALE LIKE '%GL %'
                                OR NIM_RATIONALE LIKE '%general ledger%'"""),
                 ("remap_nodest", """SELECT COUNT(*) FROM qa_line WHERE NIM_ACTION='Re-mapped'
                                     AND NIM_SUGGESTED_KEY IS NULL"""),
                 ("hollow", """SELECT COUNT(*) FROM qa_line
                               WHERE NIM_MODELS_RESPONDED < 3"""),
                 ("misc_nodest", """SELECT COUNT(*) FROM qa_line WHERE NIM_ACTION='Miscategorised'
                                    AND NIM_SUGGESTED_KEY IS NULL""")):
        c.execute(q)
        out[k] = c.fetchone()[0]
    qa.close()
    print(f"\n=== INVARIANTS ({tag}) ===", flush=True)
    checks = [
        (f"qa_line rows (qa_run says {out['expected']:,})", out["rows"],
         out["rows"] == out["expected"]),
        ("distinct run_id", out["run_ids"], out["run_ids"] == 1),
        ("lines with no verdict", out["unjudged"], out["unjudged"] == 0),
        ("lines with no action", out["no_action"], out["no_action"] == 0),
        ("rationales citing the GL", out["gl_leak"], out["gl_leak"] == 0),
        ("Re-mapped with no destination", out["remap_nodest"], out["remap_nodest"] == 0),
        ("Miscategorised with no destination", out["misc_nodest"], out["misc_nodest"] == 0),
        # 🔒 NOT ==0: a dropout is normal at low rates and this must not cry wolf.
        # It is a RATE check because the failure it catches is gradual - at 16 workers
        # 11 lines of 2,000 lost a model, at 24 it was 26, at 48 it was 102. A jury that
        # is quietly hollowing out is invisible in every other number on this list,
        # because 2of2 reads exactly like agreement. 1% is the line between the two.
        ("lines judged by <3 models", out["hollow"], out["hollow"] <= 0.01 * out["rows"]),
    ]
    bad = 0
    for label, val, ok in checks:
        bad += not ok
        print(f"  {label:<36} {val:>6}   {'OK' if ok else '** INVESTIGATE **'}", flush=True)
    return bad


def main():
    ap = argparse.ArgumentParser(description="Run one complete judging generation.")
    ap.add_argument("--workers", type=int, default=16,
                    help="parallel batches per client. 16 is the MEASURED CEILING and the default. "
                         "Throughput flattens there (154 lines/min; 24 and 32 buy nothing) but "
                         "that is not the reason to stop: ABOVE 16 MODELS DROP OUT OF THE JURY - "
                         "26 lines at 24 workers, 36 at 32, 102 at 48, against 2 at 16. Raising "
                         "this trades verdict quality for speed. RUN_LOG Finding 95.")
    ap.add_argument("--batch", type=int, default=10,
                    help="lines per prompt. Above ~10 the response truncates silently.")
    ap.add_argument("--clients", help="comma-separated subset; default is every configured client")
    ap.add_argument("--reset", action="store_true",
                    help="⚠️ CLEAR every NIM_* column first. Destroys the current generation. "
                         "Claude's verdicts, MSD_COHERENCE and the REVIEW layer are NOT touched.")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--production", action="store_true",
                    help="⚠️ run the generation against PI_Medical_QA_Indirect - 2,786,018 lines, "
                         "~40 days. Without this every step runs on the 2,000-row pilot, which is "
                         "the safe default on purpose.")
    ap.add_argument("--topup", action="store_true",
                    help="repair pass: ALSO re-offer lines that fewer than 3 models answered. "
                         "Non-destructive - nim_judge.write() refuses to lower "
                         "NIM_MODELS_RESPONDED, so a line can only improve. Use this instead of "
                         "--reset when the jury has hollowed out; --reset would destroy every "
                         "verdict to repair a few percent of them.")
    args = ap.parse_args()

    global LOG
    os.makedirs(LOGDIR, exist_ok=True)
    logpath = os.path.join(LOGDIR, f"Indirect judging - {time.strftime('%Y-%m-%dT%H%M%S')}.log")
    LOG = io.open(logpath, "w", encoding="utf-8", errors="replace", newline="")
    sys.stdout, sys.stderr = _Tee(sys.stdout, LOG), _Tee(sys.stderr, LOG)
    print(f"log -> {logpath}", flush=True)

    clients = ([c.strip() for c in args.clients.split(",")] if args.clients else list_clients())
    plan = [(c, unc) for c in clients for unc in (False, True)]
    print(f"generation plan: {len(plan)} passes over {len(clients)} clients, "
          f"workers={args.workers} batch={args.batch}   "
          f"** {'PRODUCTION - PI_Medical_QA_Indirect' if args.production else 'pilot'} **",
          flush=True)
    for c, unc in plan:
        print(f"   {c:<20} {'uncategorised' if unc else 'categorised'}", flush=True)
    if args.dry_run:
        return 0

    if args.reset:
        qa = connect_qa(pilot=not args.production, production=args.production, env=load_env())
        c = qa.cursor()
        c.execute("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                     WHERE TABLE_NAME='qa_line' AND COLUMN_NAME LIKE 'NIM[_]%'""")
        cols = [r[0] for r in c.fetchall()]
        c.execute("SELECT COUNT(*) FROM qa_line")
        n_rows = c.fetchone()[0]
        c.execute("UPDATE qa_line SET " + ", ".join(f"{n}=NULL" for n in cols))
        qa.commit()
        qa.close()
        # The row count is READ, not assumed. It said "2,000 rows" whatever it had just cleared.
        print(f"\n⚠️ RESET: cleared {len(cols)} NIM_* columns on {n_rows:,} rows. "
              f"Claude's verdicts, MSD_COHERENCE and the REVIEW layer are untouched.", flush=True)

    t0 = time.time()
    judged_before = judged_count(args.production)
    failed = []
    for client, unc in plan:
        cmd = [os.path.join(HERE, "nim_judge.py"), "--client", client, "--all",
               "--batch", str(args.batch), "--workers", str(args.workers)]
        if unc:
            cmd.append("--uncategorised")
        if args.topup:
            cmd.append("--topup")
        if args.production:
            cmd.append("--production")
        label = (f"{client} {'uncategorised' if unc else 'categorised'}"
                 + (" [top-up]" if args.topup else ""))
        ok, dt, _ = sh(cmd, label)
        print(f"  {label:<38} {dt/60:5.1f} min   {'ok' if ok else 'FAILED'}", flush=True)
        if not ok:
            failed.append(label)
    judged = time.time() - t0
    print(f"\njudging done in {judged/60:.1f} minutes"
          + (f"   ** {len(failed)} pass(es) FAILED: {', '.join(failed)} **" if failed else ""),
          flush=True)

    # 🔒 ALWAYS, and always AFTER judging. See the module docstring.
    ok, dt, _ = sh([os.path.join(HERE, "action_classify.py")]
                   + (["--production"] if args.production else []), "action_classify")
    print(f"classify: {dt:.0f}s   {'ok' if ok else 'FAILED'}", flush=True)

    ok, dt, out = sh([os.path.join(HERE, "score_answer_key.py")], "score_answer_key")
    if ok:
        for line in out.splitlines():
            if any(k in line for k in ("agreement", "same LEAF", "same BRANCH",
                                       "genuinely different", "NO destination")):
                print("  " + line.strip(), flush=True)

    bad = invariants("after this generation", args.production)
    total = time.time() - t0
    # 🔒 THE NUMERATOR IS WHAT WAS JUDGED, NOT THE SIZE OF THE TABLE. On a top-up or a resume most
    # lines are already done, so dividing the table by the elapsed time reports a rate nothing ran
    # at. Measured 2026-08-24: a 142-line top-up printed "514 lines/min" and "3.7 days" against a
    # figure measured three times at ~50/min and ~40 days.
    did = max(0, judged_count(args.production) - judged_before)
    rate = did / (judged / 60) if judged and did else 0
    print(f"\ntotal {total/60:.1f} minutes   judged {did:,} line(s) this run   "
          f"rate ~{rate:.0f} lines/min at {args.workers} workers", flush=True)
    if rate:
        remaining = max(0, invariants_rows(args.production) - judged_count(args.production))
        print(f"at that rate the {remaining:,} line(s) still unjudged in this database would take "
              f"{remaining / rate / 60 / 24:.1f} days of continuous judging", flush=True)
    else:
        print("no lines were judged this run - no rate to report", flush=True)
    return 1 if (failed or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
