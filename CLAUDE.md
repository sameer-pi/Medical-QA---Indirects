# CLAUDE.md — operating rules for this project

Line-level QA of **indirect (non-clinical)** spend categorisation across four hospital clients.
Read `PLAN.md` before doing anything. It is the plan of record, currently **v3.71**.

---

## Start of every session

1. **Run `python pipeline/state_audit.py`** — read-only, pilot-only. It prints what is actually in
   the database and flags drift from the state recorded in `RUN_LOG.md`. Do this before reading
   anything, so the docs are checked against reality rather than trusted.
2. Read **`TRACKER.md`** — one page, where the programme is, what is gated and on whom. Then
   `PLAN.md`'s change table and the tail of `RUN_LOG.md` (what actually happened). The newest finding
   always ends with a **"Next session starts here"** list.
3. Check `ACTIONS.md` for what Sameer is unblocking.
4. Findings go to `RUN_LOG.md`. When something genuinely changes the plan, bump the version and
   **state the change in the table at the top of `PLAN.md`** — never a silent edit. Where a new
   version reverses an old one, strike the old entry through and point it forward rather than
   deleting it; the reasoning that was wrong is part of the record.

## End of every session, or when interrupted

Append to `RUN_LOG.md`: what was run, what was found, what broke, what the next step is. **The next
session starts from that file.** Knowledge that only exists in a chat transcript is knowledge lost.

**And update `TRACKER.md`** — its as-at date, its measured block, and any stage or gate that moved. A
tracker that lags the log is worse than no tracker: it reads as current and is not. `PLAN.md`'s old
status section was wrong for 15 days on exactly this failure.

---

## Where things live — never break this

| Path | Contains | Rule |
|---|---|---|
| `DESKTOP-START-HERE.md` | **The office desktop runbook** — the five steps from clone to judging, what must not be closed, what to do when it looks wrong. Written for Sameer *and* for the Claude session on that machine | Internal. **The ONLY copy of the runbook** — `ACTIONS.md` points here rather than repeating it, because a second copy of a procedure drifts exactly as a second copy of status does. **No status in it**; that stays in `TRACKER.md` |
| `TRACKER.md` | **Where the programme actually is** — the stage board (0–8), gates, timelines, carried defects | Internal. **The ONLY place status lives.** Carries an as-at date; if it is older than the last `RUN_LOG.md` entry it is stale and not to be trusted. Update it at session end, beside `RUN_LOG.md`. Its measured block is copied from `state_audit.py`, never typed from memory |
| `PLAN.md` | Technical plan of record — the **reasoning**. Status lives in `TRACKER.md`, not here | Internal. Version-bump + state changes at the top |
| `PROJECT-BRIEF (shareable).md` | Plain-language version | **The only doc cleared to share.** No credentials, no server details, no provisional figures |
| `JUDGING-RULES (Indirects).md` | How the judge decides — evidence hierarchy + the nine adjudication rules | Internal. Every rule states the measurement behind it. Update it when `PROMPT_VERSION` moves |
| `DEPLOYMENT-CONCEPT (Indirects QA in PIDA).md` | Thought-stage concept for the analyst review module in the PIDA app | Internal. Not a build plan — revisit when we get to that stage |
| `APP.md` | The **live run monitor** — a read-only local page watching the 40-day judging run. Feasibility, parameters, safety rules, six open decisions | Internal. **Discussion, not a build plan — nothing is built.** 🔒 It is NOT the analyst app Sameer killed on 2026-08-21: it writes nothing, has no analyst in it, is not a deliverable. If it ever grows a review screen, an override or a client login, **stop and ask**. Its *status* still lives in `TRACKER.md`, not here |
| `ACTIONS.md` | Sameer's to-do list | Keep current — tick things off as they land |
| `RUN_LOG.md` | Dated record of every run and finding | Append-only |
| `pipeline/` | All code | **No client names anywhere in here.** Ever |
| `clients/<key>/config.yaml` | Per-hospital settings | **No code in here.** Ever |
| `output/<client>/<date>/` | Generated deliverables | Regenerable; never hand-edited |
| `output/QA_LINE_TEST/` | The four review workbooks (Sameer's chosen folder name, 2026-08-06) **plus the ANSWER KEY workbook** (2026-08-17) | Regenerable by `make_review_workbook.py` and `make_answer_key.py`. **A COMPLETED one is not** — an analyst's answers exist nowhere else until ingested. Never overwrite a returned file; `make_answer_key.py` refuses to, and writes ` v2` instead. ⚠️ **The answer key is DE-ANCHORED BY DESIGN** — sheet 1 hides our verdict and destination, sheet 2 reveals them. Do not "helpfully" merge the sheets: an anchored answer key cannot be un-anchored, and it is the only human yardstick we have |
| `output/Taxonomy/` | The taxonomy merge. **FIVE FILES, and only five** — *MERGED* (.xlsx), *CROSSWALK* (.csv), *DECISIONS NEEDED* (.xlsx), *HIERARCHY* (.html), *Taxonomy_Draft (Indirect)* (.xlsx). ~~THREE FILES~~ ~~FOUR FILES, and only four~~ Sameer, 2026-08-12: *"i just want to see 3 files in the taxonomy folder not 6"* — **still the same rule, one generation only**; it moved to four on 2026-08-13 when he chose to keep the browsable chart in with the workbooks, and to five later the same day when he asked for a flat Excel copy of the chart. **The draft is a COPY and nothing may exist only in it** — if a ruling is ever typed into it, say so, because it stops being regenerable at that moment. More than five files means an old generation was left behind | Regenerable — the first three by `merge_taxonomy.py --emit`, the chart by `taxonomy_chart.py`, the draft by `taxonomy_draft.py` (both read the newest MERGED and open no database). **The DECISIONS workbook is not.** It is both the sheet Sameer answers in and the store of every answer he has given — read back as an **input** on the next run, so `SAMEERS_RULING` exists nowhere else. Answered rows stay in it, greyed, marked `ANSWERED`. A re-run overwrites it **only when every ruling in it is carried into the new content**; otherwise it writes ` v2`. Never add a second copy in another format — a second file is a second place an answer can live |
| `program/` | Cross-client outputs (MSD register, dashboards) | |
| `_reference/` | Frozen Nufarm template | Read-only. Reference, not a dependency |
| `Assets/` | Snapshots Sameer drops in (e.g. the exported rules Google Sheet) | Read-only inputs. Never edited, never authoritative — the live DB is |
| `.env` | Live credentials | **Never** print, paste into chat, or copy into any other file |

Sameer's standard, in his words: *"I can never get confused as to which file lives where."* If a new
file doesn't obviously belong in one of the above, ask before creating it.

---

## Hard rules

~~**PILOT ONLY — standing instruction from Sameer, 2026-07-30.** All work targets
`PI_Medical_QA_Indirect_Pilot`. **Production (`PI_Medical_QA_Indirect`) is not to be created or
built against** until the pilot has run and proven schema v2. `QA_DATABASE` is deliberately blank in
`.env`; leave it blank.~~

🔓 **DISCHARGED 2026-08-18 by Sameer, who created the production database.** The condition it was
waiting on was met: schema v2 is proven — `schema.sql` matches the live pilot **84 = 84 across all
four tables**, and every `CREATE TABLE` in it has been **executed** against the server, not merely
compared. `PLAN.md` v3.53, `RUN_LOG.md` Findings 98 and 99.

**TWO DATABASES NOW, AND THE DISTINCTION STILL MATTERS.**

```
PI_Medical_QA_Indirect_Pilot   2,000 rows · the proving ground · regenerates in ~16 minutes
PI_Medical_QA_Indirect         created 2026-08-18 14:57 · EMPTY · the real run
```

**Scope every query, table and deliverable to ONE of them explicitly, and say which.** The pilot is
no longer "the database" — it is *a* database, and a figure quoted without naming its source is now
ambiguous in a way it never was before. ⚠️ **`QA_DATABASE` in `.env` stays BLANK until the schema is
applied to production and verified against production itself** — not against the pilot it was
generated from.

⚠️ **Production is not a bigger pilot. Four known defects fail ONLY at scale** and cannot be caught by
any check that runs today: `--all` caps at 100,000 lines and reports success, five hardcoded
2,000-row assertions, `fetchall()` over the whole population, and the recovery model below. **Pilot-
passing is not evidence about production for anything whose failure mode is size.**

~~🔴 **RECOVERY MODEL IS STILL `FULL` ON BOTH DATABASES.** Measured 2026-08-18. `SET RECOVERY SIMPLE`
has never run — not on production, and not on the pilot since 2026-07-30. It needs `db_owner`, which
`Claude` deliberately lacks. **Do not start a bulk load until it is SIMPLE**: under FULL with no log
backup scheduled, the log grows until the volume fills. It is in `ACTIONS.md` § 2a.~~

🔓 **WITHDRAWN 2026-08-25 by measurement — `RUN_LOG.md` Finding 126. The recovery model is still
`FULL` and that is FINE, because the premise of the rule was false: there IS a backup chain, and
there always was.** Nobody had looked at `msdb.dbo.backupset` — a hazard argued from the recovery
model alone for a week, which is the "measure a risk before raising it" rule broken in the document
that states it. **Re-measured 2026-08-26, the morning of the go/no-go:**

```
PI_Medical_QA_Indirect        FULL   log_reuse_wait = NOTHING
  full  2026-08-26 00:15   4,257.3 MB      log  2026-08-26 01:23   85.2 MB
```

`log_reuse_wait = NOTHING` means nothing is blocking the log from truncating. ⚠️ **Two things worth
knowing rather than fearing: log backups run ONCE DAILY, not hourly, and production's log file is
already 12,616 MB against 4,257 MB of data.** The judging run adds ~70,000 row UPDATEs a day, which
is small beside that — but **if the log ever starts growing across days rather than being reclaimed,
that is a finding, and `log_reuse_wait` is where it will show.**

**Write access.** The pipeline writes to the **QA databases** — pilot and production — and nothing
else. The four client databases and the MSD are **read-only, always**. No exceptions, no temp tables,
no "just this once". `[Claude]` holds `db_ddladmin` + `db_datawriter` + `db_datareader` on both and
**not `db_owner`**, verified by measurement on 2026-08-18: a role list is a claim about permissions,
a successful write is the permission. 🔒 **`db_owner` is withheld deliberately — it can DROP, and
once production holds a completed run that is ~15.5 days of compute behind one command.**

**Never keyword-filter for clinical content.** The clinical split is `Category Level 0`. Substring
matching on descriptions silently deletes in-scope indirect spend — *"clinical waste removal"*,
*"theatre HVAC maintenance"*, *"patient meal trolley"* — and corrupts the accuracy denominator.
`clientcfg.py` rejects any config that tries. Leave that guard in place.

**A client's taxonomy NEVER resolves another client's lines.** Standing instruction from Sameer,
2026-07-31. Every query runs inside the connection already opened for that one hospital, and every
table reference is a **one- or two-part name** — `[dbo].[MH_Taxonomy]`, never
`[Z_Melbourne_Health].[dbo].[MH_Taxonomy]`. `clientcfg.assert_same_database()` refuses three-part
names and `verify_client.py` FAILS on them.

This is not hygiene, it is correctness. **The taxonomy keys collide across hospitals while meaning
different things:**

```
key 379   Melbourne: Non-Clinical > Food and Beverage > Dairy Products > Cheese > Cheese
          Northern : Non-Clinical > Facilities Management > Soft Facilities Management > ...
```

Melbourne and Northern share 260 keys and **46.5% of them mean something different**; Melbourne and
Sydney Adventist, 47.3%. A leak would silently relabel cheese as facilities management and measure
accuracy against the wrong yardstick with nothing visibly broken. Every loaded row therefore carries
`taxonomy_source` naming the database and table it came from, so a leak is visible in the data and
not merely absent from the code.

**🔒 NEVER LET A GENERATED ARTEFACT BECOME ITS OWN INPUT.** Found 2026-08-17, the worst defect so
far. `load_taxonomy.load_merged()` stores the merged taxonomy in `qa_category` under
`merged_indirect`; `merge_taxonomy.load_nodes()` selected from `qa_category` with **no client
filter**, so the next `--emit` read our own output back **as a fifth hospital** and merged the
taxonomy with itself. It compounds every emit → load → emit cycle. **13 exact-duplicate leaves
manufactured, ~4M lines double-counted, 85 phantom "open decisions"** — categories 350 → 365 with no
client data changing. `load_nodes()` now excludes it. ⚠️ **The WRITE side is unchanged** — nothing
yet stops a future script repeating this.

**🔑 A SELF-CONSISTENCY CHECK CANNOT SEE A CONTAMINATED INPUT.** `line conservation` printed **OK**
on every contaminated run: 6,408,848 in = out + dropped, perfectly consistent *with an input that
was already wrong*. It proves nothing was lost in processing; it cannot prove the right thing went
in. **A guarantee must be measured against something OUTSIDE the process** — the GL against the
judge's rationales, the taxonomy against the *client* node count, never against its own arithmetic.
**An unexplained delta is a finding, not a rounding error**: this was caught only because +15 did
not match the +2 categories that had actually been asked for.

**Verify joins and values; never infer them from names.** A previous session asserted
`MASTER CATEGORY ID → Category ID` because the names looked alike. It was wrong — the real key is
`Master ID`, 2,380,203 matches versus zero. **Confirm every join by match count before relying on
it**, and state the count.

**MEASURE A RISK BEFORE RAISING IT. A hazard inferred from schema structure is the same error as a
join inferred from a column name** — it just feels like diligence, so it goes unchallenged longer.
2026-08-03: I argued for four turns that joining a line to `qa_rule` on `rule_id` alone would fan
out at scale, because `qa_rule`'s key carries `rules_table` and Western has two rules tables. **One
query killed it — Western's two tables share ZERO RuleIDs.** It would have bought a redundant column
and a code change to defend against nothing. Sameer caught it: *"I don't understand how the spill is
gonna happen unless you mess up the code."*

**And never argue from "the sample is too small to show it."** The pilot's 243 rules showed no
collisions and I read that as a sampling limitation rather than as evidence — which makes a claim
unfalsifiable and is how a guess survives four turns. **An absence of evidence is a reason to go and
measure the full population, never a licence to assert the risk.** `pipeline/rule_overlap.py` is
that measurement, kept so it is never re-argued.

**The vendor name is pulled VERBATIM. Never trim, case-fold, normalise, de-duplicate or mask it.**
Standing instruction from Sameer, 2026-07-31: *"do not tweak this col or input, let it remain in the
same format from where you are pulling."* The value in our extract has to be the value an account
manager can paste into their own system and find. This holds even though individuals appear as
vendors — Melbourne embeds an employee number in the name (`MURNANE(126016), TEGAN`), Northern pools
them under `Reimbursement Supplier`. **PII is handled at the extract/sharing boundary, by deciding
what leaves the building — never by editing the stored value.** `_verbatim()` in `smoke_test.py` is
the only accessor for this column; `_txt()` must not be used on it.

The decision cost nothing: normalising vendor names merges **0.05–0.65%** of them, because within one
client's view they come from a single ERP vendor master and are already clean. And
`SUPPLIER NUMBER` is **not** the better key it looks like — Northern holds 7,766 numbers for 3,548
names, with `Reimbursement Supplier` alone carrying 4,284. **The raw name is the vendor key.**

**A client's RuleIDs may span more than one rules table — and a RuleID may not be a rule at all.**
Resolve every RuleID by match count against **all** the client's configured tables, and report the
unresolvable rate. Western's `PMML_Medical_Rules` carries **20.7% of its in-scope lines**; the config
had dismissed it on its name. Sydney Adventist's `RuleID` is the literal string `CBoard Lookup` on
**41.7%** of in-scope lines — a second categorisation mechanism, not a rule, with nothing to fix.
**An unresolvable RuleID produces a fix queue that comes back short and reads as "nothing to fix
there"** — the worst failure mode available, because it looks like success. Scope is decided by
`Category Level 0` on the **line**, never by the name of the table a rule came from.

**A `MEL-` RuleID on a Northern line is NOT a leak — rules are copied between hospitals.** Each
hospital's rules table holds a **borrowed-rule fallback tier** at priority `LOWEST` under
`Source = "C. OTHER CLIENT RULES"`. Northern's table is **NH- 1,591 · HL- 1,341 · MEL 1,276 ·
PH- 1,252 · CM- 1,013** — fewer than a third its own, and **4.6% of its in-scope lines (40,196) are
categorised by a `MEL-` rule**. Do not "fix" this and do not report it as contamination; the
taxonomy isolation rule above is about **taxonomies**, which is a different thing.

**A rule ID names independent COPIES, not one rule.** Fixing `MEL-0881` in Northern's table does
nothing to Melbourne's. **Every fix instruction must state the table it applies to** —
`zz_smoke_rule.rules_table` carries it. The upside: the same ID defective in several hospitals is
found by joining the fix queue to itself on `rule_id`, which is cross-client *diagnosis* with
per-client *remediation*, exactly as the plan intends.

**"Filled" is not "informative". Count placeholders, not just blanks.** Melbourne and Sydney
Adventist store the literal string `NO DESCRIPTION` / `No Description` — non-blank, so every fill-rate
check reads them as 100% populated. Measured in scope: **388,510 lines (14.1%) have no usable item
text** — Western 31.9% blank, SAH 16.0% placeholder, Melbourne 12.3%, Northern 1.4%. Two
consequences: the unjudgeable bucket is **not Western-only**, and a `COALESCE(NULLIF(a,''), b)`
description fallback **never fires**, because the placeholder is non-blank. Treat placeholders as
blank in the priority list.

**14.1% is a floor, not a ceiling.** A second flavour exists that the placeholder list does *not*
catch — the **identifier-as-description**. Northern's CityLink lines read `1GY7YT 8071211238099`:
a number plate and the invoice number. 22.8% of that vendor, 1.8% of Northern in scope. **Do not add
it to `PLACEHOLDERS`** — unlike `NO DESCRIPTION`, an identifier is sometimes the only handle a person
has, and stripping it would be us deciding what counts as information. Let the judge's confidence
carry it. ~~and lean on `gl_account_name`, which is what makes such a line judgeable at all~~ —
**struck 2026-08-17, see the evidence hierarchy below: GL is no longer evidence.** An
identifier-as-description now resolves to `Uncertain` and goes to the analyst, which is the intended
outcome rather than a gap. It is still not a `PLACEHOLDER`, for the reason given above — an
identifier is a handle a *person* can use, and the analyst is the person.

**A spread is not a spread if `TOP` follows it.** `ABS(CHECKSUM(<supplier>)) % n = 0` picks the
vendors; `TOP n` with no `ORDER BY` then takes the first rows in scan order, so the result is a
leading slice of a vendor subset. It read as 55 vendors with 56% from one at Northern, over a 14-month
window. **Always `ORDER BY` a hash of the row key**, and check the vendor concentration and date span
of any sample before quoting a figure from it.

**`qa_line` is the table. `zz_smoke_test` is the PROTOTYPE.** The `zz_` tables designed the schema
on 1,200 sampled rows and are superseded; they survive only so the column decisions stay auditable.
**Every verdict, and every figure worth quoting, is in the `qa_*` tables.** Do not analyse from
`zz_`, and do not let a reader think it is the main table — a real one did.

**Check `SELECT DISTINCT run_id FROM qa_line` before quoting anything.** `build_pilot.py` has **no
superseded-run purge**. An aborted run once left two generations in the table at the same time, and
every figure taken from it double-counted. One `run_id` is expected; more than one means stop.

**A KILLED PROCESS IS NOT A PROCESS THAT DID NOTHING.** 2026-08-04: I stopped a rebuild mid-run and
told Sameer nothing had been written. It had already committed Melbourne and Northern — 528,091 rows
across two `run_id`s while I was calling the pilot untouched. `build_pilot.py` commits **per
client**, so an interruption leaves a partial generation. **After any stop, crash or timeout, run
`pipeline/state_audit.py` and report what it says — never a state you have not just measured.**

**Never quote a figure without its provenance — including your own from earlier in the session.**
This has now failed twice by recall rather than by measurement: "59,480 lines" (the true figure is
**26,165**) and a rule-recency query that returned 48 stale rules out of 21. **If a number is going
into a document or a sentence to Sameer, re-measure it.** Several numbers in `PLAN.md` are flagged
provisional; provisional figures do not go into anything client-facing until re-measured.

**"Indirect" must appear in every artefact name.** The folder is called *Medical QA - Indirects*.
Without the qualifier, a future reader concludes we QA'd medical items — the opposite of the truth.

**Report failures plainly.** If a check fails, say so with the output. Don't soften it, don't
proceed as though it passed.

---

## The things most easily got wrong

**ALWAYS TRIM category values before comparing.** Sydney Adventist stores `'Clinical '` with a
trailing space; the other three store `'Clinical'`. SQL Server pads on comparison so a SQL filter
matches anyway — **Python's `==` does not**. An untrimmed pandas-side gate would pass 524,923
clinical lines into scope silently. Trim both sides, everywhere, every time.

**Scope — two conditions, both must hold:**
1. `Category Level 0` ≠ `Clinical`
2. `Category Level 0` ≠ `Inter-Hospital Spend`

**`Category Scope` is DROPPED** — never filter or judge on it, never carry it into a table or an
output. It is fully reproduced by `Non-Procurement` at Level 0 or Level 1, which identifies the
accounting-noise reporting segment.

Uncategorised lines (`Category Level 0` null) are **in scope**, flagged
`scope_status = 'in_scope_uncategorised'`.

**🔒 THE FINDING IS IMMUTABLE. The analyst redirects; they never rewrite.** Standing instruction
from Sameer, 2026-08-04: *"they can make changes to it later, but can never change our findings but
only redirect the incorrect rule to the correct taxonomy level."* Our layer — `verdict`,
`confidence`, `basis`, `rationale`, `suggested_cat_l1..l4` — is written once and **never edited in
place**. Their layer — `review_override_verdict`, `review_override_cat_path`, `review_status`,
`reviewed_by`, `reviewed_at` — sits beside it with an author and a timestamp. **Keeping both is what
makes the override rate a live measurement of the judge**; overwrite the original and that signal is
gone. **Override data is NOT a golden set** — the analyst sees our answer first and is anchored to
it, so agreement reads higher than the truth. It monitors, it does not calibrate.

**The app may write ONLY:** override verdict · override category (that client's taxonomy only) ·
rule fix status, owner, notes. **Never** our verdict/confidence/basis/rationale/suggestion, and never
any line, unit or spend figure. Enforce by database permission, not by convention.

**Suggestions come from that client's own non-clinical taxonomy, with NO restriction to categories
already in use.** Sameer, 2026-08-04. An unused category can be the right answer — *"you should be
filing this here and never have"* is a finding, not an error. **The override is the safety net, not
a narrower candidate list.**

**Category level markers are conditional on Level 0, not per level.** Level 0 empty → **all five
levels read `Uncategorised`** (there is no path at all). Level 0 filled but a deeper level empty →
`(not used at this level)` — a real category with a short path, ~230 of 1,999 pilot units.

**HOW THE JUDGE WEIGHS EVIDENCE — standing instruction from Sameer, 2026-08-03, in his words:**

1. **Vendor name sets the neighbourhood.** It bounds what is plausible and **is never a factor by
   itself**. *"A vendor like Traffic Management cannot come under Food and Beverage by just the
   vendor name — it should broadly be under some traffic management category."*
2. **The item description picks the category** within that neighbourhood. Vendor + description is
   the **only** basis for a confident verdict.
3. ~~**No usable description** → vendor + `gl_account_name` + cost centre → a calculated call **at
   lower confidence**, stated as such in the rationale.~~ **🔒 REVERSED 2026-08-17 — GL ACCOUNT AND
   COST CENTRE ARE NOT EVIDENCE.** Sameer: *"we have a hard rule that the GL will never be used to
   make any judge or assumption, neither the cost centre ... if the vendor is incoherent, obviously
   supplier name wouldnt just be enough, but in this case we would need to make some sense through
   the item description, if the item description doesnt give us that granularity, it would be
   manually sorted by the analyst."* **No usable description → `Uncertain`, routed to the analyst
   for manual sorting.** There is no third evidence source.
4. **No evidence at all** → `Uncertain`. Never a guess.

**`MSD_COHERENCE` IS A FLAG BESIDE THE VENDOR. IT IS NEVER A JUDGE INPUT.** Added 2026-08-17 at
Sameer's request — five values in `qa_line`: `coherent` · `incoherent` · `inconclusive` ·
`unevaluated` · `no match`, from the MSD, refreshed by `msd_coherence.py`. It answers *"does this
vendor's stated business match what it invoices for?"*, which is **step 1 above** answered by another
team. Feed it to the judge and you get a verdict resting on the vendor alone — the exact failure step
1 exists to prevent. It is not in `emit_batch`'s payload; do not add it.

Three things measured before it was built, so none is re-argued: it does **not** carry the GL (its
prompt sees a web summary plus item descriptions, no GL, no cost centre — *checked on the input, not
inferred from the design*); the vendor joins **verbatim at 99.1%**, so nothing is normalised on
either side; and ⚠️ **`pi_vendors.invoice_coherence` must NOT be thresholded** — `inconclusive`
appears at 0.5 *and* at 0.25, so `MSD_COHERENCE_CUT` would file those vendors as `incoherent`. The
verdict word lives only in `llm_call_logs.raw_output`. ⚠️ **And it does not predict miscategorisation
— incoherent vendors are misfiled LESS often than coherent ones (7.9% vs 11.4%).** What it tracks is
our own `Needs evidence`, because the MSD's *"could not tell"* and ours share one cause: thin item
text. **Read it as a data-coverage signal, never as an error predictor.**

**THE FIELDS ARE REMOVED FROM THE PAYLOAD, not merely forbidden in the prompt.** A field that is
present is a field a model can read whatever the instructions say, and nothing afterwards would show
that it had. The only guarantee that evidence was not used is that it was never supplied.
`emit_batch` sends **vendor · item_text · has_usable_text · assigned · assigned_in_taxonomy · rule ·
spend** and nothing else.

⚠️ **AND THAT WAS NOT ENOUGH. v4 CLAIMED THE GL WAS CLOSED AND THREE PATHS WERE STILL OPEN** — found
2026-08-17 by grepping the judge's rationales, never by reading the diff. (1) `rule.fires_on` was
sent whole, so a GL rule spelled it out: `"ACCOUNT NAME CONTAINS FREIGHT"` — **274 lines, 40
rationales, 24 firm verdicts.** (2) **Adjudication rule I still instructed the judge to use it**, a
v3 paragraph the v4 edit walked past. (3) The **uncategorised prompt still carried the v3 hierarchy
verbatim**, so the rule was never in force on that entire pass. Fixed in **v5**.

🔑 **A GUARANTEE ABOUT WHAT THE JUDGE SAW MUST BE MEASURED ON THE OUTPUT, EVERY RUN.** Removing the
obvious field is a start, not a proof — the same evidence reappears in a rule description, a prompt
paragraph, a second code path. `action_classify.py` now greps every rationale for GL / account name
/ cost centre and prints the count, so this is a standing measurement rather than an assertion.

**The filter is an ALLOWLIST, never a blocklist.** Only `VENDOR_NAME` and `ITEM_DESCRIPTION` may be
named in `fires_on`; everything else is withheld by default, including fields that do not exist yet.
A blocklist of GL-ish names fails **open** on the next client's rules table — which is exactly how
this survived v4. `BUSINESS UNIT DESCRIPTION` is withheld on the same reasoning as the cost centre:
it says **who bought**, never **what was bought**.

**It also closes a circularity we had not measured.** 38 of 352 rules fire on `ACCOUNT NAME` or
`CHARGED COST CENTRE` and categorised 199 pilot lines. Showing the judge the same GL the rule fired
on had it confirming the rule's own input — the identical trap as agreeing with a vendor-fired rule
on vendor evidence, which step 1 already guards against. **A rule that fires on GL alone is itself a
finding for the fix queue**, not just a cause of one.

⚠️ **THE COST, measured 2026-08-17 and stated rather than discovered later:** 297 pilot lines have no
usable description; **189 of them held a firm verdict resting on GL and become `Uncertain`** — 9.4%
of the pilot. The full-scale equivalent is **388,510 lines (14.1%)** with no usable item text. That
is the size of the manual queue this rule creates. `PROMPT_VERSION` moved **v3 → v4**, so verdicts
either side of it are **not comparable on lines with no usable description**.

**Never return `Correct` on the vendor name alone.** That is not an audit — 61.8% of Northern's
rules fire on `VENDOR_NAME`, so agreeing with a vendor-fired rule on vendor evidence is the judge
confirming the rule's own input. The guard is step 1, not discarding the vendor: **I proposed
"ignore the vendor" and Sameer corrected it — that throws away real signal.** The vendor's job is
**detecting contradictions, not picking categories**, which is exactly what catches the dumping-
ground rules (garbage bags as *Safety Equipment*, combs as *Property*).

**Confidence must show how strong the evidence was.** ~~Vendor + description beats vendor + GL~~ —
**struck 2026-08-17; there is no vendor + GL step any more.** The live distinction is between a
*specific* item text on a coherent vendor and a *vague* one, and it still has to be visible in the
output rather than buried. ⚠️ **`NIM_BASIS` does not currently do this** — it reports `no_evidence`
on 1,527 of 2,000 lines including 1,307 that plainly had evidence. Broken, excluded from every
extract, not yet fixed. `RUN_LOG.md` Finding 87.

**The judged unit is `(client, vendor, term, assigned_category)`** — the assigned category is part of
the key. Drop it and Case B (same vendor, same term, two different categories) collapses into one
verdict and hides a real rule defect.

**Three keys, all deterministic** — `unit_key`, `subject_key`, `input_hash`. If any becomes an
identity column, the Excel status re-attach and the movement tracker both break silently. See
`PLAN.md` § *The three keys*.

**Line dates stay in SQL.** They do not go into Excel extracts. **Unit-level `first_txn_date` /
`last_txn_date` stay in SQL too** — kept because 182 Melbourne and 221 Western units show an error
running over a year, held back from Excel because they are **blank on 47.6% of Northern and
single-day on 72.8% of SAH**. Decided 2026-08-03; revisit when coverage is understood, not before.

**Uncertain verdicts are excluded from both numerator and denominator**, with the % stated plainly.
Never folded silently into either side.

---

## Query and data lessons — learned the hard way, 2026-07-30

**Aggregate before joining, never after.** Joining a 3.4M-row view to the rules table and then
grouping timed out at 15 minutes. Group by `RuleID` first, then join the small result to the rules
table. Applies pipeline-wide.

**Test SQL against a slice first — but NEVER measure on one.** Run every generated query against
`(SELECT TOP 50000 * FROM <view>) s` to prove it *executes*. Errors surface in seconds instead of
after a multi-minute scan. This is how a description-attribution bug was caught.

**A leading slice is clinical-heavy and will lie to you about fill rates**, in both directions.
Measured 2026-07-31: Melbourne's `ACCOUNT NAME` reads 39% on a leading slice and **85%** in scope;
Sydney Adventist's `INVOICE DATE` reads 99.7% and **52%**. Melbourne's `UNSPSC` reads 69% and
**exactly 0%** — it is a clinical-item field, so it is empty on every line this project judges.
**Any figure that will be quoted, acted on, or written into a config must be measured on the
in-scope population with a spread sample** (`ABS(CHECKSUM(<supplier>)) % n = 0`), never on `TOP n`.

**Merge scans.** Profiling ran two full passes for figures obtainable in one. On millions of rows
that is minutes of duplicated work. Compute every aggregate you can in a single scan.

**Western's rows are not unique, and its counts are inflated.** It is the only client with no
`RowID`, and its `INVOICE DISTRIBUTION ID` repeats on **52,824 of 2,347,469 rows (2.25%)** with
byte-identical content — same vendor, description, amount, category, RuleID, source file. Adding
`INVOICE ID` and `INVOICE LINE NUMBER` changes nothing; the distinct count is identical. **Every
per-line and per-dollar figure for Western must be de-duplicated before it is quoted**, with the
raw count alongside. Judge units are unaffected — identical lines collapse into one unit anyway.
Northern's `INVOICE ID + INVOICE LINE NUMBER` also repeats (26.88%), but that is one invoice line
split across cost centres, **not** duplication — do not report it as such.

**SPEND IS REPORTED EXACTLY AS THE DATA HOLDS IT.** Standing instruction from Sameer, 2026-07-31:
*"i dont need any threshold on the value, the data should be as is ... there is no tweak in the
spend!"* **No threshold, no outlier guard, no exclusion, no `is_extreme_value` flag, no netting, no
absolute values.** Signed, as it appears.

The data does contain implausible extremes — 237 Melbourne lines carry $24.5bn gross against $433M
net, e.g. `−$5,625,000,000` on one line. **They are reported as a data-quality finding for the client
to act on, not silently corrected by us.** The correct handling is the one already in the plan:
**always report line counts alongside spend**, so a reader can see when a spend figure rests on a
handful of lines. Never filter, weight or rank anything by spend in a way that requires deciding
which rows are "real" — that decision is not ours to make. **Rank by line count instead**, which
needs no threshold and no judgement.

**QUALIFIED 2026-08-11 by Sameer — separate REPORTING from PRIORITISING.** *"when we scale we will
need to use a spend weighted approach."* The rule above governs **what we report** and is unchanged:
as-is, signed, no threshold, no netting, no absolute values. **Which lines get judged first at scale
is a different question** — it decides where to look, not which rows are real — and that ordering is
now spend-weighted. **The two must never be conflated in code or in a sentence to a client.**

⚠️ **Not yet built, because one decision is outstanding and guessing it would be irreversible.**
Measured 2026-08-11: **Northern holds $53.9bn absolute against $2.97bn signed — an 18× gap — and its
top 1% of lines carries 99.4% of absolute spend.** A naive weight puts ~8,750 lines in front of the
judge and never reaches the other 866,268 — pointing it almost entirely at the rows the plan already
calls data-quality defects. Signed and absolute give **opposite** answers on the same row: a
−$5.6bn line ranks last on one and first on the other. ~~Recommendation on the table is **banded** — spend bands, then rank by line count within each band~~ — **SUPERSEDED 2026-08-17 by Sameer: the rollup is PER VENDOR NAME, largest spends first.** Better than my banding: a vendor total is far steadier than a line, so it does not put the −$5.6bn data defects at the top of the queue. ⚠️ **Not built.** Two questions must be measured first — signed or absolute (Northern is $2.97bn against $53.9bn, 18×), and whether big spend actually leads to the errors at all. `PLAN.md` v3.43, `RUN_LOG.md` Finding 71.

**THE SIZE OF THE JOB AT FULL SCALE — measured 2026-08-11, quote these and not a recollection:**
**2,778,595 in-scope lines** (2,767,046 with Western de-duplicated — it repeats 11,549 of its 671,200
in-scope rows, 1.72%) across **1,014,752 distinct subjects**, of which **413,924 (14.9%) are
uncategorised**. Judging is per line since grouping was removed (v3.22), so the **line** count is the
job; the analyst queue groups by `subject_key`, so the **subject** count is the clicking. 1,389× the
pilot.

**Client databases change during working hours.** Sydney Adventist's taxonomy was replaced mid-
session, breaking its dashboard view. Fingerprint the source structure and record an as-at on every
run, so "the numbers moved" stays separable from "the ground moved".

## Environment gotchas

- **`Z_Western Health` contains a space.** Bracket it in SQL, quote it in shell.
- **PowerShell's stdin is the null device here.** `python - <<'EOF'` drops into the interactive REPL
  and hangs until timeout. Use the **Bash** tool with a heredoc for inline Python, or write a script
  to the scratchpad and run it.
- Windows, Python 3.13 (Anaconda), ODBC Driver 17, one SQL server for all five databases.
- Client column names differ per hospital and contain spaces and `$`. Always bracket them.
- Views differ structurally: Western has no `Master Category Level` columns and no `RowID`; Sydney
  Adventist has no `ITEM_DESCRIPTION` (uses `INVOICE DESCRIPTION`).

---

## Working with Sameer

- **Interrogate before planning.** Question to ~95% confidence before proposing. When he says
  *"not sure"* or *"I don't know"*, that is a request for a recommendation — decide, state why, and
  move on. Don't hand the question back.
- **Verify rather than ask** whenever the answer is in the data. He has said so directly.
- He reviews written plans carefully and checks for internal contradictions. Self-audit any document
  before saying it's ready.
- Say plainly when something isn't done, is broken, or is provisional.

