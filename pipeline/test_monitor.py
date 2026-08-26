#!/usr/bin/env python
"""Tests for monitor.py. NO DATABASE - every case here is pure.

    python pipeline/test_monitor.py

WHY THIS FILE EXISTS. monitor.py makes one safety claim - IT ISSUES SELECT AND NOTHING ELSE - and a
claim that is only ever checked by hand is a claim that stops being true the first time someone edits
the SQL. `_ro()` is that guard; this is what proves it fires. The guard was verified by hand on
2026-08-26 and that verification lived in a scratchpad script that no longer exists, which is exactly
the failure mode this project keeps paying for.

IT ALSO PINS THE TWO DEFINITIONS THAT ARE EASIEST TO GET WRONG:

  ERROR RATE = Incorrect / (Correct + Incorrect).  Uncertain is in NEITHER side.
      Incorrect / everything is a different, smaller, WRONG number, and it is the number anyone
      would write by accident. CLAUDE.md: "Uncertain verdicts are excluded from both numerator and
      denominator, with the % stated plainly."

  'Out of scope' IS NOT AN ERROR, and 'needs an analyst' is 'Miscategorised' ALONE.
      Folding 'Out of scope' in inflates every rate on the page. action_classify.py says so in the
      value's own description; this asserts the page agrees with it.

A test that only checked _ro() would leave those two free to drift, and they are the numbers a
manager reads.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor                                                          # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print("  {:<62} {}".format(name, "PASS" if ok else "FAIL  got %r want %r" % (got, want)))
    if not ok:
        FAIL.append(name)


def fmt(r):
    return monitor.fmt_rate(r)


def refuses(sql, why):
    try:
        monitor._ro(sql)
    except RuntimeError:
        print("  {:<62} PASS".format("refuses " + why))
        return
    print("  {:<62} FAIL  ** NOT REFUSED **".format("refuses " + why))
    FAIL.append(why)


def allows(sql, why):
    try:
        monitor._ro(sql)
        print("  {:<62} PASS".format("allows " + why))
    except RuntimeError as e:
        print("  {:<62} FAIL  {}".format("allows " + why, e))
        FAIL.append(why)


def main():
    print("=== the read-only guard: it must refuse anything that is not a plain SELECT ===")
    refuses("UPDATE qa_line SET NIM_VERDICT='Correct'", "a bare UPDATE")
    refuses("DELETE FROM qa_line", "a bare DELETE")
    refuses("DROP TABLE qa_line", "a bare DROP")
    refuses("TRUNCATE TABLE qa_line", "a TRUNCATE")
    refuses("ALTER TABLE qa_line ADD x int", "an ALTER")
    refuses("CREATE INDEX ix ON qa_line (CLIENT_CODE)", "a CREATE INDEX")
    refuses("EXEC sp_who", "an EXEC")
    refuses("BACKUP DATABASE x TO DISK='y'", "a BACKUP")
    refuses("GRANT db_owner TO Claude", "a GRANT")
    # 🔒 THE ONES THAT LOOK LIKE READS. Each of these BEGINS with SELECT, so a check that only
    # looked at the first word would wave all three through.
    refuses("SELECT * INTO scratch FROM qa_line", "SELECT ... INTO (starts with SELECT, WRITES)")
    refuses("SELECT 1; DROP TABLE qa_line", "a stacked statement after a SELECT")
    refuses("select client_code from qa_line; delete from qa_run", "lower case, stacked DELETE")
    refuses("SELECT\n  *\n  INTO  t\nFROM qa_line", "SELECT ... INTO split across lines")

    print("\n=== ...and it must NOT refuse the reads this file actually makes ===")
    allows("SELECT COUNT(*) FROM qa_line WITH (NOLOCK)", "a plain count")
    allows("SELECT DB_NAME()", "DB_NAME()")
    allows("""SELECT CLIENT_CODE, SUPPLIER_NAME, SUM(CAST(SPEND AS float))
              FROM qa_line WITH (NOLOCK) WHERE NIM_VERDICT='Incorrect'
              GROUP BY CLIENT_CODE, SUPPLIER_NAME ORDER BY COUNT(*) DESC""", "the vendor rollup")
    allows("""SELECT TOP 15 l.CLIENT_CODE, l.RULE_ID, MAX(r.RULES_TABLE), COUNT(*)
              FROM qa_line l WITH (NOLOCK) LEFT JOIN qa_rule r WITH (NOLOCK)
                ON r.RULE_ID=l.RULE_ID GROUP BY l.CLIENT_CODE, l.RULE_ID""", "the rule rollup")

    print("\n=== every statement monitor.py can issue passes its own guard ===")
    # 🔑 THE GUARD IS ONLY WORTH ANYTHING IF THE REAL QUERIES SATISFY IT. A blocklist that also
    # blocks the legitimate SQL gets loosened by whoever hits it next, and then it guards nothing.
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.py"),
               encoding="utf-8").read()
    body = src.split('"""', 2)[2]                       # skip the module docstring
    found = re.findall(r'q\(cur,\s*("""(?:.|\n)*?"""|"[^"]*")', body)
    print("  found {} q(cur, ...) call(s) in monitor.py".format(len(found)))
    check("at least the 9 known reads are present", len(found) >= 9, True)
    for i, raw in enumerate(found):
        sql = raw.strip('"')
        try:
            monitor._ro(sql)
        except RuntimeError as e:
            print("  query %d FAILS ITS OWN GUARD: %s\n     %s" % (i + 1, e, sql[:90]))
            FAIL.append("query %d" % (i + 1))
    if not any(f.startswith("query ") for f in FAIL):
        print("  {:<62} PASS".format("all of them pass _ro()"))

    print("\n=== error rate: Uncertain is in NEITHER numerator NOR denominator ===")
    # Melbourne's real pilot numbers, 2026-08-26: C 120, I 221, U 159, judged 500.
    C, I, U = 120, 221, 159
    check("error rate = I / (C + I)", monitor.pct(I, C + I), "64.8%")
    check("it is NOT I / judged", monitor.pct(I, C + I) != monitor.pct(I, C + I + U), True)
    check("uncertain is reported on its own", monitor.pct(U, C + I + U), "31.8%")
    check("a client with nothing judged shows an em dash, never 0%", monitor.pct(0, 0), "—")

    print("\n=== 'Out of scope' is NOT an error, and 'needs an analyst' is Miscategorised alone ===")
    check("ERROR_ACTIONS is exactly ('Miscategorised',)", tuple(monitor.ERROR_ACTIONS),
          ("Miscategorised",))
    check("'Out of scope' is NOT in ERROR_ACTIONS", "Out of scope" in monitor.ERROR_ACTIONS, False)
    check("'Re-mapped' is NOT in ERROR_ACTIONS", "Re-mapped" in monitor.ERROR_ACTIONS, False)
    check("'Incomplete' is NOT in ERROR_ACTIONS", "Incomplete" in monitor.ERROR_ACTIONS, False)
    check("all six actions are on the page", len(monitor.ACTIONS), 6)

    print("\n=== spend is signed, and a minus sign must survive formatting ===")
    check("a negative reads as negative", monitor.money(-5625000000.0), "-$5,625,000,000")
    check("a positive reads as positive", monitor.money(1469113957.26), "$1,469,113,957")
    check("zero", monitor.money(0), "$0")

    print("\n=== lines/min: THE BUG FOUND BY WATCHING A REAL JUDGE, 2026-08-26 ===")
    # 🔴 THE REGRESSION THIS SECTION EXISTS FOR, and it could not have been found any other way.
    # Four minutes into a live pilot run the page read "lines/min last 15 = 1" and "last 60 = 0"
    # WHILE THE JUDGE WAS VISIBLY WORKING - 22 lines in 4 minutes is 5.5/min. Two faults: dividing
    # by the NOMINAL window instead of the span the data actually covers, and integer rounding
    # turning a real rate into a displayed zero.
    #
    # A page that reads 0 lines/min on a healthy run is worse than no page at all - it is the
    # number someone checks to decide whether to go and restart the judge.
    from datetime import datetime as _dt, timedelta as _td
    now = _dt(2026, 8, 26, 13, 22, 35)
    four = now - _td(minutes=4)
    check("22 lines, 4 min into a run, is 5.5/min and NOT 1",
          fmt(monitor.rate(22, four, 15, now)), "5.5")
    check("...and on the 60-min window too, NOT 0",
          fmt(monitor.rate(22, four, 60, now)), "5.5")
    check("a full 15-min window divides by 15",
          fmt(monitor.rate(750, now - _td(minutes=15), 15, now)), "50")
    check("the window CAPS the span, it never exceeds it",
          fmt(monitor.rate(750, now - _td(minutes=60), 15, now)), "50")
    check("nothing judged in the window really is 0", fmt(monitor.rate(0, None, 15, now)), "0")
    check("a slow but REAL rate never displays as 0",
          fmt(monitor.rate(3, now - _td(minutes=10), 60, now)), "0.3")
    check("a fast rate carries no misleading decimal",
          fmt(monitor.rate(600, now - _td(minutes=10), 15, now)), "60")

    print("\n=== the stall clock ===")
    check("never judged", monitor.ago(None), "never")
    check("seconds", monitor.ago(0.5), "30 sec ago")
    check("minutes", monitor.ago(47.0), "47 min ago")
    check("hours", monitor.ago(600.0), "10.0 hours ago")

    print("\n=== the banner cannot be dropped by accident ===")
    # ⚠️ CASE-INSENSITIVE, and that is a deliberate loosening made on 2026-08-26 rather than a
    # convenience. The guarantee is that the banner still SAYS these things: "Largest vendors first"
    # at the head of a sentence carries it exactly as well as "largest vendors first" mid-clause.
    #
    # 🔑 This test caught a wording tidy-up that had capitalised one of them, which is precisely
    # what it is for. But a test that fails on capitalisation trains whoever hits it to edit the
    # test, and then it guards nothing at all. What it must NEVER tolerate is a phrase going
    # missing, and that is what it still checks.
    for phrase in ("INTERNAL", "largest vendors first", "not client-facing"):
        check("banner still says %r" % phrase, phrase.lower() in monitor.BANNER.lower(), True)

    if FAIL:
        print("\n** {} FAILED **  {}".format(len(FAIL), ", ".join(FAIL)))
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
