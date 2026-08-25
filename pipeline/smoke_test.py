"""PHASE 0 - multi-client smoke test. Loads a real sample from EVERY configured client into the
pilot QA database, shaped exactly like `qa_line` will be.

    python pipeline/smoke_test.py            # all clients, ~2,000 lines each
    python pipeline/smoke_test.py --n 500

Why this exists, and why it loads four clients rather than one:

The earlier smoke test held 1,000 Melbourne lines and 7 columns. It proved the connection worked.
It could not prove the thing that actually matters - that ONE table shape can hold four hospitals
whose views disagree about almost everything. Measured 2026-07-31, of the columns this project
needs, exactly EIGHT are present in all four views (Category Level 0-4, PO LINE NUMBER, RuleID).
Everything else - the line's identity, its date, its GL account, its cost centre, its ABN - has a
different name per client, a different fill rate, or does not exist at all.

A single-client smoke test finalises a schema against one shape. The gaps then surface during the
production load, which is the exact failure the pilot exists to prevent.

WRITES ONLY to the pilot QA database. The four client databases are read-only, always.

Output is a per-column, per-client fill matrix - the evidence for which fields schema v1 can
require, which must be nullable, and which are not worth carrying.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg  # noqa: E402
from db import connect_client, connect_qa, load_env  # noqa: E402

TABLE = "zz_smoke_test"
RUN_TABLE = "zz_smoke_run"      # the qa_run stand-in: one row per client per run
RULE_TABLE = "zz_smoke_rule"    # the qa_rule stand-in: the FIX QUEUE, one row per RuleID
# The fix queue is half the deliverable - "here is the RuleID that caused it and what to change" -
# and until now nothing in the pilot database showed it. These are the fields an owner needs in
# front of them to action a rule, plus the full-population impact so the queue can be ranked.
RULE_FIELDS = [
    "run_id", "client_code", "rule_id", "rules_table", "resolves",
    "priority", "source",
    "field_1", "operator_1", "value_1",
    "field_2", "operator_2", "value_2",
    "field_3", "operator_3", "value_3",
    "category_assignment",
    # Does this rule READ the item description? It decides what our evidence is worth, so the judge
    # has to know before it weighs its own conclusion. Measured at Northern 2026-08-03: 61.8% of
    # rules fire on VENDOR_NAME, 36.0% on ITEM_DESCRIPTION, and 2,574 of 6,697 (38.4%) never read
    # the description in any of their three conditions.
    #   N - the rule never saw the item text, so the item text is INDEPENDENT evidence and checking
    #       the category against it is a genuine audit.
    #   Y - the item text is the rule's OWN input. Checking the category against it re-runs the rule
    #       rather than auditing it; the independent evidence has to come from the GL account and
    #       cost centre instead, and confidence should be lower.
    # Derived here rather than left for each reader to parse three fields differently.
    "tests_description",
    # impact, measured on the FULL in-scope population - not on the sample. This is what decides
    # whether a rule is worth an owner's time, and units_in_scope is what it costs to judge it
    # completely: judging every unit a rule touches makes its error rate exact rather than estimated.
    "lines_in_scope", "units_in_scope", "vendors_in_scope", "spend_in_scope",
    "lines_clinical", "lines_per_unit",
]
RULE_NUMERIC = {"lines_in_scope", "units_in_scope", "vendors_in_scope", "spend_in_scope",
                "lines_clinical", "lines_per_unit"}
# Rule-table columns vary; resolved against INFORMATION_SCHEMA and mapped onto the names above.
RULE_SRC = {
    "priority": ["Priority"], "source": ["Source"],
    "field_1": ["Field_1"], "operator_1": ["Operator_1"], "value_1": ["Value_1"],
    "field_2": ["Field_2"], "operator_2": ["Operator_2"], "value_2": ["Value_2"],
    "field_3": ["Field_3"], "operator_3": ["Operator_3"], "value_3": ["Value_3"],
    "category_assignment": ["Category Assignment", "Category_Assignment"],
}

# The qa_line shape. The order below is BOTH the load order and the order the columns appear in the
# table, and it is a reading order rather than a grouping of like types. Left to right:
#
#   which line -> who -> what was bought -> how much -> what it was categorised as ->
#   what the taxonomy says -> what put it there -> the verdict -> the evidence behind the
#   verdict -> the join keys
#
# Reordered 2026-08-03 on Sameer's instruction. It previously ran identity, vendor, description,
# money, category, taxonomy, RULE, GL context, gates, then the verdict at the far right - so the
# evidence a reader needs to judge a line (GL account, cost centre) sat AFTER the categorisation it
# is evidence about, and the verdict sat six columns past the rule that caused it. Nothing was
# added or removed by the move.
#
# Every column is nullable: three of the four clients cannot supply at least one of them.
FIELDS = [
    # --- 1. WHICH RUN, WHICH LINE -------------------------------------------------------------
    # run_id is the ONE column the schema review added. Everything else on that list was either a
    # property of the rule, the vendor or the run - none of which gets copied onto 2.76M lines - or
    # a field that was always going to live on qa_unit. See PLAN.md v3.6 changes 29-34.
    #
    # source_row_id is the whole of line identity. Measured 2026-07-31: it identifies as many rows
    # on its own as it does combined with INVOICE ID and INVOICE LINE NUMBER, at every client
    # including Western (1,951 of 2,000 either way). Those two were dropped 2026-08-03.
    # invoice_number stays because it is what an owner searches for in their own system.
    # posting_date dropped 2026-08-03. invoice_date kept - one date an owner recognises, no more.
    "run_id", "client_code", "source_row_id", "invoice_number", "invoice_date",
    # --- 2. WHO -------------------------------------------------------------------------------
    # Supplier_Name is pulled VERBATIM. Standing instruction from Sameer 2026-07-31: do not trim,
    # case-fold, normalise or mask it - it must read exactly as it does in the client's own system,
    # so an account manager searching their ERP for the name in our extract finds it. Measured
    # before the decision: normalising merges 0.05-0.65% of names, so there was nothing to gain.
    # Renamed from `supplier` 2026-08-03 - the value is the vendor's NAME, and `supplier` alongside
    # `supplier_number` read as though one were the vendor and the other an attribute of it.
    "Supplier_Name", "supplier_number", "abn",
    # --- 3. WHAT WAS BOUGHT - the evidence about the line itself -------------------------------
    # The item text and the two coding fields that describe the same purchase from the finance
    # side. These belong together and BEFORE the category: they are the input to the question
    # "is this in the right bucket", so a reader meets the evidence before meeting the answer.
    # Melbourne's ACCOUNT NAME reads 85% in scope, which makes it real judge input, not filler.
    #
    # desc_usable REPLACED desc_source 2026-08-03, on Sameer's read that desc_source was noise. He
    # was right about half of it. desc_source carried two facts welded together:
    #
    #   WHICH FIELD supplied the text   - near-constant, and therefore noise. Measured on the FULL
    #                                     in-scope population: the fallback fires on 1,108 Melbourne
    #                                     lines and NOWHERE ELSE. Northern, Sydney Adventist and
    #                                     Western use field 1 on 100% of lines that have any text.
    #                                     0.04% of the project, against a value repeated on 2.76M
    #                                     rows. It also actively misled - it reads
    #                                     'ITEM_DESCRIPTION' on a line whose rule fired on the
    #                                     vendor name and never opened the description.
    #   WHETHER THE TEXT IS USABLE      - load-bearing. 387,402 in-scope lines (14.0%) have none:
    #                                     Melbourne 106,944, Northern 12,202, SAH 54,123,
    #                                     Western 214,133.
    #
    # So the second fact is kept and the first is dropped. Y/N, and the three states are all still
    # recoverable: N with a blank item_desc is genuinely empty, N with text is a placeholder
    # ('NO DESCRIPTION' and friends), Y is real text. Nothing is rewritten - the stored value stays
    # exactly as the client has it, and this column is the only thing that marks it.
    "item_desc", "desc_usable",
    "gl_account", "gl_account_name", "cost_centre", "cost_centre_description",
    # --- 4. HOW MUCH --------------------------------------------------------------------------
    # Signed, exactly as the data holds it. No threshold, no outlier guard, no absolute value.
    "spend", "is_credit",
    # --- 5. WHAT IT WAS CATEGORISED AS - the thing under test ---------------------------------
    # the category as the VIEW carries it, denormalised onto the line. Levels 0-4.
    # scope_status and is_non_procurement sit here because both are pure functions of these same
    # levels - the gate and the reporting segment belong with the values they are derived from.
    #
    # cat_l5 and tx_cat_l5 were DROPPED 2026-08-03. They held ONE value across all 8,000 rows at all
    # four hospitals - the literal text '(no level 5 in this taxonomy)' - because no client taxonomy
    # has a Level 5. Carried as future-proofing, which does not survive contact with the fact that
    # this table is dropped and recreated on every run: adding a column back is one entry in this
    # list, so there was nothing to proof against. The cost was a column of pure noise in every
    # extract an account manager opens.
    #
    # The risk that cutting them creates - a client gaining a Level 5 and us silently discarding it -
    # is closed by check_level_overflow() below, which FAILS the run rather than dropping the data.
    "cat_l0", "cat_l1", "cat_l2", "cat_l3", "cat_l4", "taxonomy_key",
    "scope_status", "is_non_procurement",
    # --- 6. WHAT THE TAXONOMY SAYS - the yardstick --------------------------------------------
    # the category as the CLIENT TAXONOMY defines it, resolved through the join. This is the
    # judge's ground truth and the half that was missing: without it there is no full path, no
    # sibling set and no definition, so nothing the judge is supposed to reason against.
    #
    # ISOLATION: taxonomy_source names the exact table AND database the row came from, on every
    # row. A taxonomy row from one hospital resolving another hospital's line would corrupt the
    # yardstick invisibly - the keys collide across clients while meaning different things.
    # tx_levels_present dropped 2026-08-03 - it held ONE value across all 8,000 rows ('0,1,2,3,4'),
    # and the '(no level N in this taxonomy)' marker already states absence per column.
    # tx_cat_l0..l4, tx_category_addressable and tx_category_description were REMOVED 2026-08-03.
    # They are properties of the CATEGORY, not of the line, and qa_category now holds them - it did
    # not exist when they were added. Measured before removing: qa_category reproduces tx_cat_l0..l4
    # on 316,430 of 316,430 joined lines (100.00%), joined on taxonomy_key. Seven columns on 2.76M
    # rows storing what ~240 rows per hospital already hold. Same argument that keeps rule text on
    # qa_rule.
    #
    # NOTHING derived is lost: cat_path_agrees reads the taxonomy columns directly from the join,
    # and tx_category_path_full / tx_sibling_count / tx_depth_distinct are computed at load time and
    # stored. Lines that never joined keep their marker - tx_category_path_full still reads
    # '(no taxonomy match) > ...' and tx_join_ok says 'N'.
    "taxonomy_source", "tx_join_ok",
    "tx_category_path_full",
    # --- 7. WHY - what put the line in that category ------------------------------------------
    # UNSPSC is deliberately NOT here. It looked like the richest field on Melbourne's view
    # (35% of all lines) but it is clinical-only: 47% filled on clinical lines, EXACTLY ZERO on
    # the 880,865 in-scope ones. Carrying it would put an always-empty column in every extract.
    # rule_source and rule_priority are deliberately NOT here. They are properties of the RULE -
    # ~4,500 of them against 2.76M lines - and live on qa_rule, joined on the rule_id already
    # present. master_cat_l1..l5 is cut outright: the master taxonomy is explicitly not the QA
    # target, Western has none, and taxonomy_key on every line recovers it in one join if ever
    # needed.
    #
    # rule_priority and rule_source ARE here, reversing that exclusion, on Sameer's suggestion
    # 2026-08-03: "think about if from the rule sheet we add this detail? Priority". Measured on the
    # full in-scope population, and it is the sharpest triage signal found so far - LOWEST is the
    # catch-all tier that fires only when nothing more specific matched, so those lines are where
    # the errors will concentrate:
    #
    #   Melbourne  LOWEST 68.0%  HIGHEST 11.7%  MEDIUM  8.6%   unresolved 11.6%
    #   Northern   LOWEST 53.4%  HIGHEST 18.1%  MEDIUM 13.7%   unresolved 14.7%
    #   SAH        LOWEST 37.0%  HIGHEST  0.0%  MEDIUM  6.3%   unresolved 56.6%
    #   Western    Lowest 23.8%  Highest 14.2%  Medium 37.6%   unresolved 24.4%
    #
    # rule_source is the tier LABEL and it is how the borrowed-rule finding becomes visible per
    # line: 'C. OTHER CLIENT RULES', 'D. MATER RULES' at Melbourne on 35,269 lines, and Sydney
    # Adventist's PRIMARY tier labelled 'A. NH RULES' on 37% of its in-scope lines.
    #
    # This is the same argument that puts the verdict on the line: a raw table dump has to answer
    # the question without a join. The exclusion above still holds for rule TEXT - field/operator/
    # value belong on qa_rule and are not copied onto 2.76M rows.
    "rule_id", "rule_priority", "rule_source",
    # --- 8. THE VERDICT -----------------------------------------------------------------------
    # Added 2026-08-03, and moved to sit directly after rule_id 2026-08-03. Until the verdict block
    # existed nothing in this table said whether a line's category is WRONG - it held the inputs to
    # that decision and not the decision, and there was a real risk of cat_path_agrees being read
    # as a verdict. It is not one (see group 9).
    #
    # These are NULL until the judge is built in Phase 0.5, and are here so the shape is visible
    # and the Excel layout can be settled before there is data to reshape around.
    "verdict", "confidence",
    "suggested_cat_l0", "suggested_cat_l1", "suggested_cat_l2", "suggested_cat_l3",
    "suggested_cat_l4",
    "basis", "rationale",
    # --- 9. THE EVIDENCE BEHIND THE VERDICT ---------------------------------------------------
    # Moved here 2026-08-03. These three are the machinery a reader checks AFTER reading the
    # verdict, not part of the categorisation itself: how many alternatives existed under the same
    # parent, how deep the real path goes, and whether the view's copy still matches the taxonomy.
    #
    # cat_path_agrees is NOT a verdict and must never be read as one - it only says the line's
    # label still matches the taxonomy row for the same code, and it reads Y on 100% of joined rows
    # at three of the four hospitals. Both sides can be wrong together. Sitting after `rationale`
    # rather than in the middle of the category block is part of the point.
    #
    # tx_depth dropped 2026-08-03 - populated depth OVERSTATES real depth wherever the taxonomy pads
    # by repeating the leaf, and the two disagree on 96.5% of Northern's rows. tx_depth_distinct is
    # the honest measure and is the one the sibling set is taken from.
    "tx_sibling_count", "tx_depth_distinct", "cat_path_agrees",
    # --- 10. THE JOIN KEYS --------------------------------------------------------------------
    # Plumbing, so they sit at the far right where they are out of the reading path but still in
    # every extract. Both are computed - every input exists, and they are deterministic by
    # construction. unit_key is the seam to Excel: an owner's recorded status re-attaches by join.
    "unit_key", "subject_key",
]
NUMERIC = {"spend", "tx_sibling_count", "tx_depth_distinct", "confidence"}

# --- the DATABASE-FACING column names -------------------------------------------------------------
# Sameer, 2026-08-05: capitalise every column and spell the abbreviations out. These are the names
# an account manager and the app both read, so they are written for a person, not for the code.
#
# Deliberately a MAPPING rather than a rename of the Python keys. Several internal keys collide with
# the CLIENT-side config keys - `cat_l0`, `spend`, `taxonomy_key` all appear in clientcfg.column_map
# meaning "the client's column", not "ours". Renaming the Python names in place would silently
# rewrite half of those too. The alias is applied at exactly one point: where the SELECT is built.
OUT_NAME = {
    "run_id": "RUN_ID", "client_code": "CLIENT_CODE", "source_row_id": "SOURCE_ROW_ID",
    "invoice_number": "INVOICE_NUMBER", "invoice_date": "INVOICE_DATE",
    "Supplier_Name": "SUPPLIER_NAME", "supplier_number": "SUPPLIER_NUMBER", "abn": "ABN",
    "item_desc": "ITEM_DESCRIPTION", "desc_usable": "DESCRIPTION_USABLE",
    "gl_account": "GL_ACCOUNT", "gl_account_name": "GL_ACCOUNT_NAME",
    "cost_centre": "COST_CENTRE", "cost_centre_description": "COST_CENTRE_DESCRIPTION",
    "spend": "SPEND", "is_credit": "IS_CREDIT",
    "cat_l0": "CATEGORY_LVL_0", "cat_l1": "CATEGORY_LVL_1", "cat_l2": "CATEGORY_LVL_2",
    "cat_l3": "CATEGORY_LVL_3", "cat_l4": "CATEGORY_LVL_4",
    "taxonomy_key": "TAXONOMY_KEY", "scope_status": "SCOPE_STATUS",
    "is_non_procurement": "IS_NON_PROCUREMENT", "taxonomy_source": "TAXONOMY_SOURCE",
    "tx_join_ok": "TAXONOMY_JOIN_OK", "tx_category_path_full": "TAXONOMY_CATEGORY_PATH",
    "rule_id": "RULE_ID", "rule_priority": "RULE_PRIORITY", "rule_source": "RULE_SOURCE",
    "verdict": "VERDICT", "confidence": "CONFIDENCE",
    "suggested_cat_l0": "SUGGESTED_CATEGORY_LVL_0",
    "suggested_cat_l1": "SUGGESTED_CATEGORY_LVL_1", "suggested_cat_l2": "SUGGESTED_CATEGORY_LVL_2",
    "suggested_cat_l3": "SUGGESTED_CATEGORY_LVL_3", "suggested_cat_l4": "SUGGESTED_CATEGORY_LVL_4",
    "basis": "BASIS", "rationale": "RATIONALE",
    "tx_sibling_count": "TAXONOMY_SIBLING_COUNT", "tx_depth_distinct": "TAXONOMY_DEPTH",
    "cat_path_agrees": "CATEGORY_PATH_AGREES",
    "unit_key": "UNIT_KEY", "subject_key": "SUBJECT_KEY",
}


def out(f):
    """The database column name for an internal field name. Uppercase is the fallback, so a new
    field is never silently written in lower case just because nobody added it to the map."""
    return OUT_NAME.get(f, f.upper())
# Judge-filled, so NULL on every row today. Named here so the loader does not try to source them
# from a client column that does not exist.
JUDGE_FILLED = ["verdict", "confidence", "suggested_cat_l0", "suggested_cat_l1",
                "suggested_cat_l2", "suggested_cat_l3", "suggested_cat_l4", "basis", "rationale"]
# --- REMOVED 2026-07-31, and why. "No stale elements" - Sameer. ------------------------------------
#   method                  three values ('Rules' / null / 'Pharma' on 7 SAH rows) and NULL on all
#                           of Western. Duplicates `rule_id IS NULL`, which every client has. The
#                           plan already recorded it as captured-but-unused; now it is gone.
#   tx_sibling_count_leaf   the superseded fixed-Level-3 sibling measure, carried for one run so the
#                           correction was auditable rather than asserted. It has been audited.
#   tx_category_path        the taxonomy's `Category` STRING - a SECOND copy of the path that can
#                           disagree with the Category Level columns the QA actually judges on.
#                           Measured: 19 / 11 / 31 / 0 rows diverge (0.8% / 0.8% / 2.2% / 0%), e.g.
#                           Melbourne key with string 'Non-Clinical > Professional Services > ...'
#                           against levels 'Non-Clinical > ICT > ...'. Small, but two sources of
#                           truth for the same fact is exactly the ambiguity to remove before
#                           judging. `tx_category_path_full` is built from the levels and stays.
#   tx_category_label       blank on 100% of Western and 21-28% elsewhere, and it matches neither
#                           Level 3 nor Level 4 - a third naming of a thing already named twice.
#   is_extreme_value        NEVER ADDED. Standing instruction from Sameer 2026-07-31: the spend is
#                           reported exactly as the data holds it. No threshold, no outlier guard,
#                           no exclusion, no flag.
#   desc_is_placeholder     removed 2026-08-03. The complement of one branch of desc_source, so it
#                           carried no fact desc_source did not - identical on 8,000 of 8,000 rows,
#                           and identical by construction rather than by coincidence.
# Text that occupies a description field without describing anything. These read as 100% filled on
# any fill-rate check, which is how 162,000 lines at Melbourne and Sydney Adventist were counted as
# judgeable when they are not. Flagged, never rewritten - the stored value stays as the client has it.
PLACEHOLDERS = ["NO DESCRIPTION", "NO DESC", "N/A", "NA", "UNKNOWN", "NONE", "NIL", "TBA",
                "MISC", "MISCELLANEOUS", "SUNDRY", ".", "-", "XXX",
                # "NULL" added 2026-08-17. The literal four-letter STRING, not a SQL NULL - so it
                # is non-blank, and every fill-rate check read it as a populated description.
                # 42 pilot lines carry it. Found because the judge kept saying "no usable
                # description" on lines our own flag called usable, and Sameer asked why.
                # The judge was right and our flag was wrong on those rows.
                "NULL"]
# Taxonomy-side columns, mapped to the name each client's taxonomy actually uses. Resolved
# against INFORMATION_SCHEMA at runtime because Western's taxonomy has 10 columns to Northern's 23.
TX_COLUMNS = {
    "tx_category_addressable": ["Category Adressable"],   # sic - missing 'd', in all four
    "tx_category_description": ["Category Description"],
}
# Fields whose absence degrades the report rather than stopping the run.
REPORTABLE = ["invoice_number", "invoice_date", "gl_account_name", "cost_centre_description",
              "taxonomy_key", "abn"]


# The category levels this table carries: 0 to the deepest any client taxonomy actually populates.
# NOT clientcfg.MAX_CATEGORY_LEVEL, which is the width the full-project schema reserves. The two
# differ on purpose and check_level_overflow() is what keeps the difference honest.
LEVELS = range(clientcfg.DEEPEST_OBSERVED_LEVEL + 1)


def check_level_overflow(client_key, tx_cols):
    """FAIL the run if a taxonomy has grown a level deeper than this table carries.

    Dropping cat_l5/tx_cat_l5 was safe only because no client taxonomy has a Level 5. If one gains
    one - and clientcfg notes Sydney Adventist's newer Master_Taxonomy uses Levels 1-5 - the loader
    would otherwise carry on and silently discard the deepest, most specific level of the
    categorisation under test. That is precisely the failure that looks like success. So it stops."""
    over = [i for i in range(clientcfg.DEEPEST_OBSERVED_LEVEL + 1,
                             clientcfg.MAX_CATEGORY_LEVEL + 1)
            if f"Category Level {i}" in tx_cols]
    if over:
        raise SystemExit(
            f"\n  STOP - {client_key}'s taxonomy now has Category Level {over} and this table only "
            f"carries 0-{clientcfg.DEEPEST_OBSERVED_LEVEL}.\n"
            f"  Add cat_l{over[0]} / tx_cat_l{over[0]} to FIELDS and raise "
            f"clientcfg.DEEPEST_OBSERVED_LEVEL to {max(over)} before re-running.\n"
            f"  Refusing to load rather than drop the deepest level of the categorisation "
            f"under test.\n")


def _txt(col, alias="v"):
    """Trimmed nvarchar, table-qualified. TRIM matters everywhere - one client stores 'Clinical '
    with a trailing space, and SQL Server pads on comparison where Python does not.

    The alias is not optional: once the taxonomy is joined, `Category Level 0` exists on BOTH
    sides and an unqualified reference is ambiguous. That ambiguity is the whole point of the
    join - the view's copy and the taxonomy's original can disagree."""
    return f"LTRIM(RTRIM(CONVERT(nvarchar(400), {alias}.[{col}])))"


def _col_or_null(cols, field):
    return _txt(cols[field]) if field in cols else "CAST(NULL AS nvarchar(400))"


def load_rules(cfg, client_key, cur, rule_ids, run_id):
    """The fix queue for the RuleIDs this client's sample actually used.

    Rule text comes from the client's own rules table(s) - a client's RuleIDs may span more than one,
    and Western's second table resolves 20.7% of its in-scope lines. Impact is measured on the FULL
    in-scope population, because a rule's importance has nothing to do with how many of its lines
    happened to land in a sample."""
    cols = clientcfg.column_map(cfg)
    tbl, c0, rid = clientcfg.source_table(cfg), cols["cat_l0"], cols["rule_id"]
    sup, spend = cols["supplier"], cols["spend"]

    def T(e):
        return f"LTRIM(RTRIM(CONVERT(nvarchar(200), {e})))"

    ids = [r for r in rule_ids if r]
    if not ids:
        return []
    inlist = ", ".join("'" + r.replace("'", "''") + "'" for r in ids)

    # --- impact, one grouped scan. Clinical counted in the same pass, for the blast-radius flag.
    excl = ["Clinical"] + list(clientcfg.scope_exclusions(cfg))
    notin = ", ".join(f"'{v}'" for v in excl)
    gate = f"(({T(f'v.[{c0}]')} NOT IN ({notin})) OR v.[{c0}] IS NULL)"
    dparts = ", ".join(f"NULLIF({T(f'v.[{d}]')},'')" for d in clientcfg.description_fields(cfg))
    path = " + '|' + ".join(f"ISNULL({T(f'v.[{cols[c]}]')},'')"
                            for c in clientcfg.CATEGORY_LEVELS[:5] if c in cols)
    unit = f"{T(f'v.[{sup}]')} + '|' + COALESCE({dparts}, '') + '|' + {path}"
    cur.execute(f"""SELECT {T(f'v.[{rid}]')},
          SUM(CASE WHEN {gate} THEN 1 ELSE 0 END),
          COUNT(DISTINCT CASE WHEN {gate} THEN {unit} END),
          COUNT(DISTINCT CASE WHEN {gate} THEN {T(f'v.[{sup}]')} END),
          SUM(CASE WHEN {gate} THEN TRY_CONVERT(float, v.[{spend}]) ELSE 0 END),
          SUM(CASE WHEN {T(f'v.[{c0}]')} = 'Clinical' THEN 1 ELSE 0 END)
        FROM {tbl} v WHERE {T(f'v.[{rid}]')} IN ({inlist})
        GROUP BY {T(f'v.[{rid}]')}""")
    impact = {r[0]: r[1:] for r in cur.fetchall()}

    # --- rule text, from every configured rules table, primary first
    text = {}
    for rt in clientcfg.rules_tables(cfg):
        bare = rt.replace("[", "").replace("]", "").split(".")[-1]
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?", bare)
        have = {c[0] for c in cur.fetchall()}
        pick = {}
        for internal, cands in RULE_SRC.items():
            hit = next((c for c in cands if c in have), None)
            pick[internal] = f"{T(f'r.[{hit}]')}" if hit else "CAST(NULL AS nvarchar(200))"
        sel = ", ".join(f"{pick[f]} AS [{f}]" for f in RULE_SRC)
        cur.execute(f"SELECT {T('r.[RuleID]')} AS rid, {sel} FROM {rt} r "
                    f"WHERE {T('r.[RuleID]')} IN ({inlist})")
        for row in cur.fetchall():
            text.setdefault(row[0], (rt, dict(zip(RULE_SRC, row[1:]))))

    out = []
    for r in ids:
        rt, t = text.get(r, (None, {}))
        n_lines, n_units, n_vend, sp, n_clin = impact.get(r, (0, 0, 0, 0.0, 0))
        row = {"run_id": run_id, "client_code": client_key, "rule_id": r,
               "rules_table": rt, "resolves": "Y" if rt else "N",
               "lines_in_scope": n_lines, "units_in_scope": n_units,
               "vendors_in_scope": n_vend, "spend_in_scope": sp, "lines_clinical": n_clin,
               "lines_per_unit": (n_lines / n_units) if n_units else None}
        row.update({f: t.get(f) for f in RULE_SRC})
        # 'DESCRIPTION' matches ITEM_DESCRIPTION, PO LINE DESCRIPTION and INVOICE DESCRIPTION at
        # every client. NULL rather than 'N' when the rule did not resolve - we do not know what an
        # unresolved rule tests, and 'N' would assert that it ignores the description.
        fields = [row.get(f) for f in ("field_1", "field_2", "field_3")]
        row["tests_description"] = (
            None if not rt else
            "Y" if any("DESCRIPTION" in (f or "").upper() for f in fields) else "N")
        out.append(tuple(row[f] for f in RULE_FIELDS))
    return out


def desc_expression(cfg):
    """The composed item text, placeholder-aware. Returns (expression, usable_predicate).

    ONE definition, exported, because a judge unit is (vendor, THIS TEXT, category) and any code
    that COUNTS units must compose the text exactly as the code that LOADS them does.

    Found the hard way 2026-08-03: build_pilot's rule ranker had its own copy that took the first
    NON-BLANK field where this takes the first USABLE one. Melbourne stores the literal string
    'NO DESCRIPTION' on 12.3% of its lines, so the ranker folded every one of those into a single
    unit per category and undercounted by 2x - 500 units budgeted, 1,023 loaded. The budget being
    wrong was the visible symptom; the dangerous one was `qa_rule.is_complete`, which compares
    units judged against units_in_scope and would have certified rules as settled EXACTLY when they
    were half judged. A wrong count that reads as success is the worst failure this project has.
    """
    desc = clientcfg.description_fields(cfg)
    ph = ", ".join(f"'{p}'" for p in PLACEHOLDERS)

    def usable(d):
        return f"CASE WHEN UPPER({_txt(d)}) IN ({ph}) THEN NULL ELSE NULLIF({_txt(d)},'') END"

    # fall back to the first field's raw value so a placeholder is still CARRIED, never blanked -
    # the stored text stays exactly what the client has, and desc_usable is what marks it.
    expr = f"COALESCE({', '.join(usable(d) for d in desc)}, {_txt(desc[0])}, '')"
    return expr, usable


def cat_expression(cfg, i):
    """One assigned category level, with absence STATED rather than left blank.

    Which word depends on LEVEL 0, not on this level. Sameer, 2026-08-04: "if level 0 is
    uncategorised and levels 1-4 are uncategorised the levels 0-4 should read as uncategorised as
    well."

        Level 0 empty  -> EVERY level reads 'Uncategorised'. The line was never categorised, so
                          there is no path at all, and saying "(not used at this level)" at Level 1
                          would imply a genuine three-level category that stops there.
        Level 0 filled, this level empty -> '(not used at this level)'. The line IS categorised;
                          its path is simply shorter than four levels. ~230 of 1,999 pilot units.
    """
    cm = clientcfg.column_map(cfg)
    vc = cm.get(f"cat_l{i}")
    if not vc:
        return f"'{clientcfg.NO_SUCH_LEVEL.format(i)}'"
    if i == 0:
        return (f"CASE WHEN NULLIF({_txt(vc)},'') IS NULL "
                f"THEN '{clientcfg.LEVEL_UNCATEGORISED}' ELSE {_txt(vc)} END")
    l0 = cm.get("cat_l0")
    # No Level 0 column at all for this client: fall back to the per-level marker.
    if not l0:
        return (f"CASE WHEN NULLIF({_txt(vc)},'') IS NULL "
                f"THEN '{clientcfg.LEVEL_NOT_USED}' ELSE {_txt(vc)} END")
    return (f"CASE WHEN NULLIF({_txt(l0)},'') IS NULL THEN '{clientcfg.LEVEL_UNCATEGORISED}' "
            f"WHEN NULLIF({_txt(vc)},'') IS NULL THEN '{clientcfg.LEVEL_NOT_USED}' "
            f"ELSE {_txt(vc)} END")


def unit_parts(cfg, client_key):
    """The judge unit's ingredients, in order: client + vendor + item text + assigned category.

    The vendor goes in VERBATIM - the key must be derived from what is stored, or the key and the
    column would disagree about what a vendor is. The assigned category is INSIDE the unit on
    purpose: drop it and the Cleanaway Case B situation (same vendor, same text, two different
    categories) collapses into one verdict and hides a real rule defect.
    """
    sup = clientcfg.column_map(cfg)["supplier"]
    return ([f"'{client_key}'", _verbatim(sup), desc_expression(cfg)[0]]
            + [cat_expression(cfg, i) for i in LEVELS])


def unit_concat(cfg, client_key):
    """The unit as one delimited string - for COUNT(DISTINCT ...) without hashing."""
    return " + '|' + ".join(f"ISNULL({p}, '')" for p in unit_parts(cfg, client_key))


def _verbatim(col, alias="v"):
    """The column exactly as the client stores it - no trim, no case fold, no rewrite.

    Used for the vendor name on Sameer's standing instruction of 2026-07-31. The value an account
    manager sees in our extract has to be the value they can paste into their own system and find.
    CONVERT is a widening type cast only, so it changes nothing about the text."""
    return f"CONVERT(nvarchar(400), {alias}.[{col}])"


def build_select(cfg, client_key, n, spread, tx_cols=frozenset(), run_id="smoke", rule_cols=(),
                 rule_ids=None, strata=None, census=False):
    """One SELECT producing the full qa_line shape for this client. All differences between
    hospitals are resolved here, from config - never by branching on a client name.

    tx_cols is the set of columns that actually exist in THIS client's taxonomy table.
    rule_cols is [(table, {columns}), ...] for EVERY configured rules table, primary first.

    rule_ids, when given, switches from SAMPLING to CENSUS-OF-A-STRATUM: every in-scope line
    belonging to those rules, no TOP, no vendor spread. That is what makes a rule's error rate
    exact rather than estimated - the whole point of selecting rules by lines-per-unit. This
    function is shared with the real loader on purpose: one definition of the line shape, so the
    smoke test cannot drift from what Phase 0.5 actually writes.

    census=True is the FULL POPULATION: every in-scope line for the client, no TOP, no
    strata, no vendor spread. Added 2026-08-20 for the production load. Until then the
    only paths here were SAMPLE and CENSUS-OF-NAMED-RULES - there was no way to ask for
    all of it, which is what actually blocked loading production (RUN_LOG Finding 104).
    No ORDER BY: ordering a census is meaningless work, and SQL Server rejects ORDER BY
    in a derived table without TOP anyway."""
    cols = clientcfg.column_map(cfg)
    desc = clientcfg.description_fields(cfg)
    tbl = clientcfg.source_table(cfg)
    spend = cols["spend"]
    c0 = cols["cat_l0"]

    # description: first USABLE field of the priority list wins, plus WHICH field supplied it.
    #
    # 'Usable', not merely 'non-blank'. Melbourne and Sydney Adventist store the literal string
    # 'NO DESCRIPTION', which is non-blank - so a plain COALESCE stops there and never tries the
    # next field even when that field has real text. It is a small recovery (1,108 Melbourne lines)
    # but it is free, and desc_source records which column actually supplied the text, so nothing
    # is hidden by the change.
    # from desc_expression() - the SINGLE definition, shared with whatever counts units
    desc_expr, usable = desc_expression(cfg)
    any_usable = " OR ".join(f"{usable(d)} IS NOT NULL" for d in desc)
    sel_usable = f"CASE WHEN {any_usable} THEN 'Y' ELSE 'N' END"

    # scope: two conditions, both trimmed. Uncategorised is IN scope, flagged separately.
    excl = [v.strip() for v in
            set(clientcfg.clinical_exclusions(cfg)) | set(clientcfg.scope_exclusions(cfg))]
    notin = ", ".join(f"'{v}'" for v in excl) or "''"
    scope = (f"CASE WHEN v.[{c0}] IS NULL OR {_txt(c0)} = '' THEN 'in_scope_uncategorised' "
             f"WHEN {_txt(c0)} IN ({notin}) THEN 'out_of_scope' ELSE 'in_scope' END")

    # the accounting-noise reporting segment: Non-Procurement at Level 0 OR Level 1. A label, never
    # a filter - nothing is dropped, it is excluded from the headline accuracy figure and reported
    # in its own right. Derived here rather than stored upstream: it is a pure function of the path.
    np_cols = [cols[c] for c in ("cat_l0", "cat_l1") if c in cols]
    non_proc = (" OR ".join(f"{_txt(c)} = 'Non-Procurement'" for c in np_cols)
                if np_cols else "1 = 0")

    sel = {
        "run_id": f"'{run_id}'",
        "client_code": f"'{client_key}'",
        # VERBATIM - see _verbatim(). Do not wrap this in LTRIM/RTRIM/UPPER.
        # `cols["supplier"]` is the CONFIG key and stays as it is; Supplier_Name is the output
        # column. The two are deliberately not the same name - one is per-client mapping, the
        # other is the shape every client lands in.
        "Supplier_Name": _verbatim(cols["supplier"]),
        "item_desc": desc_expr,
        "desc_usable": sel_usable,
        "spend": f"TRY_CONVERT(float, v.[{spend}])",
        "is_credit": f"CASE WHEN TRY_CONVERT(float, v.[{spend}]) < 0 THEN 1 ELSE 0 END",
        "scope_status": scope,
        "is_non_procurement": f"CASE WHEN {non_proc} THEN 'Y' ELSE 'N' END",
    }

    # --- the rule's tier and priority, resolved across EVERY configured rules table -------------
    # Single-table would be actively misleading, not merely incomplete: Western's second table
    # PMML_Medical_Rules carries 20.7% of its in-scope lines, and those lines would read as having
    # no priority when they have one. UNION ALL with an explicit ordinal, then TOP 1 by that
    # ordinal, so the primary table wins where a RuleID exists in both - the same precedence
    # load_rules() uses for rule text.
    #
    # Correlated, but it sits OUTSIDE the TOP n derived table, so it evaluates against the sampled
    # rows only - not against the 3.4M-row view. Same principle as the taxonomy join below.
    rule_join = ""
    if "rule_id" in cols and rule_cols:
        legs = []
        for i, (rt, rcs) in enumerate(rule_cols):
            pr = _txt("Priority", "r") if "Priority" in rcs else "CAST(NULL AS nvarchar(400))"
            sc = _txt("Source", "r") if "Source" in rcs else "CAST(NULL AS nvarchar(400))"
            legs.append(f"SELECT {i} AS ord, {pr} AS pr, {sc} AS src FROM {rt} r "
                        f"WHERE {_txt('RuleID', 'r')} = {_txt(cols['rule_id'])}")
        if legs:
            rule_join = ("\nOUTER APPLY (SELECT TOP 1 z.pr, z.src FROM ("
                         + " UNION ALL ".join(legs) + ") z ORDER BY z.ord) rp")
            sel["rule_priority"] = "rp.pr"
            sel["rule_source"] = "rp.src"

    # --- taxonomy join: the client's OWN definition of the category, which is the standard the
    # judge is measured against. Absent this, the smoke test only proves we can read the label
    # the view already denormalised onto the line - which is the thing under suspicion.
    tx_tbl = clientcfg.taxonomy_table(cfg)
    tx_key = clientcfg.taxonomy_join_column(cfg)
    join_sql = ""
    if tx_tbl and tx_key and "taxonomy_key" in cols:
        # The taxonomy is referenced with a one- or two-part name ONLY, so it resolves inside the
        # connection already opened for this client. There is no server-, database- or linked-
        # server qualifier anywhere in this query, which is what makes cross-client contamination
        # structurally impossible rather than merely unlikely. clientcfg.assert_same_database()
        # refuses any config that tries to widen it.
        join_sql = (f"\nLEFT JOIN {tx_tbl} tx "
                    f"ON LTRIM(RTRIM(CONVERT(nvarchar(80), tx.[{tx_key}]))) "
                    f" = LTRIM(RTRIM(CONVERT(nvarchar(80), v.[{cols['taxonomy_key']}])))")
        for internal, cands in TX_COLUMNS.items():
            hit = next((c for c in cands if c in tx_cols), None)
            sel[internal] = (f"LTRIM(RTRIM(CONVERT(nvarchar(400), tx.[{hit}])))" if hit
                             else "CAST(NULL AS nvarchar(400))")
        sel["tx_join_ok"] = f"CASE WHEN tx.[{tx_key}] IS NOT NULL THEN 'Y' ELSE 'N' END"

        # --- levels 0-5, on BOTH sides, with absence stated rather than left blank -------------
        # Three distinct situations that a blank cell would conflate:
        #   the taxonomy has no such level at all   -> "(no level 5 in this taxonomy)"
        #   it has the level but this row is empty  -> "(blank at this line)"
        #   the line never joined                   -> "(no taxonomy match)"
        for i in LEVELS:
            tc = f"Category Level {i}"
            if tc in tx_cols:
                sel[f"tx_cat_l{i}"] = (
                    f"CASE WHEN tx.[{tx_key}] IS NULL THEN '{clientcfg.NO_TAXONOMY_MATCH}' "
                    f"WHEN NULLIF({_txt(tc, 'tx')},'') IS NULL THEN '{clientcfg.LEVEL_NOT_USED}' "
                    f"ELSE {_txt(tc, 'tx')} END")
            else:
                sel[f"tx_cat_l{i}"] = f"'{clientcfg.NO_SUCH_LEVEL.format(i)}'"
            # the line side gets the same treatment - Melbourne's Level 4 is blank on 55% of lines.
            # From cat_expression(), so the loader and the unit counter cannot disagree.
            sel[f"cat_l{i}"] = cat_expression(cfg, i)
        # Provenance stamped on EVERY row: which database and which table this category came from.
        # If a Melbourne line ever carried a Northern taxonomy source, it would be visible in the
        # data itself rather than inferable only from the code that produced it.
        db_name = ((cfg.get("source") or {}).get("database") or "?")
        sel["taxonomy_source"] = "'" + f"{db_name}.{tx_tbl}".replace("'", "") + "'"

        # The complete path, every level spelled out including the absent ones. This is the column
        # to read when you want the whole story on one line without joining anything.
        sel["tx_category_path_full"] = " + ' > ' + ".join(
            sel[f"tx_cat_l{i}"] if sel[f"tx_cat_l{i}"].startswith("'")
            else f"({sel[f'tx_cat_l{i}']})"
            for i in LEVELS)
        # Populated depth OVERSTATES real depth: these taxonomies pad shallow categories by
        # repeating the leaf - 'Beverages > Beverages > Beverages', 'Other > Other > Other'.
        # Distinct depth is the honest measure, and it decides where the sibling set is taken from,
        # so it is computed ONCE per row in an OUTER APPLY rather than inlined six times.
        vals = ", ".join(f"({_txt(f'Category Level {i}', 'tx')})"
                         for i in LEVELS
                         if f"Category Level {i}" in tx_cols)
        if vals:
            join_sql += (f"\nOUTER APPLY (SELECT COUNT(DISTINCT x) AS dd "
                         f"FROM (VALUES {vals}) AS d(x) WHERE x IS NOT NULL AND x <> '') dd")
            sel["tx_depth_distinct"] = "dd.dd"
        else:
            sel["tx_depth_distinct"] = "CAST(NULL AS int)"

        # --- the sibling set: the alternatives under the SAME PARENT -----------------------------
        # "Should this sit here, or in the box next door" is the judge's actual question, so the
        # sibling set is judge INPUT and not decoration. It therefore has to contain something.
        #
        # Taken at a fixed Category Level 3 it does not. Measured 2026-07-31 across the whole of
        # each taxonomy, grouping on Levels 0-3 leaves the set at exactly ONE - the category already
        # assigned - for 87% of Melbourne's categories, 64% of Northern's and Western's and 60% of
        # Sydney Adventist's. The cause is the padding above: where Level 4 repeats Level 3,
        # Levels 0-3 ARE the leaf, so "what else is here" has no answer by construction. That is not
        # a Northern data quirk, which is what its 0.9 average was first read as - it was ours.
        #
        # The parent is the path with the LAST DISTINCT level removed. Each condition below drops
        # out once the row's distinct depth is shallower than that level, so a category whose real
        # leaf is Level 3 matches on Levels 0-2, one whose leaf is Level 4 matches on 0-3, and so
        # on. Yields ~11 real alternatives per category at all four clients.
        # Matching the parent path alone is NOT enough, and the first attempt at this got it wrong:
        # every DESCENDANT of the parent matches those conditions too, so it counted the whole
        # subtree and returned 250-350 "siblings". What is wanted is the alternatives at the SAME
        # level - the direct children of the parent - which is the count of DISTINCT values at the
        # leaf level among the rows under it. Deeper rows collapse into their own ancestor's value
        # and stop inflating the number.
        lvls = [i for i in LEVELS if f"Category Level {i}" in tx_cols]
        sib = [f"(dd.dd < {i + 2} OR {_txt(f'Category Level {i}', 's')} "
               f"= {_txt(f'Category Level {i}', 'tx')})" for i in lvls]
        leaf = "CASE dd.dd " + " ".join(
            f"WHEN {i + 1} THEN {_txt(f'Category Level {i}', 's')}" for i in lvls) + " END"
        # The leaf expression has to be projected in a derived table before it is aggregated:
        # SQL Server refuses an aggregate whose argument mixes an outer reference (dd.dd) with
        # inner columns. Same result, one level of nesting.
        sel["tx_sibling_count"] = (
            f"(SELECT COUNT(DISTINCT z.leaf) FROM (SELECT {leaf} AS leaf FROM {tx_tbl} s "
            f"WHERE {' AND '.join(sib)}) z)" if sib and vals else "CAST(NULL AS int)")
        # does the view's denormalised category still agree with the taxonomy it came from?
        # A disagreement means the dashboard and the taxonomy have drifted apart.
        agree = " AND ".join(
            f"ISNULL(LTRIM(RTRIM(CONVERT(nvarchar(200), v.[{cols['cat_l'+str(i)]}]))),'') = "
            f"ISNULL(LTRIM(RTRIM(CONVERT(nvarchar(200), tx.[Category Level {i}]))),'')"
            for i in LEVELS
            if f"cat_l{i}" in cols and f"Category Level {i}" in tx_cols)
        sel["cat_path_agrees"] = (
            f"CASE WHEN tx.[{tx_key}] IS NULL THEN '(no join)' "
            f"WHEN {agree} THEN 'Y' ELSE 'N' END" if agree else "CAST(NULL AS nvarchar(10))")

    # --- the two deterministic keys ---------------------------------------------------------------
    # Both are hashes of values ALREADY IN THIS ROW, so they are reproducible from the data alone -
    # no counter, no identity column, no dependence on load order. That is the whole point: the plan
    # promises that an owner's recorded status re-attaches on re-run, and that accuracy can be shown
    # MOVING between runs. Neither works against a key that renumbers.
    #
    #   unit_key     client + supplier + item text + the ASSIGNED category path.
    #                One judged unit. The judge rules once per unit and the verdict propagates to
    #                every line sharing the key - which is what makes a census affordable.
    #                The assigned category is IN the key on purpose: drop it and the Cleanaway
    #                Case B situation (same vendor, same text, two different categories) collapses
    #                into one verdict and hides a real rule defect.
    #
    #   subject_key  the same MINUS the category. The movement spine. When a rule is fixed the
    #                category changes, so unit_key changes with it and a naive run-to-run diff reads
    #                "one unit retired, one appeared" instead of "this got fixed". subject_key is a
    #                property of the source line, not of the categorisation under test, so it
    #                survives recategorisation.
    #
    # The supplier goes in VERBATIM here too - the key must be derived from what is stored, or the
    # column and the key would disagree about what a vendor is.
    def _hash(parts):
        joined = " + '|' + ".join(f"ISNULL({p}, '')" for p in parts)
        return f"LEFT(CONVERT(char(64), HASHBYTES('SHA2_256', {joined}), 2), 20)"

    # unit_parts() is the shared definition; asserting it here rather than rebuilding it means the
    # hash and any COUNT(DISTINCT ...) elsewhere are the same thing by construction, not by care.
    parts = unit_parts(cfg, client_key)
    assert parts[1] == sel["Supplier_Name"] and parts[2] == sel["item_desc"], \
        "unit_parts() has drifted from the loaded columns - the keys would stop matching the data"
    sel["subject_key"] = _hash(parts[:3])
    sel["unit_key"] = _hash(parts)

    # Judge output. NULL on every row until Phase 0.5 - present so the shape is visible and the
    # Excel layout can be settled before there is data to reshape around.
    for f in JUDGE_FILLED:
        sel[f] = "CAST(NULL AS float)" if f in NUMERIC else "CAST(NULL AS nvarchar(400))"

    for f in FIELDS:
        if f not in sel:
            sel[f] = _col_or_null(cols, f)

    # --- the sample ------------------------------------------------------------------------------
    # The vendor spread alone is NOT enough, and the first version of this got it wrong. Filtering
    # to 1-in-N vendors and then taking TOP n with no ORDER BY hands the ordering back to the scan,
    # so the result is a leading slice of a vendor subset. Measured 2026-07-31 on the first build:
    # Northern's 2,000 rows came from 55 vendors, 56% of them one vendor, spanning 14 months of a
    # multi-year population; one Melbourne description was 34% of its sample. The cost was not
    # cosmetic - the sample contained ZERO Northern Case B subjects, for the client that has 42,554.
    #
    # So: spread by vendor to keep whole vendors together (the judge's pooled term profile depends
    # on it), then ORDER BY a hash of the line itself so which rows arrive is decided by the data
    # and not by where they sit in the file. Deterministic, so a re-run reproduces the same sample.
    where = f"({_txt(c0)} NOT IN ({notin}) OR v.[{c0}] IS NULL)"
    # out() is applied HERE and nowhere else: the internal names stay as they are (several collide
    # with clientcfg's client-side keys), and only what lands in the database is renamed.
    cols_sql = ",\n       ".join(f"{sel[f]} AS [{out(f)}]" for f in FIELDS)

    # --- the FULL POPULATION -----------------------------------------------------------------
    # Every in-scope line, nothing else. The scope gate is already in `where` and is the ONLY
    # filter: clinical lines are never selected, so they cannot be judged by accident later.
    #
    # No TOP, so nothing caps it; no ORDER BY, because ordering a census is work with no reader.
    # The derived-table shape is kept identical to the other paths so the joins below attach the
    # same way and the column list cannot drift between a sample and a census.
    if census:
        inner = f"(SELECT * FROM {tbl} v WHERE {where}) v"
        return f"SELECT {cols_sql}\nFROM {inner}{join_sql}{rule_join}"

    if rule_ids is not None:
        # CENSUS OF A STRATUM - every in-scope line of these rules, so their error rates come out
        # exact. No TOP and no spread: taking a sample here would defeat the reason the rules were
        # chosen. Still a derived table, so the correlated sibling subquery and the rule join run
        # against the filtered set rather than the whole view.
        if not rule_ids:
            return None
        inlist = ", ".join("'" + r.replace("'", "''") + "'" for r in rule_ids)
        where += f" AND {_txt(cols['rule_id'])} IN ({inlist})"
        inner = f"(SELECT * FROM {tbl} v WHERE {where}) v"
        return f"SELECT {cols_sql}\nFROM {inner}{join_sql}{rule_join}"

    order_key = " + '|' + ".join(
        [f"ISNULL({_txt(cols['supplier'])},'')", "ISNULL(" + desc_expr + ",'')"]
        + ([f"ISNULL({_txt(cols['source_row_id'])},'')"] if "source_row_id" in cols else []))
    order = f"ORDER BY ABS(CHECKSUM({order_key}))"

    if strata is not None:
        # LINE-LEVEL STRATIFIED SAMPLE. Sameer, 2026-08-05: 500 lines per hospital, "a mix of lines
        # which carry category levels and the lines which are left blank ... at least 75% of the
        # lines should have the category levels present in them."
        #
        # Two independent draws rather than one draw plus a filter, because the blank share differs
        # wildly per client (Northern is 25% uncategorised in scope, Western 3.7%) - one draw would
        # give whatever the population happens to hold, not the mix asked for.
        #
        # NO VENDOR SPREAD here, and that is deliberate. The spread existed to keep whole vendors
        # together for a pooled term profile, which mattered when the judged unit was a group. Every
        # line is now judged on its own, so the spread would only narrow the sample for no gain.
        # The hash ORDER BY still decides which rows arrive - never scan order.
        n_cat, n_blank = strata
        filled = f"NULLIF({_txt(c0)},'') IS NOT NULL"
        empty = f"NULLIF({_txt(c0)},'') IS NULL"
        legs = []
        if n_cat:
            legs.append(f"SELECT * FROM (SELECT TOP {n_cat} * FROM {tbl} v "
                        f"WHERE {where} AND {filled} {order}) a")
        if n_blank:
            legs.append(f"SELECT * FROM (SELECT TOP {n_blank} * FROM {tbl} v "
                        f"WHERE {where} AND {empty} {order}) b")
        if not legs:
            return None
        inner = "(" + "\n     UNION ALL\n     ".join(legs) + ") v"
        return f"SELECT {cols_sql}\nFROM {inner}{join_sql}{rule_join}"

    # --- otherwise, the smoke-test sample --------------------------------------------------------
    where += f" AND ABS(CHECKSUM({_txt(cols['supplier'])})) % {spread} = 0"
    # Take the sample FIRST, then resolve the taxonomy against those rows. Written the other way
    # round - one flat SELECT with TOP and an ORDER BY - the optimiser is free to evaluate the
    # correlated sibling subquery for every row of a 3.4M-row view before discarding all but 2,000
    # of them. Same principle as the aggregate-before-join rule that fixed the 15-minute rules
    # query: cut the row count down before doing per-row work, never after.
    inner = f"(SELECT TOP {n} * FROM {tbl} v WHERE {where} {order}) v"
    return f"SELECT {cols_sql}\nFROM {inner}{join_sql}{rule_join}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000, help="lines per client")
    ap.add_argument("--spread", type=int, default=7, help="1-in-N vendor spread")
    ap.add_argument("clients", nargs="*")
    args = ap.parse_args()

    env = load_env()
    wanted = args.clients or clientcfg.list_clients()
    run_id = "smoke-" + datetime.now().strftime("%Y%m%dT%H%M%S")

    qa = connect_qa(pilot=True, env=env)
    qcur = qa.cursor()
    qcur.execute("SELECT DB_NAME()")
    print(f"writing to {qcur.fetchone()[0]}  (pilot only)   run_id = {run_id}")

    ddl_cols = ",\n  ".join(
        f"[{f}] {'float NULL' if f in NUMERIC else 'nvarchar(400) NULL'}" for f in FIELDS)
    qcur.execute(f"IF OBJECT_ID('{TABLE}','U') IS NOT NULL DROP TABLE [{TABLE}]")
    qcur.execute(f"CREATE TABLE [{TABLE}] (\n  smoke_id int IDENTITY(1,1) PRIMARY KEY,\n  {ddl_cols}\n)")
    # The qa_run stand-in. This is where the source fingerprint belongs - ONCE per run per client,
    # not copied onto every line. It is what keeps "the numbers moved" separable from "the ground
    # moved": Sydney Adventist's taxonomy was replaced mid-session on 30 Jul and broke its view, and
    # without an as-at and a structure fingerprint there is no way to tell those two apart later.
    qcur.execute(f"IF OBJECT_ID('{RUN_TABLE}','U') IS NOT NULL DROP TABLE [{RUN_TABLE}]")
    qcur.execute(f"""CREATE TABLE [{RUN_TABLE}] (
      run_id nvarchar(64) NOT NULL, client_code nvarchar(64) NOT NULL,
      loaded_at datetime2 NOT NULL, source_table nvarchar(200) NULL,
      source_columns int NULL, taxonomy_source nvarchar(300) NULL, taxonomy_rows int NULL,
      taxonomy_columns int NULL, rules_tables nvarchar(400) NULL, rules_rows int NULL,
      lines_loaded int NULL, scope_note nvarchar(400) NULL)""")
    # The qa_rule stand-in - the FIX QUEUE. Half the deliverable, and nothing in this database
    # showed it until now: rule text, the tier and priority it fires at, and its impact measured on
    # the full in-scope population rather than on the sample.
    rule_ddl = ",\n  ".join(
        f"[{f}] {'float NULL' if f in RULE_NUMERIC else 'nvarchar(400) NULL'}" for f in RULE_FIELDS)
    qcur.execute(f"IF OBJECT_ID('{RULE_TABLE}','U') IS NOT NULL DROP TABLE [{RULE_TABLE}]")
    qcur.execute(f"CREATE TABLE [{RULE_TABLE}] (\n  rule_row_id int IDENTITY(1,1) PRIMARY KEY,"
                 f"\n  {rule_ddl}\n)")
    rule_ins = (f"INSERT INTO [{RULE_TABLE}] ({', '.join('['+f+']' for f in RULE_FIELDS)}) "
                f"VALUES ({', '.join('?'*len(RULE_FIELDS))})")
    qa.commit()
    print(f"created {TABLE} ({len(FIELDS)} cols), {RUN_TABLE}, {RULE_TABLE} "
          f"({len(RULE_FIELDS)} cols)\n")
    SCOPE_NOTE = ("INDIRECT (non-clinical) spend only. In scope = Category Level 0 is neither "
                  "Clinical nor Inter-Hospital Spend; uncategorised lines are IN scope and flagged.")

    ins = f"INSERT INTO [{TABLE}] ({', '.join('['+f+']' for f in FIELDS)}) VALUES ({', '.join('?'*len(FIELDS))})"
    loaded = {}
    for k in wanted:
        cfg = clientcfg.load_config(k)
        if not cfg or clientcfg.missing_for_run(cfg):
            print(f"  {k:20} SKIPPED - config incomplete")
            continue
        cn = connect_client(k, env=env, timeout=60)
        cn.timeout = 600
        cur = cn.cursor()
        # Which columns this client's taxonomy actually has - Western's has 10, Northern's 23.
        tx_cols = set()
        tx_tbl = clientcfg.taxonomy_table(cfg)
        if tx_tbl:
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                        tx_tbl.replace("[", "").replace("]", "").split(".")[-1])
            tx_cols = {c[0] for c in cur.fetchall()}
        check_level_overflow(k, tx_cols)
        # every configured rules table and the columns it actually has - Western has two, and its
        # second one resolves 20.7% of its in-scope lines
        rule_cols = []
        for rt in clientcfg.rules_tables(cfg):
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                        rt.replace("[", "").replace("]", "").split(".")[-1])
            rule_cols.append((rt, {c[0] for c in cur.fetchall()}))
        q = build_select(cfg, k, args.n, args.spread, tx_cols, run_id, rule_cols)
        try:
            cur.execute(q)
            rows = cur.fetchall()
        except Exception as e:
            print(f"  {k:20} FAILED: {str(e).split(']')[-1].strip()[:90]}")
            cn.close()
            continue
        # fingerprint the SOURCE as it stood for this run, before the connection closes
        src_tbl = clientcfg.source_table(cfg)
        cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?",
                    src_tbl.replace("[", "").replace("]", "").split(".")[-1])
        n_src_cols = cur.fetchone()[0]
        n_tx_rows = None
        if tx_tbl:
            cur.execute(f"SELECT COUNT(*) FROM {tx_tbl}")
            n_tx_rows = cur.fetchone()[0]
        n_rule_rows = 0
        for rt in clientcfg.rules_tables(cfg):
            cur.execute(f"SELECT COUNT(*) FROM {rt}")
            n_rule_rows += cur.fetchone()[0]
        # the fix queue for the RuleIDs this sample actually used
        ridx = FIELDS.index("rule_id")
        used = sorted({(r[ridx] or "").strip() for r in rows} - {""})
        try:
            rule_rows = load_rules(cfg, k, cur, used, run_id)
        except Exception as e:
            print(f"  {k:20} rule load FAILED: {str(e).split(']')[-1].strip()[:80]}")
            rule_rows = []
        cn.close()
        qcur.fast_executemany = False
        qcur.executemany(ins, [tuple(r) for r in rows])
        db_name = ((cfg.get("source") or {}).get("database") or "?")
        qcur.execute(
            f"INSERT INTO [{RUN_TABLE}] (run_id, client_code, loaded_at, source_table, "
            f"source_columns, taxonomy_source, taxonomy_rows, taxonomy_columns, rules_tables, "
            f"rules_rows, lines_loaded, scope_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            run_id, k, datetime.now(), f"{db_name}.{src_tbl}", n_src_cols,
            f"{db_name}.{tx_tbl}" if tx_tbl else None, n_tx_rows, len(tx_cols) or None,
            ", ".join(clientcfg.rules_tables(cfg)), n_rule_rows, len(rows), SCOPE_NOTE)
        if rule_rows:
            qcur.executemany(rule_ins, rule_rows)
        qa.commit()
        loaded[k] = len(rows)
        gaps = clientcfg.missing_for_report(cfg)
        print(f"  {k:20} loaded {len(rows):>6,} lines, {len(rule_rows):>4,} rules"
              + (f"   report gaps: {', '.join(gaps)}" if gaps else ""))

    # --- the point of the exercise: per-column fill, per client ---
    print(f"\n{'='*78}\nFILL MATRIX - % of loaded lines where the column is non-blank\n{'='*78}")
    keys = list(loaded)
    if not keys:
        print("nothing loaded.")
        return 1
    hdr = " ".join(f"{k[:4].upper():>6}" for k in keys)
    print(f"{'COLUMN':30} {hdr}   note")
    print("-" * 78)
    for f in FIELDS:
        if f in ("client_code",):
            continue
        vals = []
        for k in keys:
            if f in NUMERIC:
                qcur.execute(f"SELECT COUNT(*), SUM(CASE WHEN [{f}] IS NOT NULL THEN 1 ELSE 0 END) "
                             f"FROM [{TABLE}] WHERE client_code=?", k)
            else:
                qcur.execute(f"SELECT COUNT(*), SUM(CASE WHEN [{f}] IS NOT NULL AND [{f}]<>'' "
                             f"THEN 1 ELSE 0 END) FROM [{TABLE}] WHERE client_code=?", k)
            n, v = qcur.fetchone()
            vals.append(100.0 * (v or 0) / n if n else 0.0)
        cells = " ".join(("  --  " if v == 0 else f"{v:5.1f}%") for v in vals)
        absent = sum(1 for v in vals if v == 0)
        note = ""
        if absent == len(keys):
            note = "NOT AVAILABLE ANYWHERE"
        elif absent:
            note = f"absent at {absent}"
        elif min(vals) < 50:
            note = f"thin (min {min(vals):.0f}%)"
        print(f"{f:30} {cells}   {note}")

    # --- CROSS-CLIENT ISOLATION. Asserted against the loaded data, not just the code that wrote
    # it. The taxonomy keys collide between hospitals while meaning different things, so a leak
    # would relabel spend against the wrong yardstick with nothing visibly broken.
    print(f"\n{'='*78}\nCROSS-CLIENT ISOLATION\n{'='*78}")
    leaked = 0
    for k in keys:
        cfg = clientcfg.load_config(k)
        own_db = ((cfg.get("source") or {}).get("database") or "?")
        qcur.execute(f"SELECT DISTINCT taxonomy_source FROM [{TABLE}] WHERE client_code=?", k)
        srcs = [row[0] for row in qcur.fetchall() if row[0]]
        foreign = [s for s in srcs if not s.startswith(own_db)]
        leaked += len(foreign)
        mark = "[ok]  " if not foreign else "[FAIL]"
        print(f"  {mark} {k:20} -> {', '.join(srcs) or '(no taxonomy joined)'}")
        if foreign:
            print(f"         FOREIGN TAXONOMY SOURCE: {', '.join(foreign)}")
    qcur.execute(f"SELECT COUNT(DISTINCT taxonomy_source) FROM [{TABLE}]")
    distinct_srcs = qcur.fetchone()[0]
    print(f"\n  {distinct_srcs} distinct taxonomy sources across {len(keys)} clients "
          f"- must equal the client count, one per hospital.")
    print("  " + ("ISOLATION HOLDS: every row's category came from its own hospital's database."
                  if not leaked and distinct_srcs == len(keys)
                  else "** ISOLATION VIOLATED - investigate before using this data. **"))

    # --- taxonomy resolution. Fill rate is the wrong measure for a Y/N flag, so these are
    # reported as rates in their own right: does the join land, does the view still agree with
    # the taxonomy it was derived from, and is there a definition to judge against.
    print(f"\n{'='*78}\nTAXONOMY RESOLUTION - the judge's ground truth\n{'='*78}")
    print(f"{'client':20} {'join':>7} {'agrees':>8} {'has defn':>9} {'siblings':>9}"
          f" {'uniq depth':>11}")
    print("-" * 78)
    for k in keys:
        qcur.execute(f"""SELECT
              AVG(CASE WHEN tx_join_ok='Y' THEN 100.0 ELSE 0 END),
              AVG(CASE WHEN cat_path_agrees='Y' THEN 100.0
                       WHEN cat_path_agrees='N' THEN 0 END),
              CAST(NULL AS float),   -- 'has defn' now lives on qa_category, not the line.
                                     -- 89 of 6,834 categories carry one (1.3%), so boundary calls
                                     -- rest on the category PATH, not on written definitions.
              AVG(tx_sibling_count), AVG(tx_depth_distinct)
            FROM [{TABLE}] WHERE client_code=?""", k)
        j, a, d, sib, dpd = qcur.fetchone()
        fmt = lambda x, s="%": "     --" if x is None else f"{x:6.1f}{s}"
        print(f"{k:20} {fmt(j)} {fmt(a):>8} {fmt(d):>9} "
              f"{('     --' if sib is None else f'{sib:8.1f}')} "
              f"{('         --' if dpd is None else f'{dpd:11.2f}')}")
    print("\n  ** These are SAMPLE rates and the sample is spread by VENDOR, so it is biased for")
    print("     category-side measures. Measured 2026-07-31, it read Sydney Adventist's join rate")
    print("     as 98% where the full-population truth is 82%, and its path drift as 17% where the")
    print("     truth is 37%. Treat these as a smoke signal; quote only full-population figures.")
    print("\n  join     = line's taxonomy_key resolved to a taxonomy row")
    print("  agrees   = view's denormalised Category Level 0-4 still matches the taxonomy's")
    print("  has defn = a written Category Description exists for that line's category")
    print("  siblings = alternative categories under the same parent - judge input, not decoration")
    print("  uniq depth = DISTINCT category level values. The padded count was dropped 2026-08-03:")
    print("             these taxonomies repeat the leaf ('Other > Other > Other'), so populated")
    print("             depth overstates real depth and the two disagreed on 96.5% of Northern.")

    print(f"\n{'='*78}")
    qcur.execute(f"SELECT client_code, scope_status, COUNT(*) FROM [{TABLE}] "
                 f"GROUP BY client_code, scope_status ORDER BY 1,2")
    print("scope split of the loaded sample:")
    for r in qcur.fetchall():
        print(f"  {r[0]:20} {r[1]:26} {r[2]:>6,}")
    # --- the fix queue: what an owner would actually be handed ------------------------------------
    print(f"\n{'='*94}\nTHE FIX QUEUE - {RULE_TABLE}, ranked by judging leverage\n{'='*94}")
    print("  Judging EVERY unit a rule touches makes its error rate exact rather than estimated -")
    print("  a census of the rule. 'units' is therefore the price of a complete verdict on it.\n")
    print(f"  {'client':20} {'RuleID':14} {'units':>7} {'lines':>9} {'per unit':>9} "
          f"{'vendors':>8} {'spend':>15}")
    print("  " + "-" * 90)
    for k in keys:
        qcur.execute(f"""SELECT TOP 3 client_code, rule_id, units_in_scope, lines_in_scope,
                          lines_per_unit, vendors_in_scope, spend_in_scope
                         FROM [{RULE_TABLE}] WHERE client_code=? AND units_in_scope > 0
                         ORDER BY lines_per_unit DESC""", k)
        for r in qcur.fetchall():
            print(f"  {r[0]:20} {r[1][:14]:14} {r[2]:>7,.0f} {r[3]:>9,.0f} {r[4]:>9,.0f} "
                  f"{r[5]:>8,.0f} {r[6]:>15,.0f}")
    qcur.execute(f"SELECT COUNT(*), SUM(CASE WHEN resolves='N' THEN 1 ELSE 0 END) FROM [{RULE_TABLE}]")
    nr, unres = qcur.fetchone()
    print(f"\n  {nr:,} rules in the queue; {unres or 0} do not resolve to any rules table "
          f"(those have no rule to fix).")
    print("  Spend is shown exactly as the data holds it - signed, no threshold, no outlier "
          "exclusion.")

    qcur.execute(f"SELECT COUNT(*) FROM [{TABLE}]")
    print(f"\n{TABLE}: {qcur.fetchone()[0]:,} rows across {len(keys)} clients, {len(FIELDS)} columns")
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
