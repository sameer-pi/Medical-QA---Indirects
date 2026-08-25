# pi-categoriser-v2 — what Milan built, and what it does and does not do for Indirects QA

**Written 2026-08-21.** Analysis only. Nothing in our project was changed, and nothing in their repo
was touched.

---

## 0. Provenance — where every statement below comes from

| | |
|---|---|
| Repo | `github.com/comprara/pi-categoriser-v2` |
| Branch | `sandbox` — it is the **default branch**; there is no `main` |
| Commit read | `d310be3`, 2026-08-21 16:09 AEST |
| Visibility | **PRIVATE.** My clone succeeded only because a GitHub credential for your account is already stored on this machine. An unauthenticated fetch returns `Repository not found` |
| Author | Milan Panchmatia — **51 commits, all theirs**, two email addresses (`milan@comprara.com.au` ×40, gmail ×11) |
| Span | 2026-08-15 → 2026-08-21. **Six days** |
| Size | 154 Python files, 22 `.tsx`, 17 markdown. ~49,085 insertions against 1,088 deletions across 438 file-touches |

⚠️ **READ THIS BEFORE QUOTING ANYTHING BELOW.** I have **not run this code**, not against our
hospitals and not against anything else. Every number in section 3 and section 5 is **Milan's own
measurement, read out of their source comments and docs**. I have not re-measured a single one. Under
our own standing rule — *never quote a figure without its provenance* — these are their figures with
their provenance, and they are not ours until we measure them.

---

## 1. What it is, in one paragraph

A Comprara platform module — FastAPI backend on port 18203, React frontend federated into shell-v2
under PIDA — that takes a client's **Accounts Payable spend** and **categorises it into UNSPSC v26**
(~158,000 nodes) down to the L4 commodity, then **mints deterministic rules** from what it decided,
with a human review loop that feeds corrections back as training precedent. It is **not** new work
written from scratch this month: it is a **lift-and-adapt** of a standalone app Milan already runs
(`PI_Auto_Categorizer`, which their ADR says carries **1,743 passing tests**). The six days of commits
are mostly the *port* — moving a working engine onto the platform's auth, tenancy, database and
LLM-credential plumbing.

**Its central design principle, stated in their `CLAUDE.md` and worth keeping:**
> *the LLM only proposes; deterministic Python decides identity, mints stable IDs, matches rules, and
> counts spend. Every dollar traces to a rule with a stable ID.*

That is the same discipline our project runs on. The two efforts have converged on it independently.

---

## 1a. ⚠️ It is not one repo, it is FOUR efforts — and none of them is ours

Two source comments in `pi-categoriser-v2` cite a repo neither you nor I had mentioned:

- `core/searchtier.py`: *"Ported from **comprara/PI_Medical_Categorizer** `pipeline/search_keys.py`,
  with the vertical removed: their `known` set privileges medical segments (41/42/51/85) because
  their book is medical. This book is general AP spend."*
- `core/ballot.py`: *"**comprara/PI_Medical_Categorizer** hit the identical shape and named it
  precisely: a $4.4M SAPIEN 3 ..."* — a SAPIEN 3 is a heart valve, i.e. clinical spend.

I checked: **both that repo and the standalone exist and are reachable** with the credential on this
machine.

| # | Effort | What it categorises | Version-controlled |
|---|---|---|---|
| 1 | `comprara/PI_Auto_Categorizer` | General AP spend → UNSPSC. Milan's standalone, the reference implementation (**1,743 tests**) | ✅ |
| 2 | `comprara/pi-categoriser-v2` | The same engine, ported onto the platform. **This repo** | ✅ |
| 3 | `comprara/PI_Medical_Categorizer` | **Medical/clinical items.** Two of its modules were lifted into #2 | ✅ |
| 4 | **Medical QA – Indirects** (us) | **Non-clinical** hospital spend, judged against each hospital's OWN taxonomy | ❌ **no repo at all** |

**None of #1–#3 is our work, and we did not build any part of #2.** #3 is the closest neighbour by
name and is the *opposite* population: it categorises the clinical items our scope rule excludes at
`Category Level 0`.

🔑 **The finding is the shape, not any one repo.** Four categorisation efforts inside one company,
three of them sharing code with each other and **none of them sharing anything with the fourth.** The
one that is not in the family is the one with 2,786,018 lines loaded and a 40-day run about to start.

---

## 2. What it actually does — the pipeline

From `backend/app/pipeline/orchestrator.py` (2,425 lines, lifted byte-identically):

```
group by vendor -> cluster the vendor's lines -> reasoner WALKS the taxonomy to L4
  -> QA verify (3-vote panel, different model families) -> signal-based confidence
  -> mint KNIME rules + a multi-segment vendor floor -> Aho-Corasick apply -> hash-chained audit
```

The pieces that matter:

- **Clustering** (`core/clustering.py`) — groups a supplier's lines so the engine **reasons once per
  cluster, not once per line**. Their comment calls it *"the single biggest lever on cost, since LLM
  calls scale with clusters, not rows."* Two paths: embedding cosine (local Ollama, `bge-m3`,
  threshold 0.70) with **token-Jaccard fallback** when the embedder is down, so a run still finishes.
- **The walk** (`core/walk.py`) — segment → family → class → commodity, **each level a separate model
  call shown only the children of the level above**. Their reasoning: *"asking 'which of these 57
  families' is a question a model can answer, where 'which of 158,000 codes' is not."* Stopping early
  is allowed and gated — a line too generic to pin a commodity may stop at class rather than invent
  an L4.
- **Rule minting** — this is the "automated rule writer" you remembered. It produces **KNIME-semantics
  rules** (`core/rules.py` implements CONTAINS_ALL / CONTAINS_ANY / CONTAINS_NONE / EQUALS /
  STARTS WITH / MISSING / numeric operators, with priority ranks) plus a **vendor floor** — the
  catch-all category for a vendor's blank or uncovered lines, capped at L3 (L2 for opaque text).
- **Confidence and triage** (`core/confidence.py`) — a computed score, never self-reported by the
  model, banded: `auto_accept` ≥ 0.75 · `review` ≥ 0.50 · `flag` below.
- **A memory that grows** (`core/writeback.py`, `library.py`, `supplier_memory.py`) — confirmed
  decisions become precedent for the next run.
- **Web search** (`providers/search.py`, `core/searchgate.py`) — a relevance gate screens a result
  before it can be banked as evidence.
- **Scorecard** (`core/scorecard.py`) — one accuracy implementation for the whole platform.

Backend: **13 routers, 72 routes**, 18 database tables in schema `pi_categoriser`, **53 test files**.
Frontend: runs list, run detail, start-a-run, review queue, rules, spend tree, audit.

---

## 3. Six pieces of engineering judgement in there that are genuinely good

These are worth reading whatever we decide about adopting the thing.

1. **One ruler for accuracy.** `scorecard.py` is deliberately the *only* implementation of every
   accuracy figure. Their note: a second implementation means *"two rulers in circulation, which has
   already produced one recorded mistake upstream."*
2. **It scores at the "deepest defensible level", not at exact L4.** Their argument: only ~4.7% of
   spend sits with a supplier whose own history pins a single commodity, and the gold itself is ~76%
   class-level, so scoring everything at 8 digits *"marks correct-but-honestly-shallower answers as
   failures."* Segment, class, defensible and exact are reported side by side. **This is the same
   problem our answer key hit** — 56.9% leaf against 80.4% branch — and they have a considered answer to
   it where we have two numbers and no ruling.
3. **A load-bearing claim gets a test, not a sentence.** `test_lift_integrity.py` asserts that the 21
   modules claimed byte-identical to the standalone really are. They added it because *"the claim
   decayed silently once already — an autofix pass rewrote eleven of these files while the
   documentation went on saying they were untouched."*
4. **The confidence docstring is honest in a way ours is not.** It states plainly that the score *"is
   NOT a probability and has never been calibrated against gold"*, that both band boundaries are
   hand-set, and — the important bit — a **grain caveat**: the score is attached to an L4 code but
   most of the agreement credit is earned by votes about the *segment*, so *"a pick whose segment is
   right and whose commodity is wrong collects agreement credit it has not earned."*
5. **Feeding a run's own answers back is quarantined.** `writeback.py` opens with *"a run that feeds
   its own answers back is grading its own homework"* and holds three rules: only `auto_accept` rows
   are eligible, machine observations *"buy reach, never depth"* and can never corroborate each
   other, and every row carries its `source_run_id` so a bad run's contribution can be revoked. **This
   is our Finding 93 — the generated-artefact-as-its-own-input defect — recognised and fenced before
   it happened.** They also name where it already bit them: `service` resolving to 18 categories
   across 12 segments.
6. **No LLM credential lives in the module.** Every model call goes through ai-hub-v2, and **two
   structural tests** enforce it — one asserts no provider key name appears anywhere in the source,
   the other that no second provider module exists.

---

## 4. Four structural mismatches with our job — read these before getting excited

**None of these are defects in their work.** They are differences in what the two systems are for.

### 4.1 🔴 Different taxonomy. They categorises to UNSPSC; we judge against each hospital's own tree

Their engine's entire vocabulary is **UNSPSC v26, ~158,463 nodes**, and *"a node's 8-digit code IS the
category id."* Our project judges each line against **that client's own non-clinical taxonomy**, and
`CLAUDE.md` carries a hard rule that a client's taxonomy never resolves another client's lines —
because Melbourne and Northern share 260 keys and **46.5% of them mean something different**.

UNSPSC is not a drop-in for that. Worse, our own measurement says the `UNSPSC` column on Melbourne
**reads exactly 0% in scope** — it is a clinical-item field, empty on every line this project judges.

**But there is a bridge, and it is the most interesting file in the repo.** `api/crosswalk.py` maps
**PI-taxonomy `L0 > L1 > L2` paths onto UNSPSC**, once, so — their words — *"the ~64M already-categorised
historical lines become usable supervision."* Two layers kept deliberately separate: the model's
mapping is read-only, human decisions land in a separate decisions file, *"which a single mutated
file cannot do."* That is the same de-anchoring discipline as our answer key.

They also independently hit our exact collision problem: *"`category_id` is CLIENT-SCOPED in the source
data, so the stable key here is the normalised `L0 > L1 > L2` path string, not an id."*

⚠️ **The open question is whether the four hospitals' taxonomies are inside that PI crosswalk.** The
crosswalk data file is not committed (data artefacts are gitignored), so I cannot tell from the repo.

### 4.2 🔴 Different job shape. Their engine categorises from cold; ours audits an existing categorisation

Their orchestrator docstring says it plainly: *"the **cold-start** UNSPSC pipeline."* It answers *"what
is this line?"* Our job answers *"is the category already on this line right, and if not, which rule
put it there?"* The only place they do our shape of work is `api/second_opinion.py`, which reviews one
line the pipeline already categorised — and it is marked **advisory only**, one line at a time, from
the UI.

The engine has **no concept of an incoming assigned category to agree or disagree with**. Our judged
unit is `(client, vendor, term, assigned_category)` with the assigned category *in the key*. Their is a
vendor-description cluster. Retargeting their engine at our question is not configuration; it is a
different prompt, a different unit and a different output shape.

### 4.3 🔴 It uses the GL account. We banned it on 2026-08-17

This is the sharpest conflict and it is unambiguous:

- `core/config.py` maps four header spellings onto a `gl` field.
- `core/models.py` carries `gl` on every `Line`.
- `core/router.py` consults the GL *"only when the description carries no usable signal"* — with a
  measured defence: 283 of 4,875 lines (5.8%) and **$394.7M** matched a tax regex in the GL but not in
  the description, and discarding them on the GL's name was wrong.
- `api/second_opinion.py` puts `GL account:` straight into the prompt.
- There is a config flag `WALK_GL_BEATS_BLANK_STOP` whose comment says a blank-description line *"whose
  GL carries real words is not evidence-free, so it should not be forced to stop"*.

Our standing instruction, yours, 2026-08-17: *"we have a hard rule that the GL will never be used to
make any judge or assumption, neither the cost centre ... if the item description doesnt give us that
granularity, it would be manually sorted by the analyst."* We removed the fields from the payload
entirely — because a field that is present is a field a model can read — and it cost us **189 pilot
lines** of firm verdicts, scaling to **388,510 lines (14.1%)** of manual queue.

**Their engine would fail our own GL grep on day one.** Adopting any of the reasoning modules means
either stripping the GL channel out of them or reversing your ruling. That is your call, not mine,
and it should be made explicitly rather than by importing a module.

### 4.4 🟠 Different data source, and it needs infrastructure we do not have

They reads `PI_All_Client_Consolidated` (~19.5M client/vendor/description/GL combos) joined to
`PI_Master_Supplier_Database_v2`, on `PIDEVSQL2022-DV`, via a dedicated `pi_categoriser_read` login.
We read the four hospital databases directly and write to `PI_Medical_QA_Indirect`. Different server
role, different credentials, different shape. And their runtime needs ai-hub-v2, admin-v2 identity, a
tenant GUID, and shell-v2 to mount the UI — **none of which we have or need**.

---

## 5. 🔑 The single most relevant thing in the whole repo

From ADR 0002, and repeated in their `CLAUDE.md`:

> *"The evidence channel is not optional. **On Western Health, measured 2026-08-13: with the MSD join,
> 96% of lines are codeable; without it, 27%.** The gap is opaque line text (single tokens, part codes,
> blanks) where the supplier's identity is the only evidence available."*

**Western Health is one of our four hospitals.** So the standalone engine has already been pointed at
one of our clients, and the thing it says carries a 96%-vs-27% swing is exactly the population our
project sends to the analyst: our **14.1% with no usable item text**.

**What the MSD join gives their engine is not the coherence verdict we already flag.** It is the
supplier's **description, industry tags, source-confidence trust score, a corroborating URL, and the
supplier's own invoice examples** — pulled from `pi_vendors` via `pi_client_vendors`, with a trust
floor of 0.85 below which an enrichment cannot carry a line on its own.

⚠️ **And it collides head-on with your evidence hierarchy.** Rule 1 says vendor name *"sets the
neighbourhood"* and *"is never a factor by itself"*; rule 3 as you reversed it says no usable
description → `Uncertain` → analyst. A rich vendor profile is still **vendor evidence deciding a
category when the description is blank** — which is the thing you closed. It is a better-grounded
version of it, with a trust score and a URL behind it, but it is the same shape.

**I am not recommending we adopt it. I am putting it in front of you because it is a real number on a
real client of ours, it is 14.1% of our population, and the decision is yours.** If the answer stays
no, that is a one-line ruling and we stop wondering.

---

## 6. What is worth taking, ranked, and what it would cost

| # | What | Why it matters to us | Realistic effort | Blocked by |
|---|---|---|---|---|
| **1** | **Clustering — reason once per cluster, not once per line** | Our judging run is **~40 days (38–42)** at ~50 lines/min, per line, on 2,786,018 lines. This is the one lever that changes the order of magnitude | Module is **pure Python, no I/O, dataset-agnostic by design**. Needs a local Ollama for the embedder; the token-Jaccard fallback needs nothing | ⚠️ **We removed grouping deliberately in `PLAN.md` v3.22.** That decision must be re-read before anyone reverses it |
| **2** | **The rule-minting design (stage 8)** | Our stage 8 — rule-fix recommendations, **the actual deliverable** — is *"Not started, no design yet"*. They have a working one that emits KNIME-semantics rules with stable IDs and a vendor floor | Design borrowing, not code borrowing. Their rules mint *forward* (this line → this category); ours must mint *corrective* (this rule is wrong → redirect) | Nothing. This is readable today |
| **3** | **The scorecard's "deepest defensible level"** | Directly answers the question our answer key leaves open — 56.9% leaf vs 80.4% branch, with no ruling on which is the headline | Small. It is one file with a narrow protocol interface | Nothing |
| **4** | **The crosswalk pattern** (PI taxonomy path → UNSPSC, model layer and human layer kept separate) | If the hospitals are in it, it is a ready-made bridge between our four taxonomies. If not, the **pattern** is still exactly our DECISIONS-workbook discipline | Unknown until we see whether hospital paths are in the mapping file | ⏸ **Ask Milan** |
| **5** | **`test_lift_integrity.py` and the "measured defaults" test** | We have the same failure mode: a documented claim that decays. `test_measured_defaults.py` fails if a knob's default drifts from its measured value | Small, and the idea is free | Nothing |
| **6** | **The whole platform module** — run it on hospital data as-is | ❌ **Not viable.** Wrong taxonomy, wrong job shape, uses the GL, needs ai-hub + admin-v2 + shell-v2 + a tenant | — | §4 in full |

---

## 7. Maturity and risk — stated plainly

**What is real:** the backend is **live on staging-v2 since 2026-08-17** (NSSM service, port 18203,
`/health/ready` returning 200). The database `pi_categoriser_v2` is provisioned and migrated. The
UNSPSC taxonomy is **seeded: 158,463 nodes**, verified by resolving codes on the server rather than by
counting rows. The frontend is deployed and mounted in shell-v2 behind a feature flag and a permission,
granted to super-admin only. 53 test files, four CI workflows.

**What is not:**

- 🔴 **`docs/ARCHITECTURE.md` contradicts `CLAUDE.md` and `DEPLOYMENT.md` inside the same repo.**
  ARCHITECTURE says the migration *"has never run against MSSQL"* and lists the database as something
  *"only Milan can provide"*; the other two say it was provisioned and applied on 2026-08-17. **This is
  the same defect that hit our `PLAN.md` status section** — a correct snapshot with no way to refresh
  itself. Worth telling them, kindly, since they will hit it again.
- 🟠 **`README.md` is still the module-template README** — it opens *"Comprara Module Template. Fork this
  when starting any new module"* and still carries the search-and-replace instructions. `CHANGELOG.md`
  is still the untouched stub with a `YYYY-MM-DD` placeholder.
- 🔴 **`docs/EXPERIMENTS.md` is missing.** ADR 0001 says the experiment ledger *"travels with it as
  `docs/EXPERIMENTS.md` so the reasoning behind each choice stays attached to the code."* It is not in
  the repo. Five source comments cite it by experiment id (N9, D18, D12, A13, A12) and point at
  nothing. **The evidence behind the engine's tuning is not in the repo we were given.**
- 🟠 **The last 12 commits, all 2026-08-21, are CI and deployment plumbing** — lockfiles, ESLint config,
  PATH fixes, tenant settings. Engine work appears to stop around 18–19 August.
- 🟠 **The embedder runs on Milan's Mac** as an interim, over a tunnel. Single point of failure, and a
  person dependency.
- 🟠 **Missing UI:** scorecard, library, crosswalk, conflicts, action comments, the UNSPSC browser and
  the single-line debugger all have working backends and **no page**. The experiments feature (their
  Phase E) is not built.
- 🟠 **App state still on disk** — gold panels, the vendor-id map and the floor file are read from files
  by the runner and belong in tables.
- 🟠 **Client names and spend figures sit in source comments** — BLUESCOPE (×70), WYNDHAM (×40), NANDOS,
  DFFH, MOPT, QUU, IPLEX, and at least one named vendor with a dollar figure (`JOVECROFT PTY LTD, blank
  description and blank GL, $281,153`). Our `pipeline/` has a hard rule against exactly this. Their repo
  is private, so it is a difference of convention rather than a breach — but it is why ours has the rule.
- ✅ **No credentials are committed.** `.env.example` carries `<password>` placeholders. Server names,
  database names and login names *are* in the repo; in a private repo that is normal.
- ⚠️ **Their own self-consistency floor, from ADR 0001:** *"Two identical runs agree on only ~54% of picks
  and differ by ~5.6 points at segment. Every accuracy claim the module makes has to be read against
  that floor."* For comparison our jury measured **91.5%** — different engine, different taxonomy depth,
  not a like-for-like, but it is the number to compare against if we ever run both.

---

## 8. My read

**It does not help the run we are about to start, and it should not delay it.** Nothing in §6 is
ready to drop into a pipeline that judges against four hospital taxonomies, and three of the four
mismatches in §4 are structural rather than fixable.

**It matters a great deal for stage 8 and for anything after this engagement.** Our deliverable —
rule-fix recommendations — is unbuilt and undesigned, and they have a working rule-minter with the
identical governing principle. That is the conversation to have.

**Two things should be decided by you rather than drifting:**

1. **The MSD evidence channel (§5).** 96% vs 27% on Western Health is their number, not ours, but it is
   about our client and our 14.1%. Yes or no, and if no, it goes in `CLAUDE.md` so it stops coming back.
2. **Whether these two systems are meant to converge at all.** They are categorising AP spend into UNSPSC
   across every PI client. We are QA-ing indirect categorisation for four hospitals against their own
   taxonomies. Both mint rules. Both have a review loop. Both have a scorecard. If nobody decides,
   they will duplicate each other for another six months and the duplication will be found late.

**Three questions for Milan, in priority order:**

1. **Are the four hospitals' taxonomies in the PI→UNSPSC crosswalk?** One answer decides whether §6 row 4
   is worth anything.
2. **Where is `docs/EXPERIMENTS.md`?** Five code comments cite it and it is not in the repo. Without it
   the measured basis for the engine's tuning is not reviewable.
3. **What was the Western Health run on 2026-08-13?** Which lines, what scope, in-scope-indirect or
   everything? If it included clinical spend, the 96%/27% figure is not about our population.

---

## 9. Can we use it to categorise OUR data? — measured 2026-08-21

**Short answer: their LOGIC yes, their CODE no.** Nothing of theirs runs on our data, for the four
reasons in §4. But one idea of theirs is worth about 25 days, and it needs none of their code.

⚠️ **First, a correction to §4.2.** It says their engine categorises from cold while ours audits an
existing categorisation, and treats the overlap as small. That undersells it: **413,924 of our
in-scope lines (14.9%) are UNCATEGORISED.** For those our job *is* categorisation, not audit — that
is precisely the population their engine is built for.

### 9.1 🔴 "LLM calls scale with clusters, not rows" — applied to a key we already hold. ~40 d → ~14 d

Their clustering exists so the engine reasons once per cluster instead of once per line. **We do not
need their clustering to get most of that** — `unit_key` already exists and is populated on every row.

```
2,786,018 in-scope lines    ÷ ~50 lines/min  ≈  38.7 days      <- what is planned
1,016,303 distinct units    ÷ ~50 lines/min  ≈  14.1 days      <- the same job, per unit
                                                ------------
                                                ~24.6 days
```

*(Line and unit counts from `TRACKER.md`, measured 2026-08-21; the rate is the settled ~50/min from
`RUN_LOG.md` Finding 115.)*

**Why we judge per line, and why the reason has expired.** `PLAN.md` v3.22 change 123 deleted
`qa_unit` deliberately, to buy a **free self-consistency check** — Sameer: *"how can the same vendor
same item and same category come back with different answers."*

That check cost nothing on 2,000 pilot lines. **On 2,786,018 it costs ~25 days.** And it has already
returned its answer twice: **211 repeated lines, 0 disagreements** (2026-08-05), and jury
self-consistency separately measured at **91.5%**. Re-judging a **2% sample** of repeats buys the same
signal for roughly seven hours rather than twenty-five days.

⚠️ **This reverses a standing instruction from Sameer, so it is his call and not a change to be made
quietly.** It is recorded here because it is the only thing found in this review that changes the
ORDER OF MAGNITUDE of the run, and because the trade was correct when it was made and is not now.

### 9.2 🟠 The descent and the depth gate — pointed straight at the open A2 gate

**Measured on the pilot 2026-08-21:** `qa_category` holds **352 merged categories, 351 in scope**, and
`nim_judge.candidates()` hands the judge **the whole flat list** to pick from.

Our A2 finding is that the 44.4% answer-key miss is a **pattern**: we land on a vaguer node one level
up — `stationery` → `General Admin Supplies > General Admin Supplies`, a padded dead-end. That is the
characteristic failure of a flat pick, and their walk exists to prevent it: level by level, shown only
the children of the level above, with an explicit gate on stopping short (`core/depth.py`).

Two qualifications, both important:

- ⚠️ **`PLAN.md` change 86 already specifies the two-step descent** — *"pick the branch, then pick
  within it. 58 choices instead of 1,449"*. But `nim_judge.py`'s own comment describes a model
  *"deliberat[ing] over a 350-category candidate list"*. **Check whether change 86 was ever
  implemented before borrowing anything** — this may be a gap in our build rather than a gap in our
  design.
- ⚠️ **A2 comes first regardless.** If `stationery` is not a leaf in that hospital's taxonomy, no
  descent fixes it: it is a taxonomy gap and their logic is beside the point.
- ⚠️ **And their opposite failure is the warning.** Forced descent manufactured *'Handcrafts
  vocational training'* out of `SCHOOL BASED APPRENTICES`. A depth gate that only pushes deeper is
  worse than the flat pick.

🔑 **Their walk's COST argument does not transfer.** It exists because 158,000 codes cannot be
weighed in one prompt. **351 is not 158,000.** What transfers is the depth DISCIPLINE, not the descent
itself — and the cheap version of it is to make the judge state why it stopped on a node that has
children.

---

## 10. Can we implement their rule writing? — yes, but the reusable piece is not the writer

**"Tweak our code" is the wrong frame. It is a new module — but the design exists and half the
machinery is liftable.**

### 10.1 ✅ What is genuinely liftable: their rule EVALUATOR

`core/rules.py` — 438 lines, **pure Python, no I/O, no database coupling**. KNIME semantics
(`CONTAINS_ALL` / `CONTAINS_ANY` / `CONTAINS_NONE` / `EQUALS` / `STARTS WITH` / `MISSING` / numeric
operators, with priority ranks), plus an Aho-Corasick accelerator and a randomised parity test that
asserts the fast path and the reference path never disagree.

🔑 **This is the fix for the red line on stage 8 in `TRACKER.md`:** *"A fix is still never simulated
before it is handed over."* An evaluator lets us apply a proposed corrective rule across that
hospital's own lines and **count what it would actually move** before recommending it. Without one we
hand a client a rule change with no measurement of its blast radius.

### 10.2 ⚠️ What transfers less well: their MINTER

Theirs mints **forward** — a walk decides a category, a keyword rule is minted to reach it. Ours must
mint **corrective** — this existing rule put N lines in the wrong place, here is the redirect. Same
output shape, entirely different input: ours starts from a jury verdict plus a suggested path.
**The machinery is reusable; the logic above it is ours to write.**

### 10.3 🔒 Four of our constraints that must survive the port

| | |
|---|---|
| **Allowlist, never blocklist** | A minted rule may fire on `VENDOR_NAME` and `ITEM_DESCRIPTION` **only**. Their engine is comfortable keying on the GL; ours must refuse to |
| **Every fix names its table** | A rule ID names independent COPIES per hospital. Fixing `MEL-0881` in Northern's table does nothing to Melbourne's |
| **Read-only on client databases** | We recommend; we never apply. Their engine has the same discipline under ADR 0002, so this one is free |
| **The finding is immutable** | A minted rule is a suggestion **beside** the verdict, never a rewrite of it |

### 10.4 One measured result of theirs worth re-testing on ours

Their retrieval key is a **sorted two-word pair**, because single keywords measured **61.6%** correct
at segment against **90.2%** for pairs — and longer phrases measured *worse* (89.6 → 88.6 → 86.1 as
keys lengthen). `RULE_MAX_KEYWORDS` defaults to 2 for that reason.

⚠️ **Their number, their taxonomy, their book.** If it holds on ours it is a free improvement to every
rule we mint; if it does not, far better to know before minting across 2.78M lines.

### 10.5 Effort and sequencing, stated plainly

- **The evaluator lift: small.** ~1 day with tests, because it is pure and already has a parity test.
- **The minter: a real build**, and it **cannot be validated until stage 6 produces verdicts to mint
  from.** That is not a blocker on starting it — `TRACKER.md` already says stages 7 and 8 should be
  underway *while* the judging run is going, or the calendar is a fortnight of waiting for nothing.
- 🔴 **Lifting their code needs Milan's say-so.** Same company, but it is their repo and their ADR 0001
  governs what may be lifted from where.

---

## 11. What I did not do

- Did not run the code, or any part of it, against anything.
- Did not re-measure a single one of their figures.
- Did not modify their repo, or our `PLAN.md`, `TRACKER.md`, `RUN_LOG.md` or `ACTIONS.md`.
- **Did** run three read-only measurements against **`PI_Medical_QA_Indirect_Pilot`** for §9:
  `state_audit.py`, a `qa_category` count by client (352 merged / 351 in scope), and a read of
  `nim_judge.candidates()`, `PLAN.md` v3.22 change 123 and change 86. Nothing was written.
- Did not read every file. I read all 17 markdown docs, the four ADRs, `orchestrator.py`'s interface,
  and `config.py`, `rules.py`, `confidence.py`, `writeback.py`, `router.py`, `clustering.py` (via its
  architecture note), `crosswalk.py`, `second_opinion.py` and `mssql_source.py`. **~44,000 lines were
  not read**, including the 2,425-line orchestrator body and the entire frontend.

**Working clone**, if anyone wants to look before it is cleaned up:
`C:\Users\SAMEER~1\AppData\Local\Temp\pcv2` — commit `d310be3`, branch `sandbox`.
