"""Derive ONE indirect taxonomy from the four clients' own, and propose the crosswalk.

    python pipeline/merge_taxonomy.py                 # read-only. Reports, writes nothing.
    python pipeline/merge_taxonomy.py --commit        # writes qa_taxonomy_merged + qa_taxonomy_map

Read-only by default, because a taxonomy merge is a judgement exercise and the first pass is a
proposal for a human, not a migration. Nothing is written without --commit.

THE FINDING THAT SHAPES THIS FILE - measured 2026-08-11
-------------------------------------------------------
Level 4 is USUALLY PADDING. 487 of the 789 in-scope nodes that carry a Level 4 (61.7%) hold a
verbatim copy of their Level 3:

    Non-Clinical > ICT > Hardware > Audio Visual Equipment > Audio Visual Equipment

One client fills that slot by convention and another leaves it empty, and the two taxonomies then
look completely different while saying the same thing. Measured on the raw stored paths, the
outlying client appeared to share only ~12% of its paths with the rest. Collapse the padding and it
shares 49.1%, the paths distinct across all four fall 436 -> 355, and the paths common to all four
rise 24 -> 102.

So EVERY comparison in this file is made on the CANONICAL path - consecutive identical segments
collapsed - and never on the stored string. Comparing the stored string measures a formatting
convention and calls it a disagreement.

WHY NO CLIENT IS NAMED IN THE CODE
----------------------------------
The agreeing group is found by MEASUREMENT, not by a hardcoded name: pairwise canonical overlap,
then the largest mutually-agreeing set becomes the spine. If the data changes - a client re-cuts its
taxonomy, a fifth hospital arrives - the spine follows the data instead of a comment that has gone
stale. It also keeps client identity out of pipeline/, per the standing rule.

KEYS. The merged taxonomy gets a FRESH namespace (IND-0001...). A client key is NEVER reused.
Taxonomy keys collide across hospitals while meaning different things - measured on the indirect
subset, 190 of 216 keys shared between two of the clients (88.0%) mean something different - so
reusing one would make a collision invisible at exactly the moment two key spaces are live at once.

Reads the pilot QA database. Writes to the pilot QA database only, and only with --commit.
"""
import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import connect_qa  # noqa: E402

# Sameer's chosen folder, 2026-08-12: all taxonomy working files live here.
OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "output", "Taxonomy")

# Fresh namespace. A client key is NEVER reused - see the module docstring.
KEY_PREFIX = "IND-"

# The FOOD decision, recommended 2026-08-12 and pending sign-off (RUN_LOG Finding 72).
# Food stays a TOP-LEVEL branch. Not because two clients happen to have one, but because it is the
# only position where the real food taxonomy fits inside four levels:
#     top-level today : L0 > L1 Food > L2 group > L3 leaf            4 slots, one spare
#     under Soft FM   : L0 > L1 FM > L2 SoftFM > L3 Food > L4 group  the leaf has NO slot
# Measured: the top-level branches hold 47 distinct leaves across 281,742 lines; the
# `Soft FM > Food and Beverage` sub-branch holds THREE (`Food`, `Beverages`, `Food Packaging
# Supplies`) across 53,605. Folding the first into the second collapses 47 categories into 3.
FOOD_L1_CANON = "FOOD AND BEVERAGE"
FOOD_STUB_L3 = "FOOD AND BEVERAGE"      # sits under Facilities Management > Soft FM

LEVELS = ["CATEGORY_LVL_0", "CATEGORY_LVL_1", "CATEGORY_LVL_2", "CATEGORY_LVL_3", "CATEGORY_LVL_4"]

# A canonical path agreeing with this share of the group's members counts as group-wide.
SPINE_MIN_SHARE = 0.5

# A parent match must reach at least this deep to mean anything. Matching on 'Non-Clinical' alone
# is matching on the scope gate: it says the line is indirect, which we already knew, and would
# have reported 96,016 lines as "mapped to a known parent" when nothing was known about them.
MIN_ANCESTOR_SEGS = 3

# TYPO DETECTION - corrected 2026-08-12 after Sameer caught it (RUN_LOG Finding 74).
# The first version tested whether one loose label was a PREFIX of the other. That test cannot see
# a typo in the MIDDLE of a word, so it missed the pair the plan had flagged from the start:
#     'Not Yet Categorized'  vs  'Non Yet Categorized'      same length, differ at character 3
# It sat unnormalised under NINE different parents and 85,662 lines, and was shown to Sameer as
# nine separate "no home" rows. Replaced with a real edit distance.
#
# Distance 1 is unified automatically; distance 2 is REPORTED and never merged. That boundary is
# not arbitrary - it is where the one dangerous pair in this data sits:
#     'Direct Care Services' (67,914)  vs  'Indirect Care Services' (241)      distance 2
# opposite meanings, two characters apart. Auto-merging at 2 would have destroyed a real category.
TYPO_AUTO_DIST = 1
TYPO_FLAG_DIST = 2
TYPO_MIN_LEN = 5        # below this a single character is a large share of the word

# A one-edit SUBSTITUTION is not automatically a typo. Measured in the food branch:
#     'Processed Foods > Paste' (204 lines)  vs  'Processed foods > Pasta' (194 lines)
# one character apart and two different foods. Merging them would be exactly the error the
# distance-2 guard exists to prevent, one character lower down.
#
# The discriminator is not the spelling, it is HOW MANY PARENTS IT OCCURS UNDER. A word misspelled
# by one client appears everywhere that client has a category - 'Non Yet Categorized' sits under
# NINE parents. Two genuinely different leaves that happen to be one letter apart sit under one.
# So a substitution is unified only when it repeats across parents; an append/trim ('Spice' ->
# 'Spices') is unified anywhere, because a plural is not a different category.
TYPO_AUTO_PARENTS = 3


def lev(a, b, cap=3):
    """Levenshtein distance, abandoned early once it exceeds `cap`. Used on LOOSE forms only."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def loose(s):
    """Comparison-only form for spotting a SPELLING variant of the same category.

    Never used for storage or for the canonical path - only to propose a candidate a human then
    confirms. Two variants measured across the four taxonomies that exact matching misses:
        'Food and Beverage'  vs  'Food & Beverages'      ('&' against 'and', and a plural)
        'Non-Procurement'    vs  'NonProcurement'        (a hyphen)
    Reporting these as a distinct tier is the point. Silently folding them together would be us
    deciding two clients meant the same thing, which is exactly the call a human should make.
    """
    s = (s or "").upper().replace("&", " AND ")
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split()).replace(" ", "")


# The documented marker for "this category's path is shorter than the deepest level available".
# It is a DISPLAY string, not a category, and it must never become a segment of a canonical path -
# doing so invents a leaf called "(not used at this level)" under ~230 nodes.
NOT_USED = "(not used at this level)"


def _t(v):
    """Trim on the way in. One client stores a trailing space on a category value and SQL Server
    pads on comparison where Python does not - an untrimmed compare would split one category in
    two and invent a disagreement. The level marker is treated as empty."""
    s = (v or "").strip() if isinstance(v, str) else ""
    return "" if s.lower() == NOT_USED else s


def canonical(segments):
    """Drop the repeat-convention padding: collapse CONSECUTIVE identical segments.

    'ICT > Hardware > Audio Visual Equipment > Audio Visual Equipment'
        -> 'ICT > Hardware > Audio Visual Equipment'

    The repeat test is LOOSE, not exact, because the padding is not always spelled consistently:

        'Non-Procurement > NonProcurement'   ->  'Non-Procurement'      (76,363 lines)

    An exact compare leaves that as a two-level path and the merged taxonomy then carries both
    `Non-Procurement` and `NonProcurement` as separate top-level branches - one real, one an
    artefact of a hyphen.

    Consecutive only. A label that legitimately recurs further up the tree is left alone -
    collapsing those would merge two different categories that happen to share a word.
    """
    out = []
    for s in segments:
        s = _t(s)
        if s and (not out or loose(s) != loose(out[-1])):
            out.append(s)
    return out


# The merged taxonomy is STORED in qa_category alongside the four hospitals, under its own
# client_code (load_taxonomy.MERGED_CLIENT). Named here rather than imported, because
# load_taxonomy imports smoke_test and clientcfg and this module must stay importable on its own.
MERGED_CLIENT_CODE = "merged_indirect"


def load_nodes(qcur):
    """Every in-scope (indirect) node, with its canonical path. One row per stored node.

    🔒 THE MERGED TAXONOMY IS EXCLUDED FROM ITS OWN INPUT. Found 2026-08-17, and it had been
    silently corrupting every regeneration.

    `load_taxonomy.load_merged()` writes the emitted taxonomy back into `qa_category` under
    client_code 'merged_indirect'. This query had NO client filter, so the next `--emit` read those
    365 rows back **as if they were a fifth hospital** and merged the taxonomy with itself.

    THE DAMAGE, measured:
      * the tree grew 350 -> 365 with no client data changing. Thirteen of the "new" categories had
        `merged_indirect` as their ONLY source node - our own previous output, re-entering as
        evidence that a category should exist.
      * every one of the 13 was an EXACT DUPLICATE of a leaf already in the tree
        (Vehicle Leasing, Electricity, Gas, Water and Sewerage, Parking & Tolls, Egg, Seafood...),
        which is the two-homes-for-one-item defect Sameer's answer key had just exposed.
      * line conservation inflated from 4,372,242 to 6,408,848 - the merged tree's own lines
        counted a second time. Conservation still reported OK, because the total was consistent
        with its own inflated input. **A self-consistency check cannot see a contaminated input.**
      * it compounds: each emit -> load -> emit cycle feeds the previous output back in again.

    The 2026-08-14 generation (350) was CLEAN - it was emitted before the first load. Everything
    emitted after that load, until this fix, was not.
    """
    qcur.execute(f"""SELECT CLIENT_CODE, CATEGORY_KEY, {', '.join(LEVELS)},
                            PATH_FULL, LINES_IN_SCOPE
                       FROM qa_category
                      WHERE IN_SCOPE = 1 AND CLIENT_CODE <> ?""", MERGED_CLIENT_CODE)
    nodes = []
    for r in qcur.fetchall():
        segs = canonical(list(r[2:7]))
        nodes.append({
            "client": r[0], "key": _t(r[1]), "levels": [_t(x) for x in r[2:7]],
            "stored_path": _t(r[7]), "lines": int(r[8] or 0),
            "canon": " > ".join(segs), "canon_up": " > ".join(s.upper() for s in segs),
            "depth": len(segs),
        })
    return nodes


def load_authoritative(nodes):
    """Swap in a declared AUTHORITATIVE source for one branch of one client's taxonomy.

    Ruled by Sameer 2026-08-12: CBORD is authoritative for the food categories (RUN_LOG Finding 73).
    The client's own taxonomy table holds thirteen food stubs while the lines carry 156 distinct
    food paths that live only in the food-service system. Merging the stubs produced a food branch
    containing none of the paths 131,529 lines actually use.

    Config-driven, so no client and no system is named here: any client whose config declares
    `source.authoritative_taxonomy` gets that branch loaded from the table it names, inside the
    connection already opened for that one client. Line counts come from the client's own view,
    because the authority list carries structure and the view carries usage.

    Every replacement node carries `taxonomy_source` naming the table it came from - a leak or a
    mis-swap is then visible in the data rather than merely absent from the code.
    """
    import clientcfg
    from db import connect_client

    report = []
    for client_key in clientcfg.list_clients():
        try:
            cfg = clientcfg.load_config(client_key)
        except Exception:
            continue
        blocks = (cfg.get("source") or {}).get("authoritative_taxonomy") or []
        if not blocks:
            continue
        clientcfg.assert_same_database(cfg, client_key)
        cols = clientcfg.column_map(cfg)
        view = clientcfg.source_table(cfg)
        cat = [cols[f"cat_l{i}"] for i in range(5)]
        excl = list(clientcfg.clinical_exclusions(cfg)) + list(clientcfg.scope_exclusions(cfg))
        excl = excl or ["Clinical"]
        if "Inter-Hospital Spend" not in excl:
            excl.append("Inter-Hospital Spend")
        inlist = ", ".join("?" for _ in excl)

        cn = connect_client(client_key)
        try:
            cur = cn.cursor()
            for blk in blocks:
                branch, table = blk["branch_l1"], blk["table"]
                lv = blk["levels"]
                sel = ", ".join(f"LTRIM(RTRIM(ISNULL([{c}],'')))" for c in lv)
                # 1. the authority list - every path the system defines for this branch
                cur.execute(f"SELECT DISTINCT {sel} FROM {table} "
                            f"WHERE LTRIM(RTRIM(ISNULL([{lv[1]}],''))) = ?", branch)
                paths = [canonical(list(r)) for r in cur.fetchall()]
                # 2. usage - line counts from the client's own view, in scope, same branch
                gsel = ", ".join(f"LTRIM(RTRIM(ISNULL([{c}],'')))" for c in cat)
                cur.execute(f"SELECT {gsel}, COUNT(*) FROM {view} "
                            f"WHERE LTRIM(RTRIM(ISNULL([{cat[0]}],''))) NOT IN ({inlist}) "
                            f"  AND LTRIM(RTRIM(ISNULL([{cat[1]}],''))) = ? "
                            f"GROUP BY {gsel}", *excl, branch)
                used = {}
                for r in cur.fetchall():
                    segs = canonical(list(r[:5]))
                    # keyed upper for matching, but the DISPLAY segments are kept - building a node
                    # from the upper-cased key puts 'NON-CLINICAL' into the merged taxonomy.
                    used[" > ".join(s.upper() for s in segs)] = (int(r[5] or 0), segs)

                seen, new = set(), []
                for segs in paths:
                    up = " > ".join(s.upper() for s in segs)
                    if not segs or up in seen:
                        continue
                    seen.add(up)
                    new.append({"client": client_key, "key": "", "levels": (segs + [""] * 5)[:5],
                                "stored_path": " > ".join(segs), "lines": used.pop(up, (0, None))[0],
                                "canon": " > ".join(segs), "canon_up": up, "depth": len(segs),
                                "taxonomy_source": table})
                # A path in USE but not in the authority list is a real finding, not a drop.
                orphan_lines = sum(v[0] for v in used.values())
                for up, (ln, segs) in used.items():
                    new.append({"client": client_key, "key": "", "levels": (segs + [""] * 5)[:5],
                                "stored_path": " > ".join(segs), "lines": ln, "canon": " > ".join(segs),
                                "canon_up": up, "depth": len(segs),
                                "taxonomy_source": f"{table} (in use, not in the authority list)"})
                pref = os.path.basename(table).strip("[]").split("_")[0].upper()
                for i, n in enumerate(sorted(new, key=lambda x: x["canon_up"]), start=1):
                    n["key"] = f"{pref}-{i:04d}"

                lb = loose(branch)
                old = [n for n in nodes if n["client"] == client_key
                       and len(n["canon"].split(" > ")) > 1
                       and loose(n["canon"].split(" > ")[1]) == lb]
                for n in old:
                    nodes.remove(n)
                nodes.extend(new)
                report.append({"client": client_key, "branch": branch, "table": table,
                               "removed": len(old), "removed_lines": sum(n["lines"] for n in old),
                               "added": len(new), "added_lines": sum(n["lines"] for n in new),
                               "orphans": len(used), "orphan_lines": orphan_lines})
        finally:
            cn.close()
    return nodes, report


def unify_spellings(nodes, forced=None):
    """Unify SIBLING labels that are the same word spelled two ways, before anything is matched.

    This has to run first. Two branches spelled differently never match each other, so their whole
    sub-trees stay separate and the merged taxonomy ends up with two homes for one thing - which is
    the exact duplication the merge exists to remove. Measured examples:

        'Food and Beverage'  vs  'Food & Beverages'      two top-level food branches
        'Non-Procurement'    vs  'NonProcurement'
        'Applications Software - Non Clinical' vs '... > Non Clinical'

    Only SIBLINGS are unified - same parent, same level. Two identically-named leaves under
    different parents are different categories and are left alone.

    The surviving spelling is the one carrying the most lines, ties broken alphabetically, so a
    re-run picks the same winner. Every rewrite is returned and reported: this is a decision about
    what two clients meant, and it is shown rather than silently applied.
    """
    lines_by = defaultdict(int)
    variants = defaultdict(set)
    for n in nodes:
        segs = n["canon"].split(" > ")
        for i, s in enumerate(segs):
            parent = " > ".join(x.upper() for x in segs[:i])
            variants[(parent, i, loose(s))].add(s)
            lines_by[(parent, i, s)] += n["lines"]

    rewrite, report = {}, []
    for (parent, i, lo), spellings in variants.items():
        if len(spellings) < 2:
            continue
        # Sameer's ruling beats the line-count winner: he chose 'Reimbursements' although
        # 'Re-imbursements' carried all 4,070 lines.
        winner = (forced or {}).get(lo) or sorted(
            spellings, key=lambda s: (-lines_by[(parent, i, s)], s))[0]
        for s in spellings:
            if s != winner:
                rewrite[(parent, i, s.upper())] = winner
                report.append((parent, i, s, winner, lines_by[(parent, i, s)]))

    if rewrite:
        for n in nodes:
            segs = n["canon"].split(" > ")
            out = []
            for i, s in enumerate(segs):
                parent = " > ".join(x.upper() for x in out)
                out.append(rewrite.get((parent, i, s.upper()), s))
            n["canon"] = " > ".join(out)
            n["canon_up"] = " > ".join(s.upper() for s in out)
    return sorted(report, key=lambda r: -r[4]), rewrite


def _sibling_index(nodes):
    """Every (parent, level) -> the set of labels sitting there, with lines per label."""
    lines_by, sibs = defaultdict(int), defaultdict(set)
    for n in nodes:
        segs = n["canon"].split(" > ")
        for i, s in enumerate(segs):
            parent = " > ".join(x.upper() for x in segs[:i])
            sibs[(parent, i)].add(s)
            lines_by[(parent, i, s)] += n["lines"]
    return sibs, lines_by


def typo_pairs(nodes, keep=None, forced=None):
    """Sibling labels one or two edits apart, GROUPED BY THE PAIR rather than by the parent.

    Two separate corrections live here, both from Sameer on 2026-08-12.

    1. THE TEST WAS WRONG. It asked whether one loose label was a prefix of the other, which
       cannot see a typo in the middle of a word. 'Not Yet Categorized' vs 'Non Yet Categorized'
       differ at character three, are the same length, and were therefore never flagged - under
       NINE parents and 85,662 lines. Now measured with a real edit distance.

    2. THE QUESTION WAS ASKED NINE TIMES. The same typo under nine parents is ONE decision about
       what two clients meant, not nine. Sameer, looking at two rows that carried identical
       options: *"seems like the same thing"*. So the pair is the unit, and every parent it occurs
       under is listed against it.

    Returns (auto, flag). `auto` is distance <= TYPO_AUTO_DIST and is applied; `flag` is distance
    TYPO_FLAG_DIST and is only ever reported - that is where 'Direct Care Services' vs 'Indirect
    Care Services' sits, two characters apart and opposite in meaning.
    """
    sibs, lines_by = _sibling_index(nodes)
    grouped = defaultdict(lambda: {"lines": defaultdict(int), "where": set(), "dist": 0})
    for (parent, i), labels in sibs.items():
        for a, b in combinations(sorted(labels), 2):
            la, lb = loose(a), loose(b)
            if la == lb:
                continue                      # already handled by unify_spellings
            if min(len(la), len(lb)) < TYPO_MIN_LEN:
                continue
            d = lev(la, lb, cap=TYPO_FLAG_DIST)
            if d > TYPO_FLAG_DIST:
                continue
            g = grouped[(i, a, b)]
            g["dist"] = d
            g["where"].add(parent.split(" > ")[-1] if parent else "(top level)")
            g["lines"][a] += lines_by[(parent, i, a)]
            g["lines"][b] += lines_by[(parent, i, b)]

    auto, flag, kept = [], [], []
    for (i, a, b), g in grouped.items():
        rec = (i, a, g["lines"][a], b, g["lines"][b], sorted(g["where"]), g["dist"])
        la, lb = loose(a), loose(b)
        if frozenset((la, lb)) in (keep or set()):
            kept.append(rec)              # Sameer has ruled these are two different categories
            continue
        if la in (forced or {}) or lb in (forced or {}):
            auto.append(rec)              # ...and a ruling to MERGE has to be applied, not re-asked
            continue
        short, long_ = (la, lb) if len(la) <= len(lb) else (lb, la)
        append_only = long_.startswith(short) or long_.endswith(short)
        safe = g["dist"] <= TYPO_AUTO_DIST and (append_only
                                                or len(g["where"]) >= TYPO_AUTO_PARENTS)
        (auto if safe else flag).append(rec)
    key = lambda r: -(r[2] + r[4])
    return sorted(auto, key=key), sorted(flag, key=key), sorted(kept, key=key)


def apply_typos(nodes, auto, forced=None):
    """Rewrite the losing spelling of every auto-unified typo pair, everywhere it occurs.

    The winner is the spelling carrying the most lines, ties broken alphabetically, so a re-run
    picks the same one. `forced` carries Sameer's rulings and OVERRIDES that - he chose
    'Reimbursements' over 'Re-imbursements' although the hyphenated one held all 4,070 lines.
    """
    forced = forced or {}
    rewrite, report = {}, []
    for i, a, la, b, lb, where, d in auto:
        winner = forced.get(loose(a)) or sorted([(-la, a), (-lb, b)])[0][1]
        for s, ln in ((a, la), (b, lb)):
            if s != winner:
                rewrite[(i, s.upper())] = winner
                report.append((i, s, winner, ln, where, d, loose(a) in forced))
    if rewrite:
        for n in nodes:
            segs = n["canon"].split(" > ")
            out = [rewrite.get((i, s.upper()), s) for i, s in enumerate(segs)]
            n["canon"] = " > ".join(out)
            n["canon_up"] = " > ".join(s.upper() for s in out)
    return sorted(report, key=lambda r: -r[3]), rewrite


def remap_path(path, sp_rw, ty_rw):
    """Put a path written BEFORE normalisation through the same rewrites the nodes went through.

    Without this, a ruling made on 'Corporate Services > Non Yet Categorized' stops matching the
    moment the typo is unified, and Sameer is asked a question he has already answered.
    """
    out = []
    for i, s in enumerate(path.split(" > ")):
        parent = " > ".join(x.upper() for x in out)
        s = sp_rw.get((parent, i, s.upper()), s)
        out.append(ty_rw.get((i, s.upper()), s))
    return " > ".join(out)


def internal_duplicates(nodes):
    """Nodes sharing a canonical path with another node in the SAME client.

    This is duplication inside one taxonomy, before any cross-client merge, and it has to be
    resolved first - otherwise it is carried into the merged set and blamed on the merge.
    """
    seen = defaultdict(list)
    for n in nodes:
        seen[(n["client"], n["canon_up"])].append(n)
    return {k: v for k, v in seen.items() if len(v) > 1}


def agreeing_group(nodes):
    """Find the largest set of clients that already share a taxonomy, by measurement.

    Returns (group, pairwise) where group is the client set forming the spine. No client is named
    here; the data decides which is the outlier.
    """
    by_client = defaultdict(set)
    for n in nodes:
        by_client[n["client"]].add(n["canon_up"])
    clients = sorted(by_client)
    pairwise = {}
    for a, b in combinations(clients, 2):
        inter = len(by_client[a] & by_client[b])
        pairwise[(a, b)] = inter / max(1, min(len(by_client[a]), len(by_client[b])))

    best = set()
    for size in range(len(clients), 1, -1):
        for combo in combinations(clients, size):
            if all(pairwise[tuple(sorted(p))] >= 0.75 for p in combinations(combo, 2)):
                best = set(combo)
                break
        if best:
            break
    return (best or set(clients)), pairwise, by_client


def build_spine(nodes, group):
    """The merged taxonomy's backbone, plus the two indexes the matcher needs.

    `spine`    canonical LEAF paths held by at least half the agreeing group.
    `prefixes` every ancestor of every spine path. Without this a parent match can never fire,
               because qa_category stores leaves only - no row exists for 'Non-Clinical > ICT'.
    `by_leaf`  leaf label -> the spine paths ending in it. This is what catches a category that
               exists in both taxonomies at DIFFERENT DEPTHS, which is the dominant real
               difference once the repeat padding is gone.
    """
    per_client = defaultdict(set)
    for n in nodes:
        if n["client"] in group:
            per_client[n["client"]].add(n["canon_up"])
    counts = Counter(p for s in per_client.values() for p in s)
    # ceil, not int: with a group of three, "at least half" must mean 2, not 1. int() would put
    # every path held by any single member into the spine and report nothing as needing review.
    need = -(-len(group) * 1 // 2) if SPINE_MIN_SHARE == 0.5 else max(1, int(len(group) * SPINE_MIN_SHARE))
    spine = {p for p, c in counts.items() if c >= need}
    minority = {p for p, c in counts.items() if c < need}

    # An AUTHORITATIVE branch enters the spine regardless of how many clients hold it. Sameer ruled
    # CBORD authoritative for food on 2026-08-12, and only one client holds it - a majority test
    # would drop the only real food taxonomy in the data and leave the other clients' food nodes
    # with nothing to map onto. This is what makes the ruling apply to ALL FOUR hospitals rather
    # than to the one client whose system it is. Reversible: delete the config block and the
    # majority test resumes.
    auth = {n["canon_up"] for n in nodes if n.get("taxonomy_source")}
    spine |= auth
    minority -= auth

    prefixes, by_leaf, by_leaf_loose = set(), defaultdict(set), defaultdict(set)
    for p in spine:
        segs = p.split(" > ")
        for cut in range(1, len(segs)):
            prefixes.add(" > ".join(segs[:cut]))
        by_leaf[segs[-1]].add(p)
        by_leaf_loose[loose(segs[-1])].add(p)
    return spine, minority, prefixes, by_leaf, by_leaf_loose


def propose_mapping(node, spine, prefixes, by_leaf, by_leaf_loose, display):
    """Map one node onto the spine, or say why it cannot be mapped yet.

    Tiered, most specific first. The tier IS the finding - it tells a reviewer what kind of
    decision they are being asked for, so 969 rows do not arrive as one undifferentiated list:

      exact          canonical path already in the spine. Mechanical, no judgement needed.
      leaf_moved     the same leaf label exists in the spine at a DIFFERENT DEPTH. The category
                     agrees; only its position differs. Confirm, do not re-decide.
      leaf_ambiguous the leaf label exists at several spine paths. A human picks; candidates listed.
      parent_match   a proper ancestor is in the spine, so this is a NEW LEAF under a known parent.
                     Additive - it keeps a category the group does not have rather than flattening it.
      unmapped       not even the branch is recognised. Nothing is guessed.
    """
    cu = node["canon_up"]
    if not cu:
        return "malformed", None, 0.0, None
    if cu in spine:
        return "exact", display.get(cu, node["canon"]), 1.0, None

    # A node whose leaf is 'Not Yet Categorized' HAS no home - that is what it says. Asking which
    # category it belongs to is not a decision anybody can take, and it was arriving as 19 rows and
    # 245,989 lines of open questions. Sameer, having answered two of them by hand with the same
    # answer both times: *"why cant you do something for the other levels which are not yet
    # categorized."* It keeps its own path under its own parent, carried down to Level 4 by
    # `carry_uncategorised`, and never reaches the decisions file.
    segs = cu.split(" > ")
    if loose(segs[-1]) == loose(UNCATEGORISED):
        return "uncategorised_by_rule", None, 1.0, None

    segs = cu.split(" > ")
    for index, tier, conf_hit, conf_far in ((by_leaf, "leaf_moved", 0.9, 0.6),
                                            (by_leaf_loose, "leaf_variant", 0.7, 0.5)):
        key = segs[-1] if tier == "leaf_moved" else loose(segs[-1])
        cands = index.get(key, set()) - {cu}
        if not cands:
            continue
        same_branch = {c for c in cands
                       if len(segs) > 1 and c.startswith(segs[0] + " > " + segs[1])}
        if same_branch:
            if len(same_branch) == 1:
                t = next(iter(same_branch))
                return tier, display.get(t, t), conf_hit, None
            return f"{tier}_ambiguous", None, 0.3, sorted(
                display.get(c, c) for c in same_branch)[:4]
        # NO candidate in the same top-level branch. Never taken automatically, however few
        # candidates there are: a leaf label like 'Other' matches across the whole taxonomy, and a
        # single far candidate was silently moving 26,434 Western lines from
        # 'Non-Clinical > General Admin Supplies > Other' to 'Non-Procurement > Reimbursements >
        # Other'. A cross-branch move is a re-categorisation, which is Sameer's call, not a match.
        return "leaf_crosses_branch", None, 0.3, sorted(display.get(c, c) for c in cands)[:4]

    for cut in range(len(segs) - 1, MIN_ANCESTOR_SEGS - 1, -1):
        anc = " > ".join(segs[:cut])
        if anc in prefixes or anc in spine:
            return "parent_match", display.get(anc, anc), round(cut / len(segs), 2), None
    return "unmapped", None, 0.0, None


def resolve(rows):
    """Decide, for every source node, WHICH canonical path it ends up on in the merged taxonomy.

    A node keeps its own path unless it was matched onto an existing one. The two tiers that MERGE
    are the two that change granularity, so they are counted separately and reported - every merge
    is a line-count movement somebody has to sign off, never a silent absorption.
    """
    MERGING = {"leaf_moved", "leaf_variant", "ruled_mapped"}
    for r in rows:
        r["resolved"] = r["target"].upper() if (r["basis"] in MERGING and r["target"]) else r["canon_up"]
        r["merged_away"] = r["basis"] in MERGING
    return rows


GATE_PREFIX = {"CLINICAL": "CL", "NON-CLINICAL": "NC", "NON-PROCUREMENT": "NP"}


def gate_prefix(path):
    """NC / NP / CL from the scope gate at Level 0. Sameer's format, 2026-08-14."""
    return GATE_PREFIX.get((path or "").split(" > ")[0].strip().upper(), "XX")


def load_previous_keys(outdir=None):
    """Every key already issued, read back from the newest MERGED workbook: CANON PATH -> key.

    THE KEY MUST OUTLIVE A TAXONOMY EDIT. This function is the whole mechanism.
    """
    outdir = outdir or OUTDIR
    if not os.path.isdir(outdir):
        return {}
    files = sorted(f for f in os.listdir(outdir)
                   if f.startswith("Indirect Taxonomy - MERGED - ") and f.endswith(".xlsx"))
    if not files:
        return {}
    from openpyxl import load_workbook
    ws = load_workbook(os.path.join(outdir, files[-1]), data_only=True).active
    hdr = [str(c.value or "").strip() for c in ws[1]]
    if "FULL_PATH" not in hdr or "INDIRECT_KEY" not in hdr:
        return {}
    ip, ik = hdr.index("FULL_PATH"), hdr.index("INDIRECT_KEY")
    out = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        p, k = str(r[ip] or "").strip(), str(r[ik] or "").strip()
        # Match on the CANONICAL path, because FULL_PATH is padded for display and canonical()
        # is the single truth for identity everywhere else in this file.
        if p and k and re.match(r"^(NC|NP|CL|XX)-\d{4}$", k):
            out[" > ".join(canonical(p.split(" > "))).upper()] = k
    return out


def build_merged(rows, adds=(), previous=None):
    """The merged taxonomy: one row per distinct resolved path, with a STABLE key.

    ~~Keys are assigned over the SORTED path list, so a re-run produces identical keys.~~
    **THAT WAS WRONG, and it broke on 2026-08-14.** A position in a sorted list is not an identity.
    Sameer added one `Clinical` row; it sorted above `Non-Clinical`, took IND-0001, and **every one
    of the other 349 keys shifted by one** - the exact silent re-point the old docstring warned
    about, caused by the mechanism that docstring was describing.

    The key is now `<gate>-<number>` - `NC-0042`, `NP-0007`, `CL-0001` - Sameer's format, minus the
    client code he first proposed: this is ONE taxonomy shared by four hospitals, so a client code
    in the key would mean four copies of every category and undo the merge. Which clients hold a
    category is already its own column.

    TWO properties, and the second is the one that matters:
      * the gate prefix means the three scope gates number INDEPENDENTLY, so adding a Clinical
        category can never disturb a Non-Clinical number;
      * numbers are APPEND-ONLY. Every key already issued is read back from the previous MERGED
        workbook and reused; a new category takes the next free number in its prefix regardless of
        where it sorts. Like invoice numbers - they go up, they are never re-issued.
    """
    agg = {}
    for r in rows:
        # A node with no category path at all is a SOURCE DEFECT, not a category. Letting it
        # through would mint an IND- key for the empty string.
        if not r["resolved"]:
            continue
        e = agg.setdefault(r["resolved"], {"path": None, "clients": set(), "nodes": 0, "lines": 0,
                                           "sources": set()})
        e["clients"].add(r["client"])
        e["nodes"] += 1
        e["lines"] += r["lines"]
        if not r["merged_away"] or e["path"] is None:
            e["path"] = (r.get("display") or r["canon"]) if not r["merged_away"] else r["target"]
        if r["merged_away"]:
            e["sources"].add(r["canon"])
    # Categories Sameer has added that no client holds. Injected BEFORE keys are assigned, so the
    # IND- numbering stays a deterministic function of the sorted path list rather than depending
    # on when a category was added. An added path that a client turns out to hold is not duplicated.
    for p in adds:
        e = agg.setdefault(p.upper(), {"path": p, "clients": set(), "nodes": 0, "lines": 0,
                                       "sources": set()})
        e["path"] = e["path"] or p
    previous = {} if previous is None else previous
    # Highest number already issued per prefix, so a new category never reuses a retired one.
    # A key is retired when its category is dropped; it is NOT handed to something else.
    high = {}
    for k in previous.values():
        pre, num = k.split("-")
        high[pre] = max(high.get(pre, 0), int(num))
    out = []
    # Sorted only so a FIRST issue reads top-to-bottom. Once issued, order is irrelevant - the
    # number comes from `previous`, not from position.
    for p in sorted(agg):
        e = agg[p]
        path = e["path"] or p
        segs = path.split(" > ")
        key = previous.get(p)
        if not key:
            pre = gate_prefix(path)
            high[pre] = high.get(pre, 0) + 1
            key = f"{pre}-{high[pre]:04d}"
        out.append({"key": key, "canon_up": p, "path": path,
                    "levels": segs, "depth": len(segs), "clients": sorted(e["clients"]),
                    "nodes": e["nodes"], "lines": e["lines"], "absorbed": sorted(e["sources"])})
    dupes = [k for k, n in Counter(m["key"] for m in out).items() if n > 1]
    if dupes:
        raise SystemExit(f"  TWO CATEGORIES SHARE A KEY: {dupes[:5]} - refusing to write. "
                         f"A key names one category or it names nothing.")
    return out


UNCATEGORISED = "Not Yet Categorized"
# THE ONLY VALID SCOPE GATES - Sameer, 2026-08-12: *"scope gates will only be from these 3 -
# Clinical / Non-Clinical / Non-Procurement"*. Anything else at Level 0 is not a scope gate and does
# not belong in the merged taxonomy. Measured the same day: 'Tail Spend' was 2 placeholder nodes
# (key 2992 at two hospitals, 'Tail Spend' repeated at L1 and L2) carrying ZERO lines, and
# 'Inter-Hospital Spend' is already excluded by the scope rule. Dropping them costs no lines.
ROOTS = ("Clinical", "Non-Clinical", "Non-Procurement")


def pad_to_four(levels, seed=""):
    """EVERY path carries all four category levels. Sameer, 2026-08-12.

        'Non-Clinical > Staff Related Cost > Employee Benefits'
     -> 'Non-Clinical > Staff Related Cost > Employee Benefits > Employee Benefits > Employee Benefits'

    The deepest filled label is repeated into every level below it, so L1-L4 are always populated
    and no path is ever 3 levels or 5. This is not a new convention - it is the one a hospital
    already uses (487 of 789 nodes carrying an L4 held a copy of L3) and the one CBORD uses
    (3,104 of 3,683). It replaces the '(not used at this level)' marker for the merged taxonomy.

    `seed` is the SCOPE GATE, and it exists for the one node that has nothing below it.
    2026-08-14: Sameer added `Clinical` as a handoff marker - *"from LVL 0 to LVL 5 ... just says
    clinical"*. `canonical()` collapses consecutive repeats, so the five he typed reduce to one
    segment and there are no deeper levels left to repeat. Seeded with "" this returned four BLANK
    levels, which contradicts this function's own first line and would have written a suggestion
    with an empty LEVEL_1..4 into qa_line - where five values are expected by construction.
    Seeding with the gate makes the deepest filled label L0 itself, which is what the docstring
    always said. INERT for every other node: all 349 have at least one level below the gate, so
    `last` is overwritten on the first iteration and the seed is never seen.

    DISPLAY ONLY. Matching, merging and line conservation all run on the COLLAPSED path - pad
    there and every comparison would measure padding again, which is the error the whole merge was
    built to avoid. `canonical()` is still the single truth for identity.
    """
    out, last = [], seed
    for v in (list(levels) + [""] * 4)[:4]:
        last = v or last
        out.append(last)
    return out


def pad_path(path):
    """A full path string padded to four category levels. Left alone if it is not a path."""
    if not path:
        return path
    segs = [s for s in path.split(" > ") if s]
    if not segs or segs[0] not in ROOTS:
        return path
    return " > ".join([segs[0]] + [x for x in pad_to_four(segs[1:], seed=segs[0]) if x])


def carry_uncategorised(levels):
    """Once a level reads Not Yet Categorized, EVERY deeper level reads it too.

    Sameer, 2026-08-12: *"if 3rd level is not yet categorised the 4th level also needs to be
    uncategorised."* The two empty-level markers mean opposite things and only one of them was
    being used:

        '(not used at this level)'  this category legitimately has a short path
        'Not Yet Categorized'       the deeper level is UNKNOWN, not absent

    Leaving the deeper levels blank on an uncategorised node asserts the first when the truth is
    the second - it says the path is complete when nobody has yet decided what it is. 19 nodes and
    245,989 lines were being described that way.

    The canonical PATH is untouched: it still collapses consecutive repeats, so nothing about
    matching, merging or line conservation changes. This is what the level COLUMNS say, which is
    what a downstream system reads.
    """
    out, seen = [], False
    for v in levels:
        if seen:
            out.append(UNCATEGORISED)
            continue
        out.append(v)
        if loose(v) == loose(UNCATEGORISED):
            seen = True
    return out


DEC_HEADER = ["DECISION_TYPE", "CLIENT_CODE", "DETAIL", "OPTION_A", "OPTION_A_LINES",
              "OPTION_B", "OPTION_B_LINES", "LINES_AT_STAKE", "SAMEERS_RULING",
              "ALSO_APPLIES_TO", "CARRIED_FROM", "DECISION_ID"]


def read_decisions(path):
    """Rows of a DECISIONS file as dicts. Reads .xlsx and .csv - Sameer works in Excel."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(path, data_only=True).active
        it = ws.iter_rows(values_only=True)
        hdr = [str(h or "").strip() for h in next(it)]
        return [dict(zip(hdr, [("" if v is None else str(v)) for v in row])) for row in it]
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def newest_rulings_file(outdir=None):
    """The most recent DECISIONS file that actually carries a ruling. None if there is none."""
    outdir = outdir or OUTDIR
    if not os.path.isdir(outdir):
        return None
    # BY MODIFICATION TIME, not by name. Sorting by name put '... - 2026-08-12 v2.xlsx' BEFORE
    # '... - 2026-08-12.xlsx' - a space sorts below a dot - so the run kept reading the superseded
    # file and re-writing the same version every time, which looked like a stable loop and was one.
    cands = []
    for fn in os.listdir(outdir):
        if "DECISIONS NEEDED" not in fn or fn.startswith("~$"):
            continue
        if not fn.lower().endswith((".xlsx", ".xlsm", ".csv")):
            continue
        p = os.path.join(outdir, fn)
        try:
            if any((r.get("SAMEERS_RULING") or "").strip() for r in read_decisions(p)):
                cands.append((os.path.getmtime(p), p))
        except Exception:
            continue
    return max(cands)[1] if cands else None


def load_rulings(path):
    """Read Sameer's answers back in, so a re-run never asks a settled question twice.

    A returned decisions file is the same class of artefact as a returned review workbook: his
    column exists nowhere else. It is read as an INPUT and never written back to.

    Accepts what a person actually types - 'Option A', 'A', or the literal label or path. The
    letter form is resolved against the file it was written in, because A and B can change places
    when the file is regenerated; the resolved TEXT is what gets stored.

    Returns (spelling, targets, raw, keep, rejected, adds):
      spelling  loose label -> the spelling that wins, overriding the line-count winner
      targets   (client, CANONICAL PATH) -> the path it was ruled onto ('' = keep as its own)
      raw       fingerprint -> the ruling text, for carrying an unchanged question forward
      adds      canonical paths Sameer has ADDED that no client's taxonomy holds
      renames   (label a, label b, new label) he has RENAMED outright, no variant needed
      drops     canonical paths REMOVED from the taxonomy - their lines get no target at all
    """
    spelling, targets, raw, keep, rejected, adds, renames, drops = {}, {}, {}, set(), [], [], [], []
    defines = {}
    if not path or not os.path.exists(path):
        return spelling, targets, raw, keep, rejected, adds, renames, drops, defines
    if True:
        for r in read_decisions(path):
            ruling = (r.get("SAMEERS_RULING") or "").strip()
            if not ruling:
                continue
            a, b = (r.get("OPTION_A") or "").strip(), (r.get("OPTION_B") or "").strip()
            low = ruling.lower().replace("option", "").strip()
            if low == "a":
                ruling = a
            elif low == "b":
                ruling = b
            dtype, detail = (r.get("DECISION_TYPE") or "").strip(), (r.get("DETAIL") or "").strip()
            if MANUAL_DEFINE in dtype.upper():
                # DETAIL is the path being defined; the RULING is the definition itself. Unlike
                # every other decision type the ruling is prose, not a path, so it is NOT run
                # through canonical() and NOT validated against ROOTS.
                dp = " > ".join(canonical(detail.split(" > ")))
                if dp:
                    defines[dp] = ruling
                continue
            if MANUAL_ADD in dtype.upper():
                # A CATEGORY THAT NO HOSPITAL HAS YET. Every other node in this taxonomy is derived
                # from a client's own table, so the merge had no way to express "this category
                # should exist" - Sameer, 2026-08-13, adding CCTV Camera under Fires Safety and
                # Security. It enters with ZERO lines and zero source nodes, which is the honest
                # reading: nothing is filed there until a rule or an analyst puts it there. Line
                # conservation is untouched by design.
                p = " > ".join(canonical(ruling.split(" > ")))
                if p.split(" > ")[0] not in ROOTS or len(p.split(" > ")) > 5:
                    rejected.append((r.get("CLIENT_CODE"), detail, ruling))
                    continue
                adds.append(p)
                continue
            if MANUAL_DROP in dtype.upper():
                # REMOVING A CATEGORY IS NOT REMOVING ITS SPEND. Sameer, 2026-08-13:
                # *"remove any lines in our taxonomy if a level 2 is named other"*. Those lines
                # exist; what they lose is a target category, because they never had a real one.
                # The node stays in the crosswalk with basis 'dropped_by_ruling' so the count is
                # visible, and conservation becomes in == out + dropped rather than in == out.
                # Deleting a node quietly would make 326,147 lines disappear from every total with
                # nothing looking broken - the exact failure mode this file exists to prevent.
                drops.append(" > ".join(canonical(ruling.split(" > "))))
                continue
            if MANUAL_RENAME in dtype.upper():
                # RENAMING A LABEL IS NOT THE SAME QUESTION AS UNIFYING A VARIANT, and the
                # difference is why this needs its own type. `unify_spellings` only ever reports
                # labels that are two spellings of one word sitting under the same parent, so a
                # ruling on anything else - 'Fires' -> 'Fire' where every hospital spells it
                # 'Fires', or 'Hand Cleaner' + 'Hand or body cleanser' -> 'Sanitizers', which are
                # two different phrases - generates NO row to carry the answer on the next run.
                # The relabel would apply once, vanish from the file, and the taxonomy would revert
                # with nothing looking broken. Sameer, 2026-08-13.
                if not ruling or ruling.split(" > ")[0] in ROOTS:
                    rejected.append((r.get("CLIENT_CODE"), detail, ruling))
                    continue
                renames.append((a, b, ruling))
                for label in (a, b):
                    if label:
                        spelling[loose(label)] = ruling
                continue
            raw[(dtype, detail, a, b)] = ruling
            if "spelling" in dtype or dtype.startswith("ALMOST"):
                # THREE possible answers, not two. Sameer, 2026-08-12: *"yes direct and indirect
                # care are 2 different things"* - and the row had no way to say that, so a single
                # label was the only thing to write and a single label means MERGE. Free text is
                # read too, because that is what a person types when the form has no box for the
                # answer they want: he wrote *"Pasta and Paste are two different products, cant be
                # clubbed"* rather than leave it blank.
                if KEEP_BOTH_RE.search(ruling):
                    keep.add(frozenset((loose(a), loose(b))))
                    continue
                m = MERGE_AS_RE.match(ruling)
                lbl = m.group(1).strip() if m else ruling
                for label in (a, b):
                    if label:
                        spelling[loose(label)] = lbl
            else:
                # A typed ruling goes through the same collapse a path does, so
                # '... > Not Yet Categorized > Not Yet Categorized' is not a different answer from
                # '... > Not Yet Categorized'. Sameer types the repeat; it is not an error.
                ruling = " > ".join(canonical(ruling.split(" > ")))
                detail = " > ".join(canonical(detail.split(" > ")))
                # A MAPPING RULING MUST BE A PATH. Sameer wrote a question in the ruling column -
                # *"isnt this a medical level?"* - and it was taken as a destination, minting a
                # CATEGORY of that name holding 18,580 lines. Anything that is not a path rooted in
                # the scope gate is refused and reported; the question stays an open decision.
                if ruling.split(" > ")[0] not in ROOTS:
                    rejected.append((r.get("CLIENT_CODE"), detail, ruling))
                    continue
                for client in [c.strip() for c in (r.get("CLIENT_CODE") or "").split(",")]:
                    if client:
                        # echoing the detail back means "keep it, do not fold it into anything"
                        tgt = "" if loose(ruling) == loose(detail) else ruling
                        targets[(client, detail.upper())] = tgt
    return spelling, targets, raw, keep, rejected, adds, renames, drops, defines


# Rows of these types carry an INSTRUCTION, not an answer to a question the merge asked. They are
# the decision types the tool never generates for itself, and the only ones whose content cannot be
# rebuilt from the source taxonomies - so they are written back verbatim on every run.
MANUAL_ADD = "MANUAL ADD"
# 🔒 MANUAL DEFINE, 2026-08-24. WHAT A CATEGORY EXCLUDES, IN SAMEER'S WORDS.
#
# The judge is shown a `definition` for every candidate category and ALL 353 were empty, so it had
# a category's NAME and nothing telling it where the boundary is. Measured: 11 pilot lines named
# their item correctly - "is biscuits", "is a beverage", "is cleaning supplies" - and were filed
# under Stationery & Printing anyway, because the vendor was an office-supplies retailer.
#
# 🔑 IT LIVES HERE AND NOT IN THE MERGED WORKBOOK. Every other output file is regenerated on each
# emit, so a definition typed into one is destroyed by the next run. The DECISIONS workbook is the
# only file that holds a human answer and is read back as an INPUT - the same property that makes
# it the store for every ruling. Written back verbatim on every run, like ADD / RENAME / DROP.
MANUAL_DEFINE = "MANUAL DEFINE"
MANUAL_RENAME = "MANUAL RENAME"
MANUAL_DROP = "MANUAL DROP"
KEEP_BOTH = "KEEP BOTH - two different categories"
KEEP_BOTH_RE = re.compile(
    r"keep\s+both|two\s+different|different\s+(thing|product|categor)|not\s+the\s+same"
    r"|can'?t\s+be\s+(clubbed|merged|combined)|separate", re.I)
MERGE_AS_RE = re.compile(r"^\s*merge\b[^'\"]*['\"](.+?)['\"]", re.I)


def _did(key):
    """Stable identity for a decision, independent of how the row is worded.

    The overwrite guard asks "is this ruling carried into the new content?" and it must not answer
    "no" merely because the question was rephrased - which is exactly what happened when the
    almost-the-same-label rows gained their line counts, and a settled answer looked lost."""
    import hashlib
    return hashlib.md5(" | ".join(str(k) for k in key).encode("utf-8")).hexdigest()[:10]


def decisions(rows, near=(), spell=(), carried=None, src="", kept=(), adds=(), renames=(),
              drops=(), defines=None):
    """Build the open-decision list, ONE ROW PER DISTINCT DECISION.

    Sameer, 2026-08-12, looking at two rows carrying identical options: *"seems like the same
    thing"*. He was right - the file asked him the same question once per source node, so the
    Not/Non typo arrived nine times and two ICT rows arrived as separate decisions with the same
    two options. A decision is now keyed by what is actually being decided, and everywhere it
    applies is listed beside it.

    Sorted by lines at stake, because the previous order put zero-line nodes above 96,016-line ones.
    """
    carried = carried or {}
    agg = {}

    def _pair_detail(lvl, a, la, b, lb, where):
        return (f"L{lvl} under {', '.join(where[:3])}{' +more' if len(where) > 3 else ''}: "
                f"'{a}' ({la:,} lines)  vs  '{b}' ({lb:,} lines)")

    def add(key, dtype, detail, a, la, b, lb, lines, who, applies="", ruling=""):
        e = agg.setdefault(key, {"type": dtype, "detail": detail, "a": a, "la": la, "b": b,
                                 "lb": lb, "lines": 0, "who": set(), "applies": set(),
                                 "ruling": ruling, "id": _did(key)})
        e["lines"] += lines
        e["who"].update(w for w in who if w)
        e["ruling"] = e["ruling"] or ruling
        if applies:
            e["applies"].add(applies)

    defines = defines or {}
    for raw, p in adds:
        # Written back as an ANSWERED row so the instruction lives in the same file as every other
        # ruling. Drop it and the category disappears on the next run with nothing looking broken -
        # it has no source node to regenerate it from.
        #
        # IDENTITY IS THE PATH AS TYPED, not the path after relabelling. Renaming 'Fires Safety and
        # Security' to 'Fire ...' moved the added CCTV category underneath it, so the row's id
        # changed, so the overwrite guard read its own output as a lost ruling and spawned a ` v2`.
        # The answer has not changed just because a label above it has.
        add(("add", raw.upper()), f"ANSWERED ({MANUAL_ADD}) - category added, no source lines",
            p, p, 0, "", "", 0, [], ruling=p)
    for dp, dtext in sorted(defines.items()):
        # Nothing in the source data regenerates a definition, so if it is not written back it is
        # gone on the next emit - the same reason ADD and DROP are written back.
        add(("define", dp.upper()), f"ANSWERED ({MANUAL_DEFINE}) - definition set by Sameer",
            dp, dp, 0, "", "", 0, [], ruling=dtext)
    for d in drops:
        # A DROP has to be written back for the same reason an ADD does, and the cost of forgetting
        # is larger: the categories come straight back on the next run and 326,147 lines silently
        # re-acquire a target. Caught by the overwrite guard on 2026-08-13 - it spawned a ' v2'
        # rather than lose the rulings, which is exactly the job it was built for.
        add(("drop", d.upper()), f"ANSWERED ({MANUAL_DROP}) - Level 2 named Other, removed",
            d, d, 0, "", "", 0, [], ruling=d)
    for a, b, new in renames:
        # Same reason as the adds: nothing in the source data regenerates this row, so if it is not
        # written back the label reverts on the next run.
        add(("rename", loose(a), loose(b)),
            f"ANSWERED ({MANUAL_RENAME}) - label set by Sameer",
            f"{a}{' + ' + b if b else ''}  ->  {new}", a, "", b, "", 0, [], ruling=new)
    for lvl, a, la, b, lb, where, d in near:
        # NOT called a spelling variant, and NOT a two-option question. 'Direct Care Services' and
        # 'Indirect Care Services' are two characters apart and opposite in meaning, so the answer
        # is usually "keep both" - which the first version of this row could not express. A is the
        # SAFE answer and comes first; B names the surviving label explicitly so "B" is unambiguous.
        # OPTION_A / OPTION_B hold the LABELS, never the instructions. The first version put
        # "KEEP BOTH..." in A and "MERGE - use..." in B, which read well and broke the round-trip:
        # reading the file back, the two columns no longer said which pair the answer was about,
        # so every KEEP BOTH ruling was silently dropped on the next run. The third option lives
        # in the instruction text; the columns stay machine-readable.
        add(("spell", loose(a), loose(b)), "ALMOST the same label - one thing, or two?",
            _pair_detail(lvl, a, la, b, lb, where), a, la, b, lb, la + lb, [],
            f'A or B = they are ONE thing, use that label  ·  or type "{KEEP_BOTH}"')
    for lvl, a, la, b, lb, where, d in kept:
        add(("spell", loose(a), loose(b)), "ANSWERED (spelling) - no action needed",
            _pair_detail(lvl, a, la, b, lb, where), a, la, b, lb, la + lb, [], "",
            ruling=KEEP_BOTH)
    for lvl, was, now, ln, where, d, was_ruled in spell:
        if was_ruled:
            add(("spell", loose(was), loose(now)), "ANSWERED (spelling) - no action needed",
                f"L{lvl} under {', '.join(where[:3])}{' +more' if len(where) > 3 else ''}",
                was, ln, now, "", ln, [], "", ruling=now)
            continue
        add(("spell", loose(was), loose(now)), "spelling ALREADY unified (confirm)",
            f"L{lvl} under {', '.join(where[:3])}{' +more' if len(where) > 3 else ''}",
            was, ln, now, "", ln, [], "")
    for r in rows:
        if r["basis"] == "uncategorised_by_rule":
            # Shown, not asked. It stays visible as a settled row so the file still accounts for
            # every node, and so a ruling already written against it is not reported as lost.
            add(("nyc", r["canon_up"]), "ANSWERED (by rule) - uncategorised to Level 4",
                r["canon"], r["canon"], r["lines"], "", "", r["lines"], [r["client"]],
                ruling=r["canon"])
            continue
        if r.get("ruled"):
            # ANSWERED decisions stay in the file. They are not questions any more, but his column
            # exists nowhere else - dropping the row would make the answer survive only as long as
            # the previous file did, and the previous file is regenerable-looking clutter that
            # somebody will eventually tidy away. One file, questions and answers together.
            add(("done", r["client"], r["canon_up"]), "ANSWERED (mapping) - no action needed", r["canon"],
                r["target"] or r["canon"], r["lines"], "", "", r["lines"], [r["client"]],
                ruling=(r["target"] or r["canon"]))
            continue
        if r["basis"] == "unmapped":
            add(("home", r["canon_up"]), "no home in the merged taxonomy", r["canon"],
                "", "", "", "", r["lines"], [r["client"]])
        elif r["basis"] == "leaf_crosses_branch":
            # A = LEAVE IT WHERE IT IS, B = move to the proposed home. Sameer, 2026-08-12: *"you
            # have not provided me with option B"* - the row had listed a second candidate in B,
            # which is almost always empty here, so the question arrived with one option and no way
            # to say no. Every row that offers a choice now offers both sides of it, and A means
            # "keep" on this type exactly as it does on a granularity row.
            c = r["candidates"] or []
            add(("cross", r["canon_up"], c[0] if c else ""),
                "moving this to another top-level branch - confirm",
                r["canon"], r["canon"], r["lines"], c[0] if c else "", "",
                r["lines"], [r["client"]],
                ("other possible homes: " + " | ".join(c[1:])) if len(c) > 1 else "")
        elif r["basis"].endswith("_ambiguous"):
            c = r["candidates"] or []
            add(("amb", c[0] if c else "", c[1] if len(c) > 1 else ""), "several possible homes",
                r["canon"], c[0] if c else "", "", c[1] if len(c) > 1 else "", "",
                r["lines"], [r["client"]], r["canon"])
        elif r["merged_away"]:
            add(("gran", r["canon_up"], (r["target"] or "").upper()),
                "GRANULARITY CHANGE - sign off", r["canon"], r["canon"], r["lines"],
                r["target"], "", r["lines"], [r["client"]])

    # Open questions first, biggest first; answered rows kept underneath as the record.
    out = []
    for e in sorted(agg.values(), key=lambda x: (x["type"].startswith("ANSWERED"), -x["lines"])):
        applies = sorted(a for a in e["applies"] if a != e["detail"])
        prev = e["ruling"] or carried.get((e["type"], e["detail"], e["a"], e["b"]), "")
        out.append([e["type"], ", ".join(sorted(e["who"])), pad_path(e["detail"]),
                    pad_path(e["a"]), e["la"], pad_path(e["b"]), e["lb"], e["lines"],
                    pad_path(prev), " | ".join(applies),
                    os.path.basename(src) if prev else "", e["id"]])
    return out


def emit(rows, merged, group, pairwise, near=(), spell=(), dec_rows=(), defines=None):
    """Write the working files to output/Taxonomy/. Regenerable - never hand-edit these."""
    os.makedirs(OUTDIR, exist_ok=True)
    stamp = date.today().isoformat()

    # A DECISIONS file carrying a ruling is NOT regenerable - Sameer's column exists nowhere else,
    # exactly like a returned review workbook. Re-running on the same day would otherwise write
    # straight over the answers that were just read back in. Version instead of overwrite.
    # Overwrite only when EVERY ruling in the file being replaced is already carried in the new
    # content. That is the precise test: "it has answers in it" would version on every re-run and
    # fill the folder back up, "it is regenerable" would delete answers that exist nowhere else.
    have = {r[11] for r in dec_rows if str(r[8]).strip()}
    # compare on the COLLAPSED form: a padded answer and an unpadded one are the same answer
    _c = lambda s: loose(" > ".join(canonical(str(s or "").split(" > "))))
    have_txt = {(_c(r[2]), _c(r[8])) for r in dec_rows if str(r[8]).strip()}
    v = 1
    while True:
        suffix = f"{stamp}" + ("" if v == 1 else f" v{v}")
        cand = os.path.join(OUTDIR, f"Indirect Taxonomy - DECISIONS NEEDED - {suffix}.xlsx")
        if not os.path.exists(cand):
            break
        try:
            lost = [r for r in read_decisions(cand)
                    if (r.get("SAMEERS_RULING") or "").strip()
                    and (r.get("DECISION_ID") or "") not in have
                    and (_c(r.get("DETAIL")), _c(r.get("SAMEERS_RULING"))) not in have_txt]
        except Exception:
            lost = [1]                   # unreadable is treated as precious, never as disposable
        if not lost:
            break
        print(f"  {len(lost)} ruling(s) in {os.path.basename(cand)} are not carried forward "
              f"- writing a new version rather than overwriting them")
        v += 1
    stamp = suffix

    # ONE decisions file, and it is .xlsx: it is the sheet Sameer answers in, and it is read back
    # as the rulings input. A second CSV of the same content is a second place an answer can live.
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "DECISIONS"
    ws.append(DEC_HEADER)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="404040")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    grey = PatternFill("solid", fgColor="EFEFEF")
    for r in dec_rows:
        ws.append(list(r))
        if str(r[0]).startswith("ANSWERED"):
            for c in ws[ws.max_row]:
                c.fill = grey
    for col, wid in zip("ABCDEFGHIJK", (34, 22, 60, 55, 12, 55, 12, 14, 45, 60, 34)):
        ws.column_dimensions[col].width = wid
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    dec_path = os.path.join(OUTDIR, f"Indirect Taxonomy - DECISIONS NEEDED - {stamp}.xlsx")
    wb.save(dec_path)
    # THE TAXONOMY ITSELF - the readable deliverable. Full path first, then the five levels each in
    # its own column, sorted so the tree reads top to bottom. Levels and path are built from the
    # same list, so the two can never disagree - they did once: the columns read Not Yet
    # Categorized down to L4 while the path stopped at L2, because `canonical()` collapses
    # consecutive repeats. That collapse is right for padding ('Audio Visual Equipment > Audio
    # Visual Equipment' carries no information) and wrong for the uncategorised marker, where the
    # repeat says the deeper level is UNKNOWN. Padding is applied at output only; matching still
    # runs on the collapsed path.
    defines = defines or {}
    rows_out = []
    for m in merged:
        lv = pad_to_four(carry_uncategorised((m["levels"] + [""] * 5)[1:5]), seed=m["levels"][0])
        path = " > ".join([m["levels"][0]] + [x for x in lv if x])
        rows_out.append([path, m["levels"][0], *lv, m["key"], len(m["clients"]),
                         m["nodes"], m["lines"], " | ".join(m["absorbed"]),
                         defines.get(" > ".join(canonical(path.split(" > "))), "")])
    rows_out.sort(key=lambda r: r[0])

    TAX_HEADER = ["FULL_PATH", "LEVEL_0", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4",
                  "INDIRECT_KEY", "HELD_BY_CLIENTS", "SOURCE_NODES", "LINES",
                  "ABSORBED_VARIANTS", "DEFINITION"]
    csv_path = os.path.join(OUTDIR, f"Indirect Taxonomy - MERGED - {stamp}.xlsx")
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "INDIRECT TAXONOMY"
    ws.append(TAX_HEADER)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="404040")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    band = PatternFill("solid", fgColor="F2F2F2")
    prev_l1 = None
    for r in rows_out:
        ws.append(r)
        if r[2] != prev_l1:                 # a faint band each time Level 1 changes
            prev_l1 = r[2]
            for c in ws[ws.max_row]:
                c.fill = band
    for col, wid in zip("ABCDEFGHIJK", (90, 15, 30, 34, 38, 38, 12, 15, 13, 11, 40)):
        ws.column_dimensions[col].width = wid
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(csv_path)

    cw_path = os.path.join(OUTDIR, f"Indirect Taxonomy - CROSSWALK - {stamp}.csv")
    with open(cw_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["CLIENT_CODE", "SOURCE_KEY", "SOURCE_PATH_STORED", "SOURCE_PATH_CANONICAL",
                    "LINES", "MAPPING_BASIS", "CONFIDENCE", "TARGET_INDIRECT_KEY", "TARGET_PATH",
                    "GRANULARITY_CHANGED"])
        bykey = {m["canon_up"]: m for m in merged}
        for r in rows:
            t = None if r.get("dropped") else bykey.get(r["resolved"])
            w.writerow([r["client"], r["key"], r["stored_path"], r["canon"], r["lines"],
                        "dropped_by_ruling" if r.get("dropped") else r["basis"],
                        r["confidence"], t["key"] if t else "",
                        pad_path(t["path"]) if t else "",
                        "YES" if r["merged_away"] else ""])
    return csv_path, cw_path, dec_path, len(merged)


def main(commit, do_emit=False):
    cn = qcur = None
    try:
        cn = connect_qa()
        qcur = cn.cursor()
        nodes = load_nodes(qcur)
    finally:
        if cn and not commit:
            cn.close()

    off = [n for n in nodes if (n["canon"].split(" > ")[0] if n["canon"] else "") not in ROOTS]
    if off:
        for n in off:
            nodes.remove(n)
        print(f"\n  NOT A SCOPE GATE - dropped: {len(off)} node(s), "
              f"{sum(n['lines'] for n in off):,} lines")
        for n in off:
            print(f"     {n['client']:18} {n['lines']:>7}  {n['canon'] or '(empty path)'}")

    print(f"\n  in-scope (indirect) nodes loaded: {len(nodes):,}"
          f"   across {len({n['client'] for n in nodes})} clients")

    rulings_file = newest_rulings_file()
    (forced_spelling, forced_targets, carried, keep_both,
     rejected, adds, renames, drops, defines) = load_rulings(rulings_file)
    if rulings_file:
        print(f"\n=== 0. SAMEER'S RULINGS READ BACK IN ===")
        print(f"  from {os.path.basename(rulings_file)}")
        if rejected:
            print(f"\n  !! {len(rejected)} RULING(S) REFUSED - not a category path, not applied.")
            print(f"     They stay OPEN. A ruling must start with one of {ROOTS}.")
            for c, d, v in rejected:
                print(f"       {c}  {d[:64]}")
                print(f"          you wrote: {v!r}")
        print(f"  {len(carried)} answered: {len(forced_spelling)//2 or len(forced_spelling)} "
              f"spelling, {len(keep_both)} kept-apart, {len(forced_targets)} mapping, "
              f"{len(adds)} added category. These are not asked again.")
        for p in adds:
            print(f"     ADDED (no source node, 0 lines): {p}")
        # `adds` is still the list of paths as typed at this point; relabelling happens after
        # mapping, and what is printed here is what the file holds.
        for a, b, new in renames:
            print(f"     RENAMED: {a!r}{' + ' + repr(b) if b else ''} -> {new!r}")
        for d in drops:
            print(f"     DROPPED from the taxonomy (lines keep no target): {d}")

    nodes, auth = load_authoritative(nodes)
    if auth:
        print(f"\n=== 0a. AUTHORITATIVE SOURCE SWAPPED IN ===")
        for a in auth:
            print(f"  {a['client']}  branch {a['branch']!r}  <- {a['table']}")
            print(f"      out: {a['removed']:>4} nodes / {a['removed_lines']:>9,} lines"
                  f"   in: {a['added']:>4} nodes / {a['added_lines']:>9,} lines")
            if a["orphans"]:
                print(f"      {a['orphans']} paths are IN USE but not in the authority list "
                      f"({a['orphan_lines']:,} lines) - kept and flagged, never dropped")

    spell_raw, sp_rw = unify_spellings(nodes, forced_spelling)
    grp = defaultdict(lambda: {"lines": 0, "where": set()})
    for parent, lvl, was, now, lines in spell_raw:
        g = grp[(lvl, was, now)]
        g["lines"] += lines
        g["where"].add(parent.split(" > ")[-1] if parent else "(top level)")
    spell = [(lvl, was, now, g["lines"], sorted(g["where"]), 0, loose(was) in forced_spelling)
             for (lvl, was, now), g in sorted(grp.items(), key=lambda x: -x[1]["lines"])]
    print(f"\n=== 0b. SIBLING SPELLING VARIANTS UNIFIED (before any matching) ===")
    if not spell:
        print("  none found")
    for lvl, was, now, lines, where, d, ruled in spell[:10]:
        tag = "  (Sameer's ruling)" if ruled else ""
        print(f"  L{lvl} under {', '.join(where)[:24]:24} {was[:28]!r:30} -> {now[:28]!r}"
              f"  ({lines:,} lines){tag}")
    if len(spell) > 10:
        print(f"  ... and {len(spell)-10} more")

    auto, near, kept = typo_pairs(nodes, keep_both, forced_spelling)
    typo, ty_rw = apply_typos(nodes, auto, forced_spelling)
    forced_targets = {(c, remap_path(p, sp_rw, ty_rw).upper()): t
                      for (c, p), t in forced_targets.items()}
    print(f"\n=== 0c. TYPO PAIRS - one edit apart, UNIFIED (was missed until 2026-08-12) ===")
    if not typo:
        print("  none found")
    for lvl, was, now, ln, where, d, ruled in typo:
        tag = "  (Sameer's ruling)" if ruled else ""
        print(f"  L{lvl} {was[:26]!r:28} -> {now[:26]!r}  ({ln:,} lines) "
              f"under {len(where)} parent(s){tag}")
    if near:
        print(f"\n=== 0d. TWO edits apart - NOT merged, needs a ruling ===")
        for lvl, a, la, b, lb, where, d in near:
            print(f"  L{lvl} {a[:28]!r:30} ({la:>8,})  vs  {b[:28]!r:30} ({lb:>8,})"
                  f"  under {', '.join(where[:2])}")

    dups = internal_duplicates(nodes)
    dup_nodes = sum(len(v) - 1 for v in dups.values())
    print(f"\n=== 1. DUPLICATION INSIDE EACH TAXONOMY (resolve before merging) ===")
    per = Counter(k[0] for k in dups)
    for c in sorted(per):
        print(f"  {c:20} {per[c]:4} canonical paths carry more than one node")
    print(f"  {'TOTAL':20} {dup_nodes:4} nodes collapse away before any cross-client work")

    group, pairwise, by_client = agreeing_group(nodes)
    print(f"\n=== 2. WHO ALREADY AGREES (canonical overlap, measured) ===")
    for (a, b), v in sorted(pairwise.items(), key=lambda x: -x[1]):
        mark = "  <- spine" if a in group and b in group else ""
        print(f"  {a:20} vs {b:20} {100*v:5.1f}%{mark}")
    print(f"\n  agreeing group -> {', '.join(sorted(group))}")
    print(f"  outliers       -> {', '.join(sorted(set(by_client) - group)) or '(none)'}")

    spine, minority, prefixes, by_leaf, by_leaf_loose = build_spine(nodes, group)
    display = {}
    for n in nodes:
        display.setdefault(n["canon_up"], n["canon"])
    print(f"\n=== 3. THE MERGED TAXONOMY ===")
    print(f"  spine  (held by at least half the agreeing group) : {len(spine):,}")
    print(f"  minority (one member only - review before adopting): {len(minority):,}")
    print(f"  ancestor prefixes the spine implies               : {len(prefixes):,}")

    TIERS = ["exact", "uncategorised_by_rule", "ruled_kept", "ruled_mapped", "leaf_moved", "leaf_moved_ambiguous",
             "leaf_variant", "leaf_variant_ambiguous", "leaf_crosses_branch", "parent_match",
             "unmapped", "malformed"]
    rows, tally, lines_by = [], Counter(), Counter()
    for n in nodes:
        basis, target, conf, cands = propose_mapping(
            n, spine, prefixes, by_leaf, by_leaf_loose, display)
        # A ruling outranks the matcher. It is a decision, not a proposal.
        ruled = (n["client"], n["canon_up"]) in forced_targets
        if ruled:
            t = forced_targets[(n["client"], n["canon_up"])]
            basis, target, conf, cands = ("ruled_mapped" if t else "ruled_kept"), (t or None), 1.0, None
        tally[(n["client"], basis)] += 1
        lines_by[basis] += n["lines"]
        rows.append({**n, "basis": basis, "target": target, "confidence": conf,
                     "candidates": cands, "ruled": ruled})

    print(f"\n=== 4. PROPOSED CROSSWALK - every node accounted for ===")
    tot = Counter(r["basis"] for r in rows)
    print(f"  {'tier':26}" + "".join(f"{c.split('_')[0][:8]:>10}" for c in sorted(by_client))
          + f"{'TOTAL':>9}{'lines':>13}")
    for t in TIERS:
        if not tot[t]:
            continue
        print(f"  {t:26}" + "".join(f"{tally[(c,t)]:>10}" for c in sorted(by_client))
              + f"{tot[t]:>9}{lines_by[t]:>13,}")
    assert len(rows) == len(nodes), "a node was dropped - the crosswalk must account for all of them"
    assert sum(tot[t] for t in TIERS) == len(nodes), "a node landed in no tier"
    print(f"  every one of {len(nodes):,} nodes has an outcome. No silent drops.")

    for tier, note in (
            ("leaf_moved", "same category, different depth - CONFIRM, do not re-decide"),
            ("leaf_variant", "same category, DIFFERENT SPELLING - confirm they are the same thing"),
            ("leaf_moved_ambiguous", "leaf sits at several spine paths - pick one"),
            ("leaf_variant_ambiguous", "spelling variant matches several - pick one"),
            ("leaf_crosses_branch", "the only match is in ANOTHER top-level branch - never taken "
                                    "automatically, this is a re-categorisation"),
            ("parent_match", "NEW leaf under a known parent - additive, keeps the category"),
            ("unmapped", "branch not recognised - nothing guessed"),
            ("malformed", "no category path at all - a source data defect, not a mapping decision")):
        sel = [r for r in rows if r["basis"] == tier]
        if not sel:
            continue
        print(f"\n=== {tier.upper()} - {len(sel)} nodes, {sum(r['lines'] for r in sel):,} lines "
              f"({note}) ===")
        for r in sorted(sel, key=lambda x: -x["lines"])[:6]:
            print(f"  {r['lines']:>9,}  {r['client'][:3]}  {r['canon'] or '(empty path)'}")
            if r["target"]:
                print(f"                  ->  {r['target']}")
            for c in (r["candidates"] or []):
                print(f"                  ?   {c}")
        if len(sel) > 6:
            print(f"  ... and {len(sel)-6} more")

    rows = resolve(rows)
    # A RULING ON A LABEL APPLIES TO THAT LABEL EVERYWHERE, and it has to be re-applied here.
    # `unify_spellings` runs before any mapping, so it only ever sees labels that are siblings AT
    # THAT MOMENT. Sameer's fold of the duplicated Non-Procurement branch made 'Re-imbursements'
    # (49 lines) a sibling of 'Reimbursements' (80,433) for the first time - after unification had
    # already finished - so his ruling on that spelling silently missed it and the merged taxonomy
    # carried both. Ordering, not judgement, so it is corrected rather than asked about.
    # NOTE the fields this touches. `canon` is the source node's IDENTITY - it is what a ruling is
    # keyed on - so relabelling it makes every stored answer stop matching on the next run and the
    # output stops converging. Measured that way round first: 450 categories, then 453, then a
    # spurious new version. Only the DESTINATION is relabelled; the source path is left alone and
    # a separate `display` carries the corrected label into the merged taxonomy.
    def _relabel(v):
        segs = (v or "").split(" > ")
        return " > ".join(forced_spelling.get(loose(s), s) for s in segs)

    relabelled = 0
    for r in rows:
        r["display"] = _relabel(r["canon"])
        if r.get("target"):
            r["target"] = _relabel(r["target"])
        before = r["resolved"]
        r["resolved"] = _relabel(r["resolved"]).upper()
        if r["resolved"] != before or r["display"] != r["canon"]:
            relabelled += 1
    if relabelled:
        print(f"\n  ruled spellings re-applied after mapping: {relabelled} paths")
    # The added paths carry the ruled labels too - CCTV Camera sits under a branch Sameer renamed in
    # the same file. Kept beside the path AS TYPED, which stays the row's identity (see decisions()).
    adds = [(raw, _relabel(raw)) for raw in adds]
    # A DROP MUST NOT REWRITE THE NODE'S RULING. First version blanked `target` and `basis`, so
    # decisions() wrote the node back as "keep as its own" - the mapping that had sent it to
    # `X > Other` was lost, the next run resolved it somewhere else entirely, and the drop silently
    # stopped matching: 356 categories on run 1, 375 on run 2. Same rule as 2026-08-12's *never
    # rewrite the thing you look answers up by*. The drop is a FLAG carried beside the ruling.
    drop_up = {d.upper() for d in drops}
    dropped_lines = 0
    for r in rows:
        r["dropped"] = r["resolved"] in drop_up
        if r["dropped"]:
            dropped_lines += r["lines"]
    merged = build_merged([r for r in rows if not r["dropped"]], [p for _, p in adds],
                          previous=load_previous_keys())
    deep = [m for m in merged if m["depth"] - 1 > 4]
    print(f"\n=== 5. THE MERGED INDIRECT TAXONOMY ===")
    print(f"  source nodes in            : {len(rows):,}")
    print(f"  MERGED CATEGORIES OUT      : {len(merged):,}")
    print(f"  merged away (granularity change, needs sign-off): "
          f"{sum(1 for r in rows if r['merged_away']):,} nodes, "
          f"{sum(r['lines'] for r in rows if r['merged_away']):,} lines")
    print(f"  deeper than four levels    : {len(deep)}  "
          f"{'<- MUST be resolved, will not fit' if deep else '(fits)'}")
    lines_in = sum(r["lines"] for r in rows)
    lines_out = sum(m["lines"] for m in merged)
    if dropped_lines:
        print(f"  DROPPED by ruling          : {dropped_lines:,} lines have NO target category")
    ok = lines_in == lines_out + dropped_lines
    print(f"  line conservation          : in {lines_in:,} / out {lines_out:,}"
          + (f" + dropped {dropped_lines:,}" if dropped_lines else "")
          + f" {'OK' if ok else '<- MISMATCH, investigate'}")
    byd = Counter(m["depth"] - 1 for m in merged)
    print(f"  category levels used       : " + " · ".join(f"L{k}: {byd[k]}" for k in sorted(byd)))

    # loose() prefix, not equality: Sameer ruled the branch label is 'Food & Beverages', which is
    # the plural of the constant. An equality test would silently report zero food categories.
    food = [m for m in merged if m["levels"][1:2]
            and loose(m["levels"][1]).startswith(loose(FOOD_L1_CANON))]
    print(f"\n  FOOD as a top-level branch : {len(food)} categories, "
          f"{sum(m['lines'] for m in food):,} lines  (ruled 2026-08-12)")

    dec_rows = decisions(rows, near, spell + typo, carried, rulings_file or "", kept, adds,
                         renames, drops, defines=defines)
    still_open = sum(1 for d in dec_rows if not d[8])
    print(f"\n=== 6. OPEN DECISIONS ===")
    print(f"  distinct decisions : {len(dec_rows)}  ({still_open} still unanswered)")
    for d in dec_rows[:8]:
        print(f"  {d[7]:>9,}  {d[0][:34]:34} {d[2][:58]}")

    if do_emit:
        mp, cp, dp, n = emit(rows, merged, group, pairwise, near, spell, dec_rows, defines)
        print(f"\n  WRITTEN to output/Taxonomy/:")
        print(f"    {os.path.basename(mp)}   ({n:,} merged categories)")
        print(f"    {os.path.basename(cp)}   ({len(rows):,} crosswalk rows)")
        print(f"    {os.path.basename(dp)}   ({still_open} open + "
              f"{len(dec_rows)-still_open} answered)")
        print("  Regenerable - never hand-edit. Mark decisions in a COPY.\n")
    else:
        print("\n  Nothing written. Re-run with --emit to write the working files.\n")
    if not commit:
        return
    print("  --commit is not implemented until the schema lands (task 3). Database untouched.\n")
    if cn:
        cn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit", action="store_true",
                    help="write the working files to output/Taxonomy/ (no database write)")
    ap.add_argument("--commit", action="store_true",
                    help="write the merged taxonomy and crosswalk to the pilot DB (not yet built)")
    a = ap.parse_args()
    main(a.commit, a.emit)
