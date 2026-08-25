"""Apply pipeline/schema.sql to a QA database. Defaults to the pilot.

    python pipeline/apply_schema.py                # the pilot - create anything missing
    python pipeline/apply_schema.py --production   # PI_Medical_QA_Indirect
    python pipeline/apply_schema.py --drop         # drop and recreate (DESTROYS verdicts)

REFUSES any database that is not one of the two configured QA targets, and production must be asked
for on purpose. `--drop --production` is refused outright: on the pilot it costs 16 minutes, on
production it destroys a run that cannot be rebuilt from the client views at all.

ON --production IT ALSO PROVES PARITY WITH THE PILOT, automatically, and fails if they differ. That
check is not optional and not a separate script, because "production should match the pilot" is
exactly the assumption that has to be TESTED: schema.sql itself sat 30 columns adrift of the live
pilot for weeks while everyone assumed it matched (RUN_LOG Finding 98).

  Superseded 2026-08-18. This docstring used to read "REFUSES to run against anything but the
  pilot... QA_DATABASE is deliberately blank in .env". That standing instruction of 2026-07-30 was
  DISCHARGED when Sameer created production and schema v2 was proven. The sentence survived the
  code change by a few hours - the same "a comment states its reasoning and the world moves on
  underneath it" defect recorded in Finding 100's addendum, found by grepping for the claim rather
  than by reading the file.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import assert_writable_qa_database, connect_qa, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "schema.sql")
# Order matters on drop: nothing here has FKs, but keep it deterministic anyway.
#
# qa_unit removed from this list 2026-08-18. The TABLE was deleted on 2026-08-05 when grouping was
# removed and every line became judged on its own, but this list was never updated - so the
# verification loop printed "qa_unit MISSING" on every single run since. A verification step that
# reports a known-false failure every time is worse than no verification: it trains the reader to
# skim the output, which is exactly where a REAL missing table would then hide.
TABLES = ["qa_line", "qa_rule", "qa_category", "qa_run", "qa_vendor_queue"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true",
                    help="drop the tables first - DESTROYS any verdicts already recorded")
    ap.add_argument("--production", action="store_true",
                    help="target QA_DATABASE instead of the pilot. Must be asked for on purpose: "
                         "without it everything goes to the 2,000-row pilot, where a mistake "
                         "costs 16 minutes")
    args = ap.parse_args()

    env = load_env()
    qa = connect_qa(production=args.production, env=env)
    cur = qa.cursor()
    cur.execute("SELECT DB_NAME()")
    live = cur.fetchone()[0]

    # THE GUARD, re-checked here against the LIVE connection rather than against .env.
    # connect_qa already refused anything not on the allowlist, so this looks redundant - it is
    # not. .env says which database we ASKED for; DB_NAME() says which one the driver actually
    # OPENED, and a per-client server override or a stale connection string can make those differ.
    # Two independent checks, because one of them could be wrong: that was the reasoning when this
    # guard only knew about the pilot, and it survives the move to two databases unchanged.
    assert_writable_qa_database(live, args.production, env)

    # DESTROYS DATA, and on production it destroys something that took ~15.5 days to produce.
    if args.drop and args.production:
        raise SystemExit(
            f"\n  STOP - --drop against production [{live}] is refused.\n"
            "  On the pilot this costs 16 minutes; here it destroys a run that cannot be\n"
            "  regenerated from the client views at all. Drop the tables by hand, deliberately,\n"
            "  if that is genuinely what you want.\n")
    print(f"applying schema to {live}  "
          f"({'PRODUCTION' if args.production else 'pilot'})")

    if args.drop:
        for t in TABLES:
            cur.execute(f"IF OBJECT_ID('{t}','U') IS NOT NULL DROP TABLE [{t}]")
            print(f"  dropped {t}")
        qa.commit()

    with open(SCHEMA, "r", encoding="utf-8") as fh:
        script = fh.read()
    # pyodbc has no batch separator; GO is a client-side directive, so split on it.
    batches = [b.strip() for b in script.replace("\r\n", "\n").split("\nGO") if b.strip()]
    for b in batches:
        try:
            cur.execute(b)
        except Exception as e:
            msg = str(e).split("]")[-1].strip()
            # CREATE INDEX has no IF NOT EXISTS before SQL Server 2016 syntax; ignore re-creation
            if "already exists" in msg or "duplicate key name" in msg.lower():
                continue
            head = " ".join(b.split()[:6])
            raise SystemExit(f"\n  FAILED on: {head} ...\n  {msg}\n")
    qa.commit()

    print()
    for t in TABLES:
        cur.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?""", t)
        ncols = cur.fetchone()[0]
        if not ncols:
            print(f"  {t:16} MISSING")
            continue
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        print(f"  {t:16} {ncols:>3} columns, {cur.fetchone()[0]:>9,} rows")
    qa.close()

    # ON PRODUCTION, PROVE IT MATCHES THE PILOT - automatically, not as a separate script someone
    # remembers to run. "Production should match the pilot" is exactly the assumption that has to
    # be TESTED: schema.sql sat 30 columns adrift of the live pilot for weeks while everyone
    # assumed it matched, and a column list that agrees with the FILE proves nothing, because the
    # file was the thing that was wrong. Both sides are read from INFORMATION_SCHEMA on the live
    # servers instead.
    if args.production:
        import verify_schema_parity
        print()
        if verify_schema_parity.main() != 0:
            raise SystemExit(
                "  STOP - production does not match the pilot. Everything the pilot proved\n"
                "  is only transferable if the two are the same shape.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
