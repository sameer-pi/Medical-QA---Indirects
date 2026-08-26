# APP.md — the live run monitor (Indirects QA)

**Status: 🟢 BUILT AND TESTED 2026-08-26 — `pipeline/monitor.py`** (+ `pipeline/test_monitor.py`, 37 checks, 0 failed). Runs read-only on
`http://127.0.0.1:8000`. Proven end-to-end against the pilot over real HTTP; the read-only guard was
proven by making it refuse four write statements. ⚠️ **Not yet run against a MOVING judge** — nothing
has been judged on production, so every number it shows there is a zero. **One thing is outstanding:
the email alert needs SMTP settings in `.env` (`ACTIONS.md`) — until then the page still goes red and
nothing is sent.**
Created 2026-08-26 at Sameer's request, to hold everything about the local status app in one place
so it does not live in a chat transcript.

⚠️ **ONE THING HAS CHANGED ON THE DATABASE, and it is not the monitor.** On 2026-08-26 Sameer
instructed *"add both cols to the view"*, so `NIM_JUDGED_AT` and `NIM_PROMPT_VERSION` were added to
`qa_line_view` on **both** databases — 36 → 38 columns. That was a fix to the view **on its own
merits** (it could say *what* was judged and never *when*), decided separately from the monitor, and
the monitor does not read the view. **§4.3 has the measurements.** Everything else in this file is
still discussion.

> **Read this first.** `TRACKER.md` says where the programme is. `PLAN.md` holds the judging
> reasoning. **This file holds the reasoning for the monitor and nothing else.** If the monitor is
> ever built, its status still goes in `TRACKER.md` — one status, one place, as with everything else.

---

## The change table

| Version | Date | Change |
|---|---|---|
| v0.1 | 2026-08-26 | Created. Feasibility measured on production and answered **YES** — the whole panel costs ~0.5 s against a job producing ~50 lines/min. Design options laid out, parameters proposed, six decisions put to Sameer. **Nothing built** |
| v0.2 | 2026-08-26 | §4.1 / §4.2 added, from Sameer's question *"would the view need to carry in the same information?"*. **Answer YES, proven on the pilot table vs view — identical, and `sys.indexes` on the view = 0 in both databases, so it is not materialised.** 🔴 **But the question found a real gap: the view is 36 of 84 columns and carries 12 of 28 NIM columns — `NIM_JUDGED_AT` is NOT one of them,** which would kill the entire run-health strip. `NIM_MODELS_RESPONDED` **is** present, so jury health survives. Decision **7** added |
| v0.5 | 2026-08-26 | 🔴 **RUN AGAINST A LIVE JUDGE (pilot, 587 unjudged) AND IT FOUND TWO OF ITS OWN DEFECTS IN FOUR MINUTES.** (1) **lines/min displayed ZERO while the judge was visibly working** — it divided by the nominal window instead of the span the data actually covers, and integer rounding finished the job. On the real run that would have shown zero for the whole first hour, which is exactly when someone is watching hardest. (2) *"running 2.0 days"* four minutes in, because MIN(NIM_JUDGED_AT) is the oldest verdict in the table, not the start of the run. Both fixed; **7 regression cases added — 44 checks, 0 failed.** ✅ Progress, stall True→False on resume, the full/heartbeat cadence, jury health (it caught a new thin line, 14 → 15), prompt version, run_id and the *judging now* vendor tile all read correctly. 🔑 **The monitor was killed and restarted mid-run and the judge never noticed** — the separation proven rather than claimed. ⚠️ SMTP delivery is still never proven. RUN_LOG Finding 130 |
| v0.6 | 2026-08-26 | Two visuals added at Sameer request. **(1) "How much the three graders disagree"** — deliberately NOT an accuracy table: REVIEW_OVERRIDE_VERDICT / REVIEW_STATUS / REVIEWED_AT are populated on ZERO rows and the answer key is orphaned, so **there is no ground truth and per-model accuracy cannot be shown**. It shows verdict skew, dropout, non-verdicts and conformity instead — and reveals the graders are **2.4x apart on how often they call a line Incorrect (21.4% vs 50.5%)**, so the headline error rate depends heavily on which two of three agree. **(2) "Lines judged per hour", 48h**, every hour drawn including idle ones. 🔴 **AND IT EXPOSED A REAL DEFECT — see RUN_LOG Finding 131: gemma returns non-verdicts and NIM_MODELS_RESPONDED counts them as votes, so 4.78% of judged pilot lines claim a full jury on two valid votes.** The jury tile now counts VALID votes itself and needs no judge change; the judge fix is still open |
| v0.7 | 2026-08-26 | ✅ **Sameer approved fixing the judge.** `nim_judge.responded()` now counts only valid verdicts — **the only change to `nim_judge.py` in this whole piece of work** — and `state_audit.py` now derives jury health from the votes rather than the column that lied (`0.8% OK` → `5.7% ABOVE 1%`; not a regression, the number was always 5.7%). ⚠️ **Forward-only:** production is correct from line 1, the pilot's 86 old rows are not. 🔑 Fixing it exposed that the old *"check --workers"* advice was wrong for 76% of the number — the two causes (27 silent, 86 non-verdict) are now counted and remedied separately. RUN_LOG Finding 131 + addendum |
| v0.8 | 2026-08-26 | ✅ **`pipeline/supervise.py` built** — restarts the judge, **four interlocks against running two**, every one proven by making it fire and every one failing CLOSED. ⚠️ Restarts cost ~1.5-2 h of queue re-walking on production (643 vendors ≈ 30 min measured on the pilot). 🟢 **Dashboard redesigned for legibility** — hero row, colour key (green/amber/red, one meaning only), value-first tiles, zebra tables, prose folded into the footer. 🔒 No guard dropped: banner permanent and first, denominators on every rate, no export button. 🔴 **The redesign found two defects: a spend percentage over 100% (a share of a SIGNED total is not meaningful) and 500 judged lines rendering as nothing when `NIM_ACTION` is unclassified.** Both fixed. RUN_LOG Finding 134 |
| v0.9 | 2026-08-26 | Dashboard polish at Sameer's request: **tinted section panels** (⚠️ the tints carry NO meaning and are kept deliberately far from the ok/amber/red palette — severity is the only colour here that means anything), **gridlines** on the tables at the foot, **exactly two hospitals per row** (Melbourne + Northern, then Sydney + Western — the order needed no code, the cards already sort by `client_code`), and **every em dash removed from the visible prose** (five remain as the empty-cell placeholder, which is what that character is for). 🔑 **The cascade hid a real bug:** `dashboard.CSS` also defines `.grid`, with padding, so the cards were being indented **twice** by rules from two files. Found by reading the CSS the server actually sent, not the CSS I wrote. ⚠️ **And my first cascade check asked the wrong question** — it took the last `.grid` rule in the file, which lives inside a `@media (max-width:820px)` block, and so reported the desktop layout as broken when it was fine. ⚠️ `test_monitor.py` caught a banner phrase I had capitalised mid-tidy; the check is now case-insensitive, **recorded as a deliberate loosening rather than slipped in** — missing is still a failure, capitalised is not |
| v1.0 | 2026-08-26 | Hospital cards given a **coloured header band with the name centred**. 🔒 The hues sit deliberately OUTSIDE the severity palette (blue/teal/violet/magenta, no green, amber or red) and are applied only to the band, because colour on this page already means severity and a second scale would poison both. 🔒 **Assigned by POSITION, never by name** — no hospital-to-colour map exists in `pipeline/`; verified by stripping docstrings and comments and grepping the executable code (zero hits). 🔴 **And looking at the finished cards found a real defect: `vendors 6/185` beside `100.00% judged`.** `qa_vendor_queue.QUEUE_STATUS` is stale AND structurally under-reports — `judge_queue` skips a vendor with nothing left to judge **before** marking it done, so after ANY resume every finished vendor stays `pending` for ever, and the supervisor makes that progressively worse. Vendors finished is now **counted from `qa_line`**, not read from the flag: 389/643 became 643/643, matching the lines. `judging now` is suppressed unless the judge is alive. 🟠 The judge is still unfixed; that column needs one decision alongside the `QUEUE_STATUS <> 'done'` filter. RUN_LOG Finding 134 addendum 3 |
| v0.4 | 2026-08-26 | 🟢 **BUILT — `pipeline/monitor.py`**, read-only, `127.0.0.1:8000`, proven end-to-end over real HTTP against the pilot; the read-only guard proven by making it REFUSE four write statements. Decisions 1-6 settled (Sameer: localhost on the office desktop; red page **and** an email). 🔴 **AND §3's COST FIGURE WAS CORRECTED — the real range is 22 ms warm to 47.6 s cold, not "~0.5 s". The variance is the finding.** §3.1. New **decision 8** (an index — deliberately NOT taken). ⚠️ Email needs SMTP settings in `.env`; until then the page reddens and nothing sends |
| v0.3 | 2026-08-26 | ✅ **`NIM_JUDGED_AT` + `NIM_PROMPT_VERSION` ADDED TO `qa_line_view`** on Sameer's instruction — *"add both cols to the view, and let me know"*. Applied from `schema.sql` to **both** databases, **36 → 38 columns**, `qa_line_view` = `qa_line` **delta zero** on both, 1,413 pilot timestamps proven to flow through the view and match the table, parity re-proven 38 = 38, guards 20/0, classify 15/0. Decision **7 CLOSED**; six remain. §4.3. **The monitor itself is still not built** |

---

## 1. What Sameer asked for

In his words, 2026-08-26:

> *"i need to build like a satus dashboard which can give me insights onto our progress, the
> complettion rate and error rate at a hospital level, some key insights that can benefit the team
> and the manager ... after every 500 lines of the judge read and suggestion i would like the table
> to be auto refreshed which refreshes the view and the app numbers, because if our judge is going
> to be running continously i would like my numbers to update as well. like a live viewing of the
> progress."*

The context is the ruling of 2026-08-25: **the judging run moves to the office desktop and runs
always-on for ~40 days.** For 40 days there is no other way to know what is happening inside that
machine.

---

## 2. ⚠️ THIS IS NOT A REVERSAL OF "NO APP" — and the distinction has to be stated, not assumed

`TRACKER.md`'s stage board carries two struck-through stages, killed by Sameer on 2026-08-21:

> *"this wont be an iterrative process ... we wont be building an app for this."*

Stage **7-app** (analyst review inside PIDA) and stage **4b** (the PIDA dashboard page) are **DEAD,
and they stay dead.** What died was:

- an app the **analyst works in** — a queue, a review screen, override write-back;
- an app that **writes to the database**;
- an app that is a **client deliverable** and has to be maintained.

**This is none of those.** It is a **read-only window onto a 40-day batch job**, for us. It writes
nothing, it is not delivered to anyone, it has no analyst in it, and it is thrown away when the run
finishes. The deliverable is still workbooks (stage 7) and rule-fix recommendations (stage 8).

🔒 **If this ever starts to grow a review screen, an override, or a client login, it has stopped
being this thing and has become the app Sameer killed. Stop and ask.**

---

## 3. Is it possible? — **YES.** Measured, not assumed

The only real question was whether a live aggregate over 2.79M rows is cheap enough to run every few
seconds without competing with the judge for the server. **Measured 2026-08-26, read-only, against
`PI_Medical_QA_Indirect` (production, 2,786,018 rows), via `pipeline/db.py`, `WITH (NOLOCK)`, best of
three runs:**

| Query the panel needs | Cold | Best of 3 |
|---|---|---|
| **A.** Per-client progress + verdict mix + jury health + last-judged-at, `GROUP BY CLIENT_CODE` over the whole table | 152 ms | **130 ms** |
| **B.** Judged-only count per client | 80 ms | 79 ms |
| **C.** Throughput — lines judged per minute, last 60 minutes | 129 ms | 76 ms |
| **D.** Vendor queue progress (29,469 rows, indexed) | 61 ms | 26 ms |
| **E.** Signed spend covered so far, per client | 135 ms | 127 ms |
| | | ~~**whole panel ≈ 0.5 s**~~ |

🔴 **THE LINE ABOVE IS STRUCK. THAT FIGURE WAS MEASURED ON A WARM BUFFER POOL AND QUOTED AS THE
COST — see §3.1.** The table it rests on is left standing because those numbers are real; what was
wrong was presenting them without the condition that produced them.

**There is no index on `NIM_VERDICT` or `NIM_JUDGED_AT` and none is needed.** `qa_line` carries
exactly three indexes — `pk_qa_line` (clustered), `ix_qa_line_rule`, `ix_qa_line_unit` — and the
aggregate above is a table scan that costs 130 ms regardless.

**Half a second, against a job that produces ~50 lines a minute.** Refreshing every 500 lines is not
merely feasible; it is so far below the cost of the judging itself that the cadence can be chosen on
what is *useful to look at*, not on what the server can bear.

### 3.1 🔴 CORRECTION, 2026-08-26 — the real cost is 22 ms to 47.6 s, and the VARIANCE is the finding

Building the monitor produced a measurement the probe above did not: **the same queries, run against
production from a fresh process, took 47.6 seconds.** Then 18.2 s. Then 6.1 s. Then 1.9 s. Then,
once the cache was hot, everything settled at the per-query figures below.

```
qa_line on production is 4,214 MB on disk.  Every read here is a FULL SCAN of it.

  WARM (buffer pool hot)                         COLD / server busy
    count all lines                25 ms           whole panel   47.6 s   <- first run, fresh process
    heartbeat, judged only        106 ms           whole panel   18.2 s
    per-client mix                145 ms           whole panel    6.1 s
    action mix                     87 ms           whole panel    1.9 s
    top vendors                    86 ms
    top rules (JOIN qa_rule)      103 ms
    prompt versions               132 ms
    vendor queue                   22 ms
    lines total from qa_run         9 ms   <- no scan at all
    WHOLE PANEL                  ~1.0 s
```

🔑 **The average is not the finding; the spread is.** When the pages are in the buffer pool this is a
tenth of a second. When they are not, it is however long it takes to pull 4.2 GB off disk on a shared
server. **My "~0.5 s" was a warm number presented as the cost** — the project's own standing error,
quoting a figure without the conditions that produced it, committed in the very document that warns
about it.

⚠️ **AND THE COLD CASE IS NOT HYPOTHETICAL.** The nightly FULL backup at 00:15 reads the whole
database and evicts the cache. **The first refresh after roughly 00:30 every night will be slow**, for
40 nights.

**What changed in the design as a result — it survives a slow read rather than assuming a fast one:**

| | |
|---|---|
| Reads run on a **background thread** | The page is served from the last good snapshot and never blocks on the database |
| **One refresh at a time** | A 40 s read means fewer refreshes, never a pile-up of queued queries |
| **The page prints how long the last refresh took**, and the worst so far | This stops being a guess. Re-measuring at 100k judged lines is now a glance, not a task |
| Database unreachable → **"STALE, last good read HH:MM:SS"** | It must never show an old number that looks current |
| Connection timeout raised 60 s → **180 s** | 60 s had no headroom over a measured 47.6 s read |

🔒 **NO INDEX WAS ADDED, DELIBERATELY.** An index on `NIM_VERDICT` / `NIM_JUDGED_AT` would help the
cold case a great deal. It is also a schema change to a 4.2 GB production table about to take 40 days
of writes, made **to serve a watcher** — the exact line §9 says not to cross. It is now **decision 8**,
to be taken with a measurement in hand if the cold case actually hurts, not quietly now.

### ⚠️ The other honest caveat on that measurement

**It was taken with the entire NIM layer NULL** — production has judged 0 lines. `NIM_RATIONALE` is
`nvarchar(2000)` and there are ~30 NIM columns; once they fill, `qa_line` grows materially and a scan
gets slower. **This is a re-measure item, not a guess:** re-run the probe once ~100,000 lines carry
verdicts and record the new figure in this table. Even a 5× regression is 0.65 s, which changes
nothing about feasibility — but a number that has moved gets re-measured, not recalled.
*(CLAUDE.md: never quote a figure without its provenance, including your own from earlier in the
session.)*

---

## 4. 🔑 "Auto-refresh the view" — a view has nothing to refresh

This needs saying plainly, because it would otherwise get built.

`[PI_Medical_QA_Indirect].[dbo].[qa_line_view]` is **a plain SQL view, not a materialised one.** It
holds no data. It is a stored `SELECT` executed fresh every single time anything reads it, so **it
cannot be stale and there is nothing there to refresh.** The instant the judge commits a batch, the
next read of the view already contains it.

So there is no "refresh the view, then refresh the app". **There is only one thing that refreshes:
the app's own numbers.** Everything below is about that.

*(If the view ever became slow enough to need materialising — an indexed view — that would be a
change to the database and a separate decision. It is 130 ms. It will not.)*

### 4.1 Sameer's question, and the measurement that answers it — 2026-08-26

> *"when the judge starts judging it will fill the respective cols in the table, so ideally when
> these blank cols get filled by the relvant information by our model and pipelines, ideally the
> view would need to carry in the same informtion coreect yes or no?"*

**YES — and it carries it with no action from anyone.** Proven rather than asserted, on the **pilot**,
which is the only database with judged rows. Same aggregate, run against the table and against the
view:

```
qa_line                                    qa_line_view
  melbourne_health  unjudged   0  C 120      melbourne_health  unjudged   0  C 120
  northern_health   unjudged   0  C 152      northern_health   unjudged   0  C 152
  sydney_adventist  unjudged 112  C 196      sydney_adventist  unjudged 112  C 196
  western_health    unjudged 475  C   5      western_health    unjudged 475  C   5

sys.indexes ON qa_line_view = 0, in BOTH databases
  -> not an indexed view -> holds no stored copy -> computed on every read
```

Identical, unjudged rows included. The columns fill, the view shows them, the same instant.

### 4.2 🔴 BUT THE QUESTION FOUND A REAL GAP — and it is an ADDITION, not a refresh

**`qa_line_view` is a SUBSET, and the column a live monitor is built on is not in it.**

```
qa_line       84 cols    28 NIM columns
qa_line_view  36 cols    12 NIM columns        16 MISSING
```

| Missing from the view | Consequence |
|---|---|
| 🔴 **`NIM_JUDGED_AT`** | **Kills the entire run-health strip.** No "last verdict written", no lines/min, no ETA. It is *the* column a live monitor rests on |
| 🟠 `NIM_PROMPT_VERSION` | The "stop if two prompt versions are in flight" check cannot run off the view |
| `NIM_BASIS`, `NIM_DECIDED_BY` | `NIM_BASIS` is known-broken and excluded from every extract anyway; `NIM_DECIDED_BY` is traceability |
| All 12 `NIM_1/2/3_MODEL/VERDICT/CONFIDENCE/SUGGESTED_KEY` | Per-model detail. ✅ **Jury *health* is unaffected — `NIM_MODELS_RESPONDED` IS in the view** |

✅ Everything else the monitor needs is present: `CLIENT_CODE`, `SUPPLIER_NAME`, `SPEND`, `RULE_ID`,
`SUBJECT_KEY`, `SCOPE_STATUS`, `NIM_VERDICT`, `NIM_CONFIDENCE`, `NIM_AGREEMENT`,
`NIM_MODELS_RESPONDED`, `NIM_ACTION`, `MSD_COHERENCE`.

**So the view tells you WHAT was judged and never WHEN.** For a batch deliverable that is fine. For a
live monitor it is the missing piece.

**Two ways to close it, and they are separate decisions:**

| | Option | For | Against |
|---|---|---|---|
| **(a)** | **The monitor reads `qa_line` directly** | No DDL on production, no change to a shared object, zero risk. `qa_line` is what was benchmarked at 130 ms anyway | The monitor does not use "the one view" |
| **(b)** | **Add `NIM_JUDGED_AT` + `NIM_PROMPT_VERSION` to the view** | Closes a gap that exists whether or not the monitor is built | A `DROP VIEW` / `CREATE VIEW` on production, touching an object Sameer specified |

🔑 **Recommendation: (a) for the monitor, and (b) separately on its own merits.** Sameer's instruction
was that the view is *the one place anyone looks*. A view that cannot say **when** a line was judged
leaves anyone reconciling a 40-day run blind to freshness — and that is a gap in the view, not a need
of the monitor. Doing (b) *because* the monitor wants it is how a read-only watcher starts changing
the database it watches. **Decide (b) on the view's own terms or not at all.** ~~See decision 7.~~

### 4.3 ✅ DONE — 2026-08-26. Sameer: *"add both cols to the view, and let me know"*

**`qa_line_view` is now 38 columns on both databases.** Both options above were taken, and kept apart
for the reason given: the **view was fixed on its own merits**, and the monitor still reads `qa_line`
directly. Nothing about the monitor was built.

**How it was applied — the file is the truth, the server is the copy.**
`pipeline/schema.sql` was edited first; the `DROP VIEW` / `CREATE VIEW` block was then lifted
**verbatim** out of that file and executed, so the server cannot drift from what is checked in.
The applier asserted it had exactly two statements, a `DROP VIEW` and a `CREATE VIEW`, and **refused
to run if the block contained `DROP TABLE`, `ALTER TABLE`, `TRUNCATE`, `DELETE`, `UPDATE` or
`INSERT`** — a view change may touch the view and nothing else. `assert_writable_qa_database()` ran
against the **live** `DB_NAME()`, not against `.env`.

**Measured after, on both databases:**

```
PILOT       PI_Medical_QA_Indirect_Pilot
  view columns              36 -> 38
  qa_line_view = qa_line    2,000 = 2,000        delta 0
  judged rows carrying NIM_JUDGED_AT THROUGH THE VIEW   1,413
      first 2026-08-24 14:15:41   last 2026-08-25 16:34:51
      same count straight from qa_line               1,413   MATCH
  prompt versions in flight   v7 x 1,413    <- ONE. More than one is a stop signal

PRODUCTION  PI_Medical_QA_Indirect
  view columns              36 -> 38
  qa_line_view = qa_line    2,786,018 = 2,786,018   delta 0
  judged rows carrying a timestamp  0   <- correct: nothing has been judged yet
```

```
verify_schema_parity.py   qa_line_view  pilot 38 = production 38   PRODUCTION MATCHES THE PILOT
test_guards.py            20 passed, 0 failed
test_classify.py          15 cases, 0 failures
```

🔑 **The row-count check is the one that mattered.** A view is a `SELECT`, and a careless edit to a
`SELECT` can filter rows or fan them out through the `qa_rule` join without anything looking broken —
the exact failure the view's own header warns about. **Delta zero on both databases, before and
after.**

✅ **Nothing in `pipeline/` reads `qa_line_view`** — `grep` returns no Python outside `schema.sql`
itself. So no code could break on the column positions shifting. The view is for humans and ad-hoc
analysis, which is what it was built for.

⚠️ **Timing note, and it was deliberate.** Re-creating a view means `DROP` then `CREATE`, and for that
instant the view does not exist. This was done while **production has judged 0 rows and nothing is
running against it.** Doing the same thing mid-run would error for anything reading the view at that
moment. **If the view is ever changed again, do it between runs.**

⚠️ **One thing NOT tested, stated rather than assumed.** `apply_schema.py` (without `--drop`) runs the
whole of `schema.sql`, and its error handler only swallows *"already exists"* and *"duplicate key
name"*. SQL Server's message for an existing table is *"There is already an object named 'X' in the
database"*, which may not match either string. **Whether `apply_schema.py` can be run against an
already-populated database is therefore unknown** — that is why the view block was applied on its own
rather than finding out on production with 2,786,018 rows in it. Worth a one-line test on the pilot
sometime; not urgent, and not a blocker.

⚠️ **`NIM_JUDGED_AT` IS NOT A TRANSACTION DATE.** It is when the judge wrote the row, never when the
hospital bought anything. The line's own date stays out of the view deliberately — `INVOICE_DATE` is
free text and 52% empty at Sydney Adventist. Two different clocks; only one of them is in the view,
and the header now says so.

---

## 5. What "every 500 lines" actually resolves to — and a number to see before choosing it

**How the judge writes.** `nim_judge.py` commits **one batch at a time**, serialised under a single
lock (`nim_judge.py:496`; `write()` ends in `qa.commit()`). Default `--batch` is **10 lines**. At the
measured ~50 lines/min end-to-end, that is **a commit roughly every 12 seconds**.

So the database moves in ~10-line steps, and a "500-line" trigger lands cleanly. But:

```
500 lines  ÷  ~50 lines/min  =  ONE REFRESH EVERY ~10 MINUTES
```

⚠️ **That is probably slower than "live viewing" sounds.** The cadence should be picked with that
number in front of you, not discovered afterwards.

| Trigger | Refresh interval | Cost |
|---|---|---|
| every 500 lines | ~10 min | as asked |
| every 100 lines | ~2 min | feels live; ~30 redraws/hour ≈ 15 s of server time per hour |
| every 10 lines (one batch) | ~12 s | genuinely live; still under 4% of one core-second per second |
| **every 15 s on a timer, redraw only when the count moved** | ~15 s | **recommended — see below** |

**Recommendation: poll on a timer, redraw on change.** The app runs the cheap count (query B, 79 ms)
every 15 seconds; if the judged count has not moved, it draws nothing and costs nothing. If it has,
it runs the full panel. This gives "live" without a fixed line quantum, and "every 500 lines" becomes
one line of config rather than a design commitment.

🔑 **And it requires ZERO changes to `nim_judge.py`.** That matters more than it looks: the judge is
about to run unattended for 40 days, and **the monitor must not be a reason to edit it.** Every
alternative trigger — the judge writing a heartbeat row, the judge calling the app, a database
trigger — puts new code inside the one thing we cannot afford to break. The app watches; the judge
never learns the app exists.

---

## 6. Shape

```
  OFFICE DESKTOP (always on, judge running)

  ┌────────────────────┐        ┌─────────────────────┐
  │  nim_judge.py      │ writes │  SQL Server         │
  │  --queue --all     ├───────►│  PI_Medical_QA_     │
  │  (~40 days)        │ commit │  Indirect           │
  └────────────────────┘ /batch │  qa_line            │
       ▲ knows nothing          │  qa_vendor_queue    │
         about the monitor      │  qa_line_view       │
                                └──────────┬──────────┘
                                           │ SELECT ... WITH (NOLOCK)
                                           │ read-only, ~0.5 s
                                ┌──────────▼──────────┐
                                │  monitor.py         │
                                │  localhost:8000     │
                                │  one page + /api    │
                                └──────────┬──────────┘
                                           │ browser polls /api every 15 s
                                ┌──────────▼──────────┐
                                │  Sameer / manager   │
                                │  READ ONLY. No      │
                                │  control on the     │
                                │  page writes        │
                                │  anything, ever     │
                                └─────────────────────┘
```

### Build options considered

| | Approach | For | Against |
|---|---|---|---|
| **(a)** | **Python stdlib `http.server` + `pyodbc`, one file** | **Zero new dependencies on a box that must survive 40 days unattended.** `pyodbc` is already there. One process, one file, restartable | The HTML/JS is hand-written — but `dashboard.py` already contains it |
| (b) | Flask / FastAPI | Nicer routing | A dependency, a virtualenv and a `pip install` on the run machine, to serve one page |
| (c) | Streamlit | Fastest to write, auto-refresh built in | Heavy dependency, its own server, re-runs the whole script per refresh. Wrong tool for a 40-day box |
| (d) | Extend `dashboard.py` to rewrite its HTML on a loop | No server at all | A file cannot refresh itself in a browser without a server or a meta-refresh hack, and a half-written file can be read mid-write |

**Recommendation: (a).** The rule that decides it is not elegance — **a dependency installed on the
run machine is a new way for the 40-day run to fail**, and this monitor is worth approximately none
of that risk.

### 🔑 What already exists and is reused, not rebuilt

**`pipeline/dashboard.py` already is this dashboard, minus the liveness.** Built 2026-08-18 to
Sameer's own brief, from the MSD app screenshot he sent as the level to aim at: a card per client,
headline pills, a stacked bar segmented by the six `NIM_ACTION` values, a footer of raw counts, one
shared legend, no CDN and no network. Its docstring already carries **four traps it refuses to fall
into**, all of which apply here unchanged:

1. It reads `NIM_*` — the live jury — and **never** the older Claude `verdict` columns. Two verdict
   layers coexist in `qa_line`; mixing them on one screen is how `state_audit.py` reported the wrong
   one for weeks.
2. It does **not** count `Out of scope` as an error. That is a scope finding; folding it in inflates
   every error rate on the page.
3. It does **not** compute a "% with a destination". `NIM_SUGGESTED_KEY` is NULL **by design** on a
   `Correct` verdict, so that ratio undercounts by exactly the lines we got right. It has already
   produced one false regression (`RUN_LOG.md` Finding 96).
4. It does **not** touch `qa_rule.ERROR_RATE`, which is computed from the old verdict layer.

It also refuses a stacked **spend** bar, because our spend is **signed** — Melbourne carries a
−$5,625,000,000 line — and a proportion bar cannot draw a negative segment without quietly switching
to absolute, which would break the standing rule that spend is reported exactly as the data holds it.

**So the monitor is: `dashboard.py`'s card, pointed at production, wrapped in a tiny server, with a
run-health strip added above it.** A much smaller job than "build a dashboard", and it inherits four
already-paid-for lessons instead of re-learning them.

---

## 7. The parameters — proposed, for Sameer to cut and add to

Grouped by the question each answers. **Nothing here is decided.** The rule applied: *every tile must
answer a question someone would otherwise have to ask me.*

### 7.1 🔴 RUN HEALTH — "is it alive, and is it healthy?"

> **This is the most valuable strip on the page and it is the one that was not asked for.** Over 40
> unattended days the expensive failure is not a wrong number — it is **the judge dying at 2am on day
> 6 and nobody noticing until day 9.** Completion rate cannot tell you that: a stalled run and a
> finished one both stop moving.

| Tile | Source | Why |
|---|---|---|
| **Last verdict written** — "3 minutes ago" / 🔴 "47 minutes ago — the judge may be down" | `MAX(NIM_JUDGED_AT)` | The single most useful number on the page |
| **Lines/min, last 15 and 60 min** | count over an `NIM_JUDGED_AT` window | Catches degradation, not just death. Throughput halving is a throttling problem you want on day 2 |
| 🔴 **Jury health — lines judged by fewer than 3 models** | `NIM_MODELS_RESPONDED < 3` | **Finding 124/125 made visible on day 1 instead of day 39.** A hollow jury is invisible in every other figure; `2of2` reads exactly like agreement. Show it as a **rate**, and show it whether it is good or bad — a check that only speaks when unhappy is a check nobody knows is running |
| **Current vendor** — who is being judged now, rank, client | `qa_vendor_queue` where `QUEUE_STATUS='in_progress'` | Turns "it's running" into "it's running *on this*" |
| **Prompt version in flight** | `DISTINCT NIM_PROMPT_VERSION` on judged rows | 🔒 **If this ever shows two values, stop.** Verdicts either side of a prompt bump are not comparable — v3→v4 is not comparable on lines with no usable description |
| **Batches lost to a total outage** | judge console output | Currently printed to the console only; would need the log tailed. See decision 6 |

### 7.2 PROGRESS — "how far through are we, and when does it finish?"

| Tile | Source | Notes |
|---|---|---|
| **Lines judged / total, overall and per hospital** | query A | The headline. 2,786,018 is the denominator |
| **Vendors done / 29,469** | `qa_vendor_queue.QUEUE_STATUS` | The queue is the unit of work; lines is the unit of size |
| **Signed spend covered, per hospital** | query E | ⚠️ **Signed, as held. Never netted, never absolute, no threshold.** The judging *order* is spend-weighted; what is *reported* is as-is. The two must never be conflated in a tile or a sentence |
| **ETA — projected finish**, from the last-60-min rate | A + C | ⚠️ Show the rate it rests on, beside it. An ETA with no visible basis becomes a promise |
| **Days elapsed / ~40** | `MIN(NIM_JUDGED_AT)` | Against the measured 38–42 day estimate |

⚠️ **A per-hospital completion bar will look wrong and will not be wrong.** The default order is
**global** — largest supplier anywhere first — so the hospitals do **not** advance together. Measured
2026-08-25: at the global top 100 vendors, Northern is at 86.2% of its signed spend and Sydney
Adventist at 32.7%. **The page must say the order is global**, or the first person to look will
report Sydney Adventist as stalled.

### 7.3 FINDINGS — "what are we actually discovering?"

| Tile | Definition | Notes |
|---|---|---|
| **Verdict mix** — Correct / Incorrect / Uncertain, per hospital | `NIM_VERDICT` | The raw three |
| 🔒 **Error rate = `Incorrect ÷ (Correct + Incorrect)`** | | ⚠️ **Uncertain is excluded from BOTH numerator and denominator.** Standing rule, CLAUDE.md. `Incorrect ÷ everything` is a different, smaller, wrong number |
| 🔒 **Uncertain %, stated beside it, never folded in** | | Its own headline. It is the size of the manual analyst queue, which is a finding in itself |
| **Action mix** — the six `NIM_ACTION` values, stacked | `NIM_ACTION` | ⚠️ **`Out of scope` is NOT an error** — a scope finding, owned by the hospital's clinical categorisation. The legend must carry each value's meaning, as `dashboard.py` already does |
| **Top vendors by Incorrect count** | group by `SUPPLIER_NAME` | ⚠️ Rank by **line count**, never by spend — ranking by spend requires deciding which rows are real, and 237 Melbourne lines carry $24.5bn gross against $433M net. Vendor name **verbatim**, never trimmed or cased |
| **Top rules by Incorrect count** | group by `RULE_ID` + `rules_table` | 🔒 **Must show the table**, not just the ID. A rule ID names independent COPIES; `MEL-0881` in Northern's table is not Melbourne's |
| **`Needs evidence` count** | `NIM_ACTION` | The manual queue the GL rule deliberately creates — expected around the standing 14.1% no-usable-text measurement |

### 7.4 MANAGER — "what do I tell someone who is not in this?"

Deliberately three numbers, not thirty: **% complete · % of signed spend covered · projected finish
date.** Everything else is ours.

### 7.5 What must NOT be on the page

- ❌ **Anything from `zz_smoke_*`.** Prototype, superseded. A real reader has already mistaken it for
  the main table once.
- ❌ **The old Claude `verdict` layer.** One verdict layer on screen. See trap 1 above.
- ❌ **GL account name, cost centre, business unit description.** Not evidence, and not on a page
  about the judge's evidence.
- ❌ **`MSD_COHERENCE` presented as an error predictor.** Measured: incoherent vendors are misfiled
  *less* often than coherent ones (7.9% vs 11.4%). It is a data-coverage signal or it is nothing.
- ❌ **Any credential, server name, or database host.**
- ❌ **Absolute-value or netted spend, or any spend threshold.**
- ❌ **A "% with a destination" ratio.** See trap 3.
- ❌ **Any accuracy figure presented as a hospital fact** — see §8.

---

## 8. 🔒 THE MOST DANGEROUS NUMBER ON THE PAGE

**An error rate computed mid-run is an error rate for the biggest vendors, not for the hospital.**

The run order is spend-weighted by design: largest supplier first. So at 5% complete the judged
population *is the largest suppliers*, which is the **opposite** of a spread sample. It will differ
from the hospital's true rate, and there is no reason to assume it differs in a friendly direction.

Meanwhile `TRACKER.md` records that **accuracy has never been measured on a spread sample, so no
per-client figure is client-facing** — and `PLAN.md`'s old status section went stale for 15 days
precisely because a correctly-dated snapshot had no way to refresh itself and nobody re-read it.

**Therefore, non-negotiable:**

1. A **permanent banner** at the top, not a footnote: *"INTERNAL. Judged N of 2,786,018 lines (X%),
   largest vendors first. These are not hospital rates and are not client-facing."*
2. Every rate carries **its own denominator on the tile**, not in a tooltip.
3. **No export button.** The moment a screenshot leaves the building the banner is all that travels
   with the number — making it easy to lift the figure is making it easy to lose the caveat.

`dashboard.py` already does exactly this for the pilot's 500-lines-per-hospital sample. Same
discipline, different denominator.

---

## 9. Safety — a monitor must never be able to cost us 40 days

| Rule | Why |
|---|---|
| 🔒 **The app issues `SELECT` and nothing else.** No `INSERT`, `UPDATE`, `DELETE`, `ALTER`, no temp table, no "just this once" | It is a window, not a participant |
| 🔒 **Enforce it by permission, not by convention** — a dedicated **`db_datareader`-only** login | `[Claude]` holds `db_datawriter`. A monitor running under it is one careless line from writing to the table the run is filling. Needs Sameer — see decision 5 |
| **`WITH (NOLOCK)` on every read; one short-lived connection per refresh** | Proven in the probe above. A monitor that blocks the judge's commit is worse than no monitor |
| **DB unreachable → show "stale, last good at HH:MM" and keep serving** | It must never crash, and it must never *look* live while showing an old number |
| **Bind to `127.0.0.1` by default** | See decision 4 |
| 🔒 **It stores nothing that anything else reads** | CLAUDE.md: *never let a generated artefact become its own input.* The monitor recomputes from `qa_line` every time and keeps no cache another script could pick up. That defect cost 13 phantom leaves and ~4M double-counted lines once already |
| **It lives in `pipeline/`, not `output/`** | `output/` is deliverables. This is a tool. Any HTML it writes goes to `program/`, where `dashboard.py`'s already does |
| **No client names in the code** | Standing rule. Client keys come from `clients/<key>/config.yaml`, as everywhere else |

---

## 10. Six decisions for Sameer

| # | Question | Recommendation |
|---|---|---|
| **1** | **Refresh cadence** — 500 lines is one redraw every ~10 minutes at the measured rate. Keep it, or go faster? | **Poll every 15 s, redraw only when the count moved.** Configurable. ~0.5 s of server time per redraw, and no judge changes |
| **2** | **Who sees it** — you only, or the manager and the team too? | Changes decision 4 and how hard §8's banner has to work. **Answer before building** |
| **3** | **Does it replace `dashboard.py` or sit beside it?** | **Beside.** `dashboard.py` writes a shareable static snapshot; the monitor is a live local page. Two jobs. But the card-drawing code is *imported*, not copy-pasted — one place where a card is defined |
| **4** | **`localhost` only, or visible on the office LAN?** | **`localhost` by default.** LAN only if decision 2 requires it, and then still read-only with the banner. A page on the LAN is a page that gets bookmarked and quoted |
| **5** | 🔴 **A read-only SQL login for the monitor** — needs `db_owner`/sysadmin, which `[Claude]` deliberately lacks | **Worth doing;** goes to `ACTIONS.md`. Not a blocker — the monitor can run under `[Claude]` with SELECT-only code meanwhile — but permission beats convention over a 40-day exposure |
| **6** | **Should it tail the judge's console log** for outages and thin batches, or read the database only? | **Database only, first.** A log tail means agreeing a log file and location with the judge, which is a change to the judge. Revisit if outage counts turn out to matter |
| **8** | 🆕 **Add an index on `qa_line` to kill the cold-scan cost?** A filtered index over judged rows would take the cold case from ~48 s to well under a second | **Not yet — and not on my say-so.** It is a schema change to a 4.2 GB production table that is about to take 40 days of writes, made to serve a *watcher*. The monitor already survives a slow read. **Revisit with a measurement after the run has been going a few days**, if the cold case actually hurts. §3.1 |
| ~~**7**~~ | ☑ ~~🔴 **`NIM_JUDGED_AT` and `NIM_PROMPT_VERSION` are NOT in `qa_line_view`**~~ | ✅ **CLOSED 2026-08-26 — Sameer: *"add both cols to the view, and let me know."*** Done, applied from `schema.sql` to both databases. **36 → 38 columns.** See §4.3 for what was measured. The monitor still reads `qa_line` directly — the view was fixed on its own merits, not to serve the monitor |

---

## 11. What is NOT built

⚠️ **CORRECTING THIS WHOLE SECTION — at v0.1 it said the monitor was entirely unbuilt. As of v0.4 it
is built.** `pipeline/monitor.py` exists: server, page, polling loop, `/api/status`, read-only guard,
stall detection and the email hook. The old text is kept below struck through, because a section that
silently flipped from "nothing exists" to "it all exists" is how a reader stops trusting the file.

~~**The monitor: all of it.** No monitor file has been created in `pipeline/`. No server, no page,
no polling loop, no `/api`. Nothing has been added to `.gitignore` or to any script.~~

**What is genuinely still not done:**

| | |
|---|---|
| 🟠 **The email alert has no settings** | `MONITOR_SMTP_HOST` / `_PORT` / `_USER` / `_PASS` / `MONITOR_ALERT_FROM` / `MONITOR_ALERT_TO` are absent from `.env`. The code is written and the stall path was exercised — it reported *"stall alert not configured"* rather than failing. **The page still goes red; nothing is sent.** `ACTIONS.md` |
| 🔴 **It has never watched a MOVING judge** | Production has judged 0 lines, so every number it shows there is a zero. It was proven against the pilot's 1,413 judged rows, which are static. **The first real test is the first hour of the run** |
| ✅ ~~Nothing tests it automatically~~ | **`pipeline/test_monitor.py` written the same day — 37 checks, 0 failed, no database needed.** It proves the read-only guard REFUSES a bare UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/EXEC/BACKUP/GRANT **and** the three that begin with `SELECT` and still write (`SELECT ... INTO`, a stacked `DROP`, a lower-case stacked `DELETE`) — then re-reads `monitor.py`'s own source and asserts all 11 of its real queries pass that same guard, because a blocklist that also blocks the legitimate SQL is one that gets loosened. It also pins `Incorrect ÷ (Correct + Incorrect)`, that `Out of scope` is not an error, that a negative spend keeps its minus sign, and that the banner's wording cannot be dropped |
| ⬜ **Decision 8** | Whether to index `qa_line` for the cold case. §3.1 |

⚠️ **CORRECTING WHAT THIS SECTION SAID AT v0.1 — `schema.sql` HAS SINCE CHANGED.** At v0.1 this read
*"nothing has been added to `schema.sql`"*, and at v0.3 that stopped being true: `qa_line_view` gained
`NIM_JUDGED_AT` and `NIM_PROMPT_VERSION` on Sameer's instruction, 36 → 38 columns, applied to both
databases. **It is a view fix, not the monitor** — decided on the view's own merits, and the monitor
does not read the view. §4.3 carries what was measured. Nothing else in `pipeline/` changed.

The only other thing that ran was a **read-only probe** against production, from the scratchpad,
which wrote nothing and has not been kept.

**The judging run does not depend on this and must not wait for it.** `TRACKER.md` clears stage 6 to
start; if the run starts before the monitor exists, the monitor attaches mid-run — it reads the same
table either way, and there is nothing to backfill.
