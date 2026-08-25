# Medical QA (Indirects)

Line-level spend-categorisation QA of **indirect (non-clinical)** spend across four hospital
clients: **Melbourne Health**, **Northern Health**, **Western Health**, **Sydney Adventist
Hospital**.

Internal project — findings go to each hospital's account manager, not to the client directly.

---

## Which file do I want?

| File | What it is | Share it? |
|---|---|---|
| **[`PLAN.md`](PLAN.md)** | The technical plan of record. **v3.22** — read the change table at the top first | ❌ Internal |
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

**Starting a session:** read `PLAN.md`'s change table, then the tail of `RUN_LOG.md`, then
`ACTIONS.md`. The last section of the newest `RUN_LOG.md` finding is always headed *"Next session
starts here"*.

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
| **`PI_Medical_QA_Indirect_Pilot`** | **read/write** | **The only database the pipeline writes to** |
| `PI_Medical_QA_Indirect` | — | Production. ⛔ **Not created and not built against** |

**PILOT ONLY.** Production is not created until the pilot has run and proven schema v2 —
standing instruction, and `QA_DATABASE` in `.env` is deliberately blank. `apply_schema.py` **refuses
to run against anything but the pilot**, checked two ways, so this is enforced by code rather than
by memory.

**The pipeline writes to the pilot only.** The four client databases and the MSD are read-only,
always — no temp tables, no exceptions. `Z_Western Health` genuinely contains a space — bracket it.

### The tables in the pilot

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

## Current status — 6 August 2026

| Phase | State |
|---|---|
| **Planning** | ✅ `PLAN.md` at v3.25, **reviewed and signed off by Sameer 6 Aug** |
| **0 — Housekeeping** | ✅ Structure built, template frozen into `_reference/` |
| **0 — Access** | ✅ Credentials live, all four client DBs + MSD verified readable |
| **0 — Verify & profile** | ✅ Done. All four PASS pre-flight; in-scope population confirmed at **2,764,531 lines / $5,838M**, folding to **~1,010,661 judge units** |
| **0.5 — Pilot** | ✅ **Judged.** 2,000 lines, 500 per hospital · **all four complete** · 1,462 model verdicts · 211 repeated lines, **0 disagreements** |
| **0.6 — Review round-trip** | ✅ **Built and verified.** Four workbooks in `output/QA_LINE_TEST/`, with the account managers. Ingest tested end to end. ⏳ **Waiting on the first completed workbook — no accuracy figure is publishable until agreement is measured** |
| **1 — First full client** | ⛔ Not started |
| **2 — Harden** | ⛔ Not started |
| **3 — Roll out remaining three** | ⛔ Not started |
| **4 — Program layer + movement tracker** | ⛔ Not started |

**Built:** `db.py`, `msd.py`, `clientcfg.py`, `profile_clients.py`, `verify_client.py`,
`smoke_test.py`, `schema.sql`, `apply_schema.py`, `load_taxonomy.py`, `build_pilot.py`, `judge.py`,
`state_audit.py`, `rule_overlap.py`, **`make_review_workbook.py`**, **`read_review_workbook.py`**.
**All four client configs**, all passing pre-flight.

**Deliverable destination:** the workbooks are an interim surface. The intended home is a QA
module in the internal PI Data Analytics app, where the analyst approves or overrides a finding
and an agreed correction is drafted as a rule in that hospital's own format. Design and the
measured machinery of all four hospitals are in `DEPLOYMENT-CONCEPT (Indirects QA in PIDA).md`.
Nothing is being built there until the pilot review is in.

**Not built:** `load.py`, `gates.py`, `enrich.py`, `research.py`, `rules.py`, `report.py`,
`run_client.py`. Much of what they were specified to do now lives in `build_pilot.py` and
`judge.py`; the split gets revisited at schema v2, not before.

**Pre-flight status** (`python pipeline/verify_client.py`):

```
melbourne_health   PASS      northern_health   PASS
western_health     PASS      sydney_adventist  PASS
```

**The judging is complete. All four hospitals, 500 lines each.**

| Hospital | Correct | Incorrect | Uncertain | **Accuracy** |
|---|---:|---:|---:|---:|
| Melbourne Health | 140 | 213 | 147 | **39.7%** |
| Northern Health | 227 | 137 | 136 | **62.4%** |
| Western Health | 286 | 76 | 138 | **79.0%** |
| Sydney Adventist | 311 | 42 | 147 | **88.1%** |

Accuracy = `Correct / (Correct + Incorrect)`; `Uncertain` is excluded from **both** sides and runs
27–29% per hospital. ⚠️ **These are 500-line samples, not the ~2.8M-line population, and the spread
is mostly taxonomy depth rather than how well each hospital is run** — see `PLAN.md` v3.22 #131.

**Uncategorised lines now get a suggestion from the client's FULL taxonomy.** 500 pilot lines carry
no category at all; **167 of them (33.4%) were judged CLINICAL** and had been sitting in indirect
scope purely because a field was blank. Vendor history across the full 8.4M-line population
predicted 33.0% independently. See `PLAN.md` v3.22 § D and `RUN_LOG.md` Finding 58.

**Still no golden set.** Nothing independent measures whether the judge is right; override data is a
monitor, not a calibration.

**Waiting on Sameer:** one line of SQL to set the pilot database to SIMPLE recovery, the Northern
clinical-leak decision, and Sydney Adventist's `CBoard Lookup` question for Monali — all in
[`ACTIONS.md`](ACTIONS.md).

> **Pilot only.** All work targets `PI_Medical_QA_Indirect_Pilot`. Production is not created and not
> built against until the pilot proves schema v2.

---

## Notes

- **No git.** The audit trail is dated `output/` folders, the `qa_run` table, and `RUN_LOG.md`.
  **Log every run.**
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
