#!/usr/bin/env python
"""Unit tests for the NIM_ACTION decision table and the rationale key-recovery backstop.

Run:  python pipeline/test_classify.py     (exit 0 = all pass)

WHY THIS EXISTS. Every defect in this classifier so far was found by Sameer READING THE DATA -
135 Re-mapped rows with no destination, then 73 answered lines mislabelled Needs evidence. Both
were invisible to every check we had, and both are one-line assertions here. The decision table is
pure logic over a tuple, so it needs no database and no judge: there is no excuse for testing it
by running the pipeline and looking.

The two "refuse" cases in key_from_rationale are the important ones. A backstop that guesses is
worse than no backstop, because a wrong destination in a field an analyst acts on is invisible
while a blank one is not.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from action_classify import classify, key_from_rationale, ACTIONS, OUT_OF_SCOPE_L0
cross = {("melbourne_health","379"): ("NC-0100", True),
         ("melbourne_health","500"): ("NC-0200", False)}
U = "Uncategorised"
cases = [
  # (name, row(client,taxkey,l1..l4,verdict,suggested), sug_l0, expected)
  ("uncategorised line judged CLINICAL -> Out of scope",
   ("melbourne_health","500",U,U,U,U,"Uncertain","CL-0001"), "Clinical", "Out of scope"),
  ("uncategorised, clinical suggestion, verdict Incorrect -> still Out of scope",
   ("melbourne_health","500",U,U,U,U,"Incorrect","CL-0001"), "Clinical", "Out of scope"),
  ("Non-Procurement suggestion is IN scope -> not Out of scope",
   ("melbourne_health","500","Fleet","x","y","z","Incorrect","NP-0005"), "Non-Procurement", "Miscategorised"),
  ("plain Uncertain, no suggestion -> Needs evidence",
   ("melbourne_health","500",U,U,U,U,"Uncertain",None), None, "Needs evidence"),
  ("Incorrect, no destination -> Needs evidence",
   ("melbourne_health","500","Fleet","x","y","z","Incorrect",None), None, "Needs evidence"),
  ("Incorrect WITH destination -> Miscategorised",
   ("melbourne_health","500","Fleet","x","y","z","Incorrect","NC-0270"), "Non-Clinical", "Miscategorised"),
  ("Correct + crosswalk moved -> Re-mapped",
   ("melbourne_health","379","Fleet","x","y","z","Correct",None), None, "Re-mapped"),
  ("Correct, nothing moved -> No change",
   ("melbourne_health","500","Fleet","x","y","z","Correct",None), None, "No change"),
  ("placeholder path -> Incomplete",
   ("melbourne_health","500","Food","Not Yet Categorized","Not Yet Categorized","Not Yet Categorized","Incorrect","NC-0110"), "Non-Clinical", "Incomplete"),
]
bad = 0
for name, row, l0, exp in cases:
    got, _ = classify(row, cross, suggested_l0=l0)
    ok = got == exp
    bad += not ok
    print(f"  {'ok ' if ok else '** FAIL'} {name:<58} -> {got}" + ("" if ok else f"   expected {exp}"))

print("\n=== key_from_rationale ===")
valid = {"NC-0028","NC-0270","NC-0110"}
kc = [("belongs to Nursing Staff (NC-0028)", "NC-0028"),
      ("could be NC-0028 or NC-0270", None),          # ambiguous -> refuse
      ("mentions NC-9999 which is not real", None),   # unknown key -> refuse
      ("no key at all, just prose about Milk", None), # prose -> refuse, by design
      ("", None), (None, None)]
for txt, exp in kc:
    got = key_from_rationale(txt, valid)
    ok = got == exp
    bad += not ok
    print(f"  {'ok ' if ok else '** FAIL'} {str(txt)[:44]:<46} -> {got}")
print(f"\n{len(cases)+len(kc)} cases, {bad} failures")
print("actions defined:", list(ACTIONS), "| out-of-scope L0:", OUT_OF_SCOPE_L0)
sys.exit(1 if bad else 0)
