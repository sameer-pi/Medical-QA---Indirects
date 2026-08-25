"""test_coverage.py - prove the COVERAGE check fires. No database, no network.

WHY THIS EXISTS. On 2026-08-25 the jury dropout check was a COUNT: "did the model send back as
many answers as we sent lines?" It passed on a real failure - openai/gpt-oss-120b returned 8, 8
and 7 verdicts for batches of 8, 8 and 7, and EIGHT of those 23 lines still ended up with two
votes instead of three. `parse()` returns {line_id: verdict}, so answers about line_ids we never
sent make the arithmetic work out while lines go unanswered. Finding 124.

🔑 A COUNT PROVES THE ARITHMETIC. ONLY THE ID SET PROVES THE COVERAGE.

TRACKER carried two earlier dropout fixes as "built and unproven - nothing failed on the day they
were written". This file is the answer to that: every case below MAKES a model misbehave, so the
check is proven to fire rather than assumed to. A guard nobody has watched fail is not a guard.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nim_judge  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print("  %-56s %s" % (name, "PASS" if ok else "FAIL  got %r want %r" % (got, want)))
    if not ok:
        FAILURES.append(name)


def run_batch(units, model_answers):
    """Drive ask_models with `call` stubbed out. Returns (per_model, dead, covered, output).

    model_answers is one list of line_ids per model - what that model CLAIMS to have answered
    about. None means the request failed outright.
    """
    payload = {"units": units}
    used = ["model-a", "model-b", "model-c"]
    seq = list(model_answers)

    def fake_call(env, model, pl, timeout=None):
        ids = seq[used.index(model)]
        if ids is None:
            raise RuntimeError("simulated total failure")
        return {int(i): {"line_id": i, "verdict": "Correct", "confidence": 0.9,
                         "basis": "vendor_and_description", "suggested_key": None,
                         "rationale": "x"} for i in ids}

    real_call, real_sleep = nim_judge.call, nim_judge.time.sleep
    nim_judge.call = fake_call
    nim_judge.time.sleep = lambda *_a, **_k: None      # no back-off pauses in a test
    buf, real_stdout = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        per_model, dead, covered = nim_judge.ask_models({}, used, payload, tag="", redrive=0)
    finally:
        sys.stdout = real_stdout
        nim_judge.call, nim_judge.time.sleep = real_call, real_sleep
    return per_model, dead, covered, buf.getvalue()


def main():
    units = [{"line_id": i} for i in range(1, 9)]          # eight lines: 1..8
    all_ids = list(range(1, 9))

    print("\n=== 1. the happy path - every model answers about every line ===")
    _, dead, covered, out = run_batch(units, [all_ids, all_ids, all_ids])
    check("all 8 lines have 3 votes", sorted(covered.values()), [3] * 8)
    check("nothing reported as dead", dead, [])
    check("no COVERAGE warning printed", "COVERAGE:" in out, False)
    check("no LOSE THIS MODEL warning printed", "LOSE THIS MODEL" in out, False)

    print("\n=== 2. THE DEFECT THAT GOT THROUGH - right COUNT, wrong LINES ===")
    # model-b answers EIGHT times, so the old count check saw 8 == 8 and said nothing.
    # But two of its ids (99, 100) were never in the batch, so lines 7 and 8 lose it.
    wrong = [1, 2, 3, 4, 5, 6, 99, 100]
    _, dead, covered, out = run_batch(units, [all_ids, wrong, all_ids])
    check("the model returned the RIGHT NUMBER of answers", len(wrong), len(units))
    check("...and yet line 7 has only 2 votes", covered[7], 2)
    check("...and line 8 has only 2 votes", covered[8], 2)
    check("lines 1-6 still have 3 votes", [covered[i] for i in range(1, 7)], [3] * 6)
    check("** the check FIRES: names the lines that lost the model", "LOSE THIS MODEL" in out, True)
    check("** it names line 7 specifically", ": 7," in out or ": 7 " in out, True)
    check("** invented line_ids are reported separately", "NOT IN THIS BATCH" in out, True)
    check("** batch-level COVERAGE line printed, no model having failed",
          "COVERAGE:" in out, True)
    check("no model is reported dead - they all answered", dead, [])

    print("\n=== 3. a model simply omits lines (short answer) ===")
    _, dead, covered, out = run_batch(units, [all_ids, [1, 2, 3], all_ids])
    check("5 lines dropped to 2 votes", sum(1 for n in covered.values() if n == 2), 5)
    check("the check names them", "LOSE THIS MODEL" in out, True)
    check("no false 'NOT IN THIS BATCH' - it invented nothing",
          "NOT IN THIS BATCH" in out, False)

    print("\n=== 4. a model fails outright - the OLD path, still works ===")
    _, dead, covered, out = run_batch(units, [all_ids, None, all_ids])
    check("model-b reported dead", dead, ["model-b"])
    check("every line has 2 votes", sorted(covered.values()), [2] * 8)
    check("no COVERAGE line - a dead model explains its own gap",
          "COVERAGE:" in out, False)

    print("\n=== 5. all three fail ===")
    _, dead, covered, out = run_batch(units, [None, None, None])
    check("all three dead", dead, ["model-a", "model-b", "model-c"])
    check("no line has any vote", sorted(set(covered.values())), [0])

    total = 5
    print("\n%d groups, %d checks failed" % (total, len(FAILURES)))
    if FAILURES:
        for f in FAILURES:
            print("   FAILED: %s" % f)
        return 1
    print("ALL COVERAGE CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
