# Medical QA (Indirects)

Line-level spend-categorisation QA of **indirect (non-clinical)** spend across four hospital
clients: **Melbourne Health**, **Northern Health**, **Western Health**, **Sydney Adventist
Hospital**.

Internal project — findings go to each hospital's account manager, not to the client directly.

---

## Which file do I want?

| File | What it is | Share it? |
|---|---|---|
| **[`DESKTOP-START-HERE.md`](DESKTOP-START-HERE.md)** | 🟢 **Starting the judging run on the office desktop — start here.** The five steps, what must not be closed, and what to do when it looks wrong | ❌ Internal |
| **[`TRACKER.md`](TRACKER.md)** | 🔴 **Where the programme actually is.** The ONLY place status lives — not this file | ❌ Internal |
| **[`PLAN.md`](PLAN.md)** | The technical plan of record. **v3.71** — read the change table at the top first | ❌ Internal |
| **[`PROJECT-BRIEF (shareable).md`](PROJECT-BRIEF%20(shareable).md)** | Plain-language version for the manager and account managers | ✅ **This one** |
| **[`ACTIONS.md`](ACTIONS.md)** | Sameer's to-do list to unblock the pilot | ❌ Internal |
| **[`RUN_LOG.md`](RUN_LOG.md)** | Dated record of every run and finding. Append-only | ❌ Internal |
| **[`CLAUDE.md`](CLAUDE.md)** | Operating rules for Claude sessions | ❌ Internal |
| **[`JUDGING-RULES (Indirects).md`](JUDGING-RULES%20(Indirects).md)** | How the judge decides — evidence hierarchy, the nine adjudication rules, and the measurement behind each | ❌ Internal |
| This file | How to run it, and where everything lives | ❌ Internal |

`PLAN.md` is not edited in place. Findings go to `RUN_LOG.md`; a change significant enough to move
the plan becomes the **next version with the change stated in the table at the top** — never a
silent edit. Where a later version reverses an earlier one, the earlier entry is struck through and
points forward, so the reasoning stays auditable.

**Starting a session:** run `python pipeline/state_audit.py`, then read `TRACKER.md`, then
`PLAN.md`'s change table, then the tail of `RUN_LOG.md`, then `ACTIONS.md`. The last section of the
newest `RUN_LOG.md` finding is always headed *"Next session starts here"*.

⚠️ **Sections of this file below "Setup" describe the PILOT ERA and have not been re-verified.**
The commands still exist, but treat any figure in them as provisional until re-measured.

---

## The one rule that keeps this folder clean

> **`pipeline/` contains no client names. `clients/` contains no code. `output/` is never
> hand-edited.**

If you find yourself about to write a hospital's name into a file under `pipeline/`, that logic
belongs in `clients/<key>/config.yaml` instead.

| Folder | What lives there | Who edits it |
|---|---|---|
| `pipeline/` | All the code. Client-agnostic | Developer |
| `clients/<key>/` | Config, golden set, notes — one folder per hospital | Account manager / developer |
| `output/<key>/<date>/` | Generated deliverables. One folder per run, never overwritten | **Nobody — generated** |
| `program/` | Cross-client: profiling, MSD register, movement tracker, dashboard | Program owner |
| `_reference/` | The frozen Nufarm-derived template we started from | **Nobody — read-only** |

---

## Databases

| Database | Access | Purpose |
|---|---|---|
| `Z_Melbourne_Health`, `Z_Northern_Health`, `Z_Western Health`, `Z_Sydney_Adventist` | **read-only** | Source AP lines, client taxonomies, `PMML_Rules` |
| `PI_Master_Supplier_Database_v2` | **read-only** | Vendor identity and coherence |
| **`PI_Medical_QA_Indirect_Pilot`** | **read/write** | 2,000 rows. The proving ground, regenerates in ~16 min |
| **`PI_Medical_QA_Indirect`** | **read/write** | **PRODUCTION — created 2026-08-18, loaded with 2,786,018 lines. The real run** |

~~**PILOT ONLY.** Production is not created until the pilot has run and proven schema v2.~~
🔓 **Discharged 2026-08-18** — schema v2 is proven and production exists. **There are TWO databases
now and the distinction still matters: scope every query, table and deliverable to ONE of them
explicitly, and say which.** A figure quoted without naming its source is ambiguous in a way it
never used to be. Production must be **asked for on purpose** — `--production` on every tool, a lock
`test_guards.py` pins with 20 checks.

**The pipeline writes to the QA databases only.** The four client databases and the MSD are
read-only, always — no temp tables, no exceptions. `Z_Western Health` genuinely contains a space —
bracket it.

### The tables (identical in both databases — parity proven 38 = 38)

| Table | What it is |
|---|---|
| **`qa_line`** | **The production table — one row per in-scope line, with its verdict. Start here** |
| `qa_rule` | The fix queue — one row per rule per rules table |
| `qa_category` | Every client's taxonomy: the candidate set the judge picks from |
| `qa_run` | One row per client per run: source fingerprint, scope note, counts |
| `zz_smoke_*` | ⚠️ **Prototype, superseded.** Kept only so the column decisions stay auditable — **do not analyse from them** |

---

## Setup

```bash
pip install pandas openpyxl pyodbc pyyaml pyarrow anthropic
cp .env.example .env      # then fill it in
```

`.env` holds the shared SQL login plus one `DB_<CLIENT>` per hospital. The key after `DB_` must match
the folder name under `clients/`, uppercased — `clients/western_health` → `DB_WESTERN_HEALTH`. If a
client sits on a different server, add `SERVER_<CLIENT>`.

---

## Running

### Phase 0 — verify and profile (read-only, no QA database needed)

```bash
python pipeline/verify_client.py melbourne_health     # pre-flight PASS/FAIL
python pipeline/profile_clients.py                    # all four
python pipeline/profile_clients.py western_health     # just one
```

`verify_client.py` is the loop that makes onboarding a hospital cheap: **you configure it, it tells
you in seconds whether every mapped column, the taxonomy, the join key and the MSD code actually
resolve.**

`profile_clients.py` writes `program/Client Profiling.xlsx`. It runs against half-filled configs on
purpose — with no `source.table` it lists candidate tables and views with row counts; with a table
set but columns unmapped it dumps the column list.

**Description quality is the main selection criterion for which hospital runs first.** The judge
reads the item description to decide anything. A hospital whose descriptions are mostly blank, PO
numbers or `"GOODS"` has a ceiling on achievable accuracy that no modelling fixes — better known
before it is picked as the showcase.

### First, every session — what is actually in the database

```bash
python pipeline/state_audit.py
```

Read-only, pilot-only. Prints table sizes, the `run_id`s in `qa_line`, and how far judging has
got — and **flags any drift from the state recorded in `RUN_LOG.md` Finding 51**. It exists because
this project has twice quoted a remembered figure instead of a measured one.

### Phase 0.5 — the pilot, in the order it runs

```bash
python pipeline/apply_schema.py                       # schema v1 -> pilot DB (refuses anything else)
python pipeline/load_taxonomy.py                      # -> qa_category, the candidate set
python pipeline/build_pilot.py --budget 500           # rule-led selection -> qa_line + qa_rule
python pipeline/judge.py --backend deterministic      # the pass that proves rather than guesses
python pipeline/judge.py --backend claude_code --client <key> --emit batch.json    # then judge it
python pipeline/judge.py --backend claude_code --client <key> --apply verdicts.json
python pipeline/judge.py --backend claude_code --client <key> --uncategorised --emit uc.json
python pipeline/judge.py --report
```

### Phase 0.6 — the review round-trip (the agreement check)

```bash
python pipeline/make_review_workbook.py --client <key> --outdir QA_LINE_TEST   # workbook out
python pipeline/read_review_workbook.py --file "<completed>.xlsx"              # DRY RUN, report only
python pipeline/read_review_workbook.py --file "<completed>.xlsx" --reviewer "<name>" --commit
```

One Excel per hospital: every judged line, our verdict and reasoning, our suggested category, and
three columns for the reviewer — agree / disagree / the right category. **The category dropdown is
fed from a hidden sheet holding that hospital's taxonomy only**, so no other client's category can
be chosen from the file, and the list widens to the full taxonomy on uncategorised lines exactly
as the judge's own scope guard does.

The reader is **dry-run by default** and writes only the six `REVIEW_*` columns. It checksums the
finding columns before and after the write and **rolls back if they moved** — our verdicts are
never editable by a review. It refuses a workbook whose header row has changed, and it reports
rather than guesses: a disagreement with no category, a category outside the taxonomy, or
"current category is fine" on a line already called Correct are all listed and skipped.

The report it prints is the point: agreement overall, and **split by our verdict**. Disagreements
on lines we called `Correct` are judge false positives and are called out on their own.

---

`build_pilot.py` ranks every rule in the client's in-scope population by **lines per unit** and
takes rules **whole or not at all**. Taking a rule whole is the point: judge 60% of its units and
its error rate is an estimate an owner can argue with; judge all of them and it is a fact.

⚠️ **`build_pilot.py` has no superseded-run purge.** Check `SELECT DISTINCT run_id FROM qa_line`
before quoting any figure — two generations in the table double-counts everything.

---

## Where the project actually is

🔴 **Status does NOT live in this file, and the section that used to sit here has been removed.**

It was a correctly-dated **6 August 2026** snapshot with no way to refresh itself, and by the time it
was found it said production did not exist, that there was no git repository, and that the pilot was
the only database — **all three wrong, on the first file a fresh clone opens.**

> ## → **[`TRACKER.md`](TRACKER.md)** is the only place the programme's position is recorded.
>
> It carries an as-at date and its measured block is copied from `python pipeline/state_audit.py`,
> never typed from memory.

**Starting the run on the office desktop?** → **[`DESKTOP-START-HERE.md`](DESKTOP-START-HERE.md)**


## Notes

- ~~**No git.**~~ 🔓 **There is a git repository as of 2026-08-26** —
  `github.com/sameer-pi/Medical-QA---Indirects`, **private**, and how the code reaches the office
  desktop. `.env` is **not** in it and never will be. The audit trail is still dated `output/`
  folders, the `qa_run` table and `RUN_LOG.md`. **Log every run.**
- **The clinical gate is category-based only.** Keyword exclusion is deliberately unsupported —
  substring matching on descriptions silently deletes in-scope indirect spend (*clinical waste
  removal*, *theatre HVAC maintenance*, *patient meal trolley*) and corrupts the accuracy
  denominator. `clientcfg.missing_for_run()` rejects a config that sets `exclude_keywords`.
- **Sydney Adventist is in NSW.** Don't call this program "Victorian hospitals" in a deliverable.
- **Never quote a figure without its provenance.** Measure it, or say where it was measured. A
  remembered number has already been wrong twice in this project.
- **A rule ID names independent COPIES, not one rule.** Rules are copied between hospitals, so
  `MEL-0135` exists in Northern's table *and* Melbourne's, and fixing one does nothing to the other.
  Every fix instruction states the table it applies to. This is *not* the same thing as the taxonomy
  isolation rule — a `MEL-` rule on a Northern line is normal and must not be reported as
  contamination.
- **A client's taxonomy never resolves another client's lines.** One- and two-part table names only;
  the keys collide across hospitals while meaning different things.
- **"Indirects" belongs in every artefact name.** Without it, a future reader concludes we QA'd
  medical items — the opposite of what this project does.
