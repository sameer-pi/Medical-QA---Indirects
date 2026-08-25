"""Audit the merged indirect taxonomy for structural defects. Read-only, no database.

    python pipeline/taxonomy_audit.py            all checks
    python pipeline/taxonomy_audit.py --strict   exit 1 if any BLOCKING check fails

WHY THIS EXISTS. Sameer, 2026-08-13, after finding four separate defect classes by eye:
*"why am i reviewing these stupid errors you keep making"* … *"this has to be part of the check."*

Every check below was written the day a human found the defect the check now catches. The rule the
file enforces on itself: **a defect found by eye becomes a check before the next branch is reviewed**,
or the human stays the detector.

WHAT A CHECK CAN AND CANNOT DO. Six of the seven are mechanical - a machine can decide them. The
seventh, PLACEMENT, cannot be: whether `Recruitment & Temp Staff` belongs under HR is a judgement
about the business. It is still listed here, as a REVIEW LIST rather than a verdict, because the
failure mode is not "the tool got it wrong" but "nobody looked". Printing the outline branch by
branch is what makes looking cheap.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_taxonomy import OUTDIR, canonical, lev, loose   # noqa: E402

GENERIC = ("other", "general", "misc", "not yet categorized", "n.e.c", "sundry", "various")
# A child's STATE must not contradict its parent's. 'Fresh Produce > Processed Salads' passed the
# duplicate-label, hollow-level and generic-bucket checks and is still nonsense (Finding 78c).
STATE = {"processed": "processed", "frozen": "frozen", "dried": "dried", "canned": "canned",
         "jarred": "canned", "fresh": "fresh", "pureed": "processed", "puree": "processed",
         "non dairy": "non-dairy", "non-dairy": "non-dairy", "preserved": "preserved"}
# A category label is a NAME, not a sentence. Sameer's ruling text became a live category holding
# 2,750 lines because the only validation was "is it rooted in a scope gate" (Finding 78d).
MAX_LABEL = 60


def newest_merged(outdir=None):
    outdir = outdir or OUTDIR
    c = [os.path.join(outdir, f) for f in os.listdir(outdir)
         if "MERGED" in f and f.lower().endswith(".xlsx") and not f.startswith("~$")]
    if not c:
        sys.exit("No MERGED .xlsx in output/Taxonomy/ - run merge_taxonomy.py --emit first.")
    return max(c, key=os.path.getmtime)


def load(path):
    """[(segments without padding, lines, clients, source nodes)] - one per category."""
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).active
    return [(canonical([x for x in r[1:6] if x]), r[9], r[7], r[8])
            for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]


STOP = {"AND", "OR", "OF", "THE", "SERVICES", "SERVICE", "GENERAL", "OTHER", "MISC", "SUPPLIES",
        "SUPPLY", "PRODUCTS", "PRODUCT", "EQUIPMENT", "ACCESSORIES", "ITEMS", "COSTS", "FEES"}


def words(label):
    """Content words of a label, singularised crudely. Comparison only, never stored.

    `loose()` strips the spaces out, which is what makes it good at spelling variants and blind to
    everything below: 'General Patient Aids' under 'Patient Aid Equipment and Accessories and
    Supplies' is the SAME CATEGORY NAMED TWICE, and neither the edit-distance test nor the
    substring test can see it, because the two strings share no run of characters long enough.
    Sameer found it by eye on 2026-08-13 - *"isnt Patient Aid Equipment and Accessories and
    Supplies and General Patient Aids almost the samr things?"* - which is the class of question the
    checks exist to stop him having to ask.
    """
    s = (label or "").upper().replace("&", " AND ")
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    out = set()
    for w in s.split():
        if w in STOP or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("S") and not w.endswith("SS") else w)
    return out


def state(label):
    low = label.lower()
    for word, st in STATE.items():
        if st and re.search(rf"\b{re.escape(word)}\b", low):
            return st
    return None


def check_junk_labels(node):
    """BLOCKING. A label that is prose, a question, or 60+ characters is not a category."""
    out = []
    for segs, lines, _, _ in node:
        for s in segs[1:]:
            if len(s) > MAX_LABEL or "?" in s or re.search(r",.{0,12}\bthe\b.{0,20}\blevel\b", s, re.I):
                out.append((lines, s))
                break
    return out


def check_contradictions(node):
    """BLOCKING. A child whose state contradicts its parent's - processed under fresh."""
    out = []
    for segs, lines, _, _ in node:
        for parent, child in zip(segs, segs[1:]):
            if parent == child:
                continue
            ps, cs = state(parent), state(child)
            if ps and cs and ps != cs:
                out.append((lines, f"{parent} > {child}", f"{ps} vs {cs}"))
                break
    return out


def check_duplicate_homes(node):
    """A leaf label under more than one parent. Not always wrong - fresh/frozen/processed
    Vegetables are three products - so this reports, it does not fail."""
    byleaf = defaultdict(list)
    for segs, lines, _, _ in node:
        if loose(segs[-1]) in [loose(g) for g in GENERIC]:
            continue
        byleaf[loose(segs[-1])].append((" > ".join(segs[1:-1]) or "(top)", segs[-1], lines))
    return {k: v for k, v in byleaf.items() if len({p for p, _, _ in v}) > 1}


def check_near_duplicate_labels(node):
    """Labels one or two edits apart ANYWHERE - the merge only unifies siblings, so
    'Preserverd Food' with its own group was invisible to it (Finding 77)."""
    lines_by = defaultdict(int)
    for segs, lines, _, _ in node:
        for s in segs[1:]:
            lines_by[s] += lines
    out, seen = [], set()
    for a in lines_by:
        for b in lines_by:
            if a >= b or (a, b) in seen or abs(len(a) - len(b)) > 3:
                continue
            seen.add((a, b))
            d = lev(loose(a), loose(b), cap=3)
            if 0 < d <= 2:
                out.append((d, a, lines_by[a], b, lines_by[b]))
    return sorted(out, key=lambda x: -(x[2] + x[4]))


def check_hollow_levels(node):
    """A group whose only child restates it - 'Printers and Multi-Function Print Devices >
    Printers and Multi-Function Devices' (Finding 77).

    THREE tests, because the first two only see the string. Character distance and substring both
    missed 'Patient Aid Equipment and Accessories and Supplies > General Patient Aids' - one level
    from Western's own taxonomy, 18,580 lines, and plainly one category written twice. The third
    test compares CONTENT WORDS: if everything the child names is already in the parent's name, the
    child adds nothing (Finding 80i).
    """
    kids = defaultdict(set)
    for segs, _, _, _ in node:
        for i in range(1, len(segs)):
            kids[" > ".join(segs[:i])].add(segs[i])
    out = []
    for parent, ch in kids.items():
        if len(ch) != 1 or " > " not in parent:
            continue
        child, tail = next(iter(ch)), parent.split(" > ")[-1]
        if loose(child) == loose(f"{tail} - Other"):
            continue   # reported by check 2c, which is blocking - not repeated here
        wc, wp = words(child), words(tail)
        if lev(loose(tail), loose(child), cap=3) <= 2 or \
                loose(child) in loose(parent) or loose(tail) in loose(child) or \
                (wc and wp and (wc <= wp or wp <= wc)):
            out.append(f"{parent} > {child}")
    return out


def check_word_order_duplicates(node):
    """Two labels built from the SAME WORDS in a different order - one category, two spellings.

    'Domestic Transport' (Melbourne) and 'Transport Domestic' (the other three) sat side by side
    under Travel and no check saw them: they are 18 edits apart, so the near-duplicate test skipped
    the pair on length alone. Sameer spotted it while asking for an International sibling
    (Finding 80i). Reports across the whole taxonomy, not only siblings.
    """
    def seq(label):
        keep = words(label)
        s = (label or "").upper().replace("&", " AND ")
        s = "".join(ch if ch.isalnum() else " " for ch in s)
        out = []
        for w in s.split():
            w = w[:-1] if w.endswith("S") and not w.endswith("SS") else w
            if w in keep:
                out.append(w)
        return tuple(out)

    by = defaultdict(dict)
    for segs, lines, _, _ in node:
        for s in segs[1:]:
            k = frozenset(words(s))
            if len(k) < 2:
                continue
            by[k][s] = by[k].get(s, 0) + lines
    # SAME SET, SAME ORDER is not a finding: it is '<X>' beside '<X> - Other', which is his
    # convention. Only a different word ORDER means two people named one category two ways.
    return sorted(((sum(v.values()), sorted(v.items(), key=lambda x: -x[1]))
                   for v in by.values() if len({seq(s) for s in v}) > 1), reverse=True)


def check_prefix_categories(node):
    """BLOCKING. A category whose path is a strict PREFIX of another category's path.

    It is a generic bucket sitting at a level that has real children, and it displays as the parent
    label repeated - `Transport > Courier > Courier` beside `Courier > Courier Fees`. Sameer,
    2026-08-13: *"under transport remove this line"*. His convention is that such a node is named
    `Other` explicitly. The rule the earlier pass used - path stops at Level 2 - missed this one,
    because Courier stops at Level 3. Prefix is the general form of that test.
    """
    paths = {" > ".join(segs) for segs, _, _, _ in node}
    lines = {" > ".join(segs): ln for segs, ln, _, _ in node}
    return sorted(((lines[p], p) for p in paths if any(q.startswith(p + " > ") for q in paths)),
                  reverse=True)


def check_sole_other(node):
    """BLOCKING. A `<parent> - Other` that is the ONLY child of its parent.

    His `- Other` convention says a generic child sitting BESIDE real siblings gets named for its
    parent - `Reimbursements > Reimbursements - Other` next to `Doctor Payments`. Where it is the
    only child there are no siblings to distinguish it from, so the level says the parent's name
    twice and nothing else: `Rates, Taxes and Adjustments > Rates, Taxes and Adjustments - Other`,
    108,669 lines. Sameer named three of them one at a time on 2026-08-13 - the third was the point
    at which the rule was obviously general, and the sweep found **28 nodes, 207,296 lines**.

    Blocking, because it is the third time a convention of his has had to be applied by hand, and
    the test for it is mechanical.
    """
    kids = defaultdict(set)
    for segs, _, _, _ in node:
        for i in range(1, len(segs)):
            kids[" > ".join(segs[:i])].add(segs[i])
    return sorted(((lines, " > ".join(segs)) for segs, lines, _, _ in node
                   if len(segs) >= 3 and loose(segs[-1]) == loose(f"{segs[-2]} - Other")
                   and len(kids[" > ".join(segs[:-1])]) == 1), reverse=True)


def check_generic_buckets(node):
    """How much spend sits in a category that names nothing. Not a defect to fix in the
    taxonomy - it is the size of the categorisation job (Finding 77)."""
    tot = sum(n[1] for n in node)
    hits = [(lines, " > ".join(segs)) for segs, lines, _, _ in node
            if any(g in segs[-1].lower() for g in GENERIC) and lines > 0]
    return sorted(hits, reverse=True), (sum(h[0] for h in hits), tot)


def review_placement(node):
    """NOT MECHANICAL - the outline, branch by branch, for a human to read.

    This is the class behind nearly every correction Sameer made on 2026-08-13: recruitment under
    HR, mail room out of ICT, utilities into hard FM. No rule decides it. What the check can do is
    make the outline cheap to read, and flag the two mechanical hints: a branch that carries one
    category, and a group name that appears under two different branches.
    """
    tree = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for segs, lines, _, _ in node:
        br = " > ".join(segs[:2]) if len(segs) > 1 else segs[0]
        g = segs[2] if len(segs) > 2 else segs[-1]
        tree[br][g][0] += 1
        tree[br][g][1] += lines
    thin = [b for b, gs in tree.items() if sum(v[0] for v in gs.values()) <= 1]
    groups = defaultdict(set)
    for br, gs in tree.items():
        for g in gs:
            groups[loose(g)].add(br)
    shared = {g: bs for g, bs in groups.items() if len(bs) > 1}
    return tree, thin, shared


def main(strict=False):
    path = newest_merged()
    node = load(path)
    print(f"\n{os.path.basename(path)}   {len(node)} categories, {sum(n[1] for n in node):,} lines")
    failed = []

    junk = check_junk_labels(node)
    print(f"\n=== 1. JUNK LABELS (blocking) === {'FAIL' if junk else 'pass'}")
    for lines, s in junk:
        print(f"   {lines:>8,}  {s[:96]!r}")
    if junk:
        failed.append("junk labels")

    con = check_contradictions(node)
    print(f"\n=== 2. PARENT/CHILD CONTRADICTIONS (blocking) === {'FAIL' if con else 'pass'}")
    for lines, p, why in con:
        print(f"   {lines:>8,}  {p}   [{why}]")
    if con:
        failed.append("contradictions")

    pre = check_prefix_categories(node)
    print(f"\n=== 2b. GENERIC BUCKET AT A LEVEL THAT HAS CHILDREN (blocking) === "
          f"{'FAIL' if pre else 'pass'}")
    for lines, p in pre:
        print(f"   {lines:>8,}  {p}   <- needs an explicit '> Other'")
    if pre:
        failed.append("prefix categories")

    sole = check_sole_other(node)
    print(f"\n=== 2c. '<parent> - Other' AS AN ONLY CHILD (blocking) === {'FAIL' if sole else 'pass'}")
    for lines, p in sole:
        print(f"   {lines:>8,}  {p}   <- no siblings to distinguish it from; collapse into the parent")
    if sole:
        failed.append("sole '- Other' children")

    dup = check_duplicate_homes(node)
    print(f"\n=== 3. ONE LABEL, SEVERAL HOMES === {len(dup)} label(s) - review, not a failure")
    for k, v in sorted(dup.items(), key=lambda x: -sum(l for _, _, l in x[1]))[:12]:
        print(f"   {sum(l for _, _, l in v):>8,}  {v[0][1]}")
        for p, _, l in sorted(v, key=lambda x: -x[2]):
            print(f"            {l:>8,}  {p}")

    near = check_near_duplicate_labels(node)
    print(f"\n=== 4. NEAR-DUPLICATE LABELS (1-2 edits, any parent) === {len(near)}")
    for d, a, la, b, lb in near[:12]:
        print(f"   d={d}  {a!r} ({la:,})  vs  {b!r} ({lb:,})")

    order = check_word_order_duplicates(node)
    print(f"\n=== 4b. SAME WORDS, DIFFERENT ORDER === {len(order)}")
    for tot, variants in order[:12]:
        print(f"   {tot:>8,}  " + "   vs   ".join(f"{s!r} ({n:,})" for s, n in variants))

    hollow = check_hollow_levels(node)
    print(f"\n=== 5. HOLLOW LEVELS (a group whose only child restates it) === {len(hollow)}")
    for h in hollow[:12]:
        print(f"   {h}")

    buckets, (gen, tot) = check_generic_buckets(node)
    print(f"\n=== 6. SPEND IN A CATEGORY THAT NAMES NOTHING ===")
    print(f"   {gen:,} of {tot:,} lines ({100 * gen / tot:.1f}%) - the size of the job, not a defect")
    for lines, p in buckets[:8]:
        print(f"   {lines:>8,}  {p}")

    tree, thin, shared = review_placement(node)
    print(f"\n=== 7. PLACEMENT - READ THIS ONE. No rule decides it ===")
    print(f"   {len(tree)} branches. A branch holding one category, or a group name appearing under")
    print(f"   two branches, is where a misplacement usually hides.")
    if thin:
        print(f"\n   branches holding a single category:")
        for b in thin:
            print(f"      {b}")
    if shared:
        print(f"\n   group names appearing under more than one branch:")
        for g, bs in sorted(shared.items()):
            print(f"      {g:<34} {' | '.join(sorted(bs))}")
    print(f"\n   the outline:")
    for br in sorted(tree, key=lambda b: -sum(v[1] for v in tree[b].values())):
        t = sum(v[1] for v in tree[br].values())
        print(f"\n   {br}   [{sum(v[0] for v in tree[br].values())} cats · {t:,} lines]")
        for g, v in sorted(tree[br].items(), key=lambda x: -x[1][1]):
            print(f"        {v[1]:>9,}  {g}")

    print(f"\n{'='*78}")
    if failed:
        print(f"BLOCKING CHECKS FAILED: {', '.join(failed)}")
    else:
        print("All blocking checks pass. Sections 3-7 are review lists, not verdicts.")
    print()
    if strict and failed:
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 if a blocking check fails")
    main(ap.parse_args().strict)
