"""preflight.py - can THIS machine start the judging run? Answer before committing ~40 days.

    python pipeline/preflight.py --production

WHY THIS EXISTS. The code and the data were ready on 2026-08-26 and the run moves to a different
machine - the office desktop. Five things that can stop it live on THAT machine and cannot be
checked from anywhere else: Python, pyodbc, the ODBC driver, .env, and whether the network lets us
reach the SQL server and NVIDIA. A list of those in a document is something to trust. This is
something to run.

🔒 IT PRINTS NO SECRET VALUES, EVER. Credentials are reported as present/absent and by length only.
`.env` holds live SQL logins for five databases and the NIM key; a preflight that echoed them into
a terminal - or into a log file, or a screenshot in a chat - would be the leak it exists to prevent.

READ-ONLY. It opens connections and reads counts. It writes nothing to either database, and the one
NIM call it makes asks for a handful of tokens.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def record(name, ok, detail="", fatal=True):
    RESULTS.append((name, ok, detail, fatal))
    mark = "  OK  " if ok else ("  ** STOP **" if fatal else "  ** WARN **")
    print("%s %-34s %s" % (mark, name, detail), flush=True)
    return ok


def check_python():
    v = sys.version_info
    record("python", v >= (3, 9), "%d.%d.%d" % (v.major, v.minor, v.micro))


def check_pyodbc():
    try:
        import pyodbc
    except Exception as e:                                    # noqa: BLE001
        return record("pyodbc importable", False, "pip install pyodbc  (%s)" % str(e)[:60])
    drivers = [d for d in pyodbc.drivers()]
    record("pyodbc importable", True, "version %s" % pyodbc.version)
    # An ML box has CUDA and PyTorch; it very often does NOT have a SQL Server ODBC driver, and
    # that is the single likeliest thing to stop a first run on a new machine.
    wanted = [d for d in drivers if "SQL Server" in d]
    return record("ODBC Driver for SQL Server", bool(wanted),
                  ", ".join(wanted) if wanted else
                  "NONE FOUND - install 'ODBC Driver 17 for SQL Server'. Have: %s"
                  % (", ".join(drivers[:4]) or "no drivers at all"))


def check_env(production):
    from db import load_env
    try:
        env = load_env()
    except Exception as e:                                    # noqa: BLE001
        record(".env present", False, "%s - copy it across BY HAND, never through git" % str(e)[:60])
        return None
    record(".env present", True, "loaded")

    need = ["SQL_SERVER", "SQL_USER", "SQL_PASS", "SQL_DRIVER",
            "QA_DATABASE" if production else "QA_DATABASE_PILOT",
            "NIM_BASE_URL", "NIM_API_KEY", "NIM_MODELS"]
    missing = [k for k in need if not (env.get(k) or "").strip()]
    # LENGTHS ONLY. Never the value - not for the password, not for the key.
    shape = "  ".join("%s=%d chars" % (k, len((env.get(k) or "").strip()))
                      for k in ("SQL_PASS", "NIM_API_KEY"))
    record("required .env keys", not missing,
           shape if not missing else "MISSING: %s" % ", ".join(missing))

    n_models = len([m for m in (env.get("NIM_MODELS") or "").split(",") if m.strip()])
    record("three judge models configured", n_models == 3,
           "%d configured - a 2-of-3 vote needs three" % n_models, fatal=(n_models == 0))
    return env if not missing else None


def check_sql(env, production):
    from db import connect_qa, assert_writable_qa_database
    try:
        t = time.time()
        qa = connect_qa(production=production, env=env)
        cur = qa.cursor()
        cur.execute("SELECT DB_NAME()")
        live = cur.fetchone()[0]
    except Exception as e:                                    # noqa: BLE001
        return record("SQL Server reachable", False,
                      "%s - check the network path from THIS machine" % str(e)[:70])
    record("SQL Server reachable", True, "%s in %.1fs" % (live, time.time() - t))

    try:
        assert_writable_qa_database(live, production, env)
        record("writing to the right database", True, live)
    except Exception as e:                                    # noqa: BLE001
        record("writing to the right database", False, str(e)[:70])
        return None

    # A successful SELECT is not a successful write. The judge UPDATEs qa_line for 40 days, so
    # prove the permission rather than trusting the role list - the project's own standard.
    try:
        cur.execute("BEGIN TRAN; UPDATE TOP (1) qa_line SET NIM_RATIONALE = NIM_RATIONALE; ROLLBACK")
        record("write permission on qa_line", True, "proven by a rolled-back UPDATE")
    except Exception as e:                                    # noqa: BLE001
        record("write permission on qa_line", False, str(e)[:70])
    return qa


def check_data(qa):
    cur = qa.cursor()
    cur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM qa_line")
    nrun, nrow = cur.fetchone()
    record("exactly one run_id in qa_line", nrun == 1, "%d run_id, %s rows" % (nrun, "{:,}".format(nrow)))

    cur.execute("SELECT TOP 1 run_id FROM qa_run ORDER BY loaded_at DESC")
    row = cur.fetchone()
    if not row:
        return record("qa_run populated", False, "empty")
    run_id = row[0]

    cur.execute("SELECT COUNT(*), SUM(CASE WHEN GLOBAL_RANK IS NULL THEN 1 ELSE 0 END) "
                "FROM qa_vendor_queue WHERE RUN_ID=?", run_id)
    nq, nullrank = cur.fetchone()
    record("vendor queue built", bool(nq) and not nullrank,
           "%s vendors, GLOBAL_RANK complete" % "{:,}".format(nq or 0) if nq and not nullrank
           else "run: python pipeline/vendor_queue.py --production")

    cur.execute("SELECT SUM(CASE WHEN NIM_VERDICT IS NULL THEN 1 ELSE 0 END), COUNT(*) "
                "FROM qa_line WHERE RUN_ID=?", run_id)
    unjudged, total = cur.fetchone()
    record("how much is left to judge", True,
           "%s of %s unjudged" % ("{:,}".format(unjudged), "{:,}".format(total)), fatal=False)
    return run_id


def check_nim(env):
    """One real call. Proves the key works AND that the firewall lets this machine out.

    On an office network this is the check most likely to fail and least likely to be anticipated:
    the SQL server is internal, but the judge talks to NVIDIA over the public internet for 40 days.
    """
    model = [m.strip() for m in (env.get("NIM_MODELS") or "").split(",") if m.strip()][:1]
    if not model:
        return record("NVIDIA NIM reachable", False, "no model configured")
    body = json.dumps({"model": model[0], "max_tokens": 4,
                       "messages": [{"role": "user", "content": "reply with the word ok"}]}).encode()
    req = urllib.request.Request(
        "%s/chat/completions" % env["NIM_BASE_URL"].rstrip("/"), data=body,
        headers={"Authorization": "Bearer %s" % env["NIM_API_KEY"].strip(),
                 "Content-Type": "application/json"})
    try:
        t = time.time()
        with urllib.request.urlopen(req, timeout=60) as r:
            json.loads(r.read().decode("utf-8"))
        return record("NVIDIA NIM reachable", True, "%s answered in %.1fs" % (model[0], time.time() - t))
    except urllib.error.HTTPError as e:
        hint = " - the key is rejected" if e.code in (401, 403) else ""
        return record("NVIDIA NIM reachable", False, "HTTP %s%s" % (e.code, hint))
    except Exception as e:                                    # noqa: BLE001
        return record("NVIDIA NIM reachable", False,
                      "%s - can this machine reach the internet on 443?" % str(e)[:55])


def main():
    ap = argparse.ArgumentParser(description="Can this machine start the judging run?")
    ap.add_argument("--production", action="store_true",
                    help="check against QA_DATABASE. Without it, the pilot")
    args = ap.parse_args()

    print("\nPREFLIGHT - %s\n%s" % ("PRODUCTION" if args.production else "pilot", "=" * 68), flush=True)
    check_python()
    have_driver = check_pyodbc()
    env = check_env(args.production)

    qa = None
    if env and have_driver:
        qa = check_sql(env, args.production)
        if qa:
            check_data(qa)
            qa.close()
    else:
        record("SQL checks", False, "skipped - fix .env / the ODBC driver first")

    if env:
        check_nim(env)

    fatal = [n for n, ok, _d, f in RESULTS if not ok and f]
    warn = [n for n, ok, _d, f in RESULTS if not ok and not f]
    print("=" * 68)
    if fatal:
        print("\n  ** NO-GO ** - %d blocking problem(s):" % len(fatal))
        for n in fatal:
            print("     - %s" % n)
        print("\n  Fix these before starting. Nothing has been changed.")
        return 1
    if warn:
        print("\n  GO, with %d warning(s): %s" % (len(warn), ", ".join(warn)))
    else:
        print("\n  ** GO ** - this machine can run the judge.")
    print("""
  Next, and launch it DETACHED - not inside a chat window, or closing the
  window stops it (it resumes with nothing lost, but the hours are gone):

      python pipeline/nim_judge.py --queue --top 100 --production

  --queue with no --client = the GLOBAL spend order, largest supplier anywhere
  first. --top 100 is the stop-and-look slice: 100 of 29,469 vendors carry
  68-93% of signed spend. Look at it before committing the other ~40 days.

  ONE JUDGE AT A TIME. Both machines reach the same database.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
