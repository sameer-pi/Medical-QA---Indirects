#!/usr/bin/env python
"""Score the CURRENT judge run against Sameer's human answers. The first real regression test.

    python pipeline/score_answer_key.py

WHY THIS EXISTS. Every accuracy figure this project produced before 2026-08-17 was the judge
marking its own homework - "58% accurate" meant "the judge agreed with the rule 58% of the time",
which says nothing about whether the JUDGE was right. On 2026-08-17 Sameer answered 76
Miscategorised decisions BLIND (our verdict and destination hidden), writing his own destination for
50 of them. Those 50 are a human ground truth, and this script measures every future run against
them.

🔒 IT READS THE REVIEW LAYER, NOT THE WORKBOOK. His answers are stored on 94 specific QA_LINE_IDs in
REVIEW_OVERRIDE_CATEGORY. The workbook grouped lines by (vendor, item, filed path, OUR SUGGESTION) -
and our suggestion changes on every re-judge, so re-deriving those groups would silently re-key his
answers to different lines. The line ID does not move.

⚠️ WHAT THIS CAN AND CANNOT TELL YOU. It measures agreement with ONE reviewer on ONE slice - the
3of3 Miscategorised set. It is not a general accuracy figure and must never be quoted as one. What
it IS good for: whether a change moved the judge TOWARD or AWAY from a human, which is the question
no self-consistency measure can answer.
"""
import os
import re
import sys
from collections import Counter

# This script prints ⚠️ and 🔒. A PowerShell console here is cp1252, which cannot encode them, and
# the crash landed on the LAST line - after every figure had printed, so it looked like a clean run
# that had merely fallen over on the way out. run_generation.py never saw it because it forces
# PYTHONIOENCODING=utf-8 on its children; typing the command by hand, which is what the session-start
# instructions say to do, did. Found 2026-08-18.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:      # not a real stream (piped, captured, redirected)
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import connect_qa, load_env  # noqa: E402

# Answers that are not a destination. "don't know" is an honest answer and is counted separately -
# folding it into either side would be inventing a ruling he did not give.
DK = ("don't know", "dont know", "don’t know", "not sure")
NEW_CAT = ("need a level", "need a category", "we need")


def norm(s):
    """Compare MEANING, not punctuation - the same normaliser action_classify uses, so a match here
    and a match there mean the same thing."""
    s = (s or "").strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"s\b", "", s)


def agree(his, ours_levels):
    """Did his free-text destination land on the category we suggested?

    His answers are typed by a person - 'cleaning janitorial supplies', 'EGGS', 'stationery' - so
    exact string equality would report near-total disagreement on wording alone. The test is
    whether his words match the LEAF or its parent once normalised, in either direction, because
    'stationery' is a fair way to write 'Stationery & Printing' and 'EGGS' is a fair way to write
    'Egg'.

    Returns 'leaf' | 'branch' | 'differs'.
    """
    h = norm(his)
    if not h:
        return "differs"
    lv = [norm(x) for x in ours_levels if x and "not used" not in x.lower()]
    if not lv:
        return "differs"
    leaf, parent = lv[-1], (lv[-2] if len(lv) > 1 else "")
    for cand in (leaf, parent):
        if cand and (h == cand or h in cand or cand in h):
            return "leaf" if cand == leaf else "branch"
    # a shared distinctive word - 'juice' in 'Juice', 'milk' in 'Milk' - anywhere in the path
    hw = set(h.split())
    for i, seg in enumerate(lv):
        if hw & set(seg.split()):
            return "leaf" if i == len(lv) - 1 else "branch"
    return "differs"


def main():
    qa = connect_qa(pilot=True, env=load_env())
    c = qa.cursor()
    c.execute("SELECT COUNT(DISTINCT run_id) FROM qa_line")
    if c.fetchone()[0] != 1:
        raise SystemExit("  qa_line holds more than one run_id. STOP.")

    c.execute("""SELECT QA_LINE_ID, CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION,
                        REVIEW_OVERRIDE_CATEGORY, REVIEW_NOTE, REVIEW_STATUS,
                        NIM_SUGGESTED_CATEGORY_LVL_1, NIM_SUGGESTED_CATEGORY_LVL_2,
                        NIM_SUGGESTED_CATEGORY_LVL_3, NIM_SUGGESTED_CATEGORY_LVL_4,
                        NIM_VERDICT, NIM_ACTION, NIM_AGREEMENT, NIM_PROMPT_VERSION,
                        CATEGORY_LVL_1, CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4
                 FROM qa_line WHERE REVIEW_STATUS IS NOT NULL
                 ORDER BY CLIENT_CODE, SUPPLIER_NAME""")
    rows = c.fetchall()
    if not rows:
        raise SystemExit("  no reviewed lines - ingest an answer key first "
                         "(make_answer_key.py --ingest)")

    ver = {r[14] for r in rows}
    print(f"scoring {len(rows)} reviewed lines against PROMPT_VERSION {', '.join(sorted(map(str, ver)))}\n")

    tally, per_client, differs, dk, newcat, nosug = Counter(), {}, [], [], [], []
    nochange = 0
    for r in rows:
        his, note = (r[4] or "").strip(), (r[5] or "").strip()
        blob = (his + " " + note).lower()
        if any(d in blob for d in DK):
            dk.append(r)
            continue
        if any(n in blob for n in NEW_CAT):
            newcat.append(r)
            continue
        if not his:
            continue                       # 'B' with no destination - nothing to compare
        ours = r[7:11]
        # 🔒 A `Correct` VERDICT HAS A DESTINATION - IT IS THE ONE THE LINE IS ALREADY FILED
        # UNDER. Found 2026-08-18 on qa_line 826490: BIDFOOD "PUREED BUTTER CHICKEN", filed under
        # Poultry, we said Correct / No change, and Sameer independently answered "Poultry" - and
        # this script counted it as "we now give NO destination" and printed it as a REGRESSION.
        # It is the opposite: it is exact agreement.
        #
        # 🔑 THE SCORER WAS COMPARING HIS ANSWER AGAINST AN EMPTY FIELD RATHER THAN AGAINST OUR
        # ACTUAL ANSWER. NIM_SUGGESTED_KEY is deliberately NULL when we agree with the existing
        # category (PLAN v3.44 change 240) - so on every line we got RIGHT BY LEAVING IT ALONE, the
        # measurement scored us as having said nothing. That understates agreement and inflates the
        # regression count - the worst direction for a number meant to be a yardstick.
        if not any(ours) and (r[11] or "").strip() == "Correct":
            ours = r[15:19]
            nochange += 1
        if not any(ours):
            nosug.append(r)
            tally["we now give NO destination"] += 1
            per_client.setdefault(r[1], Counter())["no destination"] += 1
            continue
        v = agree(his, ours)
        tally[v] += 1
        per_client.setdefault(r[1], Counter())[v] += 1
        if v == "differs":
            differs.append((r, his))

    scored = tally["leaf"] + tally["branch"] + tally["differs"] + tally["we now give NO destination"]
    print("=== AGREEMENT WITH SAMEER'S BLIND ANSWERS ===")
    for k in ("leaf", "branch", "differs", "we now give NO destination"):
        n = tally[k]
        label = {"leaf": "same LEAF - his answer is ours",
                 "branch": "same BRANCH, different leaf",
                 "differs": "genuinely different",
                 "we now give NO destination": "we now give NO destination"}[k]
        print(f"   {label:<34} {n:>4}" + (f"   {n/scored*100:5.1f}%" if scored else ""))
    if scored:
        print(f"\n   LEAF-level agreement   {tally['leaf']/scored*100:5.1f}%")
        print(f"   BRANCH-level agreement {(tally['leaf']+tally['branch'])/scored*100:5.1f}%")
    print(f"\n   excluded: {len(dk)} 'don't know'  |  {len(newcat)} new-category requests")
    if nochange:
        print(f"   of those, {nochange} scored against the FILED category - we said Correct, "
              f"so where it already sits IS our answer")

    print("\n=== per client ===")
    for cl in sorted(per_client):
        t = per_client[cl]
        tot = sum(t.values())
        print(f"   {cl:<18} n={tot:<4} leaf={t['leaf']:<4} branch={t['branch']:<4} "
              f"differs={t['differs']:<4} none={t['no destination']}")

    if differs:
        print(f"\n=== WHERE WE STILL DISAGREE WITH HIM ({len(differs)}) ===")
        for r, his in differs[:25]:
            ours = " > ".join(x for x in r[7:11] if x and "not used" not in x.lower())
            print(f"   [{r[0]}] {str(r[2])[:30]:<32} {str(r[3])[:44]}")
            print(f"        he says : {his}")
            print(f"        we say  : {ours[:88]}")
    if nosug:
        print(f"\n⚠️  {len(nosug)} lines he gave a destination for now carry NO suggestion from us.")
        print("    That is a REGRESSION - he answered them, so they are answerable.")
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
