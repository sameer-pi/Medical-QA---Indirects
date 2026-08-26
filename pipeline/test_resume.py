#!/usr/bin/env python
"""Tests for the resume skip in nim_judge.py. NO DATABASE - every case here is pure.

    python pipeline/test_resume.py

WHY THIS FILE EXISTS. On a restart the judge skips vendors that are already finished, which turns
2.70 hours of re-probing into 0.41 seconds (measured on production 2026-08-26: 29,469 vendors,
0.18s per probe, two probes each). The saving is worth having. THE FAILURE MODE IS NOT.

  skipping too FEW vendors   costs time, and is visible on the page.
  skipping too MANY          means lines are never judged, the fix queue comes back short, and
                             NOTHING LOOKS BROKEN. It reads as "nothing to fix there".

Those two are not symmetrical, so every case below asks the same question: WHEN IT CANNOT TELL,
DOES IT JUDGE? Three ways it could fail to tell, and all three must answer yes:

  1. the resume scan itself failed          -> sets is None
  2. the queue holds a vendor the scan never saw (a name that did not match, the trailing-space
     lesson that let 524,923 clinical lines through a pandas gate)
  3. --topup: the vendor IS fully judged, but by a hollowed-out jury. emit_batch has FOUR arms and
     only arm 1 is `NIM_VERDICT IS NULL`; arm 4 finds NIM_MODELS_RESPONDED < 3. A skip built on
     arm 1 alone walks past every thin-jury line on a --topup run. MEASURED on the pilot: a normal
     resume finds 0 vendors with work, --topup finds 18 - holding 32 thin lines that would
     otherwise have been silently abandoned.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nim_judge                                                        # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print("  {:<66} {}".format(name, "PASS" if ok else "FAIL  got %r want %r" % (got, want)))
    if not ok:
        FAIL.append(name)


def main():
    open_v = ("northern_health", "ATO")
    done_v = ("northern_health", "CITYLINK")
    live = {open_v}
    known = {open_v, done_v}
    sets = (live, known)

    print("=== the ordinary case: skip the finished, keep the unfinished ===")
    check("a vendor with work is judged", nim_judge._still_open(sets, *open_v), True)
    check("a vendor with no work is skipped", nim_judge._still_open(sets, *done_v), False)

    # NOTE: no emoji in PRINTED output - this console is cp1252 and dies on them. Comments only.
    print("\n=== WHEN IT CANNOT TELL, IT JUDGES. All three ways of not being able to tell ===")
    check("1. the resume scan failed entirely -> judge everything",
          nim_judge._still_open(None, *done_v), True)
    check("2. a queue name the scan never saw -> judge it, never assume done",
          nim_judge._still_open(sets, "northern_health", "A NAME THAT DID NOT MATCH"), True)
    check("   ...and that holds for a name differing only by a trailing space",
          nim_judge._still_open(sets, "northern_health", "CITYLINK "), True)
    check("   ...and by case, because Python's == is not SQL's",
          nim_judge._still_open(sets, "northern_health", "citylink"), True)

    print("\n=== the vendor with NO NAME is a real vendor, not a missing one ===")
    # SUPPLIER_NAME IS NULL is a whole population - judge.NO_VENDOR_NAME selects it. If None were
    # mishandled here it would be skipped for ever on every resume, silently.
    nul = ("western_health", None)
    check("None is judged when it has work", nim_judge._still_open(({nul}, {nul}), *nul), True)
    check("None is skipped when it does not", nim_judge._still_open((set(), {nul}), *nul), False)
    check("None is NOT confused with a vendor literally called 'None'",
          nim_judge._still_open(({nul}, {nul}), "western_health", "None"), True)

    print("\n=== the same name at two hospitals is two vendors ===")
    # A rule ID names independent COPIES; so does a vendor. Skipping Melbourne's because
    # Northern's is done would abandon a whole hospital's lines for that supplier.
    both = {("melbourne_health", "TELSTRA")}
    check("melbourne has work -> judged",
          nim_judge._still_open((both, both | {("northern_health", "TELSTRA")}),
                                "melbourne_health", "TELSTRA"), True)
    check("northern is done   -> skipped, independently",
          nim_judge._still_open((both, both | {("northern_health", "TELSTRA")}),
                                "northern_health", "TELSTRA"), False)

    print("\n=== --topup must WIDEN the search, never narrow it ===")
    # Read the SQL rather than trusting the docstring: the thin-jury term must be ADDED to the
    # unjudged term, so a fully-judged vendor with a hollowed-out jury still counts as having work.
    import inspect
    whole = inspect.getsource(nim_judge.vendors_with_work)
    # THE DOCSTRING IS STRIPPED, and that is not a detail. It NAMES QUEUE_STATUS in order to
    # explain why the column is not used - so a check against the whole source would read the
    # explanation as the offence. Ask the executable code, never the prose about it.
    src = whole.split('"""', 2)[2]
    check("the thin-jury term exists", "NIM_MODELS_RESPONDED < 3" in src, True)
    check("it is ADDED to the unjudged count, not substituted for it",
          "+ SUM(CASE WHEN NIM_MODELS_RESPONDED < 3" in src, True)
    check("and it is gated on topup, so a normal resume is unchanged",
          "if topup else" in src, True)
    check("the authority is NIM_VERDICT on the line, never QUEUE_STATUS",
          "QUEUE_STATUS" in src, False)
    check("...and NIM_VERDICT IS NULL really is what it asks",
          "NIM_VERDICT IS NULL" in src, True)

    print("\n=== the skip is applied AFTER --top, so the slice keeps its meaning ===")
    # --top 100 names a FIXED SET - the hundred biggest vendors. Filtering before it would refill
    # the slice with vendors 101, 102, 103... so the same command would judge a different
    # population on a resume than on the first run, and nothing would say so.
    for fn in (nim_judge.judge_queue, nim_judge.judge_global):
        body = inspect.getsource(fn)
        i_top = body.index("vendors[:top]")
        i_skip = body.index("vendors_with_work")
        check("{}: top slices first, skip filters second".format(fn.__name__), i_top < i_skip, True)

    if FAIL:
        print("\n** {} FAILED **  {}".format(len(FAIL), ", ".join(FAIL)))
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
