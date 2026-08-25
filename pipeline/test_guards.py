"""Prove the database guard. Run it after ANY change to db.py, and before any production work.

    python pipeline/test_guards.py

WHY THIS EXISTS AS A COMMITTED TEST AND NOT A ONE-OFF CHECK. This guard is the only thing standing
between a pipeline that WRITES and four hospitals' live databases. Until 2026-08-18 the guard was
`"pilot" not in name -> stop`, which was correct while one QA database existed and silently became
wrong the moment production was created - production has no "pilot" in its name, so every guarded
script refused to speak to it.

The tempting fix was to delete the check. That would have been the worst possible change, because
the check was never about the pilot: IT IS ABOUT NEVER WRITING TO A CLIENT DATABASE. A typo in
.env, a stale environment or a copied command is all it takes, and nothing downstream would notice
- the pipeline would simply start writing qa_* tables into a hospital's database.

So the guard became two independent locks, and this file is the evidence they both hold:

  lock 1   the target must be a name we KNOW      -> stops the WRONG database
  lock 2   production must be asked for on purpose -> stops the RIGHT one being hit by accident

READ-ONLY. It opens the pilot connection twice to prove the normal path still works and asserts
that everything else raises. It writes nothing anywhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import (assert_writable_qa_database, connect_qa, load_env,  # noqa: E402
                qa_database_names)

env = load_env()
names = qa_database_names(env)
PILOT = names[False]
PROD = names[True]
passed = failed = 0


def check(label, fn, want_raise, want_text=None):
    global passed, failed
    try:
        fn()
        got = "no error"
    except Exception as exc:
        got = str(exc)
    ok = (got != "no error") == want_raise
    if ok and want_text:
        ok = want_text.lower() in got.lower()
    print("  {:<58} {}".format(label, "PASS" if ok else "FAIL  -> " + got.split("\n")[0][:80]))
    if ok:
        passed += 1
    else:
        failed += 1


def main():
    print("configured:  pilot=[{}]  production=[{}]".format(PILOT or "(blank)", PROD or "(blank)"))

    print("\n=== the pilot path works, and is what you get by default ===")
    check("connect_qa()           -> pilot", lambda: connect_qa().close(), False)
    check("connect_qa(pilot=True) -> pilot", lambda: connect_qa(pilot=True).close(), False)
    check("assert(pilot, production=False)",
          lambda: assert_writable_qa_database(PILOT, False, env), False)

    print("\n=== a CLIENT database is refused in both modes - the reason this file exists ===")
    for bad in ("Z_Melbourne_Health", "Z_Northern_Health", "Z_Adventist", "Z_Western Health"):
        check("assert([{}], pilot mode)".format(bad),
              lambda b=bad: assert_writable_qa_database(b, False, env), True)
        check("assert([{}], production mode)".format(bad),
              lambda b=bad: assert_writable_qa_database(b, True, env), True)

    print("\n=== near-misses and nonsense are refused ===")
    for bad in ("master", "tempdb", "", "   ",
                (PILOT[:-1] if PILOT else "x"),          # one character short
                (PILOT + "_old" if PILOT else "x")):     # a leftover copy
        check("assert([{}])".format(bad.strip() or "<empty>"),
              lambda b=bad: assert_writable_qa_database(b, False, env), True)

    print("\n=== the two QA databases cannot be confused with each other ===")
    if PROD:
        check("assert(production name, pilot mode)      -> refused",
              lambda: assert_writable_qa_database(PROD, False, env), True)
        check("assert(pilot name, production mode)      -> refused",
              lambda: assert_writable_qa_database(PILOT, True, env), True)
        check("assert(production name, production mode) -> allowed",
              lambda: assert_writable_qa_database(PROD, True, env), False)
    else:
        check("production unreachable while QA_DATABASE is blank",
              lambda: connect_qa(production=True), True, "is empty in .env")
        print("       (QA_DATABASE is blank, so the pilot/production confusion cases cannot")
        print("        be exercised yet. Re-run this once production is configured.)")

    print("\n{} passed, {} failed".format(passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
