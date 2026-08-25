"""The judge - decides whether each LINE's assigned category is right, and if not, what it should be.

    python pipeline/judge.py --backend deterministic          # runs now, no key, no model
    python pipeline/judge.py --backend claude_code --emit     # write a batch for Claude to judge
    python pipeline/judge.py --backend claude_code --apply verdicts.json
    python pipeline/judge.py --report

THREE BACKENDS, AND ONLY ONE OF THEM NEEDS AN API KEY
`judge_backend` in .env reads `deferred` - the decision was postponed until the unit counts were
known. They are now: 2,764,531 in-scope lines fold to 1,010,661 units at full population.

  deterministic   No model at all. Only claims what can be PROVEN from the data, and refuses to
                  guess. Its verdicts need no calibration because they are not opinions:
                  a subject holding two different categories for identical vendor + identical text
                  means at least one of them is wrong, whatever anyone thinks of either.
  claude_code     Claude reads a batch and returns verdicts; this module writes them back. No API
                  key - the model is already in the room. Hundreds of units per session, which is
                  enough for the pilot stratum and enough to calibrate against.
  api             Needs ANTHROPIC_API_KEY, which is blank. The only route to a 1M-unit census.
                  Not implemented until there is a key to test it against - a backend that has
                  never run is a liability, not an option.

WHAT THE JUDGE IS ASKED
Not "what category would you pick" - that measures the judge against itself. The question is "is
this line in the right bucket, given the buckets this hospital actually has", so the candidate set
comes from qa_category (that client's own list, ~240 in-scope categories, ~130 in real use) and
never from the model's imagination. See load_taxonomy.py for why it is a table and not a column.

UNCERTAIN IS A REAL ANSWER. It is excluded from BOTH sides of the accuracy figure with its share
stated plainly - "94% of the 91% we could judge confidently is correct" - never folded silently
into either. A judge with no Uncertain bucket is a judge that has been asked to bluff.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg  # noqa: E402
from load_taxonomy import MERGED_CLIENT  # noqa: E402
from db import connect_qa, load_env  # noqa: E402

# How many SUGGESTED_CATEGORY_LVL_* columns qa_line carries. The taxonomy's own depth is measured
# per client at apply time and may be shallower than this; it must never be deeper.
N_SUGGESTED = 5

# The vendor selector for "the lines carrying NO supplier name". A distinct object rather than
# None, because None already means "do not narrow by vendor at all" - and those are opposite
# instructions. Collapsing them would silently judge a whole hospital when the queue asked for one
# bucket of 3,387 lines. Sameer ruled 2026-08-25 that these lines stay IN the queue, ranked by
# spend like any other vendor, so this is a first-class selector and not an edge case.
NO_VENDOR_NAME = object()

# v2 (2026-08-03): the evidence hierarchy, in Sameer's words. The 25 v1 verdicts stay separable
# from every later one - that is what this column is for.
# v3 (2026-08-05): the adjudication rules. v2 said how to weigh evidence but not what to DO with a
# taxonomy that is itself defective, so those calls were made per batch and drifted - the same fact
# pattern got opposite verdicts at two hospitals until it was caught by hand. Encoded here so it is
# decided once. Sameer: "this correction should also train your judging model ... when we scale".
# v4.1 (2026-08-17, same day): THE v4 WORDING OVER-PRIMED Uncertain AND HANDED THE MODEL A FALSE
# SENTENCE. Measured: Uncertain on CATEGORISED lines went 14 -> 283 when only ~167 GL-propped
# verdicts should have moved, and 74 lines with a perfectly good description came back Uncertain
# claiming "no usable description" - a phrase v4 had literally told them to write. Sameer found it
# by hand on line 825380, "CUP MEDICINE PILL 60ML PLASTIC LATEX-FREE", and asked why a line with a
# description and a supplier needed more evidence. It did not.
# THE LESSON: narrowing what the judge may reason FROM is not the same as lowering the bar for
# answering Uncertain, and a prompt that supplies the excuse will get the excuse back. Step 2 now
# says a description is SUFFICIENT; step 3 forbids claiming text was unusable when text is present.
# v4 (2026-08-17): GL ACCOUNT AND COST CENTRE ARE NO LONGER EVIDENCE. Sameer: "we have a hard rule
# that the GL will never be used to make any judge or assumption, neither the cost centre ... if the
# item description doesnt give us that granularity, it would be manually sorted by the analyst."
# This REVERSES the 2026-08-03 instruction that made them the step-3 fallback, so v3 and v4 verdicts
# are NOT comparable on the lines that have no usable description - which is exactly what this
# column exists to make visible.
# v5 (2026-08-17): THE GL LEAK IS ACTUALLY CLOSED THIS TIME - v4's claim was wrong in THREE places,
# all found by reading the output rather than the diff.
#   1. `rule.fires_on` was sent whole, so a GL rule spelled the GL out: "ACCOUNT NAME CONTAINS
#      FREIGHT". 274 pilot lines attached to such a rule; 40 rationales quoted it; 24 of those held
#      a FIRM verdict. Now filtered through an ALLOWLIST (vendor and item text only) - a blocklist
#      fails open on the next client's field names, which is how this survived v4.
#   2. Adjudication rule I still TOLD the judge to use it, ending "Such a line is usually still
#      Correct - an account named FREIGHT is where a carriage charge belongs ... Look for a second,
#      independent source: a description, A COST CENTRE, or a vendor." A v3 paragraph that the v4
#      edit walked straight past. This is what produced Correct/3of3 on Haines Medical lines whose
#      only evidence was the GL.
#   3. The UNCATEGORISED prompt still carried the v3 hierarchy verbatim - "GL and cost centre carry
#      it when the description is unusable" - so on the entire uncategorised pass the rule was
#      never in force at all.
#   Plus: gl_account_name and cost_centre_description are no longer SELECTED, only NULL literals
#   holding the column positions. They were being read out of SQL and merely omitted from the
#   payload dict, one careless edit from the judge.
# 🔑 THE LESSON, and it is the same one twice: A GUARANTEE ABOUT WHAT THE JUDGE SAW MUST BE
# MEASURED ON THE OUTPUT. v4 changed the obvious field, asserted the rule was enforced, and three
# other paths were still open. Grep the rationales, do not read the diff.
# v5 also makes two answer shapes invalid that were quietly tolerated: an `Incorrect` with no
# suggested_key (249 of 519 in v4.1 - the analyst is told they are wrong and not where to go, and
# 68 of those named the right leaf in prose), and a rationale claiming the description is missing
# when has_usable_text is true (205 in v4.1).
# v6, 2026-08-24. THREE stale statements and one new rule, found by GREPPING THE WHOLE PROMPT
# rather than by editing the obvious line - which is the lesson v4 taught at a cost: v4 claimed the
# GL was closed while three paths were still open, because the diff was read instead of the text.
#
#  1. The prompt told the judge its key would be "resolved against this hospital's own taxonomy, so
#     a category that does not exist here is rejected". FALSE since 2026-08-14, when Sameer ruled
#     suggestions come from the MERGED tree. 14 of the 353 categories exist in NO hospital's
#     taxonomy - Refrigeration Paper, Pureed Food - Other, Cutlery, CCTV Camera, the Clinical
#     hand-off - and the judge was being told they would be thrown away.
#     ⚠️ MEASURED BEFORE IT WAS CALLED A DEFECT: the judge used merged-only categories on 75 pilot
#     lines anyway, so the sentence was wrong WITHOUT being provably costly. Fixed because it is
#     false, not because a number moved.
#
#  2. Adjudication rule B named "Stationery & Printing beside General Office Supplies ... no
#     definition on either" as a standing fact. Definitions are being written, and in the merged
#     tree those two are not even siblings. Rewritten to key on the `definition` FIELD rather than
#     on a hard-coded pair, so it stays true before and after the definitions land.
#
#  3. Sameer, 2026-08-24: a line whose description is only an invoice or PO number should take
#     "a broader category of what the suppliers actually does". Asked whether he meant the narrow
#     or the broad reading, he chose BROAD, having been shown that it touches 388,510 lines (14.1%)
#     that currently resolve to Uncertain and go to the analyst.
#     🔒 WITH ONE GUARD HE AGREED TO: the vendor alone may name a DESTINATION, and may never make an
#     existing filing Correct. 61.8% of Northern's rules fire on VENDOR_NAME, so a Correct verdict
#     resting on the vendor would be the rule confirming its own input - the exact circularity
#     step 1 of the hierarchy exists to prevent. New rules 3b and 3c.
#
#  4. The uncategorised pass restates the hierarchy IN FULL and said "where it does not, leave
#     suggested_key out" - so the new rule would have been in force on one pass and not the other.
#     This is precisely how v4's GL rule was never in force on the uncategorised pass at all.
#
# ⚠️ VERDICTS EITHER SIDE OF v6 ARE NOT COMPARABLE on lines with no usable item text.
#
# v7, 2026-08-24 - THE SELF-CONTRADICTION RULE, and it exists because Sameer challenged the fix I
# had proposed. I recommended writing a definition on every category so the judge would know what
# belongs where. He asked why the models could not simply know that themselves. Reading the
# rationales settled it - THEY ALREADY DO:
#
#     "item is biscuits, not ICT hardware"
#     "item PUKKA SUPREME MATCHA TEA is a beverage, not ICT hardware"
#     "item AJAX GLSS CLNR is cleaning supplies, not ICT hardware"
#
# Every identification correct, 3of3, and every one then filed under Stationery & Printing because
# the vendor was an office-supplies retailer. 🔑 THE JUDGE IS NOT SHORT OF KNOWLEDGE. It states the
# right answer and then does not act on it - it rules out the wrong category and lets the VENDOR
# pick the replacement, which is precisely the failure step 1 of the hierarchy exists to prevent.
#
# So the fix is one rule making the rationale BINDING, not 353 definitions. Definitions remain
# worth writing as a backstop for genuinely ambiguous pairs; they are not the remedy for a judge
# that already knew the answer.
#
# 🔑 AND IT IS CHECKABLE ON THE OUTPUT, which is why this rule and not a vaguer one: the rationale
# names an item type in plain words, so a script can compare it against the category chosen and
# COUNT the contradictions. Same method that closed the GL leak - a guarantee measured on the
# output every run, never asserted from the prompt text.
PROMPT_VERSION = "v7"
# Values an owner reads. Anything else is a bug, so the writer checks.
VERDICTS = ("Correct", "Incorrect", "Uncertain")
#  basis names the STEP of the evidence hierarchy that decided the line, so the difference between a
#  verdict read off the description and one calculated from the GL account is visible in the output
#  rather than buried in the confidence number. Sameer, 2026-08-03: "confidence must show which step
#  decided it". The three model bases map one-for-one onto steps 2, 3 and 4.
BASES = ("deterministic_contradiction", "deterministic_uncategorised", "deterministic_unjudgeable",
         "vendor_and_description",   # step 2 - the ONLY basis for a confident verdict from v4
         # RETIRED at v4, kept ONLY so verdicts written before 2026-08-17 still validate. No new
         # row may carry it: there is no vendor+GL step any more. Do not delete the value - v3 rows
         # hold it, and a reader who cannot resolve a stored basis learns nothing from its absence.
         "vendor_gl_costcentre",
         "no_evidence")              # steps 3 and 4 - nothing admissible to reason from


# =====================================================================================================
#  BACKEND 1 - deterministic. Proves, never guesses.
# =====================================================================================================
def judge_deterministic(qcur, run_id, client=None):
    """Four checks. Each one is a fact about the data, not an opinion about a category.

    Anything they cannot settle is LEFT ALONE - verdict stays NULL, not 'Correct'. A judge that
    marks everything it did not examine as correct produces a beautiful accuracy figure and is
    worthless. That is the single most important line in this file.
    """
    args = [run_id, client] if client else [run_id]
    now = datetime.now()
    out = {}

    def w(alias=""):
        """The run/client filter, table-qualified. Qualification is not optional in the
        contradiction query below: qa_line appears twice there, so an unaliased client_code is
        ambiguous and SQL Server rejects it."""
        p = f"{alias}." if alias else ""
        return f"{p}run_id = ?" + (f" AND {p}client_code = ?" if client else "")

    where = w()

    # --- 1. CONTRADICTION. Same client, same vendor, same item text -> two different assigned
    # categories. At least one is wrong, and no model is needed to know it. This is the Cleanaway
    # Case B situation, and it is why the assigned category is inside unit_key: drop it and these
    # collapse into a single verdict with a real rule defect hidden underneath.
    qcur.execute(f"""
        UPDATE u SET verdict='Incorrect', confidence=1.0,
                     basis='deterministic_contradiction',
                     rationale='Same vendor and identical item text are assigned '
                       + CAST(s.n AS nvarchar(10)) + ' different categories at this hospital, so at '
                       + 'least one of them is wrong. Both were produced by the categorisation '
                       + 'process from the same input, which makes this a rule defect rather than a '
                       + 'judgement call.',
                     judge_backend='deterministic', PROMPT_VERSION=?, judged_at=?
        FROM qa_line u
        JOIN (SELECT run_id, client_code, subject_key, COUNT(DISTINCT unit_key) AS n
              FROM qa_line WHERE {where} GROUP BY run_id, client_code, subject_key
              HAVING COUNT(DISTINCT unit_key) > 1) s
          ON s.run_id=u.run_id AND s.client_code=u.client_code AND s.subject_key=u.subject_key
        WHERE {w('u')} AND u.verdict IS NULL""",
        PROMPT_VERSION, now, *args, *args)
    out["contradiction"] = qcur.rowcount

    # --- 2. NEVER CATEGORISED. Not an accuracy failure - a COVERAGE failure, and the report must
    # not conflate the two. Left as Uncertain rather than Incorrect: there is no wrong category to
    # point at, and calling it Incorrect would inflate the error rate with a different problem.
    qcur.execute(f"""UPDATE qa_line SET verdict='Uncertain', confidence=1.0,
            basis='deterministic_uncategorised',
            rationale='No category was ever assigned to this line. That is a coverage gap - no rule '
                    + 'matched it - and not a mis-categorisation. Counted and reported separately.',
            judge_backend='deterministic', PROMPT_VERSION=?, judged_at=?
        WHERE {where} AND verdict IS NULL
          AND CATEGORY_LVL_0 = 'Uncategorised'""",
        PROMPT_VERSION, now, *args)
    out["uncategorised"] = qcur.rowcount

    # --- 3. NOTHING TO JUDGE ON. No usable item text - and from v4 that is the WHOLE test.
    # ~~AND no GL account name AND no cost centre description~~ - struck 2026-08-17. Sameer:
    # *"the GL will never be used to make any judge or assumption, neither the cost centre."*
    # Once GL and cost centre are not evidence, a line with no usable description has nothing left
    # regardless of what its GL says, so requiring the GL to ALSO be blank would leave lines marked
    # judgeable that the judge is now forbidden to judge - they would come back Uncertain from the
    # model anyway, having cost three API calls to say so.
    # Measured 2026-08-17: this widens the deterministic bucket from 4 pilot lines to 297, and the
    # full-scale equivalent is 388,510 lines (14.1%). That is the price of the rule, and it is a
    # ceiling on accuracy reported honestly rather than guessed at.
    qcur.execute(f"""UPDATE qa_line SET verdict='Uncertain', confidence=1.0,
            basis='deterministic_unjudgeable',
            rationale='No usable item description. Vendor name alone is never sufficient, and GL '
                    + 'account and cost centre are not evidence for this programme. Routed to the '
                    + 'analyst for manual sorting rather than guessed at.',
            judge_backend='deterministic', PROMPT_VERSION=?, judged_at=?
        WHERE {where} AND verdict IS NULL AND DESCRIPTION_USABLE = 'N'""",
        PROMPT_VERSION, now, *args)
    out["unjudgeable"] = qcur.rowcount
    return out


# =====================================================================================================
#  BACKEND 2 - Claude Code. No API key: the model is already here.
# =====================================================================================================
def emit_batch(qcur, run_id, client, limit, path, uncategorised=False, rejudge=False,
               topup=False, vendor=None):
    """Write the units still needing a verdict, plus that client's own category list, as JSON.

    The candidate set is included IN THE FILE and comes from qa_category filtered to this client.
    That is not convenience - the taxonomy keys collide across hospitals while meaning different
    things (key 379 is Cheese at Melbourne, Facilities Management at Northern), so a judge given
    the wrong client's list would measure against the wrong yardstick with nothing visibly broken.

    `vendor` narrows the selection to ONE supplier, which is how the run consumes the vendor spend
    queue - a vendor is judged WHOLE before the next begins (stage 3, 2026-08-25):
        vendor=None             every unjudged line for the client. The behaviour before stage 3
        vendor="ACME PTY LTD"   that supplier only, matched VERBATIM
        vendor=NO_VENDOR_NAME   the lines carrying no supplier name at all - #2 in Northern's
                                queue (3,387 lines, $608m) and #1 in Western's (1 line, $47m),
                                in the queue because Sameer ruled they stay
    It also BOUNDS MEMORY, which is the defect TRACKER carries as `fetchall()` paging: this
    function materialises its whole selection, so a client is ~0.51 GB of JSON at Melbourne and a
    single vendor is a few MB. Per-vendor selection removes the need for generic paging entirely.
    """
    # 🔒 `limit=None` MEANS EVERY LINE, AND THE `TOP` CLAUSE IS REMOVED RATHER THAN RAISED.
    #
    # Found 2026-08-24: `nim_judge --all` passed a literal 100,000, which became `SELECT TOP (?)`.
    # Melbourne holds 893,173 in-scope lines, so `--all` would have judged 11% of the hospital,
    # printed `ok`, and exited zero. **That is the failure this project names as the worst one
    # available, because it looks like success**, and it is the SAME defect that was fixed in the
    # LOADER on 2026-08-18 - fixed there, and nobody asked which other file capped a population.
    # `TRACKER.md` recorded the stage as done.
    #
    # A bigger number would not have fixed it. A cap of 10,000,000 is still a cap, still silent,
    # and still wrong on the day a client exceeds it. The clause has to go.
    _top = "" if limit is None else "TOP (?) "

    # THE VENDOR NARROWING. The clause is CHOSEN from three fixed strings and the value is always
    # bound as a parameter - the supplier name never reaches the SQL text, so a name containing a
    # quote is data rather than syntax.
    #
    # ⚠️ SQL Server ignores TRAILING spaces in `=`, so two names differing only by trailing
    # whitespace would BOTH be selected while the queue holds them as two vendors. MEASURED on
    # production 2026-08-25 before relying on this: no client holds two such names (3 names carry
    # stray whitespace, none collides). Re-measure if a client's vendor master is ever reloaded.
    if vendor is NO_VENDOR_NAME:
        _vendor, _vendor_args = "\n          AND u.Supplier_Name IS NULL", []
    elif vendor is not None:
        _vendor, _vendor_args = "\n          AND u.Supplier_Name = ?", [vendor]
    else:
        _vendor, _vendor_args = "", []

    qcur.execute("SELECT " + _top + """u.qa_line_id, u.Supplier_Name, u.ITEM_DESCRIPTION, u.DESCRIPTION_USABLE,
             u.CATEGORY_LVL_1, u.CATEGORY_LVL_2, u.CATEGORY_LVL_3, u.CATEGORY_LVL_4,
             -- 🔒 v5: THE GL AND COST CENTRE ARE NOT EVEN SELECTED. They were still being read out
             -- of SQL and merely left out of the payload dict, which put them one careless edit
             -- away from the judge. NULL literals hold the column positions so every r[n] index
             -- below is unchanged, while the values never leave the database. Never restore these.
             NULL AS gl_withheld_v5, NULL AS cost_centre_withheld_v5, u.spend,
             u.rule_id, u.rule_priority, u.rule_source, r.tests_description,
             r.field_1, r.operator_1, r.value_1, r.category_assignment,
             -- THE VERDICT THE LINE ALREADY HOLDS. An uncategorised batch only ADDS a suggestion, so
             -- these must be handed back unchanged - and on 2026-08-05 nine of them were not,
             -- because the emitter did not say what they were. Six Northern, one Sydney Adventist
             -- and two Western lines carried Incorrect / deterministic_contradiction (same vendor,
             -- same item text, two or three different categories) and were flattened to Uncertain.
             -- Emitting them removes the guesswork.
             u.verdict, u.confidence, u.basis
        FROM qa_line u
        LEFT JOIN qa_rule r ON r.run_id=u.run_id AND r.client_code=u.client_code
                           AND r.rule_id=u.rule_id
        WHERE u.run_id=? AND u.client_code=?
          -- REJUDGE is a THIRD selection, not a relaxation of the other two. A re-run by a new
          -- model must offer every line again - Claude has already answered them, so the usual
          -- `verdict IS NULL` test finds nothing and the batch comes back empty, which reads as
          -- "all done" rather than "never started". Its own not-yet-done test is NIM_VERDICT,
          -- because that is the column this pass writes; Claude's verdict is never touched.
          AND ((? = 1 AND u.NIM_VERDICT IS NULL
                      AND ((? = 1 AND LTRIM(RTRIM(ISNULL(u.CATEGORY_LVL_1,''))) = 'Uncategorised')
                        OR (? = 0 AND LTRIM(RTRIM(ISNULL(u.CATEGORY_LVL_1,''))) <> 'Uncategorised')))
            OR (? = 0 AND ? = 0 AND u.verdict IS NULL)
            OR (? = 0 AND ? = 1 AND u.SUGGESTED_CATEGORY_LVL_0 IS NULL
                      AND LTRIM(RTRIM(ISNULL(u.CATEGORY_LVL_1,''))) = 'Uncategorised')
          -- 🔒 TOP-UP: A HOLLOWED-OUT JURY WAS OTHERWISE PERMANENT. A FOURTH selection, and the
          -- reason it had to be one is that the other three cannot see the problem. Measured
          -- 2026-08-24: 141 of 2,000 pilot lines (7.0%) were decided by fewer than three models,
          -- because 16 whole BATCHES lost a model to a failed request and every line in them was
          -- written with the surviving votes. Those lines carry a NIM_VERDICT, so arm 1's
          -- `NIM_VERDICT IS NULL` walks straight past them on every future run - the ONLY repair
          -- available was --reset, which destroys the whole generation. At 2.78M lines that is
          -- ~195,000 weak verdicts behind a 40-day re-run.
          -- ⚠️ It is a SEPARATE FLAG, never folded into the default. A normal resume must keep
          -- meaning exactly what it means today; and write() refuses to lower NIM_MODELS_RESPONDED,
          -- so a top-up that drops a model again leaves the better answer standing.
            OR (? = 1 AND u.NIM_MODELS_RESPONDED < 3
                      AND ((? = 1 AND LTRIM(RTRIM(ISNULL(u.CATEGORY_LVL_1,''))) = 'Uncategorised')
                        OR (? = 0 AND LTRIM(RTRIM(ISNULL(u.CATEGORY_LVL_1,''))) <> 'Uncategorised'))))"""
        + _vendor + """
        ORDER BY u.qa_line_id""", *(([] if limit is None else [limit]) + [
        run_id, client,
        int(rejudge), int(uncategorised), int(uncategorised),
        int(rejudge), int(uncategorised),
        int(rejudge), int(uncategorised),
        int(topup), int(uncategorised), int(uncategorised)] + _vendor_args))
    rows = qcur.fetchall()

    # DOES THE ASSIGNED PATH EXIST IN THIS CLIENT'S TAXONOMY AT ALL? Measured 2026-08-05: Northern
    # and Western 0%, Melbourne 2.8%, SYDNEY ADVENTIST 29.4% - every one of the latter assigned by
    # `CBoard Lookup`, the second categorisation mechanism, and 112 of its 147 are a REFINEMENT of a
    # real category rather than a contradiction of one (Bakery > Savoury Baked Goods under a
    # taxonomy that stops at Bakery > Bakery). Judged blind, those read as 147 wrong categories.
    # Computed here rather than left to the judge's eye, because it is a fact about the data.
    qcur.execute("""SELECT DISTINCT LTRIM(RTRIM(ISNULL(CATEGORY_LVL_1,''))),
                                    LTRIM(RTRIM(ISNULL(CATEGORY_LVL_2,''))),
                                    LTRIM(RTRIM(ISNULL(CATEGORY_LVL_3,'')))
                      FROM qa_category WHERE client_code=? AND in_scope=1""", client)
    tax = qcur.fetchall()
    exact_paths = {(a, b, c) for a, b, c in tax}
    parent_paths = {(a, b) for a, b, _ in tax}

    def placing(r):
        l1, l2, l3 = ((r[i] or "").strip() for i in (4, 5, 6))
        if l1 == clientcfg.LEVEL_UNCATEGORISED:
            return "uncategorised"
        if (l1, l2, l3) in exact_paths:
            return "exact"
        return "finer_than_taxonomy" if (l1, l2) in parent_paths else "branch_not_in_taxonomy"

    # 🔒 THE RULE'S FIRING CONDITION IS FILTERED THROUGH AN ALLOWLIST, v5, 2026-08-17.
    #
    # v4 removed `gl_account_name` and `cost_centre` from the payload and I reported the GL closed.
    # IT WAS NOT. `fires_on` is built from the rule's own field/operator/value and was sent WHOLE,
    # so a GL-based rule spelled the GL out in plain text: "ACCOUNT NAME CONTAINS FREIGHT",
    # "CHARGED COST CENTRE STARTS WITH X". 274 pilot lines are attached to such a rule, and the
    # judge quoted it back in 40 rationales - 24 of them on FIRM verdicts.
    #
    # AN ALLOWLIST, NOT A BLOCKLIST, and that is the whole point. A blocklist of GL-ish field names
    # fails OPEN: the next client's rules table introduces a field nobody listed and it leaks
    # silently, which is precisely how this one survived v4. Only the two fields that ARE evidence
    # under Sameer's hierarchy may be named - the vendor and the item text. Everything else is
    # withheld by default, including fields that have not been invented yet.
    #
    # BUSINESS UNIT DESCRIPTION is withheld too. Sameer named "the GL ... neither the cost centre";
    # a business unit is the same class of evidence - it says WHO bought, never WHAT was bought -
    # so treating it as evidence would reopen the rule through a synonym. 6 rules, easily reversed
    # if he disagrees.
    #
    # THE VALUE IS WITHHELD WITH THE FIELD NAME, not just the name. "CONTAINS FREIGHT" on its own
    # still hands over the GL account's content, which is the evidence; masking only the label
    # would be the same half-measure as v4.
    EVIDENCE_FIELDS = {"VENDOR_NAME", "ITEM_DESCRIPTION"}

    def fires_on(row):
        """The rule's firing condition - shown only when it tests a field the judge may reason from.

        The condition is WITHHELD RATHER THAN DELETED. The judge still needs to know the rule fired
        on something, so that it does not read a withheld rule as a rule with no basis and mark the
        line wrong for that reason alone. It must not learn WHICH field or WHAT value.
        Returns None when the rule carries no test at all.
        """
        field, op, val = row[15], row[16], row[17]
        if not field:
            return None
        if str(field).strip().upper() in EVIDENCE_FIELDS:
            return " ".join(str(x) for x in (field, op, val) if x)
        return ("[withheld - this rule fires on a field that is neither the vendor nor the item "
                "text. It is not evidence you may use, and you cannot infer it]")

    units = [{
        "line_id": r[0], "vendor": r[1], "item_text": r[2], "has_usable_text": r[3] == "Y",
        "assigned": " > ".join(x for x in r[4:8] if x and not x.startswith("(")),
        "assigned_in_taxonomy": placing(r),
        # 🔒 GL ACCOUNT AND COST CENTRE ARE NOT SENT. Sameer, 2026-08-17: *"we have a hard rule that
        # the GL will never be used to make any judge or assumption, neither the cost centre ... if
        # the item description doesnt give us that granularity, it would be manually sorted by the
        # analyst."* This REVERSES the 2026-08-03 instruction that made them the step-3 fallback.
        # REMOVED FROM THE PAYLOAD, not merely forbidden in the prompt. A field that is present is
        # a field a model can read, whatever the instructions say, and we would have no way to tell
        # afterwards that it had. The only guarantee that evidence was not used is that it was
        # never supplied.
        # It also closes a circularity: 38 of 352 rules fire on ACCOUNT NAME or CHARGED COST CENTRE
        # and categorised 199 pilot lines. Showing the judge the same GL the rule fired on had it
        # confirming the rule's own input - the identical trap as agreeing with a vendor-fired rule
        # on vendor evidence, which step 1 already guards against.
        # MEASURED COST, stated rather than discovered later: 297 pilot lines have no usable
        # description and 189 of them held a firm verdict resting on GL - those become Uncertain
        # and go to the analyst. 9.4% of the pilot; the full-scale equivalent is 388,510 lines
        # (14.1%) with no usable item text.
        "spend": round(r[10], 2) if r[10] is not None else None,
        "rule": {"id": r[11], "priority": r[12], "tier": r[13],
                 # N means the rule never read the item text, so our text is INDEPENDENT evidence
                 # and checking the category against it is a real audit rather than a re-run.
                 "read_the_description": r[14],
                 "fires_on": fires_on(r),
                 "assigns": r[18]},
        # Only in an uncategorised batch, where the task is to ADD a suggestion and nothing else.
        # Return these three EXACTLY as given; they are not yours to change.
        **({"return_verdict_unchanged": r[19], "return_confidence_unchanged": r[20],
            "return_basis_unchanged": r[21]} if uncategorised else {}),
    } for r in rows]

    # WHICH CANDIDATE SET? Normally the in-scope branches only - the judge is auditing an indirect
    # categorisation and must not be able to move a line out of the programme's scope.
    #
    # UNCATEGORISED LINES ARE THE EXCEPTION, and get the client's FULL taxonomy. Those lines carry no
    # category at all, so there is nothing to be right or wrong about and no verdict to distort - the
    # only output is a suggestion, and a suggestion is only useful if it can name the category the
    # line actually belongs in. Sameer, 2026-08-05: "blank level 0 is in scope, our judge just needs
    # to suggest a category from the relevant taxonomy based on vendor + item desc."
    # Measured the same day: 413,338 lines across the four hospitals carry no Category Level 0, and
    # 136,217 of them come from suppliers whose categorised spend is 90%+ CLINICAL. Restricted to the
    # non-clinical list the judge would have had no choice but to file every one of those as indirect.
    # SUGGESTED_CATEGORY_LVL_0 then records which branch the answer landed in, so "this is clinical"
    # needs no separate flag - the suggestion already says it.
    # SUGGESTIONS COME FROM THE LOCKED MERGED TAXONOMY, NOT THIS CLIENT'S OWN LIST.
    # Sameer, 2026-08-14: *"the current taxonomy would be currently pulled from the 4 old
    # taxonomies, however recommendation / suggested categories should only be fed from the new
    # taxonomy we locked in today."* The line's EXISTING category is still read from, and judged
    # against, its own hospital's structure - `assigned` and `assigned_in_taxonomy` above are
    # unchanged. Only the shortlist moved. Safe to action because the four hospitals are adopting
    # the merged taxonomy, so a merged path can be typed straight into their system.
    # `in_scope=0` on CL-0001 is what keeps the Clinical hand-off off the 1,500 categorised lines
    # and on the uncategorised ones, which is the case it was added for.
    qcur.execute(f"""SELECT category_key, branch, leaf, path_full, category_description,
                            lines_in_scope, in_scope, CATEGORY_LVL_0
        FROM qa_category WHERE client_code=? {'' if uncategorised else 'AND in_scope=1'}
        ORDER BY CATEGORY_LVL_0, branch, leaf""", MERGED_CLIENT)
    cats = [{"key": r[0], "branch": r[1], "leaf": r[2], "path": r[3],
             "definition": r[4], "lines_using_it": r[5],
             **({"level_0": r[7], "in_programme_scope": bool(r[6])} if uncategorised else {})}
            for r in qcur.fetchall()]

    payload = {
        "run_id": run_id, "client_code": client, "prompt_version": PROMPT_VERSION,
        "instructions": (
            "For each unit decide whether its assigned category is the right one FOR THIS HOSPITAL, "
            "choosing only from candidate_categories - never invent a path. "
            "verdict is Correct, Incorrect or Uncertain. Use Uncertain when the evidence does not "
            "settle it; it is excluded from both sides of the accuracy figure and is a better "
            "answer than a confident guess.\n"

            "🔒 INCORRECT REQUIRES A DESTINATION - THIS IS NOT OPTIONAL. If you answer Incorrect "
            "you MUST also return suggested_key, the 'key' of the chosen entry in "
            "candidate_categories. An Incorrect with no suggested_key is an INVALID ANSWER: it "
            "tells a person their filing is wrong without telling them where it goes, so they must "
            "redo the whole job by hand and your verdict has cost them time instead of saving it. "
            "If you cannot name a destination from candidate_categories, then you have not "
            "established that the current category is wrong - answer Uncertain instead. "
            "NEVER name the right category in the rationale while leaving suggested_key empty: if "
            "you can write it in a sentence you can put it in the field, and the field is the only "
            "part anyone can act on. The key is resolved against the MERGED indirect taxonomy - "
            "the one candidate_categories is drawn from - and NOT against this hospital's own "
            "list. Some categories here exist in no hospital's taxonomy at all because they were "
            "added deliberately; choosing one is correct and it will be stored, not rejected.\n"

            "rationale must cite the evidence used, in one or two plain sentences an account "
            "manager can disagree with. IT MUST DESCRIBE THE EVIDENCE YOU WERE ACTUALLY GIVEN. "
            "Each unit carries has_usable_text. When it is true, item_text describes the item and "
            "writing that the description is missing, unusable, generic or 'just an identifier' is "
            "a FALSE STATEMENT ABOUT THE EVIDENCE - it is worse than a wrong verdict, because it "
            "sends someone to look for information that is already in front of them.\n"

            "\u2b50 YOUR RATIONALE BINDS YOUR ANSWER. THE CATEGORY YOU CHOOSE MUST MATCH WHAT "
            "YOU JUST SAID THE ITEM IS. If you write that the item is biscuits, the category "
            "must be the one for biscuits; if you write that it is a beverage, choose the "
            "beverage category; if you write that it is cleaning supplies, choose the cleaning "
            "one. Naming the item correctly and then filing it somewhere else is a "
            "SELF-CONTRADICTION and is always wrong, however plausible the vendor makes the "
            "other category look. Before you answer, re-read your own sentence and check the "
            "key you chose says the same thing. \u26a0 THIS IS THE MOST COMMON MISTAKE MADE ON "
            "THIS TASK: measured 2026-08-24, eleven lines identified the item exactly right - "
            "'item is biscuits', 'is a beverage', 'is cleaning supplies' - and were then filed "
            "under Stationery & Printing because the vendor was an office-supplies retailer. "
            "Ruling out the WRONG category is not the same as choosing the RIGHT one: having "
            "established what the line is NOT, you must still pick the leaf that matches what "
            "your own sentence says it IS.\n"

            "HOW TO WEIGH THE EVIDENCE - follow this order:\n"
            "1. VENDOR NAME SETS THE NEIGHBOURHOOD. It bounds which categories are plausible and it "
            "is NEVER sufficient on its own. A vendor called Traffic Management cannot sit under "
            "Food and Beverage whatever the line says; it belongs broadly in traffic management. "
            "Use the vendor to test whether the assigned category is plausible AT ALL - a clear "
            "mismatch between the vendor's evident business and the assigned category is strong "
            "evidence of Incorrect. Never return Correct on the vendor name alone.\n"
            "2. THE ITEM DESCRIPTION PICKS THE CATEGORY within that neighbourhood. Vendor plus "
            "description together is the ONLY basis for a confident verdict - and it is a "
            "SUFFICIENT one. If the text names what was bought, you have everything you need: "
            "decide. 'PILLOW PROTECTOR ZIPPERED SOFT PVC', 'VINYL SKIRT SUPPLY AND INSTALL' and "
            "'CUP MEDICINE PILL 60ML PLASTIC' are all decidable lines. Uncertain is NOT the safe "
            "answer on a line like these; it is the wrong one.\n"
            "3. THERE IS NO THIRD SOURCE OF EVIDENCE. You are given no GL account and no cost "
            "centre, deliberately - do not ask for them and do not infer them from the rule. "
            "This narrows what you may reason FROM. It does not lower the bar for answering "
            "Uncertain. A description that names what was bought is decidable - decide it. "
            "NEVER write that a description was unusable when text describing the item is "
            "present - that is a false statement about the evidence.\n"
            "3b. WHEN THE DESCRIPTION DOES NOT IDENTIFY WHAT WAS BOUGHT - it is blank, a "
            "placeholder, or nothing but an identifier such as a number plate, an invoice "
            "number or a purchase-order number - STILL NAME A DESTINATION. Use the BROAD "
            "category matching what this vendor actually sells: a printing company's "
            "unreadable line belongs in printing, a freight company's in freight. Choose the "
            "broadest candidate that is safely right rather than a precise one you are "
            "guessing at, set a LOW confidence, and say in the rationale that the description "
            "was unusable and the category rests on the vendor's line of business alone.\n"
            "3c. \u26a0 BUT THE VENDOR ALONE CAN NEVER MAKE AN EXISTING FILING **Correct**. On "
            "a line that already carries a category and has no usable description: if the "
            "vendor's broad category is consistent with where it sits, answer Uncertain and "
            "say the vendor is consistent but the description could not confirm it - do NOT "
            "answer Correct. If the vendor's line of business plainly contradicts the assigned "
            "category, answer Incorrect and give the vendor-broad destination. Agreeing with a "
            "vendor-fired rule on vendor evidence is the rule confirming its own input, not an "
            "audit. On an UNCATEGORISED line none of this applies - there is no filing to be "
            "right or wrong about, so simply give the suggestion.\n"
            "4. WHEN THERE IS NO EVIDENCE AT ALL - no usable description AND a vendor whose "
            "business you cannot tell - answer Uncertain. Do not guess.\n"

            "Confidence must reflect the strength of the vendor-plus-description evidence: a "
            "specific item text on a coherent vendor is a confident verdict, a vague one is not.\n"
            "Note rule.read_the_description: when Y, the item text is the rule's own input, so "
            "confirming the category from that text re-runs the rule rather than auditing it - "
            "lower your confidence accordingly, and prefer Uncertain over a Correct you cannot "
            "independently support. When N, the item text is independent of the rule and is "
            "genuine evidence.\n"

            "ADJUDICATION RULES - these decide the cases the evidence hierarchy alone leaves open. "
            "They exist because each one was got wrong first and corrected by hand; the correction "
            "belongs here so it is not re-derived, or missed, on the next batch.\n"

            "A. A PLACEHOLDER IS NOT A CATEGORY, AND IS NEVER Correct. Leaves reading 'Not Yet "
            "Categorized', 'Non Yet Categorized' or a bare 'Other' name no category - they record "
            "that the work was not done. Measured 2026-08-05: 41 such leaves hold 283,258 in-scope "
            "lines. Where the evidence points to a real leaf, answer Incorrect and suggest it. Where "
            "it does not, still answer Incorrect - the line is demonstrably not categorised - unless "
            "there is no usable evidence at all, which is Uncertain. Say in the rationale that the "
            "assigned value is a placeholder rather than a wrong category, because the fix differs: "
            "the client is not correcting a mistake, they are finishing a job.\n"

            "B. AN UNDEFINED OVERLAP BETWEEN LEAVES IS A TAXONOMY FAULT, NOT A LINE ERROR. "
            "\u2b50 READ THE `definition` FIELD ON EACH CANDIDATE FIRST. Where a definition IS "
            "given it SETTLES the question and this rule does not apply: a definition that "
            "excludes the item makes the assignment Incorrect however plausible the leaf name "
            "sounds, and one that includes it makes it Correct. Only where two leaves both "
            "plausibly hold the item and NEITHER carries a definition separating them is the "
            "assignment Correct - say in the rationale that the two leaves are undefined and "
            "overlapping. Marking such lines Incorrect charges the client for an error they "
            "cannot fix line by line, and inflates the error rate with our own preference. "
            "This does NOT excuse a real mismatch: a wireless mouse, a litre of milk or an "
            "iPad in General Office Supplies is Incorrect on the description, and the overlap "
            "has nothing to do with it.\n"

            "C. THE SAME LEAF NAME MUST MEAN THE SAME THING AT EVERY HOSPITAL. 182 of the 261 "
            "distinct in-scope leaf names appear at more than one client. Judge the fact pattern, "
            "not the hospital: a doctor's conference-fee claim under Reimbursements > Doctor "
            "Payments is Correct wherever that leaf exists, and it exists identically at Northern "
            "and Western. Where two hospitals' accuracy differs, that difference has to come from "
            "their data and not from the judge changing its mind between batches.\n"

            "D. NO SUITABLE LEAF EXISTS -> Incorrect WITH NO suggested_key. This taxonomy covers "
            "non-clinical spend, so a clinical consumable that has been filed somewhere non-clinical "
            "is Incorrect and there is nowhere right to send it. Leave the suggestion empty and say "
            "the taxonomy has no home for it. The gap IS the finding; forcing the nearest leaf hides "
            "it and hands the client a fix that is also wrong.\n"

            "E. A VENDOR SUBSTRING MATCH MAY HAVE REACHED A DIFFERENT COMPANY. When rule.fires_on "
            "is a CONTAINS test on the vendor name, check the vendor IS that business rather than "
            "merely containing the string: a rule for the nursing agency HEALTHCARE AUSTRALIA "
            "matched GE HEALTHCARE AUSTRALIA and filed an anaesthetic machine repair as agency fees. "
            "Same for description tests - a rule on PAPER caught paper hand towels.\n"

            "F. A DESCRIPTION HOLDING TWO DIFFERENT THINGS IS Uncertain. Where the text carries both "
            "a repair authorisation and a lease instalment, the line does not say which it is and "
            "neither do we. Do not pick the more likely one and present it as a finding.\n"

            "G. FOLLOW THIS HOSPITAL'S OWN SETTLED PRACTICE where the taxonomy is genuinely silent. "
            "If comparable lines here consistently sit in one leaf, that is the consistent "
            "destination, and lines_using_it on each candidate shows you where the weight is. This "
            "is the weakest rule and ranks below A-F: established practice can itself be the defect, "
            "so it settles ties, it does not overrule the description.\n"

            "H. A CATEGORY FINER THAN THE TAXONOMY IS NOT AN ERROR. Read assigned_in_taxonomy on "
            "each unit. 'exact' means the assigned path is one of candidate_categories and the "
            "normal rules apply. 'finer_than_taxonomy' means the assignment sits UNDER a real "
            "category with a sub-leaf the taxonomy does not carry - Sydney Adventist's CBoard "
            "Lookup files a spinach and feta triangle as Bakery > Savoury Baked Goods where the "
            "taxonomy stops at Bakery > Bakery. Judge it at the grain the taxonomy CAN express: if "
            "the item genuinely belongs under that parent, it is Correct, and say in the rationale "
            "that the assignment is finer than the taxonomy. It is a second categorisation "
            "mechanism working properly, not a rule to fix. 'branch_not_in_taxonomy' means even the "
            "parent is absent - judge on the evidence as usual, and if nothing in "
            "candidate_categories fits, rule D applies. 'uncategorised' means the line has no "
            "category path at all, which is scope_status in_scope_uncategorised, not a wrong "
            "category.\n"

            "I. THE FIELD THE RULE FIRED ON IS NEVER INDEPENDENT EVIDENCE - WHICHEVER FIELD IT IS. "
            "rule.read_the_description covers only the description; read rule.fires_on as well. "
            "When rule.fires_on names the VENDOR, agreeing with the rule on vendor evidence is the "
            "rule confirming its own input, not an audit - you need the item text to settle it. "
            "When rule.fires_on reads [withheld], the rule fired on a field you are deliberately "
            "not shown. TREAT THAT LINE AS IF THE RULE HAD GIVEN NO REASON AT ALL: judge it on the "
            "vendor and the item text only. Do not guess what the withheld field was, do not "
            "reason about what it might have contained, and do NOT let the rule's existence stand "
            "in for evidence. If the item text does not settle the category, the answer is "
            "Uncertain and the line goes to an analyst - that is the intended outcome, not a "
            "failure. A withheld firing condition is equally NOT a reason to mark the line "
            "Incorrect; you simply have no information about it either way.")
            + ("" if not uncategorised else
            "\n\nUNCATEGORISED BATCH - THE TASK IS DIFFERENT. Every line here carries NO category "
            "at all, so there is nothing to mark Correct or Incorrect and the verdict already on "
            "the line does not change. Add ONE thing: suggested_key, naming where this line SHOULD "
            "be filed.\n"
            "EACH UNIT CARRIES return_verdict_unchanged, return_confidence_unchanged and "
            "return_basis_unchanged. COPY THOSE THREE BACK EXACTLY. Do not assume every line in "
            "this batch is Uncertain - some carry Incorrect with basis "
            "deterministic_contradiction, because the same vendor and item text are assigned two or "
            "three different categories at that hospital, and that finding must survive.\n"
            "candidate_categories is this hospital's FULL taxonomy, not the indirect slice. Each "
            "entry carries level_0 - Clinical, Inter-Hospital Spend, Non-Clinical or "
            "Non-Procurement - and in_programme_scope. YOU MAY CHOOSE ANY OF THEM. If the line is a "
            "cardiac catheter, say so by picking the clinical leaf; that is the useful answer and it "
            "is how the line gets recorded as out of our scope. Do NOT force a non-clinical category "
            "onto something that is plainly clinical just because this is an indirect project.\n"
            "The evidence hierarchy above still governs, IN ITS v6 FORM: vendor sets the "
            "neighbourhood, the item description picks the category, and THERE IS NO THIRD SOURCE. "
            "You are given no GL account and no cost centre. Where the description names what was "
            "bought, suggest a category - that is a decidable line and leaving it blank is the "
            "wrong answer. \u2b50 WHERE IT DOES NOT, RULE 3b APPLIES HERE TOO: give the BROAD "
            "category matching what the vendor actually sells, at low confidence, saying the "
            "description was unusable and the category rests on the vendor alone. These lines "
            "carry no category, so there is nothing to be right or wrong about and rule 3c does "
            "not restrain you - a destination is the useful answer. A blank category field means "
            "nobody classified this line - it does NOT mean the line is non-clinical, and it is "
            "not evidence of anything. Leave suggested_key out ONLY when you can tell neither "
            "what was bought NOR what the vendor sells.\n"
            "\u2b50 AND YOUR RATIONALE BINDS YOUR ANSWER HERE TOO: the category you choose must "
            "match what you just said the item is. Writing that a line is a beverage and then "
            "suggesting a stationery leaf is a self-contradiction and is always wrong, however "
            "plausible the vendor makes it look. Re-read your own sentence before you answer."),
        "candidate_categories": cats,
        "units": units,
    }
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
        print(f"  wrote {len(units)} lines and {len(cats)} candidate categories -> {path}")
    return payload


def apply_verdicts(qa, qcur, run_id, client, path):
    """Read judged verdicts back in. Validates before writing - a bad verdict value would be
    invisible in a table of 1M rows."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data["verdicts"] if isinstance(data, dict) else data

    # A suggestion may name its category by KEY instead of by typing the path. The key is resolved
    # against THIS client's qa_category only, so a key belonging to another hospital cannot resolve -
    # the taxonomy keys collide across hospitals while meaning different things (379 is Cheese at
    # Melbourne and Facilities Management at Northern), and a free-text path is one typo away from a
    # category that does not exist at all. Resolution turns both failures into a rejected row.
    # RESOLVE TO THE LEVEL COLUMNS, NEVER BY SPLITTING path_full ON '>'. Ten of Melbourne's clinical
    # categories carry a '>' inside the category NAME - "Conventional Femoral Heads, >32Mm",
    # "Bone - Milled >50gr", "Repair, Graft, Large (>50 To 100Cm2)". Splitting the path turns those
    # into six segments and rejects a perfectly valid suggestion. It never showed because clinical
    # categories were not suggestable; from 2026-08-05 they are, on uncategorised lines.
    #
    # The full taxonomy is loaded, and in_scope is carried per key so the guard below can be applied
    # PER LINE rather than per batch - whatever the emitter sent, a line that already has a category
    # can still only be redirected inside the indirect branches.
    qcur.execute("""SELECT category_key, in_scope, CATEGORY_LVL_0, CATEGORY_LVL_1,
                           CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4
                      FROM qa_category WHERE client_code=?""", MERGED_CLIENT)
    by_key, key_in_scope = {}, {}
    for r in qcur.fetchall():
        k = str(r[0]).strip()
        by_key[k] = list(r[2:7])
        key_in_scope[k] = bool(r[1])
    if not by_key:
        raise SystemExit(f"  {client}: no categories loaded - load_taxonomy.py has not run")

    # WHICH MARKER FOR AN EMPTY LEVEL? The two are not interchangeable and the difference is a real
    # finding: "(not used at this level)" means this category has a shorter path than its siblings,
    # "(no level N in this taxonomy)" means the client has no such level AT ALL. qa_category stores
    # NULL for both, so the distinction is recovered by looking down the whole column: a level that
    # is NULL on EVERY row of this client does not exist here; a level that is NULL on only some
    # rows exists and this category simply stops early.
    level_exists = [any(lv[i] is not None for lv in by_key.values()) for i in range(N_SUGGESTED)]

    # Which lines have NO category of their own? Only those may be sent outside the indirect
    # branches. Read from the table, not from the verdict file, so a malformed batch cannot widen it.
    qcur.execute("""SELECT qa_line_id FROM qa_line
                     WHERE run_id=? AND client_code=?
                       AND LTRIM(RTRIM(ISNULL(CATEGORY_LVL_1,''))) = ?""",
                 run_id, client, clientcfg.LEVEL_UNCATEGORISED)
    uncategorised_lines = {r[0] for r in qcur.fetchall()}

    # HOW MANY LEVELS DOES THIS CLIENT'S TAXONOMY ACTUALLY HAVE? Measured from its own paths, never
    # assumed. All four hospitals happen to carry Level 0-4 today, and hard-coding that five would
    # reject EVERY suggestion for a fifth hospital whose taxonomy is shallower - a failure that looks
    # like "the judge found nothing to fix here", which is the worst shape a bug can take in this
    # project. Disagreement between paths is itself a finding and is reported rather than averaged.
    # Depth no longer needs measuring or guarding. qa_category itself carries exactly
    # CATEGORY_LVL_0..4, so a resolved suggestion is five values by construction and cannot be
    # deeper than the five SUGGESTED_CATEGORY_LVL_* columns it is written into. The old width check
    # was defending against the path-splitting artefact removed above, not against a real taxonomy.
    if N_SUGGESTED != 5:
        raise SystemExit(f"  N_SUGGESTED is {N_SUGGESTED} but qa_category carries five level "
                         f"columns. Add the columns to BOTH tables before changing this.")

    now, applied, bad = datetime.now(), 0, []
    for v in rows:
        if v.get("verdict") not in VERDICTS:
            bad.append((v.get("line_id"), v.get("verdict")))
            continue
        if v.get("basis") not in BASES:
            bad.append((v.get("line_id"), f"basis {v.get('basis')!r} is not one of BASES"))
            continue
        levels = None
        if v.get("suggested_key") is not None:
            k = str(v["suggested_key"]).strip()
            if k not in by_key:
                bad.append((v.get("line_id"),
                            f"suggested_key {k!r} is not a category for {client}"))
                continue
            # THE SCOPE GUARD, APPLIED PER LINE. A line that already carries a category is being
            # audited inside the indirect programme and may only be redirected within it - letting a
            # clinical key land there would move spend out of scope on our say-so, which is not ours
            # to do. A line with NO category has nothing to move: naming its real home, clinical or
            # not, is the whole point.
            if not key_in_scope[k] and v.get("line_id") not in uncategorised_lines:
                bad.append((v.get("line_id"),
                            f"suggested_key {k!r} is outside the indirect branches, and this line "
                            f"already carries a category - only uncategorised lines may be sent "
                            f"outside scope"))
                continue
            levels = by_key[k]
        # A candidate path maps one-for-one onto suggested_cat_l0..l4, starting at Level 0. Taking
        # one segment too few shifted every level by one and silently discarded the leaf, which is
        # the part of the suggestion that tells an owner where to file the line. Level 0 is not a
        # constant that can be assumed away: 65 in-scope candidates sit under Non-Procurement and two
        # under Tail Spend, so a suggestion can legitimately move a line at Level 0.
        #
        # Where the client's taxonomy is shallower than the five columns, the tail is filled with the
        # SAME marker the assigned side uses for a level the client does not have - so suggested and
        # assigned stay in one vocabulary and a reader can tell "this taxonomy has no level 4" from
        # "this category stops early", which mean different things. Never NULL: a blank would read as
        # "we had nothing to say" rather than "there is no such level here".
        if levels is None:
            p = [None] * N_SUGGESTED          # no suggestion offered - leave all five NULL
        else:
            p = [x if x is not None else
                 (clientcfg.LEVEL_NOT_USED if level_exists[i] else clientcfg.NO_SUCH_LEVEL.format(i))
                 for i, x in enumerate(levels)]
        qcur.execute("""UPDATE qa_line SET verdict=?, confidence=?,
                SUGGESTED_CATEGORY_LVL_0=?, SUGGESTED_CATEGORY_LVL_1=?, SUGGESTED_CATEGORY_LVL_2=?,
                SUGGESTED_CATEGORY_LVL_3=?, SUGGESTED_CATEGORY_LVL_4=?,
                basis=?, rationale=?, judge_backend='claude_code', judge_model=?,
                PROMPT_VERSION=?, judged_at=?
            WHERE run_id=? AND client_code=? AND qa_line_id=?""",
            v["verdict"], v.get("confidence"), p[0], p[1], p[2], p[3], p[4],
            v.get("basis"), (v.get("rationale") or "")[:2000],
            data.get("judge_model") if isinstance(data, dict) else None,
            PROMPT_VERSION, now, run_id, client, v["line_id"])
        applied += qcur.rowcount
    qa.commit()
    print(f"  applied {applied} verdicts" + (f", REJECTED {len(bad)}: {bad[:5]}" if bad else ""))
    return applied


# =====================================================================================================
def roll_up_rules(qa, qcur, run_id):
    """Roll the line verdicts up into the fix queue.

    There is no longer a verdict to PUSH anywhere: grouping was removed on 2026-08-05, so the judge
    writes straight onto the line and nothing is copied across identical lines. What is still
    needed is the rule-level summary, because "which rule caused this" is half the deliverable.

    ⚠️ error_rate IS AN ESTIMATE NOW, AND is_complete IS ALMOST ALWAYS 0. The rule-led loader judged
    every line a rule touched, which made its error rate a fact. A 500-line stratified sample
    touches a handful of each rule's lines, so these are sample rates. is_complete stays in the
    schema and stays honest: it fires only when the lines judged reach the rule's FULL in-scope
    population, which a sample will not reach. Do not quote a rule error rate from this run to a
    client.
    """
    qcur.execute("""UPDATE r SET lines_judged=a.judged, lines_incorrect=a.bad,
            lines_uncertain=a.unsure,
            error_rate = CASE WHEN (a.judged - a.unsure) > 0
                              THEN CAST(a.bad AS float)/(a.judged - a.unsure) END,
            -- is_complete requires every line of the rule judged AND at least one judged
            -- CONFIDENTLY. Without the second condition a rule whose lines are all Uncertain reads
            -- "complete" beside a NULL error rate, and NULL renders as 0% in Excel - so a rule
            -- nobody could judge would present as a rule with no errors. Found 2026-08-03 on
            -- NH-0834, NH-0867 and MEL-1867, whose lines are 100% uncategorised.
            is_complete = CASE WHEN a.judged >= r.lines_in_scope
                                AND (a.judged - a.unsure) > 0 THEN 1 ELSE 0 END
        FROM qa_rule r JOIN (
            SELECT run_id, client_code, rule_id,
                   SUM(CASE WHEN verdict IS NOT NULL THEN 1 ELSE 0 END) AS judged,
                   SUM(CASE WHEN verdict='Incorrect' THEN 1 ELSE 0 END) AS bad,
                   SUM(CASE WHEN verdict='Uncertain' THEN 1 ELSE 0 END) AS unsure
            FROM qa_line WHERE run_id=? GROUP BY run_id, client_code, rule_id) a
          ON a.run_id=r.run_id AND a.client_code=r.client_code AND a.rule_id=r.rule_id
        WHERE r.run_id=?""", run_id, run_id)
    n = qcur.rowcount
    qa.commit()
    return n


def consistency(qcur, run_id):
    """Has the judge contradicted ITSELF? Identical lines must get identical answers.

    Sameer, 2026-08-05, on judging identical lines separately: "how can the same vendor same item
    and same category come back with different answers, it can only give wrong answers because you
    made an error in your judgement call." Correct - so it is measured rather than tolerated.

    This is the free calibration that removing the grouping buys back. Same unit_key means the
    judge saw the same vendor, the same item text and the same assigned category; a different
    verdict is the judge disagreeing with itself, and the rate is a direct read on how steady it is.
    """
    qcur.execute("""SELECT COUNT(*) FROM (
            SELECT client_code, unit_key
            FROM qa_line
            WHERE run_id=? AND verdict IS NOT NULL
            GROUP BY client_code, unit_key
            HAVING COUNT(*) > 1 AND COUNT(DISTINCT verdict) > 1) x""", run_id)
    disagreed = qcur.fetchone()[0]
    qcur.execute("""SELECT COUNT(*) FROM (
            SELECT client_code, unit_key FROM qa_line
            WHERE run_id=? AND verdict IS NOT NULL
            GROUP BY client_code, unit_key HAVING COUNT(*) > 1) x""", run_id)
    repeated = qcur.fetchone()[0]
    return disagreed, repeated


def report(qcur, run_id):
    print(f"\n{'=' * 86}\nVERDICTS - run {run_id}\n{'=' * 86}")
    qcur.execute("""SELECT client_code,
            COUNT(*), SUM(CASE WHEN verdict IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN verdict='Correct' THEN 1 ELSE 0 END),
            SUM(CASE WHEN verdict='Incorrect' THEN 1 ELSE 0 END),
            SUM(CASE WHEN verdict='Uncertain' THEN 1 ELSE 0 END)
        FROM qa_line WHERE run_id=? GROUP BY client_code ORDER BY 1""", run_id)
    rows = qcur.fetchall()
    print(f"  {'client':20} {'lines':>8} {'unjudged':>9} {'Correct':>9} {'Incorrect':>10} "
          f"{'Uncertain':>10}")
    print("  " + "-" * 80)
    for r in rows:
        print(f"  {r[0]:20} {r[1]:>8,} {r[2]:>9,} {r[3]:>9,} {r[4]:>10,} {r[5]:>10,}")
    print("\n  Accuracy is stated only over lines judged CONFIDENTLY: Uncertain is excluded from")
    print("  both numerator and denominator, with its share reported. Unjudged lines are not")
    print("  counted as correct - a judge that assumes what it did not examine is worthless.")

    d, rep = consistency(qcur, run_id)
    if rep:
        print(f"\n  SELF-CONSISTENCY: {rep:,} identical (vendor + item + category) lines were "
              f"judged more\n  than once, and {d:,} of those came back with DIFFERENT verdicts.")
        print("  Identical input must give an identical answer, so any disagreement here is the")
        print("  judge contradicting itself - not a real distinction. This is the check that")
        print("  removing the grouping buys back, and it costs nothing.")

    qcur.execute("""SELECT client_code, basis, COUNT(*) FROM qa_line
        WHERE run_id=? AND verdict IS NOT NULL GROUP BY client_code, basis ORDER BY 1,3 DESC""",
        run_id)
    rows = qcur.fetchall()
    if rows:
        print(f"\n  {'client':20} {'basis':32} {'units':>8}")
        print("  " + "-" * 62)
        for r in rows:
            print(f"  {r[0]:20} {str(r[1]):32} {r[2]:>8,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="deterministic",
                    choices=["deterministic", "claude_code"])
    ap.add_argument("--run-id", default=None, help="defaults to the most recent run")
    ap.add_argument("--client", default=None)
    ap.add_argument("--emit", metavar="PATH", help="claude_code: write a batch to judge")
    ap.add_argument("--apply", metavar="PATH", help="claude_code: read judged verdicts back")
    ap.add_argument("--limit", type=int, default=60, help="lines per emitted batch")
    ap.add_argument("--uncategorised", action="store_true",
                    help="emit lines that have NO category, with the client's FULL taxonomy as "
                         "candidates. Their verdict does not change - this only adds a suggestion.")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    qa = connect_qa(pilot=True, env=load_env())
    qcur = qa.cursor()
    run_id = args.run_id
    if not run_id:
        qcur.execute("SELECT TOP 1 run_id FROM qa_run ORDER BY loaded_at DESC")
        row = qcur.fetchone()
        if not row:
            raise SystemExit("  no runs in qa_run - run build_pilot.py first")
        run_id = row[0]
    print(f"run {run_id}")

    if args.report:
        report(qcur, run_id)
        qa.close()
        return 0

    if args.backend == "claude_code":
        if args.emit:
            if not args.client:
                raise SystemExit("  --emit needs --client")
            emit_batch(qcur, run_id, args.client, args.limit, args.emit,
                       uncategorised=args.uncategorised)
        elif args.apply:
            if not args.client:
                raise SystemExit("  --apply needs --client")
            apply_verdicts(qa, qcur, run_id, args.client, args.apply)
            print(f"  rolled up into {roll_up_rules(qa, qcur, run_id):,} rules")
        else:
            raise SystemExit("  claude_code needs --emit PATH or --apply PATH")
        qa.close()
        return 0

    counts = judge_deterministic(qcur, run_id, args.client)
    qa.commit()
    print("\n  deterministic pass - only what can be PROVEN from the data:")
    for k, v in counts.items():
        print(f"    {k:18} {v:>8,} lines")
    print(f"  rolled up into {roll_up_rules(qa, qcur, run_id):,} rules")
    report(qcur, run_id)
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
