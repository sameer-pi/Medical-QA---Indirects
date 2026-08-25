# ACTIONS — what Sameer needs to do

**As at 25 August 2026.** Everything not listed here is on me.

---

## 🔵 WHERE THIS SITS — one decision is the real gate, the rest is mine

### 1. ☑ ~~How hard do you want me to push concurrency?~~ — ANSWERED BY MEASUREMENT, 2026-08-18

**16 workers. Not because it is faster — because above it the jury quietly falls apart.**

```
 12 workers     74 lines/min        0-9 lines lost a model
 16 workers    154 lines/min          2 lines lost a model   <- here
 24 workers    148 lines/min         26
 32 workers    156 lines/min         36
 48 workers    crashed              102
```

Throughput stops improving at 16. What keeps going is the damage: at 24 and above a model gets
throttled, **drops out silently, and the line is decided by two models instead of three** — and
`2of2` in the data looks exactly like agreement. Nothing would have told us. **No NVIDIA arrangement
is needed; more capacity would not help, because 16 is not where the speed limit is.**

```
2,786,018 in-scope lines  ÷  ~50 lines/min end-to-end  ≈  ~40 days
(124/min was measured ONCE; 52 and 46 on the two most recent runs. 15.5 days SUPERSEDED)
```

Down from 53, then 20. ⚠️ **The clean re-run at 16 gave the best agreement we have measured —
54.9% leaf / 78.4% branch.** A 41% score you may have glimpsed mid-test was my own experiment
contaminating the live table, not a regression. `RUN_LOG.md` Finding 95.

### 2. ☑ ~~THE ACTUAL GATE — do we lift PILOT-ONLY and create the production database?~~ — DONE 2026-08-18

**`PI_Medical_QA_Indirect` created 14:57, empty, collation matching the pilot.** Access verified by
measurement rather than taken on trust: `db_ddladmin` + `db_datawriter` + `db_datareader`, **no
`db_owner`**, and a CREATE / INSERT / DROP test that left nothing behind.

### 2a. ☑ ~~DEFERRED — `SET RECOVERY SIMPLE`~~ — 🟢 **WITHDRAWN 2026-08-25. THE ARGUMENT FOR IT WAS WRONG**

This item said, since 2026-08-03: *"under FULL, every insert is kept in the transaction log until a log backup runs — **and no log backup is scheduled** — so the log grows until the volume fills."*

```
no log backup is scheduled     FALSE - one runs nightly at 01:22 on both databases
the log grows until it fills   FALSE - measured on production 2026-08-25:
    log file allocated 12,616.0 MB      USED 146.6 MB      98.8% free
    log_reuse_wait_desc = NOTHING       nothing is holding it open
```

🔑 **FULL with nightly log backups is the SAFER setting, not the worse one** — it gives point-in-time recovery, which SIMPLE does not. The only reason this item existed was log growth, and the log is not growing. **Nothing to do. Do not ask the DBA for it.**

⚠️ **How it survived 22 days on your list:** recovery model = FULL *was* measured; *“therefore the log will fill the disk”* was **inferred and never measured**. That is the project's own standing rule — *measure a risk before raising it* — broken by me. Two corrections had already been bolted onto this item and neither of us thought to check the one number that mattered. `RUN_LOG.md` Finding 126.

<details><summary>The superseded reasoning, kept because it was wrong in an instructive way</summary>

### ~~2a. DEFERRED by you, 2026-08-18 — `SET RECOVERY SIMPLE`~~

**Your call: *"yeah leave it for now, just make a note of it."*** Nothing is blocked. It is needed
before the **load**, not before the schema, and the schema is several steps away.

⚠️ **And I had overstated it — two corrections on the record:**

1. **I said it would "fill the disk and stop the run". I never measured that.** I tried to read the
   free space on that volume and was refused — correctly, `Claude` holds no server-level
   permissions. **So I do not know how much room there is**, and I asserted a consequence I could
   not check. Whoever administers that server can see it in seconds; ask them when you ask about
   backups.
2. 🔑 **`SIMPLE` ON ITS OWN WOULD NOT HAVE SAVED US ANYWAY.** A log record cannot be cleared until
   its transaction commits, **even under SIMPLE**. `build_pilot.py` loads an entire hospital in ONE
   transaction — ~880,000 rows at full scale — so the log must hold all of it either way. The
   actual fix is **committing in batches**, which is already on my list as the paging work. SIMPLE
   *plus* batching keeps the log small; either alone does not.

**What IS measured, and it is why this stays on the list rather than being dropped:**

```
PI_Medical_QA_Indirect_Pilot     data 1,096 MB     log 3,656 MB     <- 3.3x the data
PI_Medical_QA_Indirect           data     8 MB     log     8 MB     <- new, empty
```

The pilot holds 2,000 judged lines and has accumulated a **3.6 GB** log, because under FULL the log
is retained until a log backup runs and none is scheduled. Switching to SIMPLE reclaims almost all
of it. **That is not a prediction — it is what is on the disk today.**

~~ONE LINE STILL OUTSTANDING, and it is yours~~

```
PI_Medical_QA_Indirect         recovery = FULL     <- should be SIMPLE
PI_Medical_QA_Indirect_Pilot   recovery = FULL     <- should be SIMPLE, since 2026-08-03
```

**Both databases are still on FULL recovery.** Under FULL, every insert is kept in the transaction
log until a log backup runs — and no log backup is scheduled — so **the log grows until the volume
fills**. At 2,000 rows that is invisible, which is exactly why it has sat unnoticed since 3 August.
At a 2.77M-row bulk load it is a stopped run and a full disk.

It needs `db_owner`, which `Claude` deliberately does not have. **One line each, as `sa`:**

```sql
ALTER DATABASE PI_Medical_QA_Indirect       SET RECOVERY SIMPLE;
ALTER DATABASE PI_Medical_QA_Indirect_Pilot SET RECOVERY SIMPLE;
```

It does **not** block applying the schema, which I can now do. It blocks the **load**.

</details>

### 3. 🟠 NEW — 37 lines are labelled "Needs evidence" when the evidence is right there. Do you want a seventh action?

**What is happening on those lines:** all three models read the item text, all three agreed the line
is misfiled — and each named a *different* home. The vote needs two of three to agree on a
destination, so the line ends up with none, and the classifier calls it `Needs evidence`.

```
[825887]  WINC  'S BISCS DELTA CRM/BUTTERNUT SNAP CTN150'      you said: biscuits
    model 1  ->  Stationery & Printing
    model 2  ->  Fresh Produce > Vegetables
    model 3  ->  Bakery > Biscuit          <- your answer
```

**`Needs evidence` sends an analyst looking for information that is already on the line.** The item
says *biscuits*. Nothing is missing except a decision about which shelf.

**It is the same mistake we made with `Out of scope`** — the judge did its job and my label
described it badly.

**My recommendation: a seventh value, and the analyst is shown the three candidates to pick from.**
They already exist in the row. That turns a research task into a three-way click.

```
37 lines today  (1.9% of the pilot)   32 of them with all three models agreeing it is WRONG
```

⚠️ **Not built — the action values are yours.** You set the five, and you set the sixth. Say the word
and it is a small change.

### 4. 🟢 Testing moves INTO the app — you called this, and it changes what I build next

Sameer, 2026-08-17: *"testing needs to get done with we need to build it into the app interface."*
The workbook round-trip was the slow part of my two-week estimate and it is the part that should not
exist. **`DEPLOYMENT-CONCEPT (Indirects QA in PIDA).md` is thought-stage and now out of date** — it
predates the answer key, `NIM_ACTION` and `MSD_COHERENCE`. **I have not touched it. Say the word and
I will rewrite it around what the review actually looks like now.**

### 5. ☑ ~~Three taxonomy decisions left over from your answer key~~ — CLOSED 2026-08-18

**Sameer, 2026-08-18: *"lets drop the taxonomy part, im fine with where everything is at the
moment."*** ⚠️ **NOTHING WAS CHANGED — the taxonomy stands at 352 categories exactly as it was**, and
that is because the change was never started: it was held pending his confirmation and the
confirmation was a no. There is nothing to revert.

~~Rename `Food Containers and Utensils` → `Food Containers`~~ · ~~`Stationery & Printing` vs
`General Admin Supplies`~~ · ~~`Printer Cartridges and Toners`~~ — all three struck.

🔑 **KNOWN CONSEQUENCE, recorded so it is not re-discovered as a surprise: the answer-key score is
now capped.** Four of the eight remaining disagreements are the stationery three-way overlap, and
**no prompt change can fix them** — the judge is choosing between three defensible homes. The cap
holds at **56.9% leaf / 80.4% branch**, which is where the current run sits, until the taxonomy
question is reopened. **Do not read that as judge quality.**

⚠️ **Restated 2026-08-18. This said the cap was "near 51% leaf and 76.5% branch"** — written the same
day `PLAN.md` change 284 measured **56.9% / 80.4%**, so this file and the plan of record disagreed
about the ceiling from the hour it was written. The cause is the scorer defect: the cap was estimated
against the pre-fix scorer, which counted every line we got right by leaving it alone as if we had
said nothing. **The ceiling did not move — the measurement of it did.** The same applies to `Cutlery`, which sits beside a leaf still
called `Food Containers and Utensils`.

⚠️ **And a mid-course correction of mine, on the record:** I told him *"7 of 8 disagreements are the
stationery overlap"*. **It is 4 of 8** — I eyeballed it instead of counting. The rest are 2 cleaning,
1 sanitiser, 1 HVAC.

---

## ☑ 0a. ~~THE ONE THING ON YOU — backups~~ — 🟢 **CLOSED 2026-08-25. IT WAS NEVER OPEN**

🔑 **Nightly FULL backups AND nightly LOG backups have been running on both databases the whole time**, to `F:\MSSQLDB_BACKUPS\`. Measured on `msdb.dbo.backupset`, which nobody had ever looked at:

```
PRODUCTION, the real chain (not copy-only)
  FULL  2026-08-25 00:15   4,238.3 MB
  log   2026-08-25 01:23       4.8 MB
  FULL  2026-08-24 00:15   4,237.3 MB
  ...192 backup records, back to at least 2026-07-30
```

⚠️ **I held this over you as "the only real blocker" from 2026-08-18, and this morning told you the single full backup understated the ask and a NIGHTLY job was needed. It was already running.** Nothing was ever required of you here. `RUN_LOG.md` Finding 126.

⚠️ **Two honest residuals, both small:** nobody has ever TESTED a restore — 192 records prove the job runs, not that a file restores — and the retention period on `F:\` is not visible from here, which over ~40 days decides how far back recovery reaches. Worth one question to the DBA; neither blocks starting.

~~It is the only real blocker.~~ ⚠️ **And the 31 August start date is MY estimate, not a deadline** —
there is slack in it. Wednesday or Thursday is possible if the vendor queue lands and this exists.

```
production   2,786,018 lines   ~40 days of compute   no restore point today
```

Everything else on the board is a quality check, not a gate.

**What to ask the DBA for — full after the load, then NIGHTLY. ~25 GB all in.**

⚠️ ~~One full backup after the load, before the run. ~25 GB.~~ **Corrected 2026-08-25 — that was
understated, and this file disagreed with `TRACKER.md`, which had it right.** Production today holds
the **load and zero verdicts**, so a single full backup taken now protects the ~20 minutes it takes
to re-run `build_pilot.py --production`. **That is not what is at risk.** The compute accumulates
*during* the ~40 days: with only a pre-run full, losing the database on day 30 costs **30 days**, not
nothing. **The nightly job is the thing that must be scheduled before stage 6 starts** — the single
full is only its baseline.

**Same conversation, same person: `SET RECOVERY SIMPLE` on both databases** (§ 2a). It needs
`db_owner`, which `Claude` deliberately lacks, so it cannot be done from here.

☑ **No, the PILOT does not need a backup — asked and answered 2026-08-25.** Its one irreplaceable
property is that it *can* be wiped, which is what makes it the test harness. It was destroyed by a
`--dry-run` on 2026-08-20 and rebuilt in **~40 minutes**, and its current mid-run state costs less
than that again: selection is `NIM_VERDICT IS NULL`, so a plain re-run resumes the 635 unjudged
lines. **The backup gate is production only.**

---

## 🔒 0c. WHERE THE RUN HAPPENS — SETTLED 2026-08-25. The office desktop, code by GitHub

Your laptop shuts at end of day. The office desktop is always on. **The judging run lives there.**

```
runs 24 hours a day    ~40 days      the estimate assumes this
runs 8 hours a day     ~120 days     what a laptop that sleeps actually buys
```

⚠️ **It will NOT run faster on that machine, and it is worth knowing now rather than in
October.** The three models run on NVIDIA's hosted endpoint, not on your hardware — we send lines
out and wait. **The desktop's job is UPTIME, not throughput.** 16 workers is where the jury starts
silently dropping models, not where the speed limit is, so more compute buys nothing.

🔴 **NOT DECIDED, AND NOTHING IS PUSHED — this is the first thing to settle tomorrow.** There is **no repo, no remote, no commit**; this folder has never been a git repository. I wrote *"pull the branch"* into three separate hand-offs before checking, and you caught it. Three options, your call:

1. **GitHub private repo** *(my recommendation)* — `gh` is already authenticated as `sameer-pi`, so create-and-push is minutes. The desktop clones to a **non-synced** local path. ⚠️ 18 MB including docs naming all four hospitals and their spend would go to GitHub — **private only**.
2. **The SharePoint library may already sync to that desktop** — zero work if it does, but the run would write into a synced folder for 40 days (OneDrive conflict-copies) and `.env` rides along.
3. **Just copy the folder** — 18 MB, simplest, no history, two copies drift.

⚠️ **Whichever we pick, a git repo must NOT live inside the synced folder** — the sync client can corrupt `.git`.

**✅ Done on my side:** `.gitignore` written. `.env` and `.env.*` are excluded — live SQL
logins and the NIM key must never enter a repository, because a committed secret stays in the
history forever even after the file is deleted.

🔑 **`output/` is deliberately NOT excluded.** The **DECISIONS workbook holds 583 of your
rulings and is the only output file read back as an INPUT**, and `output/Checked/` holds analyst
answers that exist nowhere else. Whole project is 18 MB — there is no size argument for leaving
them out, and losing a ruling because it sat on the other machine is a real and expensive failure.

**☑ Three things do NOT travel with the branch and would stop you on day one:**

```
.env                      copy by hand, once. NEVER through GitHub
pyodbc + ODBC Driver 17   an ML box has CUDA and PyTorch, not a SQL driver. Two-minute fix,
                          but check it BEFORE the run day rather than on it
network to the SQL server you have said the desktop is on the office server and connected
```

⚠️ **The repo must be PRIVATE.** `PLAN.md`, `TRACKER.md` and `RUN_LOG.md` name all four
hospitals and quote their spend.

🔴 **ONE JUDGE AT A TIME.** Both machines reach the same database, and the judge picks up
"lines with no verdict yet" — so two runs at once would grab the same lines and duplicate the
work. **The desktop runs it; the laptop watches it.** You can check progress from anywhere, because
both machines see the same database.

**And don't run it inside the Claude chat window.** Close the window and the job stops — it
resumes with nothing lost, but you lose every hour until someone notices. It gets launched so it
runs on its own. I will set that up.

---

## ☑ 0b. ~~Six borderline items + the Stationery definition~~ — ANSWERED 2026-08-24

```
newspapers            -> NC-0038 Corporate Services > Subscriptions and Memberships
chart recorder paper  -> NEW leaf: Consumables & Disposables > Refrigeration Paper   (13 lines)
clocks                -> General Office Supplies (the EXISTING NC-0083, 87,817 lines)
USB drive             -> NC-0271 Storage & Backup Devices     "yes usb should be under storage"
whiteboard cleaner    -> stays under Stationery & Printing
TAX INVOICE: / PO:    -> the vendor's BROAD category
```

🔒 **`Refrigeration Paper` is IN — the taxonomy is 353 categories.** ⚠️ **`General Office
Supplies` was NOT added: it already existed** and a second one would have been a duplicate in a
different branch. Clocks go to the existing leaf.

⚠️ **The last ruling reverses a standing rule and Sameer chose it knowingly.** *"Broad"* — any line
with no usable description takes the vendor's broad category, rather than going to the analyst as
`Uncertain`. It affects **388,510 lines (14.1%)** and moves `PROMPT_VERSION` **v5 → v6**, so verdicts
either side are not comparable on those lines. Being built 2026-08-25.

---

## 🔄 0. Should the analyst see the GL account? — **ANSWERED TWICE, AND THE SECOND ANSWER REVERSES THE FIRST**

🔒 **NO. Sameer, 2026-08-21: *"no dont show gl to the analyst since that is not a judging factor"*.** That is the ruling in force. `qa_line_view` carries **no `GL_ACCOUNT`, no `GL_ACCOUNT_NAME`, no `COST_CENTRE`, no `COST_CENTRE_DESCRIPTION`**, and the workbook is built from that view.

⚠️ **This item recorded the OPPOSITE from 2026-08-17 until 2026-08-24**, so the plan of record and this file disagreed for three days about what the analyst sees. The earlier ruling is kept below struck through, because the reasoning was correct for the question as it was asked then — it was about **not rewriting GL-based rules**, and it got widened into **showing the GL to a person**.

~~**Yes, the analyst keeps it. Nothing changes in `make_review_workbook.py`.**~~

Sameer, 2026-08-17: *"if the rules are wrttien based on gl for now thats fine, you dont make any
changes to that, the analyst will deal with it later, you dont need to, **all i said is the judge
cant use GL and cost centre as a field to judge**."*

**The scope was explicit and I widened it twice** — once into "GL-based rules are a defect for the
fix queue" (struck from `PLAN.md` change 229 and `JUDGING-RULES` § 2) and once into "strip the GL
from the analyst too". Neither followed from what he said. **The rule governs what the JUDGE may
read. That is all it governs.** The analyst is a person deciding with their name against the
decision, which is not the thing being constrained.

---

> ## ☑ CLEARED TODAY — nothing is blocking me right now
>
> | Was | Outcome |
> |---|---|
> | ~~Four `run_id`s in `qa_line` — a hard rule needs your nod~~ | **Withdrawn, never needed asking.** You said *"can never have more than 2000 rows ... yes we can go with addtional colums but not rows."* The three models' votes went into **columns** on the same 2,000 rows, so there is still exactly one `run_id` and the standing "more than one means stop" rule is untouched |
> | ~~NIM API key setup~~ | Done. Key is in `.env`, never printed or copied |
> | ~~Which models~~ | Done and **re-decided mid-run**: `meta/llama-3.3-70b-instruct` went unhealthy (timed out on a 16-token prompt, twice) and was replaced with `google/gemma-4-31b-it` |
> | ~~Suggestions from the old taxonomies~~ | Done. **427 suggestions made, 0 outside the locked 350** |

---

## ☑ 1. ~~The 35 rows judged on a different footing~~ — RESOLVED by your re-run

You asked for all 2,000 to be run again, which settled it. `8 rows on a superseded model triple → 0`.
The whole file now sits on one jury.

⚠️ **The two-vote rows did not go away — 27 became 37.** A model drops a batch occasionally, and
re-running trades one set for another rather than eliminating them. They are named on the row as
`NIM_AGREEMENT = '2of2'`, which is the right handling: visible in the data, not hidden.

---

## ☐ 1. 🟠 NEW — do you want repeat runs? It is a cost question, and only you can answer it

Running the same 2,000 lines twice showed **the jury contradicts itself on 1 line in 12** (91.5%
self-consistent). That is a property of hosted models, not a bug — temperature 0 is not determinism
when batching and expert routing vary with traffic.

**It matters much less than it sounds, and the reason is measured:**

```
  run-1 agreement    stability on a re-run
  3of3                     98.5%      <- act on these
  2of3                     79.0%
  split                    17.6%      <- a coin toss; never show as a finding
```

And in aggregate it barely registers — **171 lines flipped, the headline moved 0.8 points.**

- **Do nothing** (recommended for now) — quote hospital-level figures, show `NIM_AGREEMENT` beside
  every line-level finding, and never put a `split` row in front of an analyst.
- **Repeat runs** — run the jury three times and take the majority across runs. Would lift line-level
  stability materially. **Triples a 40-minute run**, and at full scale that multiplies a number we
  already know is uncomfortable.

---

## ☐ 2. 🟡 Do you want `Incomplete` counted as Correct or Incorrect in the headline?

The new `NIM_ACTION` column splits the old single "Incorrect" pile into things that mean very
different things. One choice changes a number you may quote:

```
Incomplete = 60 lines   "you never finished categorising this; we filled it in"
```

Counted as Incorrect (current): pilot accuracy ≈ **60%**
Counted as Correct: ≈ **70%** — **without a single line changing**

Either is defensible. It just has to be **a decision on the record**, not a side effect of a label.
My recommendation: **leave it as Incorrect** and report the action split beside it, so a reader sees
the composition rather than a single flattering number.

---

## ☐ 3. 🟢 ~~Two questions~~ **ONE question** for the MSD owner (Monali) — carried, still open

1. **50,511 Sydney Adventist in-scope lines (14.9%) carry no RuleID at all** — is there a third
   categorisation mechanism we have not been told about? (`CBoard Lookup` is a separate 141,593 lines,
   41.7%, and is already understood.) `RUN_LOG.md` Finding 16.

   ⚠️ **Corrected 2026-08-18. This read "131,529 lines carry no RuleID", which is a borrowed number** —
   131,529 is Finding 73's count of SAH in-scope **food** lines categorised by `CBoard Lookup`, 96.1%
   of 136,868. It was attached to a different question, and the item's own parenthesis set `CBoard
   Lookup` aside as separate while the headline figure was made of it. The question is real; the
   number was not its own.

2. 🆕 **AND A SECOND QUESTION FOR MONALI THAT HAS NEVER BEEN ASKED.** **29.4% of Sydney Adventist's
   pilot lines (147 of 500) use categories our copy of `Adventist_Taxonomy` does not contain.** Is the
   loaded taxonomy a *different generation* from the one CBoard writes against? ⚠️ **SAH's accuracy
   figure rests on this** — if the yardstick is not the one in use, the figure measures nothing.
   `PLAN.md` v3.31 change 133, `JUDGING-RULES` § 7.

~~2. Confirm the coherence label in `llm_call_logs` is the field we should read, not the score.~~
**ANSWERED 2026-08-17 BY MEASUREMENT, not by asking — the answer was in the data, so I should not
have queued it as a question.** The label is the field to read, and the score cannot substitute for
it: across the whole MSD, `inconclusive` appears at **0.5 and at 0.25**, and 0.25 sits inside the
incoherent range, so thresholding on `MSD_COHERENCE_CUT` files those vendors as `incoherent`.
`pipeline/msd.py` derives the label from the score and is **confirmed wrong**; the new
`pipeline/msd_coherence.py` reads the latest `llm_call_logs.raw_output` per vendor instead.
`RUN_LOG.md` Finding 90 § 4.

---

## ☐ 4. 🟢 Two completed review workbooks in `output/Checked/` need a name

They cannot be ingested without a `REVIEWED_BY` value — an analyst's answers are not attributable
without one, and the override rate is meaningless if we cannot say who overrode.

---

## ☐ 5. 🟢 `.env` sits in a synced team folder

It holds live credentials and the NIM key. Offered twice to move the loader to an unsynced path;
no answer yet. **Not urgent, not nothing.**

---

## For information — what I am doing next, no input needed

1. **Fix `NIM_BASIS`.** It is meant to record which evidence decided each verdict and it is
   defaulting to `no_evidence` on 1,527 rows, including 1,307 that have a firm verdict AND a usable
   description. The judging is sound; only the label is wrong. **It is excluded from every extract
   until fixed.**
2. **The 181 Incorrect verdicts with no destination** — 33.9% of the 534 `Incorrect` verdicts.

   ⚠️ **Corrected 2026-08-18 by measurement, and it had drifted twice.** This said **302**, which
   matches no run; the "next session" lists in Findings 95 and 96 said **209**, carried forward from
   an earlier generation by recall rather than re-measured. The current generation holds **181**,
   confirmed by two independent counts (`NIM_ACTION='Needs evidence'` split, and
   `NIM_VERDICT='Incorrect' AND NIM_SUGGESTED_KEY IS NULL`).

   ⚠️ **And the diagnosis was overstated.** This said flatly *"that is a judge defect, not a data
   one"*. Finding 96 § 2 shows part of it is **not a judge defect at all** — on those lines all three
   models named a destination and no two agreed, so the consensus key is legitimately NULL. **Measure
   that split before building any mechanism**, or the fix aims at the wrong cause.
3. **Re-measure the four accuracy figures on a spread sample.** The 54-point spread between
   Melbourne and Sydney Adventist is the claim most likely to be an artefact of how the pilot rows
   were drawn. ⚠️ **Nothing client-facing until that is done.**
4. ~~Then the MSD coherence guard, which moves `PROMPT_VERSION` v3 → v4.~~ **Both halves of this are
   now wrong and it is struck.** `PROMPT_VERSION` reached **v4 on 2026-08-17 for a different reason
   entirely** — removing the GL and cost centre from the payload at Sameer's instruction — and is now
   at v4.1. And the MSD is **not a guard**: `MSD_COHERENCE` landed 2026-08-17 as a **flag beside the
   vendor name**, never a judge input, because a verdict resting on vendor coherence is a verdict
   resting on the vendor alone. `PLAN.md` v3.45, `JUDGING-RULES` § 12.
5. ~~**Close the GL leak in `rule.fires_on`**~~ ✅ **DONE 2026-08-17, and it was three leaks not one.**
   `PROMPT_VERSION` v5, all 2,000 lines re-judged. **GL mentions in rationales: 40 → 0**, measured
   across ten patterns. `fires_on` was only one path — adjudication rule I still *instructed* the
   judge to use the GL, and the uncategorised prompt still carried the whole v3 hierarchy, so the
   rule had **never been in force on that pass at all**. **No rule was touched**, per your
   instruction. `RUN_LOG.md` Finding 91, `PLAN.md` v3.46.
6. **Two judge defects remain, and both have now resisted three prompt fixes** — 55 rationales that
   deny a description which is genuinely descriptive, and 209 `Incorrect` verdicts with no
   destination (48.0% → 41.6%). ⚠️ **I am going to stop writing prompt text at these.** The next
   attempt is a mechanism, not a request: a targeted second pass over just those lines, or
   validate-and-retry at the response layer. No input needed from you unless you want it sooner.

7. ✅ **DONE — the 4-line regression is diagnosed.** **One was never a regression**: on a
   `Correct` verdict the scorer compared your answer against an EMPTY field instead of against the
   category the line is already filed under, so **every line we got right by leaving it alone scored
   as if we had said nothing.** Fixed — **56.9% leaf / 80.4% branch**, which is the SAME run counted
   correctly and **not** an improvement. The other 3 are the split-destination lines in item 3 above.
   ~~Read the 4-line regression the scorer keeps printing.~~ `score_answer_key.py` reports **4
   lines you gave a destination for that now carry NO suggestion from us** (3 Northern, 1 SAH). You
   answered them, so they are answerable. It has been printing this and nobody has looked.
8. ✅ **DONE — `NIM_MODELS_RESPONDED` is on every row**, backfilled: 1,989 judged by three
   models, **11 by two — 3 of which read `2of2`, a string that looks exactly like agreement.** It is
   now an invariant checked on every generation, as a rate rather than a zero so it cannot cry wolf.
   ~~Surface a `models_responded` count on every row.~~ The concurrency test found that a model can
   drop out of the jury silently — `2of2` reads exactly like agreement, and nothing distinguishes
   *"two models agreed"* from *"one never answered"*. 11 lines on the current clean run; it was 261
   when pushed too hard. **The data is already in `NIM_1/2/3_VERDICT`; nothing surfaces it.**
9. ✅ **`pipeline/run_generation.py` — a whole generation in one command.** Built 2026-08-18 and it
   drove the clean re-run. It **resumes** by default; clearing a generation is a deliberate
   `--reset`. Settings no longer live only in a log.
