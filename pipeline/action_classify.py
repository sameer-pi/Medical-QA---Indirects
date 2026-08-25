"""NIM_ACTION - what to DO about a verdict, as opposed to what the verdict SAYS.

WHY THIS EXISTS. Sameer, 2026-08-14: *"so let the verdict be incorrect, correct and uncertain, and
we insert a new col just next to the verdict call it action ... will this help the analyst and avoid
any confusion?"* It will, and the confusion it removes is one WE created. We replaced four hospital
taxonomies with one merged tree, so a category can have a new address without the hospital having
done anything wrong. Measured 2026-08-14: 248 pilot lines (12.4%) sit under a level-1 branch the
merge moved or renamed - `Rates, Taxes and Adjustments` is now three levels down under Corporate
Services, `General Admin Supplies` sits under Corporate Services, `Maintenance, Repairs and
Operations` under Facilities Management. 28% of those lines came back Incorrect.

**Telling a hospital it misfiled spend when in fact WE moved the shelf is a false finding.** The
verdict cannot carry that distinction - it answers "was this right", and both cases can answer no.
So the action carries it, beside the verdict, never instead of it.

THE ACTION IS DERIVED FROM THE CROSSWALK, NOT ASKED OF A MODEL. "Is this a rename or a real error"
has a factual answer sitting in `Indirect Taxonomy - CROSSWALK - <date>.csv`, which maps every old
hospital path to its new home. Ask a model and you get a judgement call on a question of fact, and
an inconsistent one across a 2,000-row file. This module is a lookup and a decision table: same
input, same answer, every time, and anyone can check it by hand.

WRITES ONE COLUMN AND NOTHING ELSE. `qa_line.NIM_ACTION`. No new table (Sameer: *"any writing into
sql strictly do it in only qa_line"*), no new rows (*"can never have more than 2000 rows"*), and it
does not touch a verdict, a confidence, a rationale or a suggestion - our layer stays written-once.
Re-running recomputes the column from scratch, which is safe precisely because it derives from the
crosswalk rather than accumulating.

    python pipeline/action_classify.py            # classify, then report
    python pipeline/action_classify.py --report   # report only, writes nothing
"""
import argparse
import csv
import glob
import os
import re
import sys

# 🔒 FORCE UTF-8 ON OUR OWN STREAMS. Fourth instance of this defect, and this one I introduced
# MYSELF on 2026-08-24 - hours after documenting it - by adding a ⭐ to the new self-contradiction
# check. run_generation sets PYTHONIOENCODING for its children, so it never fails when driven from
# there; run standalone under a cp1252 console it dies AFTER doing the work and before reporting it.
# 🔑 The sweep on 2026-08-21 concluded "exactly two files print high codepoints, both protected".
# That was true when it ran and stopped being true the moment someone wrote a new print. A sweep is
# a snapshot; a guard at the top of the file is the fix.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import connect_qa, load_env  # noqa: E402
from load_taxonomy import MERGED_CLIENT  # noqa: E402
from merge_taxonomy import canonical  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CROSSWALK_GLOB = os.path.join(HERE, "output", "Taxonomy", "*CROSSWALK*.csv")

# THE FIVE ACTIONS. Sameer, 2026-08-14: *"at a later point im going to forget what the actions
# actually mean, so make a note so we dont leak any knowledge."* This dict IS that note, and it is
# the only definition - the reporting below prints it, so the meaning travels with the numbers.
ACTIONS = {
    "No change": "Filed correctly and completely. Nothing for anyone to do.",
    "Re-mapped": "Filed correctly - but WE moved the category. The hospital did nothing wrong. "
                 "Bulk-approvable: this is a migration, not a decision.",
    "Incomplete": "Never finished. Either no category at all, or a top level with placeholders "
                  "below it. We have filled in the detail. A gap, not an error.",
    "Miscategorised": "Genuinely in the wrong branch, and we say where it belongs. THIS is the "
                      "queue that deserves an analyst's judgement.",
    "Needs evidence": "We cannot act. Either the evidence did not settle it (Uncertain), or we "
                      "know it is wrong but cannot say where (Incorrect with no destination).",
    # 🔒 SIXTH VALUE, added 2026-08-17. Sameer chose five; this is a sixth and he can strike it with
    # one word. It exists because 73 lines were being reported as `Needs evidence` when the judge
    # had in fact answered them clearly.
    #
    # THE MISTAKE WAS MINE AND IT WAS A DIAGNOSIS ERROR, not a code one. I reported these 73 to
    # Sameer as a defect - "suggestions pointing at Clinical, not a destination an analyst can use".
    # They are nothing of the kind. They are the DESIGNED behaviour: an uncategorised line is shown
    # the client's FULL taxonomy precisely so it can be filed as clinical, because that is how a
    # line gets recorded as outside this programme (judge.py, and Sameer 2026-08-05). All 73 sit on
    # uncategorised lines; ZERO sit on a line that already had a category.
    #
    # So the suggestion was right and the LABEL was wrong. "Needs evidence" tells an analyst to go
    # and find information that already exists, on a line where the answer is "this is clinical -
    # it is not ours". That is the worst kind of queue item: work that looks real and is not.
    "Out of scope": "Not an indirect line at all. The judge placed it in a Clinical branch, which "
                    "is outside this programme. Nothing to fix - it is a scope finding, and the "
                    "hospital's clinical categorisation owns it. Do NOT count these as errors.",
}

# Level 0 values that put a line outside the indirect programme. `Non-Procurement` is NOT one of
# them - it is in scope and identifies the accounting-noise reporting segment (PLAN.md).
OUT_OF_SCOPE_L0 = {"clinical", "inter-hospital spend"}

# A taxonomy key as the models write it in prose: NC-0270, NP-0005, CL-0001.
KEY_IN_TEXT = re.compile(r"\b([A-Z]{2,4}-\d{3,5})\b")

# `Category level markers are conditional on Level 0, not per level` - PLAN.md. A level 0 that is
# empty makes ALL levels read Uncategorised; a real category with a short path reads
# `(not used at this level)`. Both mean "nothing was decided here", and so do the hospitals' own
# placeholder strings. Matched case-insensitively on the STRIPPED value.
PLACEHOLDERS = {
    "", "uncategorised", "uncategorized", "not yet categorized", "not yet categorised",
    "not categorised", "not categorized", "(not used at this level)", "none", "n/a",
}


def norm(s):
    """Compare MEANING, not punctuation. `Food and Beverage` and `Food & Beverages` are the same
    branch spelled two ways, and treating them as different would manufacture false findings."""
    s = (s or "").strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"s\b", "", s)


def norm_path(p):
    """Normalise a WHOLE path for the moved-or-not test.

    `canonical()` first, and this is the difference between a real finding and a false one.
    `PLAN.md`: canonical() is the single truth for identity, pad_to_four() is display-only padding.
    Measured 2026-08-14: comparing the PADDED strings reported
        Logistics > Transport > Patient Transport
     -> Logistics > Transport > Patient Transport > Patient Transport
    as a re-map. It is the same category with its leaf repeated to fill four levels - nothing moved,
    and every such line would have carried a migration note telling an analyst to check a change
    that never happened.

    A genuine insertion still shows, and should:
        Fleet and Vehicles > Parking & Tolls
     -> Fleet and Vehicles > Fleet Operating Costs > Parking & Tolls
    """
    segs = [s.strip() for s in (p or "").split(">") if s and s.strip()]
    return " > ".join(norm(s) for s in canonical(segs))


def is_placeholder(v):
    return (v or "").strip().lower() in PLACEHOLDERS


def newest_crosswalk():
    hits = sorted(glob.glob(CROSSWALK_GLOB))
    if not hits:
        raise SystemExit(f"  no CROSSWALK csv found under {CROSSWALK_GLOB}")
    return hits[-1]


def load_crosswalk(path):
    """(client_code, source_key) -> (target_key, moved). `moved` says the CATEGORY changed address
    in the merge, independently of anything the judge thought."""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["CLIENT_CODE"].strip(), str(row["SOURCE_KEY"]).strip())
            src, tgt = row.get("SOURCE_PATH_CANONICAL", ""), row.get("TARGET_PATH", "")
            moved = bool(tgt) and norm_path(src) != norm_path(tgt)
            out[key] = (row.get("TARGET_INDIRECT_KEY", "").strip(), moved)
    return out


def classify(row, cross, suggested_l0=None):
    """The decision table. ORDER MATTERS and each rule states why it sits where it does.

    row: (client, tax_key, l1..l4, verdict, suggested_key)
    suggested_l0: the LEVEL 0 of the suggested category, for the scope test in rule 0.

    Returns (action, fill_key) where fill_key is a category key to WRITE INTO the suggestion
    columns when the judge left them empty, or None. See rule 5 for why that is needed.
    """
    client, tax_key, l1, l2, l3, l4, verdict, suggested = row
    tgt_key, moved = cross.get((client, str(tax_key).strip()), (None, False))

    # 0. OUT OF SCOPE BEATS EVERYTHING, INCLUDING Uncertain - and it has to sit above rule 1 for
    #    exactly that reason. These lines carry verdict Uncertain (an uncategorised line has no
    #    category to be right or wrong about, so the verdict never moves), but the judge DID answer:
    #    it named a clinical leaf. Letting rule 1 catch them first labelled 73 answered lines
    #    "Needs evidence" and sent an analyst hunting for evidence that was already in the row.
    if suggested and (suggested_l0 or "").strip().lower() in OUT_OF_SCOPE_L0:
        return "Out of scope", None

    # 1. Uncertain next. If the evidence did not settle whether the line is right, nothing further
    #    can be said about what to do with it - including whether it was re-mapped.
    if verdict == "Uncertain":
        return "Needs evidence", None

    # 2. Incorrect with nowhere to send it. 302 of 614 Incorrect verdicts in the pilot. Folding
    #    these into Miscategorised would put rows an analyst CANNOT ACT ON into the queue that is
    #    supposed to be actionable, which is the whole point of separating the two.
    if verdict == "Incorrect" and not suggested:
        return "Needs evidence", None

    # 3. Never finished - checked BEFORE any judgement about right or wrong branch, because a path
    #    of placeholders is not a wrong answer, it is an absent one. Level 1 is the test: level 0 is
    #    the scope gate and is never a categorisation decision.
    #    NO fill_key: for an Incomplete line we do NOT know where it belongs - the crosswalk maps a
    #    category, and this line has not got one. Only the judge can answer, and if it did not, the
    #    blank is honest.
    if all(is_placeholder(v) for v in (l1, l2, l3, l4)) or (
            not is_placeholder(l1) and all(is_placeholder(v) for v in (l2, l3, l4))):
        return "Incomplete", None

    # 4. The jury points exactly where the crosswalk already maps this category. That is not the
    #    hospital misfiling anything - it is our merge giving the same shelf a new address.
    #    The judge supplied the destination here, so nothing needs filling.
    if suggested and tgt_key and suggested.strip() == tgt_key:
        return "Re-mapped", None

    # 5. Correct, but the category itself moved in the merge. The line is right and its address
    #    still changed, and the analyst needs to see that without it reading as an error.
    #
    #    🔒 AND WE MUST SAY WHERE IT MOVED TO. Sameer, 2026-08-17, on line 825152 (Bunzl): *"why is
    #    my suggested category blank ... if Verdict is correct and Nim action is remapped why have
    #    you left those blanks, it should be filled in from a category from our new indirect
    #    taxonomy."* He is right, and the omission was mine.
    #
    #    THE CAUSE, so it is not repeated: I treated the suggestion columns as belonging to the
    #    JUDGE - "what the model recommends". But a judge that answers Correct offers no suggestion,
    #    because there is nothing to correct. So every row reaching this rule had an empty
    #    destination, and I never noticed because rule 4's rows - where the judge DID speak - looked
    #    fine. **135 of 167 Re-mapped rows carried "this category moved" without saying where to**,
    #    which is most of the useful information missing.
    #
    #    For a Re-mapped row the destination NEVER came from the judge in the first place. It comes
    #    from the crosswalk, which is a fact we already hold. Filling it is a lookup, not a verdict,
    #    so it does not touch the judge's layer - it completes a row the judge was never asked about.
    if verdict == "Correct" and moved:
        return "Re-mapped", tgt_key

    # 6. Wrong branch, and we can say where it belongs. The real finding.
    if verdict == "Incorrect":
        return "Miscategorised", None

    # 7. Correct, nothing moved.
    return "No change", None


def key_from_rationale(rationale, valid_keys, assigned_key=None):
    """Recover a destination the judge WROTE OUT but failed to put in suggested_key.

    Measured on the v4.1 run: 249 of 519 Incorrect verdicts carried no destination, and 43 of them
    spelled a taxonomy key in the rationale - "belongs to Nursing Staff (NC-0028)". That is not an
    inference, it is a value the judge stated; moving it into the field it belongs in is a LOOKUP,
    the same standing as filling a Re-mapped destination from the crosswalk. It never overrides a
    key the judge did supply.

    🔒 EXACT KEYS ONLY. 68 more rationales name the right category in PROSE with no key, and those
    are deliberately NOT recovered. Matching a leaf name inside a sentence is a guess: "Milk"
    appears in rationales that are not about the Milk leaf, and a wrong destination written into a
    field an analyst acts on is worse than a blank one, because a blank is visibly missing and a
    wrong one is not. THE REAL FIX IS THE v5 PROMPT, which makes an Incorrect with no key an
    invalid answer. This is the backstop, not the remedy - if it is ever recovering a large share,
    the prompt has regressed and that is the thing to fix.

    Returns a key, or None when there is not exactly one unambiguous candidate.
    """
    if not rationale:
        return None
    found = {k for k in KEY_IN_TEXT.findall(rationale) if k in valid_keys}
    found.discard(assigned_key)
    return found.pop() if len(found) == 1 else None


def ensure_column(qa, qcur, name, decl):
    qcur.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME='qa_line' AND COLUMN_NAME=?""", name)
    if qcur.fetchone()[0]:
        return False
    qcur.execute(f"ALTER TABLE qa_line ADD {name} {decl}")
    qa.commit()
    return True


def decided_by(verdict, votes):
    """Which models voted for the answer that WON. Sameer, 2026-08-17: *"can you add a colum to
    include which model was actually used or finalized for that line?"*

    🔒 NAMED FOR WHAT IT IS, because "the model used" does not exist. A 2-of-3 majority has no
    single author: on a `2of3` row two models carried the verdict and one disagreed, and picking
    one of the two to name would be an arbitrary choice presented as a fact. So this column lists
    EVERY model that voted the winning verdict - one name, two, or three - and the count of names
    is a second reading of NIM_AGREEMENT that needs no decoding.

    votes: [(model, verdict), ...] in NIM_1..3 order.
    """
    if not verdict:
        return None
    with_it = [m for m, v in votes if m and v == verdict]
    if not with_it:
        # A three-way split resolves to Uncertain by rule, so no model actually said it. Saying
        # "none" is the honest answer; naming a model here would invent an author for a verdict
        # that came from the tie-breaking rule rather than from any model.
        return "none - resolved by the split rule"
    return ", ".join(with_it)


def report(qcur):
    print(f"\n=== WHAT THE {len(ACTIONS)} ACTIONS MEAN ===")
    for k, v in ACTIONS.items():
        print(f"  {k:16} {v}")
    print("\n=== NIM_ACTION x NIM_VERDICT ===")
    qcur.execute("""SELECT ISNULL(NIM_ACTION,'(none)'), ISNULL(NIM_VERDICT,'(none)'), COUNT(*)
                    FROM qa_line GROUP BY NIM_ACTION, NIM_VERDICT""")
    grid, verdicts, actions = {}, set(), set()
    for a, v, n in qcur.fetchall():
        grid[(a, v)] = n
        verdicts.add(v)
        actions.add(a)
    verdicts = sorted(verdicts)
    print(f"  {'action':16}" + "".join(f"{v:>12}" for v in verdicts) + f"{'TOTAL':>9}")
    for a in sorted(actions):
        tot = sum(grid.get((a, v), 0) for v in verdicts)
        print(f"  {a:16}" + "".join(f"{grid.get((a, v), 0):>12,}" for v in verdicts) + f"{tot:>9,}")
    print(f"  {'TOTAL':16}"
          + "".join(f"{sum(grid.get((a, v), 0) for a in actions):>12,}" for v in verdicts)
          + f"{sum(grid.values()):>9,}")

    # The two sub-cases inside Needs evidence, stated rather than buried - they are different
    # problems and a reader who cannot see the split will assume the smaller, easier one.
    qcur.execute("""SELECT SUM(CASE WHEN NIM_VERDICT='Uncertain' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN NIM_VERDICT='Incorrect' THEN 1 ELSE 0 END)
                    FROM qa_line WHERE NIM_ACTION='Needs evidence'""")
    unc, inc = qcur.fetchone()
    print(f"\n  'Needs evidence' splits into: {unc or 0:,} Uncertain (evidence did not settle it)"
          f"  +  {inc or 0:,} Incorrect with no destination")

    qcur.execute("""SELECT COUNT(*) FROM qa_line WHERE NIM_ACTION='Miscategorised'""")
    print(f"  the queue that needs an analyst: {qcur.fetchone()[0]:,} Miscategorised lines")
    qcur.execute("SELECT COUNT(*) FROM qa_line WHERE NIM_ACTION IS NULL")
    left = qcur.fetchone()[0]
    print(f"  rows with no action: {left}" + ("   ** every row should have one **" if left else "   OK"))

    # 🔒 THE CHECK THAT WOULD HAVE CAUGHT IT. A Re-mapped row says "this category has a new
    # address"; without the address that is most of the information missing, and it is invisible
    # unless something counts it. Sameer found 135 such rows by reading the data. This is here so
    # the data never has to be read to find it again.
    qcur.execute("""SELECT COUNT(*) FROM qa_line
                    WHERE NIM_ACTION='Re-mapped' AND NIM_SUGGESTED_KEY IS NULL""")
    blank = qcur.fetchone()[0]
    print(f"  Re-mapped rows with NO destination: {blank}"
          + ("   ** a re-map must say where to - INVESTIGATE **" if blank else "   OK"))

    # Miscategorised must also always carry a destination - that is what separates it from
    # 'Needs evidence', which is the bucket for "wrong, and we cannot say where".
    qcur.execute("""SELECT COUNT(*) FROM qa_line
                    WHERE NIM_ACTION='Miscategorised' AND NIM_SUGGESTED_KEY IS NULL""")
    b2 = qcur.fetchone()[0]
    print(f"  Miscategorised rows with NO destination: {b2}"
          + ("   ** these belong in Needs evidence - INVESTIGATE **" if b2 else "   OK"))

    # 🔒 THE GL GUARANTEE, MEASURED ON THE OUTPUT. v4 asserted the GL was removed and it was not -
    # three separate paths were still open and all three were found by grepping rationales, never
    # by reading the diff. So the claim is now a CHECK that runs every time, not a claim.
    qcur.execute("""SELECT COUNT(*) FROM qa_line WHERE NIM_RATIONALE LIKE '%account name%'
                    OR NIM_RATIONALE LIKE '%cost centre%' OR NIM_RATIONALE LIKE '%cost center%'
                    OR NIM_RATIONALE LIKE '%GL %' OR NIM_RATIONALE LIKE '%general ledger%'""")
    gl = qcur.fetchone()[0]
    qcur.execute("""SELECT COUNT(*) FROM qa_line WHERE NIM_VERDICT <> 'Uncertain'
                    AND (NIM_RATIONALE LIKE '%account name%' OR NIM_RATIONALE LIKE '%cost centre%'
                      OR NIM_RATIONALE LIKE '%cost center%' OR NIM_RATIONALE LIKE '%GL %'
                      OR NIM_RATIONALE LIKE '%general ledger%')""")
    glfirm = qcur.fetchone()[0]
    print(f"\n  rationales mentioning GL / account name / cost centre: {gl}"
          + ("   OK" if gl == 0 else f"   ** {glfirm} of them on a FIRM verdict - INVESTIGATE **"))

    # \u2b50 THE SELF-CONTRADICTION CHECK, v7, 2026-08-24. MEASURED ON THE OUTPUT, EVERY RUN.
    #
    # Sameer, shown that biscuits were landing in Stationery & Printing, asked why the models could
    # not simply know what biscuits are. Reading the rationales settled it - THEY DO:
    #
    #     "item is biscuits, not ICT hardware"                        -> Stationery & Printing
    #     "item PUKKA SUPREME MATCHA TEA is a beverage, not ICT ..."  -> Stationery & Printing
    #     "item AJAX GLSS CLNR is cleaning supplies, not ICT ..."     -> Stationery & Printing
    #
    # \U0001f511 Every identification correct, every one 3of3, and every one then filed by the VENDOR
    # rather than by the item the judge had just named. Ruling out the wrong category is not the
    # same as choosing the right one. Prompt v7 makes the rationale BINDING; this counts whether it
    # held.
    #
    # \u26a0 DELIBERATELY CONSERVATIVE. Each pattern fires only on an unambiguous phrase, and a line
    # counts as a contradiction only when the destination contains NONE of the tokens that phrase
    # implies. It will UNDER-count - a rule that cries wolf gets ignored, and the number has to be
    # trustworthy enough to act on. It is a floor, never a ceiling.
    CONTRADICTION = [
        ("biscuit",                     ("Biscuit", "Bakery", "Food")),
        ("beverage",                    ("Beverage", "Tea", "Coffee", "Juice", "Food", "Water")),
        (" tea ",                       ("Tea", "Beverage", "Food")),
        ("cleaning suppl",              ("Cleaning", "Janitorial", "Consumable")),
        ("food service disposable",     ("Food Container", "Consumable", "Cutlery", "Disposable")),
        ("fresh produce",               ("Produce", "Vegetable", "Fruit", "Food")),
        ("confection",                  ("Confection", "Bakery", "Food")),
        ("dairy",                       ("Dairy", "Food")),
        ("stationery",                  ("Stationery", "Office", "Print")),
        ("glove",                       ("Glove", "PPE", "Safety", "Clinical")),
    ]
    qcur.execute("""SELECT QA_LINE_ID, CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION, NIM_RATIONALE,
                CONCAT(ISNULL(NIM_SUGGESTED_CATEGORY_LVL_1,''),' ',ISNULL(NIM_SUGGESTED_CATEGORY_LVL_2,''),
                       ' ',ISNULL(NIM_SUGGESTED_CATEGORY_LVL_3,''),' ',ISNULL(NIM_SUGGESTED_CATEGORY_LVL_4,''))
            FROM qa_line
            WHERE NIM_RATIONALE IS NOT NULL AND NIM_SUGGESTED_CATEGORY_LVL_1 IS NOT NULL""")
    # 🔑 SEARCH ONLY THE CLAUSE ABOUT THE ITEM, NOT THE WHOLE RATIONALE. These read
    # "Vendor WINC is an office supplies retailer; item X is biscuits" - so a whole-string search
    # matches the VENDOR's trade and calls a correctly-filed line a contradiction. Measured on the
    # first version: 3 of 11 hits were exactly that (an air freshener and a paper towel, both
    # correctly sent to Cleaning, flagged because the word "stationery" described the supplier).
    # A check that cries wolf is a check that gets ignored, so it reads from the last mention of
    # "item" onward and falls back to the whole string when the rationale never says "item".
    hits, checked = [], 0
    for lid, cl, sup, item, rat, dest in qcur.fetchall():
        r_all = (rat or "").lower()
        cut = r_all.rfind("item")
        r, d = (r_all[cut:] if cut != -1 else r_all), (dest or "")
        for phrase, need in CONTRADICTION:
            if phrase in r:
                checked += 1
                if not any(tok.lower() in d.lower() for tok in need):
                    hits.append((lid, cl, phrase.strip(), (item or "")[:44], d.strip()[:52]))
                break
    print(f"\n  \u2b50 SELF-CONTRADICTION - rationale names the item, destination disagrees")
    print(f"     rationales naming an item type : {checked}")
    print(f"     of those, filed elsewhere      : {len(hits)}"
          + ("   OK" if not hits else "   ** the judge is not acting on its own words **"))
    for lid, cl, phrase, item, dest in hits[:12]:
        print(f"       [{lid}] {cl[:12]:<12} said '{phrase}'  {item:<44} -> {dest}")
    if len(hits) > 12:
        print(f"       ... and {len(hits) - 12} more")

    # The other half of the same principle: a rationale that denies evidence the row demonstrably
    # holds. It is worse than a wrong verdict - it sends a person looking for information already
    # in front of them.
    #
    # ⚠️ DESCRIPTION_USABLE='Y' IS NOT THE RIGHT TEST ON ITS OWN, and my first version of this check
    # used it and over-counted by ~2x. That flag only excludes the PLACEHOLDERS list; it does NOT
    # catch the IDENTIFIER-AS-DESCRIPTION, which CLAUDE.md deliberately keeps out of PLACEHOLDERS
    # ("an identifier is sometimes the only handle a person has ... let the judge's confidence carry
    # it"). So a judge calling `1TD5HX 8823126` or `CBORD ID:` unusable is CORRECT, and counting it
    # as a false claim measures the wrong thing and cries wolf. Measured on v5: of 157 rows the
    # naive test flagged, 70 were identifiers where the judge was right and only 55 were genuinely
    # descriptive text.
    #
    # The discriminator is WORD-LIKE TOKENS: an identifier is code-like, a description carries
    # several actual words. Three or more is descriptive; the borderline 2 is left out of the count
    # rather than argued about, so this number is a floor and never an exaggeration.
    qcur.execute("""SELECT ITEM_DESCRIPTION FROM qa_line WHERE DESCRIPTION_USABLE='Y'
                    AND (NIM_RATIONALE LIKE '%no usable desc%' OR NIM_RATIONALE LIKE '%unusable%'
                      OR NIM_RATIONALE LIKE '%no description%'
                      OR NIM_RATIONALE LIKE '%does not identify what was bought%')""")
    flagged = [r[0] for r in qcur.fetchall()]
    word = re.compile(r"^[A-Za-z][A-Za-z\-'/]{2,}$")
    fd = sum(1 for t in flagged
             if sum(1 for tok in re.split(r"[\s,()\[\]:;#*]+", t or "") if word.match(tok)) >= 3)
    print(f"  rationales denying a description that is GENUINELY descriptive: {fd}"
          + f"   (of {len(flagged)} flagged; the rest are identifier-only lines where the judge is "
            f"right)"
          + ("   OK" if fd == 0 else "   ** false statement about the evidence **"))

    print("\n=== WHICH MODELS CARRIED THE VERDICT (NIM_DECIDED_BY) ===")
    qcur.execute("""SELECT NIM_DECIDED_BY, COUNT(*) FROM qa_line WHERE NIM_VERDICT IS NOT NULL
                    GROUP BY NIM_DECIDED_BY ORDER BY 2 DESC""")
    for who, n in qcur.fetchall():
        print(f"  {str(who)[:66]:68} {n:>6,}")

    # NIM_DECIDED_BY and NIM_AGREEMENT are two readings of the same vote, so they must agree:
    # the number of models named must equal the number in the agreement label. If they ever
    # diverge, one of them is lying and neither can be trusted.
    qcur.execute("""SELECT NIM_AGREEMENT, NIM_DECIDED_BY FROM qa_line
                    WHERE NIM_VERDICT IS NOT NULL AND NIM_AGREEMENT <> 'split'""")
    bad = 0
    for agree, who in qcur.fetchall():
        named = 0 if not who or who.startswith("none") else len([x for x in who.split(",") if x.strip()])
        want = int(str(agree)[0]) if agree and str(agree)[0].isdigit() else None
        if want is not None and named != want:
            bad += 1
    print(f"\n  rows where the models named disagree with NIM_AGREEMENT: {bad}"
          + ("   ** one of the two is wrong - INVESTIGATE **" if bad else "   OK"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print the tally, write nothing")
    ap.add_argument("--production", action="store_true",
                    help="⚠️ run against PI_Medical_QA_Indirect, not the pilot.")
    args = ap.parse_args()

    qa = connect_qa(pilot=not args.production, production=args.production, env=load_env())
    qcur = qa.cursor()

    # The standing invariant, checked before writing. More than one generation in this table means
    # every figure taken from it double-counts.
    qcur.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM qa_line")
    nrow, nrun = qcur.fetchone()
    if nrun != 1:
        raise SystemExit(f"  qa_line holds {nrun} run_ids - expected exactly 1. STOP.")
    print(f"qa_line {nrow:,} rows / {nrun} run_id")

    if not args.report:
        cw = newest_crosswalk()
        cross = load_crosswalk(cw)
        print(f"crosswalk: {os.path.basename(cw)}   {len(cross):,} source categories mapped")
        for nm, decl in (("NIM_ACTION", "NVARCHAR(20) NULL"),
                         ("NIM_DECIDED_BY", "NVARCHAR(200) NULL")):
            if ensure_column(qa, qcur, nm, decl):
                print(f"added column qa_line.{nm}")

        # The merged taxonomy, so a key can be expanded into the five level columns an analyst
        # actually reads. Same source the judge chooses from - one taxonomy, not two.
        qcur.execute("""SELECT category_key, CATEGORY_LVL_0, CATEGORY_LVL_1, CATEGORY_LVL_2,
                        CATEGORY_LVL_3, CATEGORY_LVL_4 FROM qa_category WHERE client_code=?""",
                     MERGED_CLIENT)
        keyed = {r[0]: tuple(r[1:6]) for r in qcur.fetchall()}

        qcur.execute("""SELECT QA_LINE_ID, CLIENT_CODE, TAXONOMY_KEY, CATEGORY_LVL_1,
                        CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4, NIM_VERDICT,
                        NIM_SUGGESTED_KEY,
                        NIM_1_MODEL, NIM_1_VERDICT, NIM_2_MODEL, NIM_2_VERDICT,
                        NIM_3_MODEL, NIM_3_VERDICT,
                        NIM_SUGGESTED_CATEGORY_LVL_0, NIM_RATIONALE FROM qa_line""")
        rows = qcur.fetchall()

        # PASS ONE: recover destinations the judge WROTE OUT but left out of the field. This runs
        # BEFORE classify, because a recovered key turns an unactionable `Needs evidence` row into
        # a `Miscategorised` one with somewhere to go - classifying first would bake in the old
        # answer. Order dependency, same shape as the crosswalk fill.
        recovered = []
        row_key = {}
        for r in rows:
            row_key[r[0]] = r[8]
            if r[7] == "Incorrect" and not r[8]:
                k = key_from_rationale(r[16], keyed, assigned_key=None)
                if k:
                    row_key[r[0]] = k
                    lv = keyed.get(k)
                    recovered.append((k, *lv, r[0]))
        if recovered:
            qcur.fast_executemany = False
            qcur.executemany("""UPDATE qa_line SET NIM_SUGGESTED_KEY=?,
                    NIM_SUGGESTED_CATEGORY_LVL_0=?, NIM_SUGGESTED_CATEGORY_LVL_1=?,
                    NIM_SUGGESTED_CATEGORY_LVL_2=?, NIM_SUGGESTED_CATEGORY_LVL_3=?,
                    NIM_SUGGESTED_CATEGORY_LVL_4=? WHERE QA_LINE_ID=?""", recovered)
            qa.commit()
        print(f"recovered {len(recovered):,} destinations the judge stated in the rationale but "
              f"left out of the field (exact keys only)")

        actions, fills, unmapped, deciders = [], [], 0, []
        for r in rows:
            # r[8] refreshed from row_key so a just-recovered destination is visible to classify.
            unit = (r[1], r[2], r[3], r[4], r[5], r[6], r[7], row_key[r[0]])
            sug_l0 = keyed[row_key[r[0]]][0] if row_key[r[0]] in keyed else r[15]
            action, fill_key = classify(unit, cross, suggested_l0=sug_l0)
            actions.append((action, r[0]))
            deciders.append((decided_by(r[7], [(r[9], r[10]), (r[11], r[12]), (r[13], r[14])]),
                             r[0]))
            # FILL ONLY WHAT IS STILL EMPTY. row_key holds NIM_SUGGESTED_KEY as it now stands,
            # including anything pass one just recovered: if the judge named a destination it
            # stands, always. This completes a blank, it never overrides a verdict.
            if fill_key and not row_key[r[0]]:
                lv = keyed.get(fill_key)
                if lv:
                    fills.append((fill_key, *lv, r[0]))
                else:
                    unmapped += 1

        qcur.fast_executemany = False
        qcur.executemany("UPDATE qa_line SET NIM_ACTION=? WHERE QA_LINE_ID=?", actions)
        qcur.executemany("UPDATE qa_line SET NIM_DECIDED_BY=? WHERE QA_LINE_ID=?", deciders)
        if fills:
            qcur.executemany("""UPDATE qa_line SET NIM_SUGGESTED_KEY=?,
                    NIM_SUGGESTED_CATEGORY_LVL_0=?, NIM_SUGGESTED_CATEGORY_LVL_1=?,
                    NIM_SUGGESTED_CATEGORY_LVL_2=?, NIM_SUGGESTED_CATEGORY_LVL_3=?,
                    NIM_SUGGESTED_CATEGORY_LVL_4=? WHERE QA_LINE_ID=?""", fills)
        qa.commit()
        print(f"classified {len(actions):,} lines   "
              f"filled {len(fills):,} Re-mapped destinations from the crosswalk"
              + (f"   ** {unmapped} target keys not found in qa_category **" if unmapped else ""))

        qcur.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM qa_line")
        # tuple(), because a pyodbc Row never compares equal to a plain tuple and the guard would
        # cry CHANGED on every clean run - an alarm that always fires is an alarm nobody reads.
        after = tuple(qcur.fetchone())
        print(f"qa_line after: {after[0]:,} rows / {after[1]} run_id"
              + ("   UNCHANGED" if after == (nrow, nrun) else "   <- CHANGED, investigate"))

    report(qcur)
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
