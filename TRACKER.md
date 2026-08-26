# TRACKER — where the Indirects QA programme actually is

> ## AS AT: **2026-08-26** — Findings 102-135 + close, then the monitor discussion. ✅ **RESUME IS NOW CHEAP: the judge skips vendors it has already finished — **2.70 HOURS → 0.41 SECONDS per restart**, measured on production's 29,469 vendors. Sameer asked the deciding question — *"does it add value and increase the accuracy?"* — and the honest answer is **accuracy NO, not at all; time YES, 2.70 h per crash**. 🔒 **Derived from `NIM_VERDICT` on the line, never from a stored flag**, so it cannot go stale; `QUEUE_STATUS` is neither maintained nor filtered on and `schema.sql` now says on the column itself that it is as-at-build. ⚠️ **Finding 134's stated cause was WRONG and is struck — there is no marking step: NOTHING has ever updated that column.** A mechanism inferred from reading a loop rather than measured by asking what writes it; one `grep` settled it. `pipeline/test_resume.py` 17/0. `RUN_LOG.md` Finding 135. 🆕 **A LIVE RUN MONITOR IS ON THE TABLE (Sameer, 2026-08-26) — a read-only local page showing progress, completion and error rate per hospital while the judge runs for 40 days on the office desktop. FEASIBILITY MEASURED AND ANSWERED YES: the whole panel costs ~0.5 s against production's 2,786,018 rows (per-client aggregate 130 ms, best of 3, 2026-08-26), against a job producing ~50 lines/min. 🔴 **AND THE DASHBOARD FOUND A JUDGE DEFECT: `google/gemma-4-31b-it` RETURNS WORDS THAT ARE NOT VERDICTS (`Uncategorised` 81, `categorised` 5) AND `NIM_MODELS_RESPONDED` COUNTS THEM AS VOTES — 86 of 1,801 judged pilot lines (4.78%) are stamped as a FULL JURY while holding only two valid votes.** ✅ The consensus is NOT corrupted — `vote()` discards non-verdicts before the tally — **but the recorded jury health is wrong, and at production scale that is ~133,000 lines.** 🔑 Finding 124/125 one layer deeper: **THE COUNT IS NOT THE COVERAGE.** ⚠️ It also made the monitor's own jury tile understate the very thing it exists to show (0.9% reported against 5.6% true) — **a check built on a column that lies, lies** — and `state_audit.py` still prints the understated figure. **The monitor now counts VALID votes from the votes themselves and needs no judge change.** ✅ **BOTH FIXED THE SAME DAY, Sameer: *"yes, fix both files"*.** `nim_judge.responded()` now counts only valid verdicts — **the first and only change to `nim_judge.py` in this work, made with permission** — and `state_audit.py` now derives `jury<3` from the votes instead of the column that lied. ⚠️ **FORWARD-ONLY: the pilot's 86 rows keep their inflated value unless re-judged; PRODUCTION IS CORRECT FROM ITS FIRST LINE, which is why the timing mattered.** 🔑 And fixing it exposed a third thing — the old advice *"check --workers"* was now wrong for **76% of the number**, because a non-verdict is a model/prompt problem that concurrency cannot touch. The two causes are now counted and named separately (27 silent · 86 non-verdict). ⚠️ **`0.8% OK` → `5.7% ABOVE 1%` IS NOT A REGRESSION** — the number was always 5.7%, only 0.8% of it was visible. Do not read older `OK` lines as evidence the jury was healthier then. `RUN_LOG.md` Finding 131 + addendum. 🟢 **Two visuals added: (1) the grader-disagreement panel — ⚠️ explicitly NOT an accuracy table, because `REVIEW_OVERRIDE_VERDICT` / `REVIEW_STATUS` / `REVIEWED_AT` are populated on ZERO rows and the answer key is orphaned, so THERE IS NO GROUND TRUTH; it shows instead that the three models are **2.4× apart on how often they call a line Incorrect (21.4% vs 50.5%)**, so the headline error rate depends substantially on which two of three agree — and (2) lines-judged-per-hour over 48 hours with **every hour drawn including idle ones**, after the first version closed a 20-hour gap and made an outage invisible.** ✅ **SUPERVISOR BUILT — `pipeline/supervise.py`, four interlocks against ever running two judges, each proven by making it fire, all failing CLOSED.** ⚠️ Restarts cost ~1.5-2 h of queue re-walking on production; still far cheaper than an overnight idle. 🟢 **DASHBOARD REDESIGNED for legibility (Sameer: *"the viewer wont know exactly what to look at"*) — one hero row, a colour key meaning green/amber/red only, value-first tiles, zebra tables, and all the prose folded into the footer. 🔒 No guard was dropped to tidy up: banner still permanent and first, every rate still prints its denominator, still no export button.** 🔴 **And redesigning it found TWO defects that text had been hiding: "signed spend covered 100.4%" (a share of a SIGNED total is meaningless — the unjudged lines were net negative), and 500 judged lines rendering as NOTHING because their `NIM_ACTION` was unclassified, which is the normal state of a run in progress.** Both fixed; the breakdown now reconciles or says so in red. `RUN_LOG.md` Finding 134. 🔴 **AND THEN THE JUDGE CRASHED FOR REAL AND THE MONITOR CAUGHT IT.** 2026-08-26, unplanned: the pilot judge ran 2 hours and died at 1,977/2,000 on a dropped TCP connection (`08S01 / 10054`). **`nim_judge.py` holds ONE database connection for the whole run and has no reconnect** — the retry ladder that exists is for the MODEL calls, which is why hours of throttling never killed a run and made this look robust. **~2 hours to first failure against a ~40-day run.** Nothing was lost (resume is `NIM_VERDICT IS NULL`); the cost is the hours before anyone notices. 🔑 **The monitor read `JUDGE MAY BE DOWN` within minutes, with nothing staged — a stalled run and a finished one both stop moving, and it told them apart.** ⚠️ **The email did NOT send — the app password is not in yet, which is now an argument in evidence rather than in theory.** 🔴 **AND THE CRASH REPORTED EXIT CODE 0**, because the launch piped through `tail`. **A supervisor is recommended and NOT BUILT.** `RUN_LOG.md` Finding 133. 🟢 **BUILT AND THEN RUN AGAINST A LIVE JUDGE THE SAME DAY — and watching a MOVING judge found TWO defects that a static table never could. (1) lines/min displayed ZERO while the judge was visibly working (22 lines in 4 minutes is 5.5/min): it divided by the nominal window rather than the span the data covers, and rounding finished the job — on the real run that reads ZERO for the entire first hour, exactly when someone is watching hardest. (2) it claimed "running 2.0 days" four minutes in. BOTH FIXED, 7 regression cases added, 44 checks 0 failed.** ✅ Progress, stall True→False on resume, the full/heartbeat refresh cadence, jury health (it caught a new thin line 14 → 15), prompt version, run_id and the *judging now* vendor tile all correct against 1,413 → 1,545 live rows. 🔑 **The monitor was killed and restarted mid-run and the judge never noticed — the separation proven, not claimed.** 🟢 **BUILT THE SAME DAY — `pipeline/monitor.py` + `pipeline/test_monitor.py` (37 checks, 0 failed), read-only on `127.0.0.1:8000`, proven end-to-end over HTTP against the pilot.** Sameer settled it: localhost on the office desktop, red page **and** an email on a stall. 🔴 **AND BUILDING IT CORRECTED A FIGURE I HAD GIVEN HIM — the panel is NOT ~0.5 s. Warm it is 22-145 ms; COLD it was measured at 47.6 s on a 4,214 MB table, and the nightly 00:15 backup evicts the cache every night. The ~0.5 s was a warm number quoted without its conditions — this project's own standing error, committed in the document that warns about it.** Rebuilt to survive a slow read rather than assume a fast one. 🟠 Outstanding: SMTP settings in `.env`, and it has **never watched a moving judge**. `APP.md` holds all of it. ✅ **AND IT ALREADY FOUND AND CLOSED A GAP THE SAME DAY: `qa_line_view` carries the judged columns automatically as they fill (proven — table and view identical, `sys.indexes` on the view = 0, so it is a window and not a copy) BUT IT WAS A SUBSET AND COULD SAY *WHAT* WAS JUDGED AND NEVER *WHEN*.** 🔒 **FIXED 2026-08-26 on Sameer's instruction — `NIM_JUDGED_AT` + `NIM_PROMPT_VERSION` added, 36 → 38 columns, applied from `schema.sql` to BOTH databases, `qa_line_view` = `qa_line` delta ZERO on both (2,000 and 2,786,018), 1,413 pilot timestamps proven to flow through the view and MATCH the table, parity re-proven 38 = 38, guards 20/0, classify 15/0.** ⚠️ They were an **omission, not a decision** — absent from the view's own "deliberately absent" list as well as from the SELECT. Found by measuring the view's columns against the table's, not by reading either. 🔒 It is NOT a reversal of the "no app" ruling: stages 7-app and 4b stay DEAD. This writes nothing, has no analyst in it, is not a deliverable, and is thrown away when the run ends.** 🟢 **STAGE 3 IS DONE — the run order exists and the judge consumes it, a vendor at a time. `--top 100` is the stop-and-look slice. 🔒 **AND THE ORDER IS NOW GLOBAL BY DEFAULT** — largest supplier anywhere first, irrespective of hospital. 🟢 **COVERAGE CHECK BUILT AND PROVEN (F124/125): a model can return the RIGHT NUMBER of verdicts and still leave lines with two votes — the old check counted answers, the new one compares the ID SET SENT against the ID SET RETURNED. `pipeline/test_coverage.py` reproduces the real failure deliberately: 5 groups, 22 checks, 0 failed. `--topup` repaired the pilot 22 → 14 and is now PROVEN on a real failure.** 🟢 **CLEARED TO START JUDGING — the backup gate was NEVER OPEN: nightly full + log backups have run the whole time (F126), and the `SET RECOVERY SIMPLE` ask is WITHDRAWN because its premise was false.** 🔒 THE JUDGING RUN MOVES TO THE OFFICE DESKTOP (Sameer, 2026-08-25) — always on. ✅ **REPO LIVE 2026-08-26: `github.com/sameer-pi/Medical-QA---Indirects`, PRIVATE (verified), main, 79 files. `.env` confirmed ABSENT from the remote. Desktop clones to a NON-SYNCED path and `.env` is copied by hand.** 🟢 **STAGE A2 CLOSED BY MEASUREMENT: NEITHER a shortlist bug NOR a taxonomy gap — both leaves exist and always did. `Cleaning and janitorial supplies` (merged, 168,888 lines) and `Stationery & Printing` at its NEW ruled path (merged, 185,109 lines), present in the merged set AND in all four hospitals' own taxonomies. The last engineering gate before the run is now stage 3 alone.** 🔒 **PROMPT v7 + the first category DEFINITION — the stationery contamination went 9 → 0 on Melbourne.** 🔒 **PROMPT v6 — Sameer's BROAD ruling is in force on BOTH passes, verified on the emitted text.** 🔓 **TAXONOMY IS 353 CATEGORIES — BASELINE 3 is a CANDIDATE, NOT LOCKED** (an unexplained +2,210 in the line totals, gates board). 🔒 **Taxonomy BASELINE 2 locked. Judging is ~40 days, not 15.5.** 🟢 **Jury dropout FIXED and the pilot repaired 141 → 0. The judge can now be pointed at production, and `--all` finally means all. ONE VIEW EXISTS: `[PI_Medical_QA_Indirect].[dbo].[qa_line_view]`.** 🟢 **PRODUCTION IS LOADED: 2,786,018 lines, all four
> hospitals, zero clinical.** The review lifecycle is locked. **The load no longer gates the run — the
> ORDERING does.**
>
> **This file is the ONLY place the project's position is recorded.** `PLAN.md` holds the reasoning,
> `RUN_LOG.md` the record of what happened, `ACTIONS.md` what Sameer is unblocking, and this file
> where we are. A second copy of the status is a second thing that goes stale — which is exactly what
> happened to `PLAN.md`'s old status section: a **correctly dated** 2026-08-03 snapshot with no way to
> refresh itself, sitting in a 291KB document nobody opens to check where the project is. ⚠️ **It was
> STALE, not wrong** — an earlier version of this file said "wrong for 15 days" and that was an
> overstatement Sameer corrected. `RUN_LOG.md` Finding 97 addendum, `PLAN.md` v3.52.
>
> 🔒 **STALENESS RULE. If the AS AT date above is older than the last entry in `RUN_LOG.md`, this file
> is stale and is not to be trusted.** Updating it joins the end-of-session ritual beside `RUN_LOG.md`.
> The measured block below is copied from `python pipeline/state_audit.py` — **never typed from
> memory, and never carried forward from the previous version of this file.**

---

## In one line

**Stages 0, 1 and 4a are complete, and stage 2 is under way (3 of 7).** `PI_Medical_QA_Indirect` exists, holds the four tables, and is **proven identical to the pilot**. It has no rows in it yet. The next piece of work needs nothing from anyone. The judge works, it has been measured against a human, and it runs from
one command — on **2,000 pilot lines**. Everything from here is scale, and the next real decision is
Sameer's: create the production database.

---

## Measured state — `python pipeline/state_audit.py` + direct measurement, 2026-08-24

```
PILOT       PI_Medical_QA_Indirect_Pilot
  qa_line     84 cols     2,000 rows    ONE run_id (pilot-20260820T141149)
  qa_category 19 cols     7,187 rows    <- was 7,186 on 08-24; +1 is Refrigeration Paper
                                          landing in the PILOT too. Benign, measured 08-25
  qa_rule     31 cols       360 rows    <- 360 not 352: the 08-20 rebuild drew a different sample
  qa_run      17 cols         4 rows       and touched 8 more rules. Explained, benign (F116 §8)
  qa_line_view            38 cols   <- was 36; +NIM_JUDGED_AT +NIM_PROMPT_VERSION, 2026-08-26

  JUDGING - measured at close 2026-08-26 by `python pipeline/state_audit.py`
    client                 lines  unjudged  Correct  Incorrect  Uncertain   jury<3
    melbourne_health         500         0      120        221        159       47
    northern_health          500         0      152        208        140       51
    sydney_adventist         500         0      199        129        172        5
    western_health           500         0      127        180        193       15
    TOTAL                  2,000         0                                     118

  ** THE PILOT IS FULLY JUDGED - 2,000 of 2,000, run to completion under pipeline/supervise.py
     in one attempt, 0.3 hours, exit 0 (redirected, NOT piped - so the code is trustworthy). **

  jury health  118 of 2,000 have fewer than 3 VALID votes (5.9%)  ** ABOVE 1% **
                 32 a model NEVER ANSWERED         -> throttling, check --workers
                 86 a model returned a NON-VERDICT -> --workers will NOT help
               ⚠ THIS IS NOT A REGRESSION. The old figure read "0.8% OK" because it counted
                 NIM_MODELS_RESPONDED, which counts a non-verdict as a vote. The number was
                 always ~5.9%; only 0.8% of it was visible. Finding 131.
               ⚠ google/gemma-4-31b-it returns 'Uncategorised' (81) and 'categorised' (5).
                 nim_judge.responded() is FIXED but FORWARD-ONLY: these 86 rows keep the old
                 stored value unless re-judged. PRODUCTION is correct from its first line.

  NIM_ACTION   (none) on all 2,000 - action_classify.py has not been run on this generation.
               Expected, not a fault: it runs AFTER judging.

  PROMPT_VERSION v7 on every judged row. One run_id.

  ~~JUDGING - the live jury, AFTER the 2026-08-24 top-up~~ SUPERSEDED TWICE: that snapshot read
  108/255/137 for Melbourne under v5, then a mid-run state on 08-25. Struck rather than deleted -
  the figures either side of a PROMPT_VERSION change are not comparable, and pretending the table
  had always said this would hide that.

PRODUCTION  PI_Medical_QA_Indirect
  qa_line     84 cols  2,786,018 rows   ONE run_id (prod-20260821T090819)
  qa_rule     31 cols      4,211 · qa_category 19 cols 7,187 · qa_run 17 cols 4
  merged taxonomy         353 categories (was 352; + Refrigeration Paper)
                          1 of 353 carries a DEFINITION (Stationery & Printing) - the
                          other 352 are still blank
                          loaded and verified in BOTH databases 2026-08-24
  qa_line_view            38 cols  2,786,018 rows   == qa_line, delta zero
                          <- was 36. +NIM_JUDGED_AT +NIM_PROMPT_VERSION 2026-08-26,
                             applied from schema.sql to BOTH databases, parity re-proven
  judged 0 · reviewed 0            NOTHING HAS BEEN JUDGED ON THE REAL DATA YET
  schema parity vs the pilot: IDENTICAL - 5 objects, 7 indexes/keys
  recovery model: FULL   ** CORRECT AS IS ** - nightly log backup at 01:22 truncates it;
                         log 12,616 MB allocated / 146.6 MB used (98.8% free), 2026-08-25

  client                     lines   vendors   subjects      signed spend     uncat
  melbourne_health         893,173    11,930    342,112     1,469,113,957   115,483
  northern_health          875,018     3,548    298,541     2,971,111,364   218,860
  sydney_adventist         346,627     3,768     75,260       434,565,132    56,042
  western_health           671,200    10,221    245,970       994,709,442    24,601

CHECKS, at session close 2026-08-24
  test_coverage.py        5 groups, 22 checks, 0 failed   NEW 2026-08-25
  test_guards.py          20 passed, 0 failed
  test_classify.py        15 cases, 0 failures
  verify_schema_parity    PRODUCTION MATCHES THE PILOT (via apply_schema.py --production)
  invariants              rows/run_id/verdict/action/destinations/jury  ALL OK
  GL mentions             1  ** CLEAN ** - one line's ITEM DESCRIPTION literally reads
                             'COST CENTRE'; the judge quoted the item text. F116 §8
  score_answer_key.py     ** FAILED ** - "no reviewed lines". The key was orphaned by the
                             08-20 rebuild. NO ACCURACY FIGURE EXISTS. Gate below
  output/Taxonomy/ 5 files (restored by hand - --emit reached NINE across three emits)
  output/logs/     1 file (new 2026-08-24)
```

⚠️ **`qa_line_view` returns 2,786,018 rows with EMPTY verdict columns.** That is expected, not a
fault — the judging run has not started.

---

## The stage board

🔒 **RE-CUT 2026-08-21. This is a ONE-OFF ENGAGEMENT, not a monthly product, and no app is
being built.** Sameer: *"this wont be an iterrative process, so we wont be doing it monthly, we take
what we have, review it judge it and give recommendations for which are wrong ... we wont be building
an app for this."* Stages struck through below are **dead, not deferred** — the reasoning is kept
because it was correct for the product we thought we were building, and deleting it would hide why
the work existed.

| # | Stage | What it delivers | Status | Effort | Gated by |
|---|---|---|---|---|---|
| **0** | **Pilot & judge proving** | Schema v2 · taxonomy merge · 3-model jury · blind answer key · `run_generation.py` · the 16-worker ceiling | ✅ **DONE** | — | — |
| **1** | **Document truth-up** | `PLAN.md` current, contradictions reconciled, `TRACKER.md` created | ✅ **DONE** | — | — |
| **2** | **Production readiness** | Schema 84 = 84 · allowlist guard · census path · count checks · **the delete guard, proven to fire** · **2026-08-24: `--production` on the judge/classifier/MSD, `--all` uncapped, the hardcoded 2,000s replaced by a `qa_run` measurement** | ✅ **DONE** | — | — |
| **2b** | 🔴 ~~**Marked DONE on 2026-08-21 while HALF OF IT WAS NOT**~~ | **`--all` on the JUDGE still meant the first 100,000 lines — 11% of Melbourne, reported as `ok`** — the identical defect was fixed in the LOADER on 08-18 and nobody asked which other file capped a population. **Fixed 2026-08-24.** ⚠️ **`fetchall()` paging is STILL not done** and removing the cap exposed it: 616 B/unit × 893,173 = ~0.51 GB of JSON. **The queue (stage 3) bounds it — do not build generic paging** | ✅ cap fixed · ⬜ paging → stage 3 | — | — |
| **5** | **Production load** | ✅ **DONE 2026-08-21.** `prod-20260821T090819` — **2,786,018 lines in ~20 min**, reconciled **three independent ways** per client. **0 clinical.** 4,211 rules, taxonomy loaded. 4,222 MB data / 8,217 MB log | ✅ **DONE** | ~20 min *(measured)* | — |
| **3** | **The queue: vendor spend ordering** | ✅ **DONE 2026-08-25.** `qa_vendor_queue` in both databases · `vendor_queue.py` — **29,469 vendors ranked on production in 3.4s**, lines **2,786,018 = 2,786,018**, spend delta **$0.0002** · `nim_judge.py --queue [--top N]` judges a client **one vendor at a time in spend order, BOTH passes per vendor** · 🔑 **conservation proven: vendor-by-vendor = whole-client = qa_line, 500 = 500 = 500** · ✅ live end-to-end on the pilot, resume verified (skipped 4 done vendors, judged 2) · 🔑 **top 100 vendors = 68–93% of signed spend** — that is `--top 100`, the stop-and-look slice · ✅ **the `fetchall()` memory defect is CLOSED by design** — per-vendor selection is a few MB against ~0.51 GB per client, so no generic paging was needed · **no index needed: 0.25s per vendor measured, ~2h across the whole 40-day run** | ✅ **DONE** | — | — · 🔒 **GLOBAL ORDER ADDED 2026-08-25 (Sameer): `--queue` with NO `--client` judges all four hospitals in ONE spend order, largest supplier anywhere first.** `GLOBAL_RANK` 1..29,469, no gaps. Both orders kept — per-client is `--queue --client <key>`. ⚠️ **A global order under-serves the SMALLEST hospital early**: global top 100 = northern 86.2% of its spend but SAH 32.7%; even by top 500 (all ≥61.9%). Matters only if the run stops early | ✅ **DONE** | — | — |
| **A** | ✅ **Answer key repaired — and the score it produced was wrong AGAINST us** | ✅ `CHECK_ID` is now `unit_key`, not the identity column · ✅ answer codes **OK/A/B → RIGHT/WRONG** · 🔑 **the blind score is 75.6%, and 77.3% with Sameer's own USB correction — ~~55.6%~~ was THREE faults in my string handling, none in the judge** (substring match beaten by the word *and*; his typo `carbonmated`; the report truncating our path at 72 chars). ~~the 44.4% miss is a PATTERN — we land on a vaguer node one level up, e.g. stationery → `General Admin Supplies > General Admin Supplies`, a padded dead-end~~ — **struck 2026-08-25: half was the matcher, the other half a real taxonomy overlap Sameer RULED on the same day (v3.64 change 362), moving 185,096 lines** | ✅ **DONE 2026-08-21, corrected 2026-08-25** | — | — |
| **A2** | ☑ ~~**Is it a shortlist bug or a taxonomy gap?**~~ | 🟢 **CLOSED 2026-08-25 BY MEASUREMENT — IT IS NEITHER.** Both leaves exist in the merged set the judge picks from **and** in every hospital's own taxonomy: `Cleaning and janitorial supplies` merged **168,888 lines** (MEL 67,499 · NH 28,928 · SAH 806 · WH 71,655) and `Stationery & Printing` merged **185,109 lines** at the ruled path `Non-Clinical > Corporate Services > General Admin Supplies > Stationery & Printing`. 🔑 **The padded dead-end is GONE — no leaf named `General Admin Supplies` exists anywhere in either database.** The premise was retired twice over: the cleaning half was my matcher (6 rows), the stationery half was the overlap Sameer ruled on. ⚠️ **The question survived on this board for four days after the answer landed**, because the row was never revisited when v3.64 corrected the score it rested on | ✅ **DONE** | — | — |
| **6** | **The judging run** | Every in-scope line judged, in vendor-spend order. **Stop after the top slice and look, before committing the rest** | ⬜ Not started | **~40 d** *(38–42, measured 3×)* | Stages 3, A |
| **6m** | 🟢 **The live run monitor — BUILT 2026-08-26. READ-ONLY, and NOT the app that was killed** | **`pipeline/monitor.py`** — one page on `http://127.0.0.1:8000`, refreshes itself, writes nothing. Run health (last verdict written · lines/min over 15 and 60 min · **jury health, `NIM_MODELS_RESPONDED < 3`, visible on day 1 instead of day 39** · prompt version · run_id · vendor being judged now), progress and **signed** spend covered per hospital, ETA with the rate it rests on, error rate as `Incorrect ÷ (Correct + Incorrect)` with **Uncertain excluded from both sides**, the six `NIM_ACTION` values, and top vendors + rules **by line count, never by spend**. ✅ **PROVEN end-to-end over real HTTP against the pilot's 1,413 judged rows**; `pipeline/test_monitor.py` **37 checks, 0 failed**, proving the read-only guard REFUSES writes — including the three that BEGIN with `SELECT` and still write — and that all 11 of the file's own queries pass it. 🔴 **AND IT CORRECTED A FIGURE I HAD GIVEN SAMEER: the cost is NOT ~0.5 s. It is 22 ms warm and was measured at 47.6 s cold on a 4,214 MB table — the variance is the finding, and the nightly 00:15 backup evicts the cache every night.** Rebuilt to survive a slow read: background thread, one refresh at a time, the page prints how long the last refresh took, STALE state when unreachable, timeout 60 s → 180 s. 🔒 **No index was added** — that would be a schema change to production to serve a watcher (decision 8). 🔒 Sameer 2026-08-26: **localhost on the office desktop** (all have access) — there is deliberately no `--host` flag — and **red page AND an email** when it stalls | 🟢 **BUILT** — `APP.md` | — | 🟠 **Email needs SMTP settings in `.env`** (`ACTIONS.md`); until then the page reddens and nothing sends. 🔴 **Never yet watched a MOVING judge** — production has judged 0, so every number there is a zero; the first real test is the first hour of the run. **Does NOT gate stage 6** |
| **7** | **Deliver to the analyst — WORKBOOKS, not an app** | `make_review_workbook.py` at full scale. ⚠️ **Measured 2026-08-21 on the loaded data: 961,883 subjects (91.7%) and 1,016,303 units (96.9%) against Excel's 1,048,576-row ceiling.** Fine per hospital, impossible as one file | ⬜ Not started | ~1 d + scale test | Stage 6 |
| **8** | **Rule-fix recommendations** | The deliverable. 🔴 **A fix is still never simulated before it is handed over** | ⬜ Not started | Not estimated | Stages 6, 7 |
| ~~**3b**~~ | ~~**Incremental carry-forward**~~ | ~~Monthly memory: carry verdicts and reviews forward on `unit_key`, re-judge what changed~~ **DEAD 2026-08-21 — one-off, nothing to carry forward to.** The `unit_key`/`subject_key` design that made it possible stays; it costs nothing and is already built | ⬛ **DEAD** | — | — |
| ~~**4a/4b**~~ | ~~**Manager dashboard into PIDA**~~ | `pipeline/dashboard.py` **exists and still works as a standalone HTML report** — keep it. ~~The PIDA page~~ **DEAD — no app** | 🟡 **HTML kept, app port DEAD** | — | — |
| ~~**7-app**~~ | ~~**Analyst review inside PIDA**~~ | ~~Queue, review view, override write-back, review history, spend-weighted spot-checks~~ **ALL DEAD — no app, and no second pass to quality-control** | ⬛ **DEAD** | — | — |

### ⚠️ What got HARDER, not easier — the three things the scope change costs us

1. 🔴 **THERE IS NO SECOND CHANCE, AND THE SELF-CORRECTING SAFETY NET IS GONE.** `PLAN.md` v3.60
   change 338 was elegant: an analyst who approved correctly but **wrote the rule wrong** was caught
   automatically by next month's data. **There is no next month.** A mis-written rule is now never
   found — not by us, not by them, not by the client. **Everything we hand over is final on the day
   we hand it over.**
2. 🔴 **DATA STALENESS IS NOW PERMANENT.** Northern's data stops at **2026-05, roughly three
   months back**; Western 2026-06, Melbourne 2026-07. Under a monthly model that was annoying and
   self-correcting. As a one-off we would hand the client a report that is **three months old,
   forever.** This moved from *"worth asking"* to **ask before judging.**
3. 🔴 **THE ANSWER KEY MATTERS MORE, NOT LESS.** It is the only outside check that our judge is
   any good — everything else is the judge marking its own homework. With no second pass it is the
   **only** chance to find a systematic bias cheaply, and it must work **before** a 15-37 day run,
   not after. It is on the board above as stage **A**.

### What the status marks mean

✅ done and verified · 🔵 in progress · ⬜ not started · ⏸ parked on someone else · 🔴 blocked

---

## Estimates — what is measured and what is not

**Measured, quotable:** stage 6's duration. 124 lines/min end-to-end across the whole pilot generation
(every pass's startup included), so 2,767,046 lines ≈ **15.5 days of continuous judging** at 16 workers
on the NVIDIA free tier. ⚠️ **Do not quote 154 lines/min** — that was Melbourne's per-client rate and
the full-run average is lower.

**Estimates, mine, not validated:** stages 1, 2, 3 and 4. Working days of engineering, not calendar.

⚠️ **Stage 5 is genuinely unknown.** The pilot loads 2,000 rows. A full-population extract has never
been timed, and the scope scan alone takes minutes per client. **Measure it on ONE client before
quoting a number for four.**

**Not estimated at all:** stages 7 and 8. Stage 7 depends on a build in another codebase; stage 8 has
no design yet.

---

## Sequencing

```
  1 --> 2 --> 5 --> 6                    <-- the critical path
        3  (alongside 2)
        4a progress readout (any time)
        4b view + prototype (after the snips)

        6 runs unattended for two weeks
          -> 4b, 7 and 8 should be underway WHILE it runs
```

**Stage 6 is a fortnight of a machine working and nobody watching it.** If stages 4b, 7 and 8 are not
running in parallel, the calendar is a fortnight of waiting for no reason.

## Indicative calendar — **estimates. Both remaining gates are Sameer's**

| When | What | Status |
|---|---|---|
| Mon 24 Aug | Jury dropout fixed (141 → 0) · production plumbing · `qa_line_view` · **taxonomy 352 → 353** | ✅ **DONE** |
| Wed 26 – Thu 27 Aug | **Stage 3 — the vendor spend queue.** Also what bounds the judge's memory | ⬜ |
| Fri 28 Aug | **Answer key re-attached and re-scored** · dry run on a small production slice | ⬜ |
| **Mon 31 Aug** | **Stage 6 STARTS** — top slice first, then **STOP and look** before committing the rest | ⬜ |
| ~early-mid Oct | Stage 6 completes at ~40 days (38–42) | ⬜ |

⚠️ **~40 days assumes the free NVIDIA endpoint runs at the ~50 lines/min measured twice.** It ran at
124 once and at 46 on another day. **The fixes mean a slow spell now costs TIME rather than
QUALITY** — which is the whole point of the `--topup` work.

🔴 **Two things can move this date and both are Sameer's:** the `Stationery & Printing` exclusion
definition, and **one backup before the run starts.**

---

## Gates — who holds what

| Gate | Holder | Open since | Blocks |
|---|---|---|---|
| 🔴 **THE JUDGE DIES ON A DROPPED DATABASE CONNECTION AND HAS NO RECONNECT — MEASURED, NOT FEARED.** 2026-08-26 the pilot judge ran 2 hours and stopped at 1,977/2,000 with `08S01 / 10054 — an existing connection was forcibly closed by the remote host`. `nim_judge.py:773` opens **ONE** connection in `main()` for the entire run: no reconnect, no `OperationalError` handler, no database-side retry anywhere in the file. **The retry ladder that does exist is for the MODEL HTTP calls, which is why hours of throttling never killed a run and made this look robust.** ✅ Nothing is lost — selection is `NIM_VERDICT IS NULL`, so a re-run resumes — **the cost is the hours between the crash and someone noticing.** ⚠️ **Measured mean time to first failure: ~2 hours, on a quiet afternoon, on the same LAN. The production run is ~40 days.** ✅ **BUILT 2026-08-26 — `pipeline/supervise.py`.** Restarts the judge until the queue is empty, and **four interlocks stop it ever running two**, each proven by making it fire: a judge already alive → refuse (exit 1) · a second supervisor → refuse (exit 1) · a stale lock → take over · **the process query failing → REFUSE, never assume the coast is clear.** Interlock 2 re-runs before *every* launch, so a hand-started judge is caught too. Barren-attempt guard counts attempts that judged ZERO lines, not attempts that failed. Never pipes the child. ~~⚠️ **RESTARTS ARE NOT FREE: `judge_queue` walks every vendor and costs two queries even for one with nothing left — measured 643 vendors ≈ 30 min on the pilot, so ~1.5-2 HOURS of re-walking per restart on production's 29,469.**~~ ✅ **FIXED 2026-08-26 — AND THE REAL FIGURE WAS 2.70 HOURS, not 1.5-2: measured on production, 0.18 s per probe × 2 probes × 29,469 vendors.** `nim_judge.vendors_with_work()` now asks `qa_line` **once** which vendors still have work — **0.41 s for all 29,469, measured twice.** Sameer: *"yeah for it, if it saves time if the judge happens to crash"*, after asking the right question first — *"does it add value and increase the accuracy?"* **Accuracy: no, none. Time: 2.70 h per restart.** 🔴 **AND `QUEUE_STATUS` IS UNRELIABLE, found 2026-08-26 — the pilot read `western_health 6/185` beside `100% judged`.** ~~`judge_queue` skips a vendor with nothing left to judge BEFORE marking it done~~ ⛔ **that stated cause was WRONG — corrected in Finding 135. `nim_judge.py` does not contain the string `QUEUE_STATUS` at all; `vendor_queue.py` derives it ONCE at build time and NOTHING has ever updated it.** A photograph, not a gauge. ✅ **BOTH `QUEUE_STATUS` decisions are now SETTLED, and neither was taken:** the judge does not maintain it and does not filter on it. **Progress is DERIVED from `NIM_VERDICT` on the line, which cannot go stale** — a stored flag would still be wrong after a crash mid-vendor and would be a second definition of "done" free to disagree with the lines. 🔒 **The skip matches `emit_batch`'s TWO work-finding arms, not one** — `--topup` finds thin juries that carry a verdict, proven on the pilot: normal resume 0 vendors, `--topup` **18**. 🔒 **Fails closed three ways** (scan errors · a name the scan never saw · `--topup`), and is applied **after** `--top` so the stop-and-look slice keeps its meaning. `pipeline/test_resume.py` 17/0. `RUN_LOG.md` Findings 133 + 135 | — | **2026-08-26** | ✅ **CLOSED — but `supervise-*.log` must still tell us how OFTEN it crashes (n=1)** |
| 🔴 **A PIPED LAUNCH REPORTS SUCCESS ON A CRASH.** The run above was launched as `python pipeline/nim_judge.py --queue 2>&1 \| tail -60` and the harness recorded **exit code 0** on an unhandled exception — in a shell pipeline the exit status is the LAST command's, and `tail` succeeded. Proven directly: `python -c "raise SystemExit('boom')" \| tail -5` exits 0. 🔒 **This is the project's worst failure mode — the one that looks like success — and it is now on the runbook path.** `nim_judge` is blameless; **the launch command is the defect.** ⚠️ **Tomorrow: redirect to a file (`> run.log 2>&1`), NEVER pipe through `tail`/`head`/`tee`.** | Me | **2026-08-26** | Nothing, once the launch line is right |
| 🟠 **ONE VALUE LEFT for the stall email: `MONITOR_SMTP_PASS`.** The block is in `.env` as of 2026-08-26 and **five of six keys are filled**; the password needs an **app password** because Microsoft disabled basic SMTP auth by default in 2022, so only Sameer (or IT enabling `SMTP AUTH` on that mailbox) can supply it. 🔑 **The SMTP host was VERIFIED BY MX LOOKUP, not assumed** — `p-i.com.au` → `pi-com-au0c.mail.protection.outlook.com`, SPF includes `spf.protection.outlook.com`, so M365 and `smtp.office365.com:587`. 🔴 **And filling the other five exposed that `mail_config()` would have reported `armed` with a blank password** — it never checked it. Fixed: the monitor now prints `** NOT ARMED **` and the reason. 🔴 **Separately, `.env.example` was missing ALL FOUR keys the live jury runs on** (`NIM_API_KEY` / `NIM_BASE_URL` / `NIM_MODEL` / `NIM_MODELS`) and carried only the superseded single-model block — a new machine built from it would look complete and be unable to judge. Added. `preflight.py` would have caught it loudly, which is the only reason the blast radius was small. `RUN_LOG.md` Finding 132 | Sameer | **2026-08-26** | **Nothing.** The judge never reads these keys and the page reddens without them |
| ☑ ~~**ONE BACKUP — THE ONLY REAL BLOCKER**~~ | — | 🟢 **CLOSED 2026-08-25 — IT WAS NEVER OPEN.** `msdb.dbo.backupset` measured for the first time: **nightly FULL at 00:15 AND nightly LOG backup at 01:22, both databases, to `F:\MSSQLDB_BACKUPS\`, 192 records back to at least 2026-07-30.** Production's latest full is 4,238.3 MB, 2026-08-25 00:15. ⚠️ **Held over Sameer as the only blocker since 2026-08-18 and never checked.** Residuals, both small and neither a gate: **no restore has ever been TESTED**, and the retention period on `F:\` is unknown. `RUN_LOG.md` Finding 126 | — |
| ☑ ~~**Carry the pilot's 2,000 verdicts into production?**~~ | Sameer | **CLOSED 2026-08-24: NO.** *"let them be judged from the start in the database."* Measured first — **100% of the pilot's unit and subject keys are already in production**, so no LINE is missing and there is nothing to backfill. The verdicts stay behind because they were made under `v5` / 352 categories and everything else will be `v6` / 353 — 2,000 lines judged by a different rulebook with nothing on the row to say so, to save 0.07% of the run | — |
| 🔴 **+2,210 UNEXPLAINED in the taxonomy line totals — BASELINE 3 CANNOT BE LOCKED.** Adding empty categories cannot move a line count. Ruled out by measurement: client lines, uncategorised counts, SAH path distribution, client taxonomy tables, `qa_category` in BOTH databases, the crosswalk node set, mappings/targets/bases — **all identical** — and the merge is **deterministic**. It is ONE client and ONE column: `LINES` on 61 Sydney Adventist nodes. Leading explanation (**not proven**): the 21 Aug rulings settling on the first re-emit after they were made | Me | **2026-08-24** | The Baseline 3 **lock**, not the category set |
| 🟠 **Definitions for the REMAINING overlapping categories.** ✅ **The mechanism is BUILT and PROVEN 2026-08-24** — `MANUAL DEFINE` flows DECISIONS → MERGED → `qa_category` → the judge's payload, and the first definition moved **5 of 5** stubborn lines (contamination 9 → 0 on Melbourne). **This is now just writing them**, one category at a time, cheapest-first | Me | 2026-08-24 | Should land before stage 6 |
| 🔴 **The answer key scores NOTHING today.** `score_answer_key.py` FAILED on 2026-08-24 with *"no reviewed lines"* — the 08-20 rebuild drew a different 500 lines per client and orphaned the key. **It is the ONLY outside check that the judge is any good**, and with no second pass it must work BEFORE ~40 days of compute, not after | Me | **2026-08-24** | Every accuracy figure · should land before stage 6 |
| ☑ ~~**Define `Stationery & Printing`**~~ | Sameer | **CLOSED 2026-08-24.** He ruled on all six borderline items and approved written definitions. 🔑 **And the diagnosis I gave him was wrong**: I said the branch had only one child so there was nowhere else to go — `General Office Supplies` existed the whole time with **87,817 lines**, one branch away. The remedy is unchanged; the cause is **vendor anchoring**, not a structural dead end. Now on me, as the definitions row above | — |
| ☑ ~~**~7% jury dropout**~~ | Me | **CLOSED 2026-08-24.** Not 141 unlucky lines — **16 failed REQUESTS**, each costing all 10 lines in its batch, 28% of the uncategorised pass against 0.1% of the categorised. **The judging code never changed**; the endpoint was slow, which is the same cause as 124 → 52 lines/min. Four fixes; pilot **141 → 0**. ⚠️ Two of the four (re-drive, short-answer check) are **built and unproven** — nothing failed on the day they were written | — |
| 🔴 **BACKUPS — no longer theoretical.** 2026-08-20 the pilot's 2,000 judged lines were destroyed by a `--dry-run` and **there was nothing to restore from.** Rebuilt in 40 minutes because it is small; **production is 15.5-37 days of compute and cannot be rebuilt on a whim** | Sameer / DBA | 2026-08-18 | **Must exist before stage 6** |
| ☑ ~~**The judging rate**~~ | Me | **CLOSED 2026-08-21 by a THIRD measurement.** `124 lines/min` (15.5 d) · `52` (36.9 d) · `46` (41.9 d). **The two recent runs agree at ~50/min; the 124 is the OUTLIER.** Quote **~40 days (38-42)**. 15.5 is superseded, not doubted | — |
| 🔴 **The human answer key is ORPHANED.** `CHECK_ID` is `QA_LINE_ID`, an **identity column** — exactly the failure `CLAUDE.md` warns of. 0 of 69 answers re-attach by ID; **37 is an UPPER bound** by content and the true number is lower. **No accuracy figure exists until this is re-attached** | Me | **2026-08-20** | Every accuracy figure |
| ☑ ~~**The MONTHLY line volume**~~ | Me | **CLOSED 2026-08-20, Finding 104** — measured across the 9 months where all four hospitals are present: **median 46,095, worst 53,805**, which is **6.2–7.2 h** of judging at 124 lines/min. Against 15.5 days for the first pass, the monthly top-up is an overnight job. **The design works.** Date coverage was a non-risk: 31 of 2,786,018 lines lack a posting date | — |
| ☑ ~~**The monthly refresh is not arriving**~~ | Sameer | **CLOSED 2026-08-21 by Sameer:** *"no we dont wait for the hospitals data what we have today is what needs to be in our analysis ... the analyst mentioned they are late in sending their data so its not an issue we contine our process."* ⚠️ **The consequence stands and is not a gate: Northern's data stops at 2026-05 and the deliverable is a one-off, so it is three months old permanently.** Say so on the deliverable | — |
| ☑ ~~**Create `PI_Medical_QA_Indirect`**~~ | Sameer | **closed 2026-08-18 14:57** — created, empty, collation matches the pilot. Access verified by measurement: `db_ddladmin` + `db_datawriter` + `db_datareader`, **no `db_owner`**, and a CREATE/INSERT/DROP test passed leaving nothing behind | — |
| ☑ ~~**`SET RECOVERY SIMPLE`**~~ | — | 🟢 **WITHDRAWN 2026-08-25 — the argument was wrong.** It rested on *"no log backup is scheduled, so the log grows until the volume fills"*. **One runs nightly at 01:22**, and production's log is **12,616 MB allocated against 146.6 MB used — 98.8% free**, `log_reuse_wait_desc = NOTHING`. 🔑 FULL *with* log backups is the SAFER setting: it gives point-in-time recovery, SIMPLE does not. ⚠️ Recovery model was measured; the consequence was **inferred and never measured** — the project's own *measure a risk before raising it* rule, broken by me, for 22 days | — |
| ☑ ~~**How much access does Claude get?**~~ | Sameer | **closed 2026-08-18** — the same three roles as the pilot: `db_ddladmin` + `db_datawriter` + `db_datareader`, **no `db_owner`**. Enough for every table, column and row operation; the only thing it cannot do is `ALTER DATABASE`, which is one line at creation | — |
| 🟠 **Schedule the production backups** — full after the load, then nightly. ~25 GB all in | DBA | **2026-08-18** | Nothing yet, but it must exist **before** stage 6 starts |
| ☑ ~~**PII decision**~~ | Sameer | **CLOSED 2026-08-20 — and it was never a real gate.** *"we have the info on our sql server and yes we can store their data, nothing needs hiding if they leave ... probably hospitals are paying people thats for the analyst to decide, our job is to just point the current categorisation."* The QA database sits on the **same server, same login rules, same client arrangement** as the four databases we already read — copying a row between databases on one box creates no new exposure. It came from a Phase 0 risk-table line carried forward as a gate **without anyone testing whether it was one** | — |
| ☑ ~~**Dashboard snips**~~ | Sameer | **closed 2026-08-18** — MSD-app screenshot supplied, shape settled, 4a built | — |
| 🟠 **A seventh `NIM_ACTION`** for 37 lines labelled `Needs evidence` when the evidence is on the line | Sameer | 2026-08-18 | Nothing — a small change once decided |
| 🟡 **`Incomplete` — Correct or Incorrect in the headline?** 60 lines; ≈60% vs ≈70% pilot accuracy with nothing changing | Sameer | 2026-08-17 | Any accuracy figure being quoted |
| 🟡 **Repeat judge runs?** Jury self-consistency is 91.5%. Triples the run | Sameer | 2026-08-17 | Nothing — recommendation is do nothing for now |
| 🟢 **Monali #1** — 50,511 SAH lines (14.9%) carry no RuleID. A third categorisation mechanism? | Monali | 2026-08-03 | SAH's fix-queue completeness |
| 🟢 **Monali #2 — NEVER ASKED.** 29.4% of SAH's pilot lines use categories our copy of `Adventist_Taxonomy` does not contain. **SAH's accuracy figure rests on this** | Monali | 2026-08-08 | Any SAH figure leaving the building |
| 🟢 **Monali #3** — the 110,740 rule-fired-but-uncategorised lines. Client-confirmed, **still not told** | Monali | 2026-08-06 | Nothing here; it is their defect to fix |
| 🟢 **`REVIEWED_BY` name** for the two completed workbooks in `output/Checked/` | Sameer | 2026-08-10 | Ingesting those answers |
| 🟢 **`.env` sits in a synced team folder** with live credentials | Sameer | 2026-08-06 | Nothing — not urgent, not nothing |

---

### ⚠️ The ordering, so the database is not created into a broken state

**Creating the database does not make production work.** `schema.sql` defines 54 `qa_line` columns
against the live table's 84, and 26 of the missing 30 have no DDL anywhere in the repo — so
`apply_schema.py` on a fresh database yields a table `nim_judge.py` cannot write to.

```
  1. fix schema.sql                    DONE 2026-08-18 - 84 = 84, every CREATE TABLE proven to execute
  2. create the database               DONE 2026-08-18 14:57, access verified by measurement
  3. SET RECOVERY SIMPLE               DEFERRED 2026-08-18 - with the DBA, alongside backups. Blocks step 6, not 4
  4. apply schema to production        DONE 2026-08-18 - 84/31/19/17, proven identical to the pilot
  5. QA_DATABASE named in .env         DONE - and connect_qa() with no arguments STILL returns the pilot
```

Steps 1 and 2 are closed. **Step 3 is one line and is the only thing standing between here and a
production load** — it does not block applying the schema, but it must be done before any bulk load.

🔒 **Do not run any copy of `create_databases.sql` dated before 2026-08-18.** Until then it created
`PI_Hospital_Indirects_QA` / `_Pilot` — **not the databases in use** — from a naming scheme abandoned
before the pilot was built. It also justified `SIMPLE` recovery on the grounds that everything here is
"rebuildable from the client views", which **stopped being true when `qa_line` began holding jury
verdicts that cost ~15.5 days of inference and are not reproducible on a re-run** (91.5%
self-consistency). Both corrected.

---

## Where the shareable pieces live

| What | Where | Regenerate with |
|---|---|---|
| **The one view** | `[PI_Medical_QA_Indirect].[dbo].[qa_line_view]` — 36 cols, one row per line, no filtering | `python pipeline/apply_schema.py --production` (the DDL lives in `pipeline/schema.sql`) |
| **Judging logs** | `output/logs/Indirect judging - <ts>.log` | written automatically by `run_generation.py` |
| **Manager dashboard** | `program/Indirect QA Dashboard - <date>.html` | `python pipeline/dashboard.py` |
| **Taxonomy chart (browsable)** | Artifact: `https://claude.ai/code/artifact/fd3aab24-2008-4323-a4c0-f68a66f44337` | ⚠️ **Republish to THAT url.** The filename carries the date, so a plain publish after the next emit creates a SECOND artifact and stales Sameer's link |
| **Plain-language progress report** | Artifact: `https://claude.ai/code/artifact/bfb59355-2e08-45d0-bfce-889734c31088` | ⚠️ **Republish to THAT url** — publishing fresh creates a second artifact and the link Sameer holds goes stale |

Both are **internal only**. Neither carries a per-hospital accuracy figure, because accuracy has still
never been measured on a spread sample.

---

## 🔒 What the PILOT is for — narrowed 2026-08-24

Sameer: *"do you find any value in testing th pilot, cause i dont"*. **Half right, and the half he is right about matters.**

| | |
|---|---|
| **NOT evidence about the data** | A rule-led sample, not a spread sample. **No per-hospital accuracy figure from it is quotable and none ever has been.** Its answer key is orphaned and scores nothing today. Anything that is a claim about the hospitals comes from **production** |
| **STILL a test harness** | Three full generations ran on it on 2026-08-24 — v5 → v7 → v7+definition — **~120 days of production compute in one afternoon.** The top-up fix was proved on its 141 broken lines and the no-downgrade guard by attempting a bad write against it |
| **Its one irreplaceable property** | 🔒 **It can be wiped.** There is no way to reset 2,000 production lines without resetting 2,786,018. Worth keeping until the run starts; less so after |

---

## Carried defects and unbuilt work — the register

**Unbuilt and load-bearing.** No golden set exists, so **the confidence threshold has never been set
from any curve** · rule-fix simulation (stage 8) · the movement tracker, which `PLAN.md` calls "the
value proof" — ⚠️ **still a separate build.** I briefly recorded it as a free side effect of the
fingerprint; that was wrong (v3.56 change 319). The fingerprint sees the SOURCE data change; the
ANALYST's redirect lands in our own review columns and needs no fingerprint. Two signals, two mechanisms ·
🟠 **incremental carry-forward — DESIGNED 2026-08-20, not built.** `PLAN.md` § *The incremental design*.
⚠️ **Correcting what this register said earlier today:** `unit_key` and `subject_key` **already exist and are
populated on every row** — deterministic SHA-256, no identity column. Only `input_hash` is absent, and it is
**not needed**. What is missing is the **carry-forward join** (every index is `RUN_ID`-scoped; no run reads the
previous one) plus a status vocabulary. **Not needed for the FIRST production run — nothing to carry from —
but required before the SECOND, one month later** ·
`qa_vendor` and the MSD step-1 warning light · the seven Phase-1+ pipeline files.

**Known broken.** `NIM_BASIS` reports `no_evidence` on 1,527 of 2,000 lines including 1,307 that
plainly had evidence — **excluded from every extract** · the taxonomy feedback loop's WRITE side is
still open (F93), so nothing yet stops a future script reading its own output back as an input ·
`qa_rule.ERROR_RATE` is computed from Claude's old verdict layer, not the jury's.

**Two judge defects that have resisted three prompt fixes each.** 55 rationales denying a description
that is genuinely descriptive · 209 `Incorrect` verdicts with no destination. ⚠️ **Finding 96 says
measure before fixing** — some of the 209 are not a judge defect at all but a genuine three-way jury
split, and a mechanism aimed at the wrong cause will miss.

**Raised, then quietly dropped between Findings 89 and 90.** 77,910 lines in generic food buckets ·
Insurance totalling 1,993 lines across four hospitals, recorded as *"not credible, not quotable"* ·
326,147 in-scope lines (13.9%) with no category in the merged taxonomy · 283,258 lines on 41
placeholder leaves · 49 duplicate category paths inside single clients (588,795 lines) · the flat
23.6–24.6% `Uncertain` rate across four very different hospitals, which points at the prompt.

**Never investigated, and it gates the first slice.** Northern's Case B anomaly — 42,554 units, 11–26×
every other hospital, and **zero Northern Case B subjects in the current sample.** `PLAN.md` says in
terms: investigate before choosing the first full client.

---

## ⚠️ Figures that must NOT go anywhere client-facing

Accuracy has **never been measured on a spread sample**, so the four per-hospital figures and the
54-point spread between Melbourne and Sydney Adventist are a hypothesis, not a result. SAH's 88.1%
additionally rests on a taxonomy generation nobody has confirmed (Monali #2). The pilot headline is
either ≈60% or ≈70% depending on an undecided question. Every score recorded before 2026-08-18 is
understated by the scorer defect, and **93.3% branch agreement is superseded by 78%** but still sits
in `PLAN.md` change 260 without the correction attached.

**Re-measure before quoting. Including figures from earlier in the same session.**
