/* ===================================================================================================
   Medical QA (Indirects) - schema v1
   ---------------------------------------------------------------------------------------------------
   Applied by  pipeline/apply_schema.py  to the PILOT database ONLY. That script refuses to run
   anywhere else, and QA_DATABASE (production) is deliberately blank in .env.

   This is schema v1 in the plan's sense: the best guess, to be proved by a real run and replaced by
   v2 once we can see which fields were used, which were always empty, and which were missing.

   WHY THESE FIVE TABLES AND NOT THE NINE IN THE PLAN
   The plan names qa_vendor, qa_msd_issue, qa_golden and qa_movement as well. They are NOT created
   here, deliberately: nothing writes to them yet, and an empty table with speculative columns is
   exactly the "stale element" this project keeps removing. They arrive in the same commit as the
   code that fills them.

   EVERY COLUMN IS NULLABLE except the keys. Three of the four hospitals cannot supply at least one
   field, and a NOT NULL that fires halfway through a 3.4M-row load is a worse outcome than a null.
   =================================================================================================== */

/* ---------------------------------------------------------------------------------------------------
   qa_run - one row per client per run. The as-at and the source fingerprint.

   This is what keeps "the numbers moved" separable from "the ground moved". Sydney Adventist's
   taxonomy was replaced mid-session on 30 July and broke its dashboard view; without a per-run
   fingerprint there is no way to tell those two apart afterwards.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_run','U') IS NULL
CREATE TABLE qa_run (
  RUN_ID              nvarchar(64)   NOT NULL,
  CLIENT_CODE         nvarchar(64)   NOT NULL,
  LOADED_AT           datetime2      NOT NULL,
  SOURCE_TABLE        nvarchar(200)  NULL,
  SOURCE_COLUMNS      int            NULL,
  TAXONOMY_SOURCE     nvarchar(300)  NULL,   -- database.table, the isolation stamp
  TAXONOMY_ROWS       int            NULL,
  TAXONOMY_COLUMNS    int            NULL,
  RULES_TABLES        nvarchar(400)  NULL,
  RULES_ROWS          int            NULL,
  LINES_IN_SCOPE      bigint         NULL,   -- the client's FULL in-scope population
  LINES_LOADED        bigint         NULL,   -- what this run actually loaded (rule-led subset)
  SELECTION_NOTE      nvarchar(600)  NULL,   -- how the subset was chosen, in words
  SCOPE_NOTE          nvarchar(600)  NULL,
  JUDGE_BACKEND       nvarchar(64)   NULL,
  JUDGE_MODEL         nvarchar(128)  NULL,
  PROMPT_VERSION      nvarchar(32)   NULL,
  CONSTRAINT pk_qa_run PRIMARY KEY (run_id, client_code)
);
GO

/* ---------------------------------------------------------------------------------------------------
   qa_category - the client's OWN category list, cached. THE CANDIDATE SET.

   This is the table that unblocks `suggested_cat_*`. Two shortcuts were tested and rejected on
   2026-08-03 (PLAN v3.16): the sibling set covers only 10.3% of observed disagreements, and the
   vendor's own history is useless for the 71% of vendors that have only ever used one category.
   So the shortlist is the tree itself - 50 Level-1 branches and 1,449 leaves at Northern - narrowed
   by meaning rather than by structure. Small enough to hand a judge whole; far too big to repeat on
   every one of 2.76M lines, which is why it is a table and not a column.

   ISOLATION: client_code is part of the primary key and taxonomy_source names the database and
   table every row came from. The taxonomy keys COLLIDE across hospitals while meaning different
   things - code 379 is Cheese at Melbourne and Facilities Management at Northern - so a query that
   forgets to filter by client would silently mix yardsticks.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_category','U') IS NULL
CREATE TABLE qa_category (
  CLIENT_CODE         nvarchar(64)   NOT NULL,
  CATEGORY_KEY        nvarchar(80)   NOT NULL,   -- the join key the client's lines carry
  TAXONOMY_SOURCE     nvarchar(300)  NULL,
  CATEGORY_LVL_0              nvarchar(400)  NULL,
  CATEGORY_LVL_1              nvarchar(400)  NULL,
  CATEGORY_LVL_2              nvarchar(400)  NULL,
  CATEGORY_LVL_3              nvarchar(400)  NULL,
  CATEGORY_LVL_4              nvarchar(400)  NULL,
  PATH_FULL           nvarchar(2000) NULL,   -- all five levels, absence stated not blank
  BRANCH              nvarchar(400)  NULL,   -- cat_l1: the top of the shortlist's first step
  LEAF                nvarchar(400)  NULL,   -- deepest DISTINCT level - the name a judge picks
  PARENT_PATH         nvarchar(2000) NULL,   -- path with the last distinct level removed
  DEPTH_DISTINCT      int            NULL,   -- levels holding genuinely different values
  SIBLING_COUNT       int            NULL,
  CATEGORY_DESCRIPTION nvarchar(4000) NULL,  -- exists for 33/28/28 of 2,397/1,449/1,429; none at WH
  ADDRESSABLE         nvarchar(64)   NULL,
  IS_CLINICAL         bit            NULL,   -- cat_l0 = 'Clinical'. NEVER a keyword test
  IN_SCOPE            bit            NULL,   -- cat_l0 not Clinical and not Inter-Hospital Spend
  LINES_IN_SCOPE      bigint         NULL,   -- how much of the client's spend actually uses it
  CONSTRAINT pk_qa_category PRIMARY KEY (client_code, category_key)
);
GO
CREATE INDEX ix_qa_category_branch ON qa_category (client_code, branch);
GO

/* ---------------------------------------------------------------------------------------------------
   qa_rule - the FIX QUEUE. Half the deliverable: "here is the RuleID that caused it and what to
   change".

   A rule ID names INDEPENDENT COPIES, not one rule (PLAN v3.15). Hospitals copy rules from each
   other - Northern's table is under a third its own - so rules_table is not decoration: an owner
   told to "fix MEL-0881" must be told which file. Hence the primary key includes it.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_rule','U') IS NULL
CREATE TABLE qa_rule (
  RUN_ID              nvarchar(64)   NOT NULL,
  CLIENT_CODE         nvarchar(64)   NOT NULL,
  -- rule_id and rules_table are narrower than the nvarchar(200) used elsewhere because they are
  -- KEY columns: SQL Server caps an index key at 900 bytes, and 64+64+200+200 nvarchar characters
  -- is 1,056. Real values are far shorter ('MEL-0881', '[dbo].[PMML_Rules_Ordered]').
  RULE_ID             nvarchar(100)  NOT NULL,
  -- NOT NULL and part of the key: a rule ID names independent COPIES, so the table is half the
  -- identity. The loader writes '(unresolved)' where the ID resolves to no rules table at all -
  -- Sydney Adventist's 'CBoard Lookup' on 41.7% of its in-scope lines is a categorisation
  -- mechanism, not a rule, and has nothing to fix.
  RULES_TABLE         nvarchar(128)  NOT NULL,
  RESOLVES            char(1)        NULL,   -- N = no rule to fix (e.g. SAH's 'CBoard Lookup')
  PRIORITY            nvarchar(64)   NULL,   -- LOWEST is the catch-all tier: 68.0% of Melbourne
  SOURCE              nvarchar(200)  NULL,   -- the tier label: 'C. OTHER CLIENT RULES' etc
  TESTS_DESCRIPTION   char(1)        NULL,   -- N = the item text is INDEPENDENT evidence
  FIELD_1             nvarchar(200)  NULL, operator_1 nvarchar(64) NULL, value_1 nvarchar(1000) NULL,
  FIELD_2             nvarchar(200)  NULL, operator_2 nvarchar(64) NULL, value_2 nvarchar(1000) NULL,
  FIELD_3             nvarchar(200)  NULL, operator_3 nvarchar(64) NULL, value_3 nvarchar(1000) NULL,
  CATEGORY_ASSIGNMENT nvarchar(1000) NULL,  -- in the RULE's vocabulary, not the taxonomy's
  -- impact, measured on the FULL in-scope population - never on a sample
  LINES_IN_SCOPE      bigint         NULL,
  VENDORS_IN_SCOPE    bigint         NULL,
  SPEND_IN_SCOPE      float          NULL,   -- signed, exactly as held. No threshold, ever
  LINES_CLINICAL      bigint         NULL,   -- blast radius if the rule is changed
  -- filled once its units are judged
  LINES_JUDGED        bigint         NULL,
  LINES_INCORRECT     bigint         NULL,
  LINES_UNCERTAIN     bigint         NULL,
  ERROR_RATE          float          NULL,   -- exact, not estimated, when units_judged = units_in_scope
  IS_COMPLETE         bit            NULL,
  RECOMMENDATION      nvarchar(2000) NULL,
  RECOMMENDATION_TYPE nvarchar(64)   NULL,   -- narrow / retarget / split / retire / no_change
  FIX_STATUS          nvarchar(64)   NULL,
  FIX_OWNER           nvarchar(128)  NULL,
  CONSTRAINT pk_qa_rule PRIMARY KEY (run_id, client_code, rule_id, rules_table)
);
GO

/* ---------------------------------------------------------------------------------------------------
   qa_line - one row per in-scope source line. 50 fields, in READING order.

   which line -> who -> what was bought -> how much -> what it was categorised as ->
   what the taxonomy says -> what put it there -> the verdict -> the evidence behind it -> the keys

   Not a grouping of like types. The evidence a reader needs arrives BEFORE the answer that rests
   on it, and the verdict sits next to the rule that caused it. See PLAN v3.13.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_line','U') IS NULL
CREATE TABLE qa_line (
  QA_LINE_ID          bigint IDENTITY(1,1) NOT NULL,
  -- 1. which run, which line
  RUN_ID              nvarchar(64)   NOT NULL,
  CLIENT_CODE         nvarchar(64)   NOT NULL,
  SOURCE_ROW_ID       nvarchar(400)  NULL,   -- absent at Western; its ID repeats on 2.25% of rows
  INVOICE_NUMBER      nvarchar(400)  NULL,
  INVOICE_DATE        nvarchar(400)  NULL,
  -- 2. who. VERBATIM - no trim, case fold, normalisation or mask. Standing instruction 2026-07-31
  SUPPLIER_NAME       nvarchar(400)  NULL,
  SUPPLIER_NUMBER     nvarchar(400)  NULL,
  ABN                 nvarchar(400)  NULL,
  -- 3. what was bought - the evidence, before the category it is used to check
  ITEM_DESCRIPTION           nvarchar(4000) NULL,
  DESCRIPTION_USABLE         char(1)        NULL,   -- N on 387,402 in-scope lines (14.0%)
  GL_ACCOUNT          nvarchar(400)  NULL,
  GL_ACCOUNT_NAME     nvarchar(400)  NULL,   -- the fallback evidence where ITEM_DESCRIPTION says nothing
  COST_CENTRE         nvarchar(400)  NULL,
  COST_CENTRE_DESCRIPTION nvarchar(400) NULL,
  -- 4. how much. Signed, exactly as held. No threshold, no outlier guard, no absolute value
  SPEND               float          NULL,
  IS_CREDIT           char(1)        NULL,
  -- 5. what it was categorised as - the thing under test
  CATEGORY_LVL_0              nvarchar(400)  NULL,
  CATEGORY_LVL_1              nvarchar(400)  NULL,
  CATEGORY_LVL_2              nvarchar(400)  NULL,
  CATEGORY_LVL_3              nvarchar(400)  NULL,
  CATEGORY_LVL_4              nvarchar(400)  NULL,
  TAXONOMY_KEY        nvarchar(400)  NULL,
  SCOPE_STATUS        nvarchar(64)   NULL,   -- in_scope / in_scope_uncategorised / out_of_scope
  IS_NON_PROCUREMENT  char(1)        NULL,   -- a label, never a filter
  -- 6. the yardstick - as the CLIENT taxonomy defines it
  TAXONOMY_SOURCE     nvarchar(300)  NULL,   -- the cross-client isolation stamp, on every row
  TAXONOMY_JOIN_OK          char(1)        NULL,
  TAXONOMY_CATEGORY_PATH nvarchar(2000) NULL,
  -- tx_cat_l0..l4, tx_category_addressable and tx_category_description are DELIBERATELY ABSENT
  -- (removed 2026-08-03). They are properties of the CATEGORY and live on qa_category, reachable
  -- by one join on TAXONOMY_KEY. Measured: qa_category reproduces them on 316,430 of 316,430
  -- joined lines. The path above, CATEGORY_PATH_AGREES and the two depth measures are all computed at
  -- load time from the same taxonomy join, so nothing derived depends on carrying the raw levels
  -- onto every one of 2.76M rows.
  --     JOIN qa_category c ON c.client_code = l.client_code
  --                       AND c.category_key = l.taxonomy_key
  -- 7. what put it there
  RULE_ID             nvarchar(200)  NULL,
  RULE_PRIORITY       nvarchar(64)   NULL,   -- LOWEST = catch-all. The sharpest triage signal
  RULE_SOURCE         nvarchar(200)  NULL,   -- makes borrowed rules visible per line
  -- 8. the VERDICT, denormalised from qa_unit so a raw dump needs no join
  VERDICT             nvarchar(32)   NULL,   -- Correct / Incorrect / Uncertain
  CONFIDENCE          float          NULL,
  -- LVL_0 is here so the suggestion mirrors CATEGORY_LVL_0..4 one for one and the two are read in
  -- the same vocabulary. It is NOT always 'Non-Clinical': 66 in-scope candidates sit under
  -- Non-Procurement and two under Tail Spend, so a suggestion can legitimately move a line at
  -- Level 0. Assuming it away shifted every level by one and dropped the leaf.
  SUGGESTED_CATEGORY_LVL_0    nvarchar(400)  NULL,
  SUGGESTED_CATEGORY_LVL_1    nvarchar(400)  NULL,
  SUGGESTED_CATEGORY_LVL_2    nvarchar(400)  NULL,
  SUGGESTED_CATEGORY_LVL_3    nvarchar(400)  NULL,
  SUGGESTED_CATEGORY_LVL_4    nvarchar(400)  NULL,
  BASIS               nvarchar(64)   NULL,
  RATIONALE           nvarchar(2000) NULL,
  -- 9. the evidence behind the VERDICT. CATEGORY_PATH_AGREES is NOT a VERDICT - it reads Y on 100% of
  --    joined rows at three of four hospitals, and both sides can be wrong together
  TAXONOMY_SIBLING_COUNT    int            NULL,
  TAXONOMY_DEPTH   int            NULL,
  CATEGORY_PATH_AGREES     nvarchar(16)   NULL,
  -- 10. the join keys. Fingerprints of the row's own text, so they survive a re-run
  -- Kept as ANALYSIS keys, not as grouping keys. Grouping was removed 2026-08-05 and every line is
  -- judged on its own; these two still say which lines are identical, which is what makes an
  -- inconsistency visible - two lines with the same SUBJECT_KEY and different verdicts is the
  -- judge contradicting itself, and that is measurable rather than hidden.
  UNIT_KEY            char(20)       NULL,   -- client + vendor + item text + assigned category
  SUBJECT_KEY         char(20)       NULL,   -- client + vendor + item text

  -- PROVENANCE and REVIEW. Moved here from qa_unit when grouping was removed, 2026-08-05.
  --
  -- THE FINDING IS IMMUTABLE. Sameer: "they can make changes to it later, but can never change our
  -- findings but only redirect the incorrect rule to the correct taxonomy level." The VERDICT block
  -- above is written once by the judge and NEVER edited. The analyst writes only below. Keeping
  -- both is what makes the override rate a live measurement of how good the judge is; overwrite the
  -- original and that signal is gone.
  JUDGE_BACKEND       nvarchar(64)   NULL,
  JUDGE_MODEL         nvarchar(128)  NULL,
  PROMPT_VERSION      nvarchar(32)   NULL,
  JUDGED_AT           datetime2      NULL,
  REVIEW_STATUS       nvarchar(32)   NULL,   -- pending / agreed / redirected
  REVIEWED_BY         nvarchar(128)  NULL,
  REVIEWED_AT         datetime2      NULL,
  REVIEW_OVERRIDE_VERDICT  nvarchar(32)   NULL,
  REVIEW_OVERRIDE_CATEGORY nvarchar(2000) NULL,  -- analyst's category, from THIS client's taxonomy

  -- 11. THE ANALYST'S NOTE. Added with the review workbook, 2026-08-06.
  -- Sits with the REVIEW block above: written by a person, never by the judge.
  REVIEW_NOTE                   nvarchar(2000)  NULL,

  -- 12. THE JURY - three models, one line, PER-MODEL VOTES. Live since 2026-08-14.
  --
  -- NO NEW TABLE AND NO NEW ROWS. Sameer, 2026-08-14: "can never have more than 2000 rows ... yes
  -- we can go with addtional colums but not rows." The three votes are COLUMNS on the same row, so
  -- there is still exactly one run_id and the "more than one means stop" rule is untouched.
  --
  -- The per-model votes are kept rather than collapsed into the consensus because they are the only
  -- record of HOW the jury got there. Finding 96 found three lines where one model had proposed
  -- exactly Sameer's answer and the vote threw it away - invisible without these columns.
  NIM_1_MODEL                   nvarchar(120)   NULL,
  NIM_1_VERDICT                 nvarchar(32)    NULL,
  NIM_1_CONFIDENCE              float           NULL,
  NIM_1_SUGGESTED_KEY           nvarchar(32)    NULL,
  NIM_2_MODEL                   nvarchar(120)   NULL,
  NIM_2_VERDICT                 nvarchar(32)    NULL,
  NIM_2_CONFIDENCE              float           NULL,
  NIM_2_SUGGESTED_KEY           nvarchar(32)    NULL,
  NIM_3_MODEL                   nvarchar(120)   NULL,
  NIM_3_VERDICT                 nvarchar(32)    NULL,
  NIM_3_CONFIDENCE              float           NULL,
  NIM_3_SUGGESTED_KEY           nvarchar(32)    NULL,

  -- 13. THE JURY'S CONSENSUS - this is THE LIVE FINDING. The VERDICT block in section 8 is the
  -- older single-model layer and is superseded; both are kept, and code must never mix them.
  --
  -- NIM_SUGGESTED_KEY IS NULL BY DESIGN WHEN THE VERDICT IS 'Correct'. A Correct verdict's
  -- destination is the category the line is ALREADY filed under. Any "% with a destination" over
  -- this column undercounts by exactly the lines we got right - that trap produced a false
  -- regression once already (RUN_LOG Finding 96).
  --
  -- Verdict and destination are voted SEPARATELY and deliberately: an honest 'Incorrect' with no
  -- agreed destination is a real answer, not a failure.
  NIM_VERDICT                   nvarchar(32)    NULL,
  NIM_CONFIDENCE                float           NULL,
  NIM_BASIS                     nvarchar(64)    NULL,
  NIM_AGREEMENT                 nvarchar(16)    NULL,
  NIM_SUGGESTED_KEY             nvarchar(32)    NULL,
  NIM_SUGGESTED_CATEGORY_LVL_0  nvarchar(400)   NULL,
  NIM_SUGGESTED_CATEGORY_LVL_1  nvarchar(400)   NULL,
  NIM_SUGGESTED_CATEGORY_LVL_2  nvarchar(400)   NULL,
  NIM_SUGGESTED_CATEGORY_LVL_3  nvarchar(400)   NULL,
  NIM_SUGGESTED_CATEGORY_LVL_4  nvarchar(400)   NULL,
  NIM_RATIONALE                 nvarchar(2000)  NULL,
  NIM_PROMPT_VERSION            nvarchar(16)    NULL,
  NIM_JUDGED_AT                 datetime2       NULL,

  -- 14. NIM_MODELS_RESPONDED - how many of the three actually answered.
  --
  -- WITHOUT THIS COLUMN A HOLLOWED-OUT JURY IS INVISIBLE, because '2of2' in NIM_AGREEMENT reads
  -- exactly like agreement and is in fact a two-model jury. Measured 2026-08-18: 11 lines at 16
  -- workers, 26 at 24, 36 at 32, 102 at 48 - the damage is GRADUAL, and nothing else on the
  -- invariant list moves when it happens. Checked every generation as a RATE (<=1%), never == 0,
  -- because an occasional dropout is normal and a check that cries wolf gets ignored.
  --
  -- NULL is preserved as NULL: a model that never answered is a DROPOUT, not a zero confidence.
  NIM_MODELS_RESPONDED          tinyint         NULL,

  -- 15. NIM_ACTION - the verdict says WHAT, the action says SO WHAT. Written by action_classify.py
  -- from the crosswalk, deterministically - never asked of a model. Six values; the canonical
  -- definition of each lives in action_classify.py and is printed beside the numbers so the meaning
  -- travels with them.
  --
  -- 'Out of scope' IS NOT AN ERROR. It is a scope finding, and counting it as a defect inflates
  -- every error rate downstream.
  --
  -- NIM_DECIDED_BY names every model that voted the winning verdict, so a verdict can be traced to
  -- its jury without re-reading the per-model columns.
  NIM_ACTION                    nvarchar(20)    NULL,
  NIM_DECIDED_BY                nvarchar(200)   NULL,

  -- 16. MSD_COHERENCE - the MSD's read on whether the vendor's stated business matches what it
  -- invoices for. Five values: coherent / incoherent / inconclusive / unevaluated / no match.
  --
  -- IT IS A FLAG BESIDE THE VENDOR NAME AND NEVER A JUDGE INPUT. Feeding it to the judge produces a
  -- verdict resting on the vendor alone, which is the exact failure step 1 of the evidence hierarchy
  -- exists to prevent. It is not in emit_batch's payload; do not add it.
  --
  -- AND IT DOES NOT PREDICT MISCATEGORISATION - incoherent vendors are misfiled LESS often than
  -- coherent ones (7.9% vs 11.4%). Read it as a data-coverage signal, never as an error predictor.
  MSD_COHERENCE                 varchar(16)     NULL,
  CONSTRAINT pk_qa_line PRIMARY KEY (QA_LINE_ID)
);
GO
CREATE INDEX ix_qa_line_unit  ON qa_line (RUN_ID, CLIENT_CODE, UNIT_KEY);
GO
CREATE INDEX ix_qa_line_rule  ON qa_line (RUN_ID, CLIENT_CODE, RULE_ID);
GO

/* ---------------------------------------------------------------------------------------------------
   qa_vendor_queue - THE RUNNING ORDER. Added 2026-08-25, stage 3.

   2,786,018 lines at ~50 lines/min is ~40 days, so something has to decide what gets judged first.
   Sameer, 2026-08-17: the rollup is PER VENDOR NAME, largest spends first. SIGNED, settled
   2026-08-21 on the full population - not absolute, because absolute ranks GE Healthcare's
   offsetting credits ($50.7bn abs / $9.4m signed) above the ATO's $943m of real spend and presents
   a bookkeeping artefact as our largest finding.

   A VENDOR IS JUDGED WHOLE. The queue is consumed one vendor at a time and every one of that
   vendor's lines is judged before the next begins. Two reasons, and the second is not obvious:
     1. Half a vendor's answer is not an answer - you cannot tell an account manager anything
        about a supplier you have only partly looked at.
     2. It BOUNDS THE JUDGE'S MEMORY. emit_batch materialises its whole selection: 616 B/unit x
        893,173 Melbourne lines is ~0.51 GB of JSON in one list. Per vendor it is a few MB, so the
        fetchall() paging that TRACKER carries as an open defect stops being needed at all.

   SPEND IS AS THE DATA HOLDS IT. Signed, no threshold, no netting, no outlier guard, no absolute
   values in the ranking. SPEND_ABSOLUTE sits BESIDE it as a data-quality signal and is never
   ranked on. Nothing is ever excluded from this table - a flagged vendor is ROUTED, not filtered,
   and appears with its figures exactly as held.

   BLANK VENDOR NAMES ARE IN THE QUEUE. Sameer, 2026-08-25: "i prefer those lines in que, where
   its a blank vendorr" - raised with him because ranked by signed spend they land at #2 in
   Northern (3,387 lines, $608,419,571) and #1 in Western (ONE line, $47,111,582). He ruled they
   stay. HAS_NO_EVIDENCE marks the subset the judge cannot resolve - no vendor AND no usable
   description, 30 lines carrying $607,925,308 at Northern - so an Uncertain verdict there is a
   PREDICTED outcome on the row rather than a surprise found afterwards.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_vendor_queue','U') IS NULL
CREATE TABLE qa_vendor_queue (
  RUN_ID            nvarchar(64)   NOT NULL,
  CLIENT_CODE       nvarchar(64)   NOT NULL,
  -- DETERMINISTIC, and never an identity column. SHA2_256 of client + '|' + the verbatim name,
  -- same construction as UNIT_KEY / SUBJECT_KEY. An identity here would renumber on every rebuild
  -- and every recorded queue position would silently point at a different vendor - the exact
  -- failure that orphaned the answer key on 2026-08-20.
  VENDOR_KEY        char(20)       NOT NULL,
  -- VERBATIM. Never trimmed, cased, normalised or de-duplicated - this is the value an account
  -- manager pastes into their own system. NULL where the source holds no vendor name at all.
  SUPPLIER_NAME     nvarchar(400)  NULL,
  VENDOR_RANK       int            NOT NULL,   -- 1 = judged first, WITHIN the client
  LINES_TOTAL       bigint         NULL,
  LINES_UNJUDGED    bigint         NULL,       -- as at the build; the judge is the authority
  SUBJECTS          bigint         NULL,       -- distinct SUBJECT_KEY - what the analyst clicks
  SPEND_SIGNED      float          NULL,       -- THE RANKING KEY. As held
  SPEND_ABSOLUTE    float          NULL,       -- beside it, never ranked on
  -- SPEND_ABSOLUTE / ABS(SPEND_SIGNED). GE Healthcare is 5,402. A vendor whose absolute total
  -- dwarfs its signed one is offsetting credits and debits, not spending money.
  DIVERGENCE        float          NULL,
  DATA_QUALITY_FLAG nvarchar(64)   NULL,       -- divergent | no_vendor_name | NULL. ROUTING, never a filter
  -- lines with NEITHER a vendor name NOR a usable description. No evidence exists, so the
  -- hierarchy resolves them to Uncertain - stated in advance, on the row.
  HAS_NO_EVIDENCE   bigint         NULL,
  QUEUE_STATUS      nvarchar(32)   NULL,       -- pending | in_progress | done
  BUILT_AT          datetime2(0)   NULL,
  CONSTRAINT pk_qa_vendor_queue PRIMARY KEY (RUN_ID, CLIENT_CODE, VENDOR_KEY)
);
GO
CREATE INDEX ix_qa_vendor_queue_rank ON qa_vendor_queue (RUN_ID, CLIENT_CODE, VENDOR_RANK);
GO

/* GLOBAL_RANK - the SAME vendors, ordered across ALL FOUR HOSPITALS AT ONCE. Added 2026-08-25.

   Sameer: "cant we start juding largest supplier spend first? irrespective of the hospitals".
   VENDOR_RANK orders within one hospital; GLOBAL_RANK orders the whole population, so the ATO's
   $943m at Northern is judged before Melbourne's largest supplier even though Melbourne is a
   bigger hospital overall. Spend-weighted means spend-weighted.

   BOTH ARE KEPT, because they are two sorts of the same rows and cost one column. Global answers
   "what is the biggest money anywhere"; per-client answers "finish this hospital". Which one to
   stop early on is a decision for the day, with the numbers visible, rather than one baked in now.

   ⚠️ MEASURED BEFORE IT WAS OFFERED - a global order UNDER-SERVES THE SMALLEST HOSPITAL early.
   At the global top 100: northern 86.2% of its signed spend, melbourne 52.9%, western 45.1%,
   SYDNEY ADVENTIST 32.7%. It evens out - top 500 puts every hospital above 61.9% - so it only
   matters if the run is stopped early, and Sydney Adventist is a client too.

   The judged unit is UNCHANGED: still (client, vendor), still judged inside that client's own
   taxonomy. A global ORDER never means a shared candidate list - key 379 is Cheese at Melbourne
   and Facilities Management at Northern. */
IF COL_LENGTH('qa_vendor_queue','GLOBAL_RANK') IS NULL
  ALTER TABLE qa_vendor_queue ADD GLOBAL_RANK int NULL;
GO
CREATE INDEX ix_qa_vendor_queue_global ON qa_vendor_queue (RUN_ID, GLOBAL_RANK);
GO

/* ---------------------------------------------------------------------------------------------------
   qa_unit - REMOVED 2026-08-05.

   It existed only to hold GROUPS of identical lines so one judgement could be copied across them.
   Sameer removed grouping entirely: every line is judged on its own, so qa_unit and qa_line
   were the same grain and one of them was redundant. Everything lives on qa_line.
   --------------------------------------------------------------------------------------------------- */



/* ---------------------------------------------------------------------------------------------------
   qa_line_view - THE ONE VIEW. Added 2026-08-24 at Sameer's instruction:
   *"yes i want one view, but the view should read like [PI_Medical_QA_Indirect].[dbo].[qa_line_view]"*

   ONE view, deliberately. The workbook filters it to the issue lines, the summary sheet aggregates
   it, and any ad-hoc analysis reads it - so a finding has exactly ONE definition. A second view is
   a second place that definition can drift, which is the same reasoning that keeps status in
   TRACKER.md alone.

   ONE ROW PER LINE, AND NO FILTERING. The scope gate was applied at LOAD time - every row in
   qa_line is already in scope - so this view must not filter again. A view that quietly dropped
   rows would make every count here disagree with every count against the table, and nothing would
   look broken.

   🔒 THE qa_rule JOIN CANNOT FAN OUT, and that was MEASURED before this was written rather than
   inferred from the key looking unique. In production (RUN_ID, CLIENT_CODE, RULE_ID) appears more
   than once on ZERO of 4,211 rules, and the join returns 2,786,018 rows against 2,786,018 in
   qa_line - delta zero. ix_qa_line_rule covers exactly this key.

   RULES_TABLE IS NOT OPTIONAL. A rule ID names independent COPIES in different hospitals: fixing
   MEL-0881 in Northern's table does nothing to Melbourne's. A fix instruction that does not name
   the table it applies to cannot be actioned.

   WHAT IS DELIBERATELY ABSENT, so nobody re-adds it as an oversight:
     GL_ACCOUNT, GL_ACCOUNT_NAME, COST_CENTRE, COST_CENTRE_DESCRIPTION
         Sameer, 2026-08-21: *"no dont show gl to the analyst since that is not a judging factor."*
         ⚠️ This REVERSES his 2026-08-17 ruling that the analyst keeps the GL. The later one governs.
     NIM_BASIS
         Broken - reports no_evidence on 1,527 of 2,000 pilot lines including 1,307 that plainly had
         evidence. Excluded from every extract until fixed.
     VERDICT / CONFIDENCE / BASIS / RATIONALE / SUGGESTED_CATEGORY_LVL_*
         Claude's SUPERSEDED verdict layer. Two verdict columns side by side in one view is how
         someone quotes the wrong one - and qa_rule.ERROR_RATE is already derived from this layer.
     REVIEWED_BY, REVIEW_OVERRIDE_VERDICT, REVIEW_OVERRIDE_CATEGORY, REVIEW_NOTE
         Sameer, 2026-08-21: only the latest reviewed DATE flows into the view.
     TAXONOMY_SOURCE
         Dropped 2026-08-24 at Sameer's request. ⚠️ It stays ON qa_line: it names the database and
         table each line's EXISTING category came from, and it is how a cross-hospital taxonomy leak
         becomes visible in the data. The leak check reads the TABLE, so the guarantee is untouched -
         but do not read its absence here as "there is only one taxonomy". Suggestions come from the
         one merged taxonomy; existing categories still come from four different hospital ones.
     CATEGORY_SCOPE
         Dropped from the project entirely - fully reproduced by Non-Procurement at Level 0 or 1.
     INVOICE_DATE
         ⚠️ Stored as free text and 52% empty at Sydney Adventist. There is no usable date on
         qa_line, so this view CANNOT answer "how recent is this line" - which matters, because
         Northern's data stops at 2026-05. Raised, not solved.

   SPEND IS SIGNED AND AS-IS. No threshold, no netting, no absolute values, no outlier guard.
   Always report line counts beside spend, so a reader can see when a figure rests on a few rows.
   --------------------------------------------------------------------------------------------------- */
IF OBJECT_ID('qa_line_view','V') IS NOT NULL DROP VIEW qa_line_view;
GO
CREATE VIEW qa_line_view AS
SELECT
    /* identity. 🔒 QA_LINE_ID / RUN_ID / SUBJECT_KEY / UNIT_KEY MOVED TO THE END 2026-08-25 at
       Sameer's instruction. Only CLIENT_CODE stays at the front. They are plumbing - a reader
       opening this view wants the vendor, the item and the verdict first, not four keys they
       never type. They are KEPT, not dropped: UNIT_KEY is what re-attaches an analyst's answer
       to a line after a rebuild, and dropping it is what orphaned the answer key on 2026-08-20. */
    l.CLIENT_CODE,

    /* what was bought - SUPPLIER_NAME is verbatim and must never be trimmed or normalised here */
    l.SUPPLIER_NAME,
    l.ITEM_DESCRIPTION,
    l.DESCRIPTION_USABLE,
    l.MSD_COHERENCE,
    l.SPEND,

    /* where it is filed now */
    l.SCOPE_STATUS,
    l.CATEGORY_LVL_0,
    l.CATEGORY_LVL_1,
    l.CATEGORY_LVL_2,
    l.CATEGORY_LVL_3,
    l.CATEGORY_LVL_4,
    /* The readable path. '(not used at this level)' is a REAL category with a short path, not a
       gap - ~230 of 1,999 pilot units - so it is skipped rather than printed. */
    STUFF(
        COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_1,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_1,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_2,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_2,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_3,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_3,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_4,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.CATEGORY_LVL_4,''))) END,''),'')
    , 1, 3, '') AS CURRENT_CATEGORY_PATH,

    /* which rule did it - and WHICH TABLE that rule lives in */
    l.RULE_ID,
    l.RULE_PRIORITY,
    l.RULE_SOURCE,
    r.RULES_TABLE,

    /* our finding - written once, never edited in place */
    l.NIM_VERDICT,
    l.NIM_CONFIDENCE,
    l.NIM_AGREEMENT,
    l.NIM_MODELS_RESPONDED,
    l.NIM_ACTION,
    l.NIM_RATIONALE,
    l.NIM_SUGGESTED_KEY,
    l.NIM_SUGGESTED_CATEGORY_LVL_0,
    l.NIM_SUGGESTED_CATEGORY_LVL_1,
    l.NIM_SUGGESTED_CATEGORY_LVL_2,
    l.NIM_SUGGESTED_CATEGORY_LVL_3,
    l.NIM_SUGGESTED_CATEGORY_LVL_4,
    STUFF(
        COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_1,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_1,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_2,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_2,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_3,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_3,''))) END,''),'')
      + COALESCE(' > ' + NULLIF(CASE WHEN LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_4,''))) LIKE '(%'
                 THEN '' ELSE LTRIM(RTRIM(ISNULL(l.NIM_SUGGESTED_CATEGORY_LVL_4,''))) END,''),'')
    , 1, 3, '') AS SUGGESTED_CATEGORY_PATH,

    /* the analyst layer - status and the LATEST date only */
    l.REVIEW_STATUS,
    l.REVIEWED_AT,

    /* the keys, last. Moved here 2026-08-25 - see the note at the top of the view. */
    l.QA_LINE_ID,
    l.RUN_ID,
    l.SUBJECT_KEY,
    l.UNIT_KEY
FROM qa_line l
LEFT JOIN qa_rule r
       ON r.RUN_ID = l.RUN_ID AND r.CLIENT_CODE = l.CLIENT_CODE AND r.RULE_ID = l.RULE_ID;
GO
