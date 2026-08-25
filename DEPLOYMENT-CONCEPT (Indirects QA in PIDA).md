# DEPLOYMENT CONCEPT — Indirects QA inside PI Data Analytics (PIDA)

**Status: thought-stage concept. Written 2026-08-06; § 5–6 rewritten the same day after a
read-only survey of how the four hospitals' rules are actually stored and integrated. Nothing
here is built or committed to. Internal — not shareable; `PROJECT-BRIEF (shareable).md` remains
the only doc cleared to leave the building.**

This captures Sameer's vision for how the QA output reaches analysts, so the thinking survives
until we get to this stage. It builds on the pilot (`qa_line`, run `pilot-20260805T112504`, 2,000
lines, four hospitals) and on the schema decisions recorded in `PLAN.md` v3.22.

---

## 1. The vision, in one paragraph

Instead of handing analysts manual Excel files, the QA output becomes a module inside **PIDA**
(the internal staff app at staging-v2.comprara.net/pida, alongside Client 360, Meetings, Tasks,
Contracts, Progress Reports, Onboarding, Invoicing and Time tracking). The analyst sees our
findings line by line, with an **approve / disapprove** control at the end of each row. Approve
means our finding stands, and the system drafts a **new rule** for that vendor — highest priority,
keyed on vendor + item description — so the correction propagates instead of dying in a
spreadsheet. Disapprove means the analyst overrides us by pointing to the correct category within
**that hospital's own taxonomy**. The analyst works the Incorrect and Uncertain verdicts; Correct
verdicts need nothing.

## 2. Verdict: doable — and half of it already exists

The reviewing half of this vision is what the schema was built for. These are live in the pilot
today, confirmed against the database 2026-08-06:

- `qa_line` carries the review layer beside the finding: `REVIEW_STATUS`, `REVIEWED_BY`,
  `REVIEWED_AT`, `REVIEW_OVERRIDE_VERDICT`, `REVIEW_OVERRIDE_CATEGORY`.
- `qa_rule` carries `FIX_STATUS` and `FIX_OWNER`. (A `FIX_NOTES` column was in the original spec
  and is not yet on the table — add it when we build.)
- `qa_category` holds each hospital's **full** taxonomy (clinical, inter-hospital and
  non-clinical, with `in_scope` flags) — which is exactly what the "point us to the correct
  category" picker needs, already scoped per client so one hospital's taxonomy can never resolve
  another's line.
- The three deterministic keys (`unit_key`, `subject_key`, `input_hash`) were designed so review
  status survives a rebuild. That was designed for the Excel round-trip; it is precisely what lets
  an app replace Excel — the app's decisions re-attach to the next run automatically.

**The standing rule that makes the whole thing safe is already in force: the finding is
immutable.** Our layer (`VERDICT`, `CONFIDENCE`, `BASIS`, `RATIONALE`, `SUGGESTED_CATEGORY_*`) is
written once and never edited. The analyst's layer sits beside it with an author and a timestamp.
The app enforces this **by database permission, not convention** — its SQL account gets write
access to the review columns and nothing else. Keeping both layers is what makes the override
rate a live measurement of the judge; it also means the app can never destroy a finding, only
answer it.

The genuinely new machinery is the **rule-writer** (§ 6). After the 2026-08-06 survey it is much
less speculative than it was: the rule language is measured, the authoring format is known, and a
proposal can be drafted in exactly the shape the hospitals' own rules tables use.

## 3. The screen: a queue, not a spreadsheet

- **Every line is listed — all verdicts, including Correct** (Sameer, 2026-08-06). The analyst
  filters by **client** and by **verdict** (and usefully by basis, review status and rule). Four
  kinds of row:
  1. **Incorrect** verdicts — line miscategorised, our suggested category attached.
  2. **Uncertain** verdicts — the data couldn't carry the call; the analyst supplies the answer.
  3. **Uncategorised** lines (`Category Level 0` blank, `scope_status = 'in_scope_uncategorised'`)
     — no category at all today; our suggestion may point **anywhere in that hospital's full
     taxonomy including clinical and inter-hospital**, because an uncategorised line hasn't yet
     been through the clinical split.
  4. **Correct** verdicts — listed so the analyst can spot-check the judge. Approve records a
     confirmation and drafts **no** rule (one already fires correctly; a duplicate would only add
     sprawl). **Disapprove on a Correct line is the most valuable click in the app** — it is a
     judge false-positive caught by a human, the signal the override rate exists to carry.
- **Rule-conflict rows are highlighted, not silently guarded** (Sameer, 2026-08-06). Where the
  RuleID behind a line participates in a same-tier collision (§ 5 — e.g. three `JB HI-FI` rules
  at `Lowest` pointing at three categories), the row carries a visible **conflict flag** telling
  the analyst the categorisation was decided by an arbitrary tie-break, with the competing rules
  listed. The defect is surfaced to the person fixing rules, not just checked at save time.
- **One row = one decision, not one line.** At production scale (millions of lines) line-by-line
  clicking is impossible and unnecessary. The queue groups by `subject_key` (same vendor + same
  item text at one hospital): the analyst decides once, and the decision applies to every line in
  the group. The row shows the line count and spend it covers — line count is the ranking, never
  spend, per the standing rule.
- **What a row shows:** vendor (verbatim), item description, GL account name, current category
  path, our verdict + confidence + rationale, our suggested category path (with its
  strong/moderate/weak wording), the RuleID and rules table that produced the current category,
  and the count of lines this decision resolves.
- **The row carries the vendor's MSD coherence level** (Sameer, 2026-08-10: *"in our app view we
  will need the coherence/incoherence level which is derived from the msd"*). Three points govern
  how it is rendered, all from PLAN v3.26 / RUN_LOG Finding 67:
  1. **It is spooled, not computed.** The label comes verbatim from `llm_call_logs`
     (`call_type='coherence'` → `outcome`), the same value the MSD-v2 vendor-detail panel shows.
     We never derive it from `invoice_coherence` — the score and the verdict disagree, and
     `NATIONWIDE CREDIT CONTROL` scores 1.00 while labelled `incoherent`.
  2. **Six labels, never collapsed** — `coherent` · `incoherent` · `inconclusive` · `ok` ·
     `failed` · `needs_review`, plus *no coherence call yet*. `inconclusive` displays as itself;
     it means the MSD looked and could not decide, which is a different thing from not having
     looked (16,023 of the four hospitals' 23,222 vendors).
  3. **But the analyst-facing meaning is binary.** Only `coherent` says the vendor's own identity
     may be leaned on. Everything else reads as **"supplier not assumed correct"** — so the badge
     should show the label and the treatment, not make the analyst infer one from the other.
     `description_contaminated` is a separate spooled flag and carries the same warning.
  4. **Read the human lock FIRST.** The lock lives on `pi_vendors`; the label lives in
     `llm_call_logs`; locking does not rewrite the log. Two of the five currently locked vendors
     still read `incoherent`. So the badge resolves in this order — **human lock → spooled label →
     `coherent` or not** — otherwise the screen distrusts a supplier *because* someone fixed it.
- **The analyst can act on an incoherent supplier from this row** (Sameer, 2026-08-10; PLAN v3.27
  change 154). Two buttons, matching the MSD's own two paths:
  - **"I know what this is"** → approve the vendor and point it at the right bucket. **Saved and
    locked, no requeue.** The analyst supplies the evidence; the MSD's model re-adjudicates, so one
    standard still applies across every account that uses the vendor — which is what makes this
    safe despite 53.8% of incoherent vendors being shared outside this project.
  - **"I'm not sure"** → send it back to the MSD queue to be enriched.
  **The row must then show a pending state.** A requeued vendor waits behind ~275,656 others at
  ~5,765/day — weeks, not minutes. Without *"sent for re-analysis — pending"* on the row, the
  analyst corrects the same supplier twice. Anything the analyst does **not** resolve still routes
  to the `qa_msd_issue` register and Sameer, as before.

### Four requirements the Excel test earned — 2026-08-10

Excel is finished as a surface (PLAN v3.27 change 159); these are its yield, from watching a real
reviewer use it. All four are app behaviour, not workbook fixes:

1. **Disagree must force a category.** 3 of 31 real answers were lost to this gap. The app blocks
   the save (change 148) — now confirmed by use, not just argued.
2. **A fourth response is missing: "this line should not be in scope."** A reviewer hit
   `ENDOMED / MARKER SPOT ENDOSCOPIC 5ML SYRINGES`, noted *"it's a medical product"*, and had
   nowhere to put it — the line already carries a Non-Clinical L0, so its picker holds in-scope
   categories only. That is a **scope finding for the client**, and today the vocabulary cannot
   express it.
3. **`Agree` on an `Uncertain` verdict is ambiguous** — 9 of Western's 25 answers. *"This is
   genuinely unjudgeable"* and *"your suggested category is right"* currently record identically,
   and the suggestion is captured nowhere. Split the response, or the fix queue inherits the
   ambiguity.
4. **The clinical-override question is live.** A reviewer filed an uncategorised Melbourne line as
   `Clinical > Drugs & Pharmaceutical Products`. The ingest accepted it correctly — uncategorised
   lines offer the full taxonomy — but § 9 item 3 below is no longer hypothetical and needs an
   answer before build.
- **Ordering:** by lines covered, descending — the analyst's first hour of clicking resolves the
  most lines.
- **The analyst reads a REVIEW VIEW, never the 40+ column table** (Sameer, 2026-08-06 afternoon).
  `qa_line` stays the full record; the app-facing surface is a view of ~20 columns — line
  identity/evidence (vendor verbatim, item description — ~~`GL_ACCOUNT_NAME`, load-bearing on the
  161 pilot lines judged Correct/Incorrect with no usable description~~ 🔒 **GL IS NOT SHOWN TO THE
  ANALYST. Sameer, 2026-08-20:** *"no dont show gl to the analyst since that is not a judging factor
  the analyst will not need to know or see it."* The justification above died on 2026-08-17 when GL
  ceased to be evidence - those 161 lines are now `Uncertain`. **I recommended showing it as context
  and was overruled: not a judging factor, so not on the screen.** The column stays in `qa_line`;
  it is absent from the review view), current category levels,
  verdict + confidence + basis + rationale, suggested category levels — plus the three-option
  response (Agree / Disagree-current-is-fine / Disagree-with-category → picker) and a free-text
  note. **Machinery columns stay OFF the screen and in the system**: `QA_LINE_ID` travels behind
  the row (hidden column in Excel), and `RULES_TABLE` is never shown — the analyst decides *"is
  the category right?"*; routing the fix (including Western's MEDICAL-flag table choice) is the
  proposal-writer's job, automated. The interim Excel workbook is this exact view, column for
  column, with the taxonomy dropdown fed from a hidden per-hospital sheet — which is what makes
  the workbook a genuine proof of the app screen.

## 4. What approve and disapprove actually mean

"Approve/disapprove" is really a small decision matrix, because the row kinds mean different
things:

| Row kind | Analyst action | What gets written | Rule drafted? |
|---|---|---|---|
| **Incorrect** (with suggested category) | **Approve** — agrees the line is miscategorised and our suggestion is right | `REVIEW_STATUS = 'approved'` | Yes → targets **our suggested category** |
| **Incorrect** | **Disapprove — "it was actually fine"** | `REVIEW_OVERRIDE_VERDICT = 'Correct'` | No — the existing rule stands |
| **Incorrect** | **Disapprove — "wrong, but not your suggestion either"** — picks a category from that hospital's taxonomy | `REVIEW_OVERRIDE_CATEGORY = their pick` | Yes → targets **their category** |
| **Uncertain** | There is nothing to approve — the **analyst supplies the answer** from the taxonomy picker | `REVIEW_OVERRIDE_CATEGORY = their pick` | Yes → targets their category |
| **Uncategorised** | Approve our suggested branch, or pick their own | `REVIEW_STATUS` / `REVIEW_OVERRIDE_CATEGORY` | Yes → the rule is what stops the vendor's future lines arriving uncategorised (clinical routing: § 9 q3) |
| **Correct** | **Approve** — confirms the judge | `REVIEW_STATUS = 'approved'` | No — a rule already fires correctly |
| **Correct** | **Disapprove** — the judge was wrong; picks the real category | `REVIEW_OVERRIDE_VERDICT = 'Incorrect'`, `REVIEW_OVERRIDE_CATEGORY = their pick` | Yes → targets their category. This is a judge false-positive — the highest-value override there is |

**EVERY DISAGREEMENT MUST END IN A CONCRETE CATEGORY — enforced by the app** (Sameer,
2026-08-06): *"when the user selects disagree on a line, they should be forced to select a
taxonomy level in the app."* So in PIDA:

- **"Disagree — correct category is"** → the category picker is **mandatory**; the save is
  blocked until a category is chosen. No half-finished disagreements, and no guessing later what
  a blank meant.
- **"Disagree — current category is fine"** → no picker shown, because the answer is already
  known: the system records **the line's current category** as the reviewer's answer. The rule
  still holds — every disagreement resolves to a definite category, either picked or inherited.
- **On a `Correct` verdict the "current category is fine" option is not offered at all** — it
  would mean the same thing as Agree. Disagreeing with a Correct verdict therefore always
  requires a picked category, which is right: that path is a judge false-positive and the
  correction is the whole point of capturing it.
- Excel cannot enforce this (one validation rule per cell — § 3). Sameer, same day:
  *"excel the list is fine for now."* The workbook prompts and highlights; the app enforces.

Two properties worth stating plainly:

- **An Uncertain verdict stays Uncertain forever.** The analyst's answer goes in the override
  column beside it. The count of Uncertains is a measurement of the client's data quality (no
  usable item text, etc.) and must not be erased by resolution.
- **The override is not a golden set.** The analyst sees our answer first and is anchored to it,
  so agreement reads higher than truth. It monitors the judge; it does not calibrate it. (Already
  a standing rule — restated because the app makes the override volume much larger.)

## 5. How rules are actually written today — measured 2026-08-06, read-only

This section replaces guesswork with what the four databases hold. It is the ground the
rule-writer stands on.

**The anatomy of a rule.** Every hospital authors rules in a `PMML_Rules` table with the same
shape: `RuleID` · `Priority` (`Highest` / `Medium` / `Lowest`) · up to three ANDed conditions,
each a `Field_n` / `Operator_n` / `Value_n` triple · `Category Assignment` (a path string) ·
`Source` (the tier label) · `Analyst` (at Northern, Western and Sydney Adventist; Melbourne's
table has no Analyst column) · `UNSPSC_Code`.

**The rule language is small and CONTAINS-dominated.** Measured across all four `PMML_Rules`
tables: operators are `CONTAINS` (96–99% of first conditions), `STARTS WITH`, `EQUALS`,
`ENDS WITH`, and a rare `MISSING`. First-condition fields are `VENDOR_NAME` first
(Melbourne 3,353 of 4,543; Western 2,009 of 2,181), `ITEM_DESCRIPTION` second, then GL account
name / cost centre / product group. **Sameer's vendor + item-description rule shape is already
the house style** — the app would be drafting rules in the exact idiom the team writes by hand.

**Rules compile.** `PMML_Rules` (authoring) feeds `PMML_Rules_Ordered` (compiled), which adds
`PRIORITY_SORT` (just 1/2/3 for the three tiers) and a compiled expression:

```
$VENDOR_NAME$ LIKE "*RICOH*" AND $ITEM_DESCRIPTION$ LIKE "*COPY*" => "20..MEL-0004"
```

`CONTAINS` compiles to `LIKE "*value*"`, and the right-hand side is
**`<taxonomy_key>..<RuleID>`** — the numeric key is the binding. Verified: Melbourne key `20`
resolves in the loaded taxonomy to *Non-Clinical > Facilities Management > Soft Facilities
Management > Stationery & Printing*. The `Category Assignment` path text uses a different, older
vocabulary (`INDIRECTS > ...`) that does not match the taxonomy's Level 0 labels — **a rule
proposal must carry the taxonomy key; the path text is decoration.**

**The engine runs outside the database, on a monthly refresh cycle** (cadence confirmed by
Sameer, 2026-08-06: rule writing is part of the monthly data refresh). No view or procedure our
login can see applies the rules. The flow is: an external workflow evaluates the compiled rules
and writes the base table (`AP_PO_Categorized*`) with the key and RuleID per line — Western's
base table still carries `Workflow Execution Time` and `VENDOR_NAME (Right)` join artifacts from
that tool — and then the **categorised view joins the taxonomy** to add the readable
`Category Level 0..4` columns (confirmed by column diff: that is exactly what each view adds over
its base table; Melbourne's view also carries a `Refresh Date`). Consequence for the app: **a new
rule takes effect at the next monthly refresh, not at the click** — so proposals naturally batch
into a monthly "rules to load" set, which fits the existing refresh process rather than fighting
it. The proposal's status only moves to `applied` when the refreshed data shows it firing.

**Priority is only a three-way sort, and same-tier collisions are real.** Within one tier the
tie-break is whatever the workflow happens to do — and identical single-condition rules pointing
at **different** categories exist in the same tier today: `VENDOR_NAME CONTAINS 'JB HI-FI'`
appears three times at `Lowest` with three different categories (at Melbourne, Northern **and**
Sydney Adventist, via the copied rules); `AVIS AUSTRALIA` likewise; Western has
`C4U NURSING AGENCY` three ways at `Medium`. This is very plausibly a mechanism behind our
`deterministic_contradiction` findings (same vendor + identical text, different categories) — and
it means the blast-radius check (§ 6) must also look for **existing rules on the same vendor at
the same or higher tier**, not just count matching lines.

**Western Health, read directly — 2026-08-06, from the pasted view SQL and a rules deep-dive.**
Sameer pasted Western's ALTER VIEW, and the rules tables were profiled read-only. What it adds:

- **The live view is minimal:** base table LEFT JOIN `WH_Taxonomy` on `CATEGORY ID`, five level
  columns — exactly the join the pilot config records (2,322,868 matches). The heavy lifting all
  happens before the view.
- **A commented-out legacy block preserves the older integration**, against a second database
  (`[Western Health]`, no `Z_` prefix): a three-way precedence — Rebate Lookup → UNSPSC →
  taxonomy — that **forced `Category Level 0 = 'Clinical'` whenever a UNSPSC code was present**,
  overwrote `RuleID` with the literal `'Rebate Lookup'` (the same mechanism-as-RuleID pattern as
  SAH's `CBoard Lookup`), applied client-requested `'Not Adressable'` vendor exclusions, and
  wrapped every lookup in `ROW_NUMBER()` dedup guards — the duplicate-taxonomy-key problem is
  known to whoever wrote it. One tag from that item lookup still leaks: RuleID `'INTRASPACE'`
  sits on 1,165 live lines.
- **At Western the assignment path TEXT is the binding, not a key.** `PMML_Rules_Ordered` is
  empty, the authoring tables have no key column — and the `Category Assignment` text resolves
  against `WH_Taxonomy`'s assembled path on 2,178 of 2,181 `PMML_Rules` and 2,870 of 2,875
  `PMML_Medical_Rules` (case-insensitive, trimmed). The 8 unresolvable rules include a visibly
  truncated path (`…APPLICATIONS SOFTWAR`) — rules that can literally never land, a defect class
  of its own. Western's vocabulary matches the taxonomy (`NON-CLINICAL > …`), unlike Melbourne's
  legacy `INDIRECTS > …`.
- **`PMML_Medical_Rules` is a highest-priority overlay**: 1,830 of its 2,875 rules (63.7%) are
  `Highest` (vs 15.2% in `PMML_Rules`), description-led, 100% `CONTAINS`, authored mainly by
  Smitha (1,235) and Sikhona (870).
- ~~Cross-table conflicts are the sharpest defect found yet: 121 of 176 shared conditions assign
  different categories, and the engine's table order decides the clinical boundary~~ —
  **WITHDRAWN 2026-08-06 (same day), after tracing the KNIME workflow with Sameer: there is no
  cross-table conflict at all.** The workflow routes every **line** by the base table's
  `MEDICAL (YES / NO)` flag: flagged lines are categorised against `PMML_Medical_Rules` only,
  unflagged lines against `PMML_Rules` only — perfect separation, measured across all 2,347,469
  lines (WH-MD rules: 1,792,620 fires, every one on `MEDICAL=1`; WH- rules: 529,083, none on
  `MEDICAL=1`). The 121 "disagreeing" pairs are two parallel rulebooks intentionally answering
  differently for two line classes — the same vendor's medical-flagged lines go clinical, its
  ordinary lines don't. Coherent design, not a lottery. **The design consequence survives the
  withdrawal: a drafted rule must go into the table matching the line's `MEDICAL` routing** —
  a WH-MD rule for a medical-flagged line, a WH- rule otherwise — or it will never fire.
- **A third of the rule estate never fires.** Against all 2,347,469 lines: 658 of `PMML_Rules`
  (30.2%) and 1,022 of `PMML_Medical_Rules` (35.5%) match zero lines. Dead rules are harmless
  until someone copies one — and they are exactly what a rules-hygiene view in the app should
  surface.
- **The comma rules are deliberate, not noise.** `VENDOR_NAME CONTAINS ','` exists in both
  tables (`WH-1201` Medium, `WH-MD0664` Highest, 22,469 lines) and both assign *Non-Procurement >
  Reimbursements > Doctor Payments* — a catch-all for `SURNAME, FIRSTNAME` individuals. Intent
  understood; the risk is any *company* name containing a comma being filed as a doctor payment
  from `Highest` priority, which beats every description rule.
- **Western has a third mechanism, but it barely touches us**: `Categorisation Method = 'Pharma'`
  on 500,543 lines — 500,419 of them Clinical, only 123 in non-clinical/non-procurement
  territory. Unlike CBoard at SAH, Pharma can be noted and set aside.

**Sydney Adventist, read directly — 2026-08-06, from the pasted view SQL, verified by
measurement.** The most consequential of the four:

- **SAH categorises inside the view, at read time.** Nothing is precomputed: every `Category
  Level` column is a CASE expression evaluating five mechanisms in explicit precedence —
  **Rebate lookup → UNSPSC → ML lookup → CBoard → rules/taxonomy** — and `RuleID` is overwritten
  with a mechanism literal (`'Rebate Lookup'`, `'ML'`, `'Medical Library Lookup'`,
  `'CBoard Lookup'`) for the first four.
- **The standing CBoard question is answered: a rule can NEVER outrank CBoard.** The CASE reaches
  `cbrd.[Category 0]` before it ever consults `MASTER CATEGORY ID`. A rule fix does nothing for a
  CBoard line; **the fix path for CBoard lines is the `CBORD_Taxonomy` catalogue itself**, keyed
  by `item_name` (3,683 rows, 2,931 distinct items).
- **Mechanism × scope, measured on the full view (864,127 rows):** CBoard 141,593 lines — **all
  Non-Clinical, i.e. entirely inside our scope**. ML 136,864, Medical Library 4,953 and Rebate
  110,127 — all Clinical, never touching us. Real RuleIDs: 141,291 Non-Clinical + 1,338
  Non-Procurement in scope, 109,754 Clinical. Blank RuleID: 163,225 Clinical (categorised via
  `MASTER CATEGORY ID` with no rule recorded) + 50,509 truly uncategorised. The 4,471
  rule-fired-but-uncategorised lines are `ACTIONS.md` item G (Monali not yet told).
- **CBoard's vocabulary is its own, not a different generation of the taxonomy.** Of its 186
  distinct category paths, **only 20 exist in `Adventist_Taxonomy`**. This dissolves the old
  Z3 framing and explains SAH's 29.4% orphan rate: CBoard writes food-service paths
  (`Food & Beverages > Bakery`, `> Fresh Produce`, …) that the client taxonomy never held. App
  implication: the SAH suggestion/override picker must tolerate current categories that don't
  exist in `qa_category`.
- **The `'No Description'` placeholder is manufactured by the view** — `CASE WHEN [INVOICE
  DESCRIPTION] IS NULL THEN 'No Description'`. The client stores NULL; the literal we treat as a
  placeholder is the view's own invention. Same information, but the origin matters for anyone
  tempted to "fix the data".
- **The view duplicates lines.** `SELECT DISTINCT` plus the `item_name` join inflates 863,849
  base rows to 864,127 (+278). Two catalogue items carry two different paths each
  (`Dried Mushrrom Shiitake Whole`, `Hash Brown Triangles - Mini`), so **74 base lines each
  appear twice in the view with two different categories** — a read-time contradiction generator,
  in miniature, of exactly the defect class our `deterministic_contradiction` verdict flags.
- One theoretical wrinkle measured harmless: the RuleID CASE and the category CASE order the
  mechanisms differently, so the label could disagree with the category's true source — measured
  today, zero `'ML'`-labelled non-clinical rows exist.

**Melbourne Health, read directly — 2026-08-06, from the pasted view SQL, verified by
measurement.** The cleanest of the three views read so far, with one large buried finding:

- **Same skeleton as SAH, tidier execution.** Precedence per level: **Rebate lookup → UNSPSC
  (forced `Clinical`, the third hospital confirming that pattern) → rules/taxonomy** on
  `MASTER CATEGORY ID = MH_Taxonomy.[Master ID]`. Mechanism literals: `'Rebate Lookup'`
  (37,926 lines, all Clinical), `'Medical Library'` (an item-catalogue lookup on
  vendor + description + product number; 122,284, all Clinical), `'PO Category Lookup'`
  (182,708 Clinical + 3,616 in scope — reconciling exactly with the 0.4% already in
  `ACTIONS.md`). Rules carry the rest: 759,066 Non-Clinical + 1,530 Non-Procurement + 1,756
  Inter-Hospital + 16,408 uncategorised-with-a-RuleID (= `ACTIONS.md` item G, reconciled) +
  2,226,069 Clinical. Blank RuleID: 98,489, all uncategorised.
- **The view is hygienic where SAH's is not**: base and view row counts are identical
  (3,449,852 = 3,449,852), every lookup join is wrapped in a `MAX()`/`GROUP BY` dedup guard, and
  the vendor-grouping table is unique on its key. No fan-out, no read-time contradictions.
- **Melbourne binds rules by numeric key, confirmed end-to-end**: the view joins
  `MH_Taxonomy.[Master ID]`, matching the compiled rules' `=> "20..MEL-0004"` form. The
  `INDIRECTS > …` text in `Category Assignment` is the **master taxonomy's** path language (see
  the Google Sheet subsection below) — the authoring vocabulary, resolved to the client taxonomy
  through Master ID.
- **Client-side vendor grouping exists**: `PI_Supplier_Grouping` (11,471 raw names → `PI Grouped
  Names`), joined on the raw vendor name. It does not touch our verbatim-vendor rule — the view
  carries `VENDOR_NAME` and `SUPPLIER NAME_ORIGINAL` through untouched — but it is prior art for
  any future cross-vendor roll-up, and evidence the raw name is the working key client-side too.
- **The buried finding — a hardcoded magic value, `MASTER CATEGORY ID = '2978'`.** The view
  treats 2978 as *effectively uncategorised* and retries those lines through the PO lookup. 2978
  resolves to **`Clinical > Not Yet Categorized > Not Yet Categorized > …`** — and **369,549
  lines (10.7% of Melbourne) still sit on it**, topped by JOHNSON & JOHNSON MEDICAL (80,170),
  SYMBION (18,713), REHAB HIRE (17,429). These lines wear a `Clinical` Level 0 while being, by
  the client's own machinery's admission, not categorised — so Melbourne's true uncategorised
  population is far larger than blank-Level-0 shows (98,489 blank + 16,408 rule-no-category +
  369,549 disguised as Clinical). Whether 2978 lines should count as uncategorised for the QA is
  a scope decision for Sameer — raised as `ACTIONS.md` Z4, not decided here.

**Northern Health, read directly — 2026-08-06, from the pasted view SQL, verified by
measurement. All four hospitals are now read.**

- **Same skeleton, fourth confirmation**: Rebate lookup → UNSPSC (forced `Clinical`) →
  rules/taxonomy. Hygienic like Melbourne: base = view exactly (1,744,381), the medical-item
  lookup is `MAX()`-guarded, and all three unguarded-looking joins are unique on their keys. No
  fan-out anywhere.
- **`Reimbursement Supplier` is manufactured by the view.** Whenever a line's `Category Level 2`
  is `Reimbursements`, both supplier columns are overwritten with the literal — 47,207 lines,
  hiding **3,457 real vendor names that sit unmasked in the base table**. Two consequences: PII
  masking is category-triggered (recategorise a line away from Reimbursements and the real name
  reappears), and for those 47,207 lines the judge's vendor evidence is a literal with zero
  signal — description and GL carry the whole verdict, which the evidence hierarchy already
  handles but the app should display knowingly.
- **Item G decomposed — Northern's 89,861 rule-fired-no-category lines are TWO defects, not
  one**: 89,126 lines have no `MASTER CATEGORY ID` at all (the workflow bug Sakule is
  investigating), and **735 lines carry one of 5 IDs that exist in `Master_Taxonomy` but are
  absent from `NH_Taxonomy`** — the view's chained join (`Master_Taxonomy` hop, then
  `NH_Taxonomy` on `Master ID`) drops them at the second hop. A taxonomy gap, separately fixable
  from Sakule's bug.
- **The tag-leak pattern again**: the medical-item lookup writes its `Tag` into `RuleID` —
  Northern's single literal is `'Product Library'`, 273,066 lines, all Clinical (Western's
  `'INTRASPACE'` writ large). Mechanism × scope: rules 494,017 Non-Clinical + 162,141
  Non-Procurement in scope, 587,458 Clinical; blank RuleID 128,999 uncategorised + 8,839
  Clinical (UNSPSC present without a rule).
- `'No Description'` is manufactured here too — on `PO LINE DESCRIPTION`, not the item
  description. And the `'Not adressable'` vendor list (PAYCLEAR, VMIA, PATIENT REFUNDS,
  UNISUPER, DHS, VAGO, account 80402) is identical to Western's — a shared cross-client
  convention living in view code.

**The Google Sheet, read directly — 2026-08-06, from Sameer's export (`Assets\Northern Health -
Categorization Ruleset Manual Override.xlsx`). The authoring surface, finally seen.**

- **It is the client-facing override portal.** The Instructions tab is addressed to the client
  ("Categorisation Override – Instructions … please contact Purchasing Index"), and it puts the
  load process **in writing**: *"Changes to the rules are not automatic, and will be applied
  during the monthly refresh process."* Clauses combine with **AND only**; *"the rule that is
  assigned a higher priority will be applied first in the case of conflicting rules"* — still
  silent on same-tier ties. A **"Ruleset Portal Guide"** document exists and is worth obtaining.
- **The rules tabs mirror `PMML_Rules` column-for-column** (`RulesID / Priority / Field / Operator
  / Value ×3 / Category Assignment / Analyst`), one tab per source tier: `Northern Health Rules`
  (NH-), `Client Rules` (CLNH-), `UNSPSC Assignment` (CM-, with UNSPSC codes), `Product Group
  Rules` (PG-). An app proposal can be emitted in this exact shape — a paste, not a translation.
- **The `Indirects > …` mystery resolved properly**: rules are authored against the **master
  taxonomy's** path language (the `Master Taxonomy` tab, 3,014 rows, with per-client ID mapping
  columns), and the client category comes via `Master ID`. So a proposal must carry the master
  path/ID, translated from our client-taxonomy suggestion through the Master ID mapping the
  taxonomy tables already hold. (Western remains the exception — no Master ID; its assignments
  are client-taxonomy path text.)
- **The pick lists are richer than what's used**: allowed operators include `>`, `>=`, `<`, `<=`
  and `MISSING`; allowed fields include **`PI GROUPED VENDOR`** — rules can target the grouped
  vendor. A `Proposed Category` column already exists on the Product Group tab — **the proposal
  concept is existing practice**, not an invention of ours.
- **The sheet also owns supplier grouping** (wildcard patterns, `BUNNINGS*`) — the client-side
  grouping seen at Melbourne is authored here too.
- **⚠ The sheet and the live table have drifted.** Reconciled against `PMML_Rules` (read-only):
  sheet 3,063 rules, DB 6,699, **2,531 in both**. Sheet-only: **532** (the entire 423-rule
  Product Group tab, 73 CM-, 36 NH- — authored but not live). DB-only: 4,167 — the borrowed
  tiers (HL- 1,341, MEL- 1,277, PH- 1,252) plus 195 CM- and 84 PG- that match nothing in the
  sheet. The authoring surface and the live table disagree by ~17% of the sheet; any proposal
  flow that rides the sheet inherits this drift, so the app's `applied` status must be verified
  against the **table**, never assumed from the sheet. The sheet also carries visible `#REF!`
  formula errors in its validation columns.

**Rule authorship is already a tracked concept — including machine authorship.** Northern's
`Analyst` column names the writers (Cathy 1,088; Naman 1,294 across dated entries; shivani 404;
Sameer 14; …) — and **`Chatgpt` is on 261 rules**. Machine-drafted rules already exist in
production; the proposal flow formalises what is currently informal.

**Tier labels and ID schemes differ per hospital and the copies run deep.** Melbourne's tiers are
`A./C. Client-Defined`, `B. UNSPSC Rules`, `D. Mater Rules`; Northern's are `A. NH Rules`,
`B. UNSPSC`, `C. Other Client Rules`, `E. Pharmacy`. Prefixes seen: `MEL-`, `MH-M…`, `MZ-`,
`NH-`, `CLNH-`, `CM-`, `HL-`, `PG-`, `PH-`, `SAH-`, `WH-`, `WH-MD…`. **Sydney Adventist's rules
table is structurally a copy of Northern's** — its own-rules tier is literally labelled
`A. NH Rules` (313 rules) and its tier profile mirrors Northern's. A minted RuleID must follow
the target hospital's scheme and be collision-checked there.

**Known gaps this survey could not close** (they need one conversation, or one permission):

1. ~~The view SQL is hidden from our login~~ — **closed 2026-08-06: Sameer pasted all four ALTER
   VIEWs in-session** and each was verified by measurement (the per-hospital subsections above).
   `GRANT VIEW DEFINITION` is now only needed at build time, so the app can diff view logic
   against what it expects.
2. ~~What the workflow engine is~~ — **KNIME** (Sameer, 2026-08-06). ~~Case handling~~ —
   **case-insensitive**, confirmed empirically (rule authored `'cutajar, emma'` fires on stored
   `'CUTAJAR, EMMA'`, 43 lines). ~~Refresh cadence~~ — **monthly**. **Same-tier tie-break within
   one table: Sameer says the earlier row wins, and the one clean empirical test supports him**
   (`C4U NURSING`: WH-1029 took all 299 lines over WH-1205, both Medium, same table). Also
   measured: the famous vendor collisions (JB HI-FI, AVIS) are largely moot in practice — none
   of the competing vendor-only rules wins any line; more specific description rules outrank
   them all. ~~The one remaining surprise is Western's cross-table order~~ — **resolved by
   tracing the KNIME workflow with Sameer (node 864's ports) and confirmed by measurement:
   there is no cross-table order.** Lines are routed by `MEDICAL (YES / NO)` — flagged lines to
   `PMML_Medical_Rules`, the rest to `PMML_Rules` — with perfect separation across 2.35M lines.
   SCHNEIDER and MEDRECRUIT were never conflicts, just two line classes. **Every engine question
   is now closed.**
3. ~~Who loads `PMML_Rules` and from where~~ — **largely answered 2026-08-06**: the Google Sheet
   (*Categorisation Ruleset Manual Override*, one per client; Northern's read from
   `Assets\`) is the client-facing authoring/override portal, and PI applies it **monthly** —
   stated in the sheet's own instructions. Rule proposals can therefore be emitted in the
   sheet's exact tab format and ride the existing load. Remaining unknowns: who physically runs
   the load, why the sheet and the table have drifted by 532 rules (measured — see the Google
   Sheet subsection), and the **"Ruleset Portal Guide"** the instructions reference, which
   nobody has shown us yet.
4. ~~Western's empty `PMML_Rules_Ordered`~~ — **largely explained 2026-08-06**: at Western the
   assignment path *text* binds directly to `WH_Taxonomy` (99.8% resolve), so there may be
   nothing to compile; the workflow presumably resolves text→`CATEGORY ID` itself.
   ~~The new hard question is inter-table precedence~~ — **answered the same day: there is no
   inter-table precedence.** Lines are routed by `MEDICAL (YES / NO)` to one table or the other
   (see the Western subsection above); the two tables never compete for a line.
5. ~~CBoard precedence at SAH~~ — **answered 2026-08-06 from the view SQL: a rule can never
   outrank CBoard** (the view's CASE consults CBoard before the rules branch). SAH corrections
   for CBoard lines therefore need a **catalogue-fix path** targeting `CBORD_Taxonomy` by
   `item_name` — see § 6. **Sameer's call, same day: the taxonomy mismatch (166 CBoard paths
   absent from `Adventist_Taxonomy`) is reported as a finding and owned by the account manager —
   we never add categories to a client's taxonomy.** Accuracy stays segmented by mechanism, which
   already handles the yardstick question.

## 6. The rule-writer — two steps, not one click

The vision: approve → a new rule appears in that vendor's rule sheet at highest priority, keyed on
vendor + item description. § 5 shows this is exactly the house idiom, so the draft itself is
mechanical. What stays deliberate is the apply:

1. **The client databases are read-only to this pipeline, always** — a standing rule. Granting a
   staging web app INSERT into four hospitals' live rules tables is a real decision for Sameer
   and the business to make explicitly; rules written there drive live categorisation and the
   ProcureTrak dashboards clients look at.
2. **The engine's tie-break and refresh are outside our sight** (§ 5 gaps) — until they're
   confirmed, a drafted rule's effect is a prediction, not a fact.
3. **A rule is a per-hospital copy, not a shared object** — every proposal names its
   `rules_table`, mints an ID in that hospital's scheme, and is collision-checked there.

So the design is:

- **`qa_rule_proposal`** (new table, our database), drafted **in the authoring format `PMML_Rules`
  already uses** so applying it is a paste, not a translation: `rules_table` · minted `RuleID` ·
  `Priority` · `Field_1..3 / Operator_1..3 / Value_1..3` (typically
  `VENDOR_NAME CONTAINS '<vendor verbatim>' AND ITEM_DESCRIPTION CONTAINS '<term>'`) ·
  **target `taxonomy_key`** (the binding — § 5) · `Category Assignment` path text ·
  `Source` tier label in that hospital's vocabulary · `Analyst` = the PIDA login ·
  `proposed_at` · the `qa_line_id`/`subject_key` that triggered it · status
  (`draft → approved → applied → verified`).
- **Apply** is a separate controlled step through whatever the existing loading process turns out
  to be (§ 5 gap 3 — likely the Google Sheet). Proposal → applied gives an audit trail and a
  reviewable diff per hospital.
- **Verified** means the refreshed data shows the rule firing and the next pipeline run judged
  the lines Correct — the loop closes (§ 8).
- **SAH gets a second proposal type: the catalogue fix.** For a line categorised by
  `CBoard Lookup`, a rule proposal is pointless — the view consults CBoard first (§ 5). The
  approve/override click instead drafts a **`CBORD_Taxonomy` correction**: `item_name` → the
  corrected `Category 0..4` path. Same two-step apply, same audit trail; different target table.
  The two known double-pathed items (74 duplicated lines) are the first two rows in that queue.

**How the proposal-writer drafts the two conditions — Sameer's drafting rules, 2026-08-06,
settled on a worked example** (BUNZL straw paper at Northern):

- **Vendor: the distinctive trading name with the legal suffix REMOVED** — `BUNZL OUTSOURCING
  SERVICES`, never `…LIMITED`. The suffix is the volatile part (`LIMITED` / `LTD` / `PTY LTD`
  drift across files for the same company), and a full-name rule stops matching silently the
  moment it drifts. Sameer: *"if you would have written a rule BUNZL OUTSOURCING SERVICES LIMITED
  im sure our rule would have never captured"* the `LTD` variant. Guard on the other edge:
  never trim past the distinctive part — `BUNZL` alone can reach a different Bunzl entity
  (judging rule E). Suffix off, identity intact.
- **Description: the product term only — no sizes, quantities, colours or SKUs.**
  `STRAW PAPER`, never `STRAW PAPER FLEXIBLE WHITE 21CM WRAPPED (SUSTAIN) SUSSTF210W/W` — 21cm
  becomes 22cm and a specification-anchored rule dies. Guard on the other edge: not so short it
  over-matches (`STRAW` alone catches `STRAWBERRY` — the `90 SHEET` defect reborn).
- **Both proven by the preview, not assumed**: before saving, the analyst sees every distinct
  vendor spelling and every line the drafted conditions capture — suffix variants visibly in the
  net is the confirmation the gap is closed.

**The blast-radius preview — the safeguard the button needs, now two checks.** Before a proposal
is saved:

1. Run its conditions (`LIKE '%value%'`, per § 5) against that hospital's in-scope lines and show
   the analyst: *"this rule as drafted captures N lines / $X across M distinct descriptions."*
   Shows the leverage; catches a highest-priority rule over-matching — a short term like
   "FREIGHT" or "SERVICE" would silently steal thousands of correctly-categorised lines from
   good rules. Shown, never auto-blocked — consistent with how we treat spend.
2. List **existing rules on the same vendor at the same or higher tier in the rules table the
   line routes to** — at Western that means matching the line's `MEDICAL (YES / NO)` flag to the
   right table first (§ 5), because a rule drafted into the wrong table never fires at all.
   Within-table duplicates are the real collision risk (same tier, earlier row wins), and adding
   another one manufactures the exact contradiction defect this project flags. If the collision
   list is non-empty, the right fix may be to **edit or retire the old rule via the fix queue**
   rather than out-prioritise it.

**Where vendor + description can't work:** 14.1% of in-scope lines have no usable item text
(blank or placeholder — `DESCRIPTION_USABLE = 0` marks them). A vendor + description rule can't
be drafted from nothing, and a vendor-only rule at highest priority is exactly the dumping-ground
pattern this project exists to catch. For these rows the app greys out the rule-draft, says why,
and offers a GL-account-name-based draft (`ACCOUNT NAME` is an established `Field_1` in all four
tables) or a manual referral instead.

## 7. What the app may write — the permission boundary, restated for the app

### What the app may READ — locked 2026-08-10 (PLAN v3.28 change 162)

```
qa_line / qa_vendor  ->  qa_review_unit (TABLE)  ->  v_review_queue (VIEW)  ->  the app
                         built once per run,          ~20 columns, the only
                         indexed, immutable           surface the app touches
```

**The app reads `v_review_queue` and nothing else.** Not `qa_line`, not `qa_review_unit`, not the
MSD, not a client database. Our verdict, confidence, basis, rationale and suggested categories are
**not in the view**, so the app cannot reach them — it is a lock, not a rule someone has to
remember. `GRANT SELECT` on the view; `GRANT UPDATE` on the review columns only.

Why a table underneath: the MSD keeps moving, so the coherence label must be **frozen per run** or a
run stops being reproducible; and the queue's row is a `subject_key` group with a line count, which
is too expensive to aggregate on every page load. Why a view on top: the analyst's own clicks must
show **immediately**, so the review layer is joined live rather than cached.

**Client isolation holds at the view too** — filtered per client, and one hospital's taxonomy never
resolves another's lines. Every row still carries `taxonomy_source`.

*(Unmeasured: the claim that a plain view would be too slow. Test it once `qa_vendor` exists — if a
view alone is fast enough, `qa_review_unit` goes away.)*

| The app MAY write | The app may NEVER write |
|---|---|
| `REVIEW_STATUS`, `REVIEWED_BY`, `REVIEWED_AT` | `VERDICT`, `CONFIDENCE`, `BASIS`, `RATIONALE` |
| `REVIEW_OVERRIDE_VERDICT`, `REVIEW_OVERRIDE_CATEGORY` (that hospital's taxonomy only) | Any `SUGGESTED_CATEGORY_*` column |
| `qa_rule.FIX_STATUS`, `FIX_OWNER` (+ `FIX_NOTES` when added) | Any line, unit or spend figure |
| INSERT into `qa_rule_proposal` | Anything in a client database (until explicitly decided otherwise) |

Enforced by SQL permissions on the app's service account. Cleanest shape: the app reads through
views and writes through its own tables/procedures, so it holds zero UPDATE permission on the
finding columns even in theory.

## 8. The loop this closes

1. Pipeline judges lines → queue appears in PIDA.
2. Analyst approves / overrides → review layer + rule proposals (drafted in `PMML_Rules` format).
3. Proposals applied through the existing rules-loading process (controlled step).
4. The categorisation workflow refreshes; our next pipeline run re-extracts.
5. The deterministic keys re-attach review state to the new run; the movement tracker shows lines
   that moved category; proposals whose lines now judge Correct flip to `verified`.
6. Override rate per hospital = live monitor of the judge. Time-to-fix per rule = live monitor of
   the service. Both fall out of columns that already exist.

Excel stops being the working surface. It can remain as an **export of the app's state** for
clients who want a file, generated into `output/<client>/<date>/` as today.

## 9. Open questions to settle before build

1. ~~Rule engine match semantics~~ **Largely answered 2026-08-06** (§ 5): CONTAINS → `LIKE`,
   three priority tiers, up to three ANDed conditions. Still open from § 5's gap list: the
   workflow engine's identity, same-tier tie-break, case handling, refresh cadence, who loads
   `PMML_Rules`, Western's empty `_Ordered`, and CBoard precedence at SAH. Most of this is one
   conversation with whoever runs the workflow — same sitting as `ACTIONS.md` Z3 (Monali).
2. **Two concrete unblocks, both settled 2026-08-06:** (a) view SQL — Sameer pastes the ALTER
   VIEW text in-session for now; `GRANT VIEW DEFINITION` at build time. (b) the Google Sheet —
   **no custom MCP server needed, and building one is the higher-risk option** (another set of
   stored Google credentials to manage). Either export the sheet to a file in the project folder
   (zero new access, a snapshot of authoring logic is fine), or use the built-in claude.ai Drive
   connector, which is standard OAuth under Sameer's own account and revocable from his Google
   security page. One real caution either way: whatever the sheet contains enters this project's
   working context, so it must not hold credentials or client-confidential figures — same
   standard as any other file here (`.env` never, per the standing rule).
3. **Clinical suggestions on uncategorised lines:** the pilot's uncategorised work suggests
   clinical branches for roughly a third of uncategorised lines. Approving one means an
   *indirects* analyst files a line as clinical. Is that their call, or does it route to a
   separate queue for whoever owns clinical categorisation?
4. **Write access:** does the app ever get direct INSERT to client rules tables, or do proposals
   go through the existing loading process forever? Recommendation: keep the two-step
   permanently; the audit trail is worth more than the click saved.
5. **Plumbing:** can PIDA's backend (staging-v2) reach the QA database's SQL server, and under
   what account? Staging first, matching the app's own staging→production pattern — and on the QA
   side this stays **pilot-only** until the production QA database decision is made.
6. **`ACTIONS.md` Z1** (does the suggestion get its own confidence column) matters more once an
   app renders suggestions — a UI wants a sortable field, not words embedded in a rationale.
7. **Analyst identity:** `REVIEWED_BY` and the proposal's `Analyst` value should come from PIDA's
   login — the rules tables already carry named (and machine) authorship, so this continues an
   existing practice rather than inventing one.
8. **The MSD — new to this document 2026-08-10, and it should have been here already.** The MSD
   working model (the `qa_msd_issue` register, one row per `pi_vendor_id`, Sameer as sole fixer,
   AMs read-only with a pointer) was settled on 2026-07-30 **for the Excel round-trip** and was
   never carried across to the app. Every prior reference in `PLAN.md` says *"the AMs' working
   files"*. Three questions that only arise once the surface is a screen:
   - **Does the register become its own PIDA queue?** In Excel it is a column in someone else's
     file. In the app it wants to be a queue with one writer (Sameer) and many readers — which is
     a second screen, not a field on the first.
   - **What does *"your 340 lines re-verdict next run"* mean in an app?** The pointer text in the
     Excel model assumes a visible batch boundary. An app has no "next run" the analyst can see,
     so either the row shows a pending-re-verdict state or the promise has to change.
   - **Does the coherence badge gate what the analyst may do,** or only inform them? Recommendation:
     inform only. Blocking a decision on an MSD state the analyst cannot fix would stall the queue
     on someone else's backlog — and `inconclusive` alone is 1,127 of the four hospitals' vendors.

---

*Provenance: § 5 figures were measured 2026-08-06 by read-only queries against the four client
databases (`rules_survey*.py`, scratchpad; findings recorded in `RUN_LOG.md`). Pilot tallies
re-confirmed by `state_audit.py` 2026-08-06. 41.7% (CBoard) and 14.1% (no usable text) are the
standing measured figures in `CLAUDE.md`/`RUN_LOG.md`. The ~one-third clinical share of
uncategorised lines is the pilot measurement in `PLAN.md` v3.22 § D. Re-measure all of them
before any goes into a client-facing document.*
