# How the judge decides — indirect spend categorisation QA

**Status:** live. Encoded in `pipeline/judge.py` as `PROMPT_VERSION = "v5"` (v5 since 2026-08-17 — see § 0). ~~`"v4"`~~
**Written:** 2026-08-05, after all four hospitals were judged.
**Why it exists:** every rule below was got wrong first, by hand, and corrected. Sameer, 2026-08-05:
*"the corrections you are making is good, so i feel this correction should also train your judging
model to handle these cases when we scale."* Knowledge that lives only in a chat transcript is
knowledge lost. This is that knowledge.

Every figure in this file was **re-measured on 2026-08-05** against
`PI_Medical_QA_Indirect_Pilot`, run `pilot-20260805T112504`. Nothing here is quoted from memory.

---

## 0. ✅ v5 IS LIVE as of 2026-08-17 — read this before quoting anything below

`PROMPT_VERSION` in `pipeline/judge.py` reads **`v5`**. ~~`v4`~~ ~~v4 IS SPECIFIED AND NOT YET
LIVE~~ — superseded; kept so the sequence stays auditable.

### 🔒 v5 — THE GL LEAK IS ACTUALLY CLOSED. v4 SAID IT WAS AND IT WAS NOT.

Sameer, on being shown the sample: *"fix them, especially the GL leak, the gl should not be used to
judge."* **v4 changed the obvious field, declared the rule enforced, and left THREE other paths
open.** All three were found by grepping the judge's own rationales — none of them by reading the
diff, and none by any check we had.

| # | The path that stayed open | Size |
|---|---|---|
| 1 | **`rule.fires_on` was sent whole.** A GL rule spelled the GL out in plain text: `"ACCOUNT NAME CONTAINS FREIGHT"`, `"CHARGED COST CENTRE STARTS WITH X"` | **274 pilot lines** attached to such a rule; **40 rationales** quoted it; **24 of those on a FIRM verdict** |
| 2 | **Adjudication rule I still TOLD the judge to use it** — a v3 paragraph the v4 edit walked straight past, ending *"Such a line is usually still Correct — an account named FREIGHT is where a carriage charge belongs … Look for a second, independent source: a description, **a cost centre**, or a vendor"* | This is what produced `Correct` / `3of3` on Haines Medical lines whose only evidence was the GL |
| 3 | **The UNCATEGORISED prompt still carried the v3 hierarchy verbatim** — *"GL and cost centre carry it when the description is unusable"* | The rule was **never in force at all** on the entire uncategorised pass — 500 pilot lines |

Plus `gl_account_name` and `cost_centre_description` were still being **SELECTed** out of SQL and
merely left out of the payload dict — one careless edit from the judge. They are now `NULL`
literals holding the column positions, so the values never leave the database.

**THE FIX IS AN ALLOWLIST, NOT A BLOCKLIST, and that is the whole point.** Only two fields are
evidence under Sameer's hierarchy — the vendor and the item text — so only those may be named in
`fires_on`. Everything else is withheld **by default**, including fields nobody has invented yet. A
blocklist of GL-ish names fails *open* on the next client's rules table, which is exactly how this
survived v4. A withheld condition reads:

```
[withheld - this rule fires on a field that is neither the vendor nor the item text.
 It is not evidence you may use, and you cannot infer it]
```

`BUSINESS UNIT DESCRIPTION` is withheld too. Sameer named *"the GL … neither the cost centre"*; a
business unit is the same class of evidence — it says **who bought**, never **what was bought** —
so admitting it would reopen the rule through a synonym. 6 rules; easily reversed if he disagrees.

🔑 **THE LESSON, AND IT IS THE SAME ONE TWICE: A GUARANTEE ABOUT WHAT THE JUDGE SAW MUST BE
MEASURED ON THE OUTPUT.** Grep the rationales. Do not read the diff. `action_classify.py` now runs
that grep as a standing check on every classify, so the claim is a measurement and not a claim.

**v5 also makes two answer shapes INVALID that v4.1 quietly tolerated:**

- **An `Incorrect` with no `suggested_key`** — 249 of 519 in v4.1. It tells a person their filing is
  wrong without saying where it goes, so they redo the whole job by hand. **68 of them named the
  right leaf in prose while leaving the field empty.**
- **A rationale claiming the description is missing when `has_usable_text` is true** — 205 in v4.1.
  Worse than a wrong verdict: it sends someone hunting for information already in front of them.

**What v4 changed, and it is TWO things, not one:**

**a. 🔒 GL account and cost centre are no longer evidence.** Sameer, 2026-08-17. This is the change
that matters most, it **reverses** the step-3 fallback set on 2026-08-03, and it is documented in
full at § 2. **v3 and v4 verdicts are NOT comparable on lines with no usable item description** —
189 pilot lines that held a firm verdict under v3 can only be `Uncertain` under v4, because the
evidence they rested on is no longer admissible. That is the whole reason this column exists.

**b. The suggestion source is the merged taxonomy.** Live since 2026-08-14 — 427 suggestions made,
**0 outside the locked ~~350~~ 365** (see § 0 — the taxonomy moved to 365 on 2026-08-17). The verdict yardstick is unchanged: a line is still judged against the
hospital's own taxonomy, because measuring accuracy against a house view would measure it on the
wrong yardstick.

⚠️ **Sections 1 and 3 onward were written for v3 and remain correct** — the question the judge is
asked and the nine adjudication rules did not change. **Only § 2 step 3 moved.**

### Detail on (b) — the suggestion source

~~**a.** The suggestion source **changes**~~ — tense corrected: it **changed**, on 2026-08-14, and is live. Sameer, 2026-08-14: *"the
current taxonomy would be currently pulled from the 4 old taxonomies, however recommendation /
suggested categories should only be fed from the new taxonomy we locked in today."*

- **Judged against** — the hospital's own taxonomy, from `qa_category`. **Unchanged.** § 1 stands:
  the question is still *"is this line in the right bucket, given the buckets this hospital has"*,
  and an accuracy figure measured against a house view would be measured on the wrong yardstick.
- **Suggested from** — the locked merged taxonomy only: **365 categories** (~~350~~ — grew 2026-08-17, purely additive), loaded into the existing **`qa_category`** under `client_code = 'merged_indirect'** (~~`qa_taxonomy_merged`~~ — that table was never created; Sameer, 2026-08-14: *"any writing into sql strictly do it in only qa_line like we were doing before"*), **Baseline 3** (~~Baseline 2~~, `RUN_LOG.md` Finding 85). This is safe to action because the four hospitals are
  adopting the merged taxonomy; it is not us imposing a house view on their verdict.
- **Adjudication rule D is rewritten by this** — *"this taxonomy covers…"* now refers to the merged
  365, not the client's list, so the gap it reports is a gap in **our** taxonomy.
- **`Clinical` is one of the 365, and it is a HANDOFF MARKER, not a category.** Sameer, 2026-08-14:
  *"that line in Clinical the other team project will handle it not us."* Roughly a third of
  uncategorised lines are clinical (167 of the pilot's 500), and an indirect-only candidate list
  would have pushed them to the nearest indirect leaf — the exact failure Sameer stopped in v3.22.
  It reads `Clinical` at every level; there is deliberately no clinical granularity, because we do
  not QA clinical categorisation and a precise clinical leaf we cannot stand behind is worse than an
  honest hand-off.
  ⚠️ **It must NOT become an escape hatch.** `Clinical` requires **positive evidence of a clinical
  item**. Absence of evidence is `Uncertain` — never `Clinical`. This is measurable: the rate at v3
  was **167 of 500 (33.4%)**, and a materially higher figure means the model is using it as a
  dumping ground rather than a finding.

**b. ⚠️ NOT BUILT — the MSD warning light on step 1.** *(`msd.py` is known-wrong and `qa_vendor` does not exist. Everything in this sub-section is agreed and pending, not in force. It also predates the v4 reversal, so its reference to "description + GL + cost centre" is now description ALONE — see § 2.)* Agreed in `PLAN.md` v3.27 change 156 and confirmed
against the record on 2026-08-14 — this is not a new rule, it is an old one finally being built.
Step 1 says the vendor name sets the neighbourhood, which assumes the vendor **has** one — exactly
what a non-`coherent` label denies. Where the vendor is not trusted, **step 1 stops constraining**
rather than merely stops contributing: weight shifts to description + GL + cost centre, confidence
drops, and `basis` says so. **The MSD adds no step.**

- **Only `coherent` is trusted.** `incoherent`, `inconclusive`, no-call and the junk labels
  (`ok` / `failed` / `needs_review`) all mean the supplier is not assumed correct — **so
  *unevaluated* is not-trusted.**
- **A human lock on the vendor outranks the label.** 2 of the 5 currently locked vendors still read
  `incoherent`; without this we would distrust a supplier *because* a person fixed it.
- **An incoherent vendor is still judged and still gets a suggestion.** Incoherent describes the
  MSD's record of the supplier, not whether the hospital filed the line correctly.
- **Expected effect, measured in advance:** trust lanes by spend are coherent 72.2% · incoherent
  15.3% · unevaluated 12.5%. The pilot's 180 incoherent-vendor lines currently read **105 Correct /
  20 Incorrect / 55 Uncertain**, judged blind. **Some of those 105 should become Uncertain. That is
  the guard working, not a regression** — do not report it as one.

**c. Three models vote; two must agree.** The judge moves from Claude to NVIDIA NIM with a jury of
`nvidia/nemotron-3-super-120b-a12b` (primary), `openai/gpt-oss-120b` and
~~`mistralai/mistral-large-2-instruct`~~ **`google/gemma-4-31b-it`** — three lineages, because three models from one family share failure modes and their agreement proves nothing. ⚠️ **The Mistral model was never used**: it returned HTTP 404 (not entitled on this account). `meta/llama-3.3-70b-instruct` replaced it, then went unhealthy mid-run on 2026-08-17 — timing out on a 16-token prompt — and Gemma replaced that. **Being listed by `/v1/models` is not the same as being available.** `RUN_LOG.md` Findings 86, 88.

- 2 of 3 agree → that is the verdict. **Three-way split → `Uncertain`, flagged as split.**
- **Verdict and suggested category are voted separately.** Two models can agree a line is
  `Incorrect` and disagree on where it belongs; that is an honest `Incorrect` with no agreed
  destination, not a failure.
- **The deterministic backend outranks all three.** A contradiction proven from the data is not
  something three opinions overturn.
- ⚠️ **2-of-3 raises reliability, not correctness.** It removes one model's off moment; it cannot
  remove a wrong prior all three share. **Agreement is a triage signal, never a calibration one** —
  the same trap as the analyst override rate (§ *the finding is immutable*).
- ~~Every model's raw answer is kept in `qa_line_vote`~~ — **that table was never created.** Sameer, 2026-08-14: *"our qa_line database can never have more than 2000 rows ... yes we can go with addtional colums but not rows."* **The three votes live in COLUMNS on the same row** — `NIM_1..3_{MODEL,VERDICT,CONFIDENCE,SUGGESTED_KEY}` — with the consensus in `NIM_VERDICT` / `NIM_AGREEMENT`.

---

## 1. The question the judge is asked

Not *"what category would you pick"* — that measures the judge against itself. The question is:

> **Is this line in the right bucket, given the buckets this hospital actually has?**

So the candidate set comes from `qa_category`, filtered to that one client, and never from the
model's imagination. A category that does not exist at that hospital is **rejected at write time**,
not stored.

`Uncertain` is a real answer. It is excluded from **both** sides of the accuracy figure with its
share stated plainly. A judge with no Uncertain bucket is a judge that has been asked to bluff.

---

## 2. The evidence hierarchy — Sameer's, set 2026-08-03, **step 3 REVERSED 2026-08-17**

It says how to **weigh** evidence. Steps 1, 2 and 4 are unchanged since v2.

| Step | Rule | Basis recorded |
|---|---|---|
| **1** | **The vendor name sets the neighbourhood.** It bounds what is plausible and is **never sufficient on its own.** A vendor called Traffic Management cannot sit under Food and Beverage whatever the line says. Its job is **detecting contradictions, not picking categories** | — |
| **2** | **The item description picks the category** within that neighbourhood. Vendor + description is the **only** basis for a confident verdict | `vendor_and_description` |
| **3** | 🔒 **THERE IS NO THIRD SOURCE.** ~~No usable description → vendor + `gl_account_name` + cost centre → a calculated call at lower confidence~~ **REVERSED — no usable description → `Uncertain`, routed to the analyst for manual sorting** | `no_evidence` |
| **4** | **No evidence at all** → `Uncertain`. Never a guess | `no_evidence` |

**Never return `Correct` on the vendor name alone.** 61.8% of Northern's rules fire on
`VENDOR_NAME`, so agreeing with a vendor-fired rule on vendor evidence is the judge confirming the
rule's own input. I once proposed *"ignore the vendor"* instead; Sameer corrected it — that throws
away real signal. The guard is step 1, not discarding the vendor.

### 🔒 Why step 3 was reversed — Sameer, 2026-08-17

> *"we have a hard rule that the GL will never be used to make any judge or assumption, neither the
> cost centre. If the vendor is incoherent, obviously supplier name wouldnt just be enough, but in
> this case we would need to make some sense through the item description, if the item description
> doesnt give us that granularity, it would be manually sorted by the analyst ... no rules will ever
> fire in the future with just the gl code."*

**The fields are REMOVED FROM THE PAYLOAD, not merely forbidden in the prompt.** A field that is
present is a field a model can read whatever the instructions say, and nothing afterwards would show
that it had. The only guarantee that evidence was not used is that it was never supplied. Verified
on real units rather than asserted — `emit_batch` sends **vendor · item_text · has_usable_text ·
assigned · assigned_in_taxonomy · rule · spend**, and a real unit contains no GL or cost-centre key.

**It closes a circularity nobody had measured.** 38 of 352 rules fire on `ACCOUNT NAME` (37) or
`CHARGED COST CENTRE` (1) and categorised 199 pilot lines. Showing the judge the same GL the rule
fired on had it **confirming the rule's own input** — the identical trap step 1 already guards
against for vendors.

🔒 **The rules themselves are NOT our concern, and saying otherwise was my overreach.** Sameer,
2026-08-17: *"if the rules are wrttien based on gl for now thats fine, you dont make any changes to
that, the analyst will deal with it later, you dont need to, all i said is the judge cant use GL and
cost centre as a field to judge."* ~~A rule that fires on GL alone is itself a finding for the fix
queue~~ — **struck. He never said it and it does not follow.** The instruction governs **what the
judge may read**, nothing else. The 38-rule measurement is kept only because it explains *why*
removing the field from the judge matters; it is **not** a defect list and must never be reported as
one.

⚠️ **The cost, measured before it was spent:** 297 pilot lines have no usable description and
**189 of them held a firm verdict resting on GL — those become `Uncertain`**, 9.4% of the pilot.
Full-scale equivalent **388,510 lines (14.1%)**. That is the size of the manual queue this rule
creates, and it is the right trade if a verdict grounded in an accounting code is not one we would
defend in front of a client.

**Confidence must show how strong the evidence was.** ~~Vendor + description beats vendor + GL~~ —
there is no vendor + GL step any more. The live distinction is a **specific** item text on a
coherent vendor versus a **vague** one. ⚠️ `NIM_BASIS` does not currently record this at all — see
§ 10's closing note. Broken, excluded from every extract, not yet fixed.

---

## 3. The nine adjudication rules

v2 said how to weigh evidence. It said nothing about **what to do when the taxonomy itself is
defective** — so those calls were made per batch, from memory, and drifted. The proof: a doctor's
CME claim came back `Incorrect` at Western and `Correct` at Northern, on the **same taxonomy leaf**,
until it was caught by hand and 12 Western verdicts were flipped. At a million units nobody catches
that.

### A — A placeholder is not a category, and is never `Correct`

Leaves reading `Not Yet Categorized`, `Non Yet Categorized`, or a bare `Other` name no category —
they record that the work was not done.

> **Measured: 41 such leaves hold 283,258 in-scope lines.** Melbourne's
> `Food and Beverage > Not Yet Categorized` alone is **96,016 lines**; Northern's
> `Corporate Services > Non Yet Categorized` **27,559**; Western's `General Admin Supplies > Other`
> **26,434**.

Where the evidence points to a real leaf → `Incorrect` + suggestion. Where it does not → still
`Incorrect`, unless there is no usable evidence at all, which is `Uncertain`. **Say in the rationale
that it is a placeholder rather than a wrong category** — the fix differs in kind. The client is not
correcting a mistake, they are finishing a job.

### B — An undefined overlap between *sibling* leaves is a taxonomy fault, not a line error

When two leaves under the same parent both plausibly hold the item and **neither carries a
definition that separates them**, the assignment is `Correct`. Say so in the rationale.

> `Stationery & Printing` sits beside `General Office Supplies` at **all four hospitals**, and
> **neither leaf carries a definition** at any of them.

Marking such lines `Incorrect` charges the client for an error they cannot fix line by line, and
inflates the error rate with our own preference.

**This does not excuse a real mismatch.** A wireless mouse, a litre of UHT milk or an iPad in
General Office Supplies is `Incorrect` on the description, and the overlap has nothing to do with
it. *(Checked: all 25 such verdicts across Melbourne, Northern and Western turn on the item, not on
the overlap. No re-judging was needed.)*

### C — The same leaf name must mean the same thing at every hospital

> **Measured: 182 of the 261 distinct in-scope leaf names appear at more than one client**, and
> **798 of the 1,462 model-judged lines (54.6%) sit in one of them.** This governs the majority of
> the work, not an edge case.

Judge the fact pattern, not the hospital. `Reimbursements > Doctor Payments` is byte-identical at
Northern and Western — a doctor's conference-fee claim is `Correct` at both. **Where two hospitals'
accuracy differs, that difference must come from their data, not from the judge changing its mind
between batches.**

### D — No suitable leaf exists → `Incorrect` with **no** suggestion

This taxonomy covers non-clinical spend. A clinical consumable filed somewhere non-clinical is
`Incorrect` and there is nowhere right to send it. Leave the suggestion empty and say the taxonomy
has no home for it. **The gap is the finding**; forcing the nearest leaf hides it and hands the
client a fix that is also wrong.

### E — A vendor substring match may have reached a different company

When the rule fires on a `CONTAINS` test, check the vendor **is** that business rather than merely
containing the string.

- `NH-0870` fires on `HEALTHCARE AUSTRALIA` (a nursing agency) and matched **GE HEALTHCARE
  AUSTRALIA** — an anaesthetic machine repair filed as *Recruitment Agency Fees*
- `MEL-0722` fires on the word `PAPER` and filed **paper hand towels** as *Stationery & Printing*,
  against a `DOMESTIC CLEANING & TOILET MTL` GL that says otherwise
- `SAH-0169` fires on a vendor name containing the two letters **`DR`**

### F — A description holding two different things is `Uncertain`

Where the text carries both a repair authorisation and a lease instalment, or reads
`UN-ORDERED DAIRY AND MEAT ITEM`, the line does not say which it is and neither do we. Do not pick
the more likely one and present it as a finding.

### G — Follow the hospital's own settled practice where the taxonomy is genuinely silent

`lines_using_it` on each candidate shows where the weight is. **This is the weakest rule and ranks
below A–F:** established practice can itself be the defect, so it settles ties, it does not overrule
the description.

### H — A category *finer* than the taxonomy is not an error

`assigned_in_taxonomy` is computed per line and carries four values:

| Value | Meaning | How to judge |
|---|---|---|
| `exact` | the assigned path is one of `candidate_categories` | normal rules |
| `finer_than_taxonomy` | sits **under** a real category, with a sub-leaf the taxonomy lacks | judge at the grain the taxonomy **can** express; if the item belongs under that parent it is `Correct` |
| `branch_not_in_taxonomy` | even the parent is absent | judge on the evidence; if nothing fits, rule D |
| `uncategorised` | no category path at all | `scope_status = in_scope_uncategorised`, **not** a wrong category |

Sydney Adventist's `CBoard Lookup` files a spinach and feta triangle as
`Bakery > Savoury Baked Goods` where the loaded taxonomy stops at `Bakery > Bakery`. That is a
second categorisation mechanism working properly, **not a rule to fix.**

### I — The field the rule fired on is never independent evidence — whichever field it is

`rule.read_the_description` covers only the description. **Read `rule.fires_on` as well.** When it
tests `ACCOUNT NAME`, the GL is the rule's own input, and confirming the category from that GL alone
re-runs the rule exactly as agreeing with a vendor-fired rule on vendor evidence does.

> `SAH-0198` fires on `ACCOUNT NAME CONTAINS FREIGHT`, and **52 of its lines carry no description at
> all** — so the GL is the only evidence there is.

Such a line is usually still `Correct` — an account named FREIGHT is where a carriage charge
belongs, and a person made that coding decision — **but the verdict is corroboration-free and the
confidence must say so.** Look for a second, independent source first: a description, a cost centre,
a vendor whose evident business settles it.

---

## 4. Taxonomy defects found while grounding these rules — both bigger than the rules

### 283,258 in-scope lines (~10%) are assigned to a leaf that names no category

41 placeholder leaves. See rule A. This is not a mis-categorisation the client corrects; it is work
not yet done, and it should be reported as its own finding.

### 49 category paths are carried by more than one `category_key`, inside a single client's own taxonomy

**588,795 in-scope lines.** Northern has **33 keys** on one identical path
(`Soft Facilities Management > Food and Beverage > Food`), Western **22**, Sydney Adventist **21**.
Melbourne has 3 keys on `ICT > Hardware > Desktop / Laptop / …` (125,783 lines).

**This does not affect our verdicts** — the judge compares paths, not keys, and a suggestion
resolves to the same path either way. It is a client-side finding, and it is **why "the wrong key"
can never be reported as a line-level error.**

---

## 5. Results — all four hospitals, pilot, 500 lines each

| Hospital | Correct | Incorrect | Uncertain | **Accuracy** | Uncertain share |
|---|---:|---:|---:|---:|---:|
| Melbourne Health | 140 | 213 | 147 | **39.7%** | 29.4% |
| Northern Health | 227 | 137 | 136 | **62.4%** | 27.2% |
| Western Health | 286 | 76 | 138 | **79.0%** | 27.6% |
| Sydney Adventist | 311 | 42 | 147 | **88.1%** | 29.4% |

Accuracy = `Correct / (Correct + Incorrect)`. **Uncertain is excluded from both sides.**

**Self-consistency: 211 identical (vendor + item + assigned category) lines were judged more than
once, and 0 came back with different verdicts.** This check is what removing the grouping buys back,
and it costs nothing.

1,462 of 2,000 lines carry a model verdict; the remaining 538 are deterministic (`Uncertain` for the
uncategorised stratum and the unjudgeable, plus contradictions).

### Why the spread is so wide — it is mostly taxonomy depth, not care

**Melbourne's taxonomy is deep, so a vendor-name dumping-ground rule lands somewhere visibly wrong.
Western's is shallow, so the same rule lands somewhere defensible.** Same vendor, opposite outcome:
Viva Energy fuel is *Vehicle Repairs* at Melbourne (wrong) and *Petrol and Diesel* at Western
(right). **The accuracy figures are not a league table of how well each hospital is run.**

---

## 6. Sydney Adventist — the finding that reframes `CBoard Lookup`

`CBoard Lookup` is not a RuleID. It is a second categorisation mechanism, and it was on the open-
questions list as a gap. **It is the best-performing mechanism of the four hospitals.**

| Mechanism | Correct | Incorrect | Uncertain | n | **Accuracy** |
|---|---:|---:|---:|---:|---:|
| **`CBoard Lookup`** | 200 | 2 | 2 | 204 | **99.0%** |
| SAH's own RuleIDs | 111 | 39 | 31 | 181 | **74.0%** |
| No rule (uncategorised) | 0 | 1 | 114 | 115 | — |

**Sydney Adventist's 88.1% is carried by CBoard, not by its rules.** Its rules score 74.0%, between
Northern and Western.

**CBoard is a food catalogue.** Both of its two errors are its only non-food lines — a dishwashing
technician's labour and a rethermalisation equipment item. On food it is essentially perfect,
because it looks the product up rather than pattern-matching a vendor name.

### It categorises against a *different, richer* taxonomy than the one we measure against

> **147 of Sydney Adventist's 500 pilot lines (29.4%) carry an assigned path that is not in the
> loaded `Adventist_Taxonomy` at all.** Every one of them is `CBoard Lookup`.
> **Melbourne 14 (2.8%). Northern 0. Western 0.**

Of those 147:

- **112 are a refinement** — the parent resolves. `Bakery > Savoury Baked Goods`, `Meat > Poultry`,
  `Beverages > Concentrate Syrup`, `Dairy > Cream` under parents the taxonomy does carry
- **35 sit under branches the taxonomy does not have at all** — `Processed Foods`,
  `Ready to Eat meals`, `Frozen Products`, `Confectionery`, `Cooking Oil`, `Nutritional
  Supplements`, `Protein Products - Veg`

**All 147 were judged `Correct`.** Under rule H that is the honest answer: a mandarin filed as
`Fruits` and a KitKat filed as `Chocolate` are right, and the missing branch is a fact about our
copy of the taxonomy, not about the line.

⚠️ **Open question for Monali:** is the loaded `Adventist_Taxonomy` a *different generation* from the
one CBoard writes against? Sydney Adventist's taxonomy was replaced mid-session once before. One of
the 35 is only a spelling difference — `Safety Equipment & PPE` against the taxonomy's
`Safety Equipment and PPE`.

### Sydney Adventist's fix queue

| Rule | Incorrect lines | What it does |
|---|---:|---|
| `SAH-0089` | **18** | Fires on GL `SWADDLE RECEIVABLES` and files **per-patient doctor receivables** as *Recruitment > Doctor / Consultant*. Those lines carry a patient ID and name, not a service period — they are medical services rendered, not temp staffing |
| `SAH-0260` | 7 | Sends every Winc line to *Packaging & Materials* while the GL reads `STATIONERY` |
| `SAH-0192` | 2 | Fires on GL containing `R&M` and files every trade as *Electrical Installation and Maintenance* — including locker servicing |
| `SAH-0023` | 2 | Sends a facilities contractor's work to *Building Repairs* even when the cost centre reads `AIRCONDITIONING` and an HVAC leaf exists |

The date-range lines under `AGENCY` and `CONTRACT SALARIES` genuinely **are** contracted doctors and
were judged `Correct`. The defect is specific to the `SWADDLE RECEIVABLES` account.

---

## 6b. Uncategorised lines — the one case where the judge sees the WHOLE taxonomy

**A blank `Category Level 0` means nobody classified the line. It does not mean the line is
non-clinical.** We had been assuming it did.

> **Measured 2026-08-05, full population: 413,338 lines carry no category at all — 4.92% of
> 8,405,829.** Northern **12.55%** · Sydney Adventist 6.36% · Melbourne 3.33% · Western 1.05%.
> **136,217 of them (33.0%) come from vendors whose categorised spend is ≥90% clinical.**

Restricted to the non-clinical candidate list, the judge had no way to *say* "this is clinical" —
so every one of those lines would have come back as indirect. Sameer caught it before a single
suggestion was written.

**How it works now.** For uncategorised lines **only**, the judge is given that hospital's **full**
taxonomy — clinical, inter-hospital and non-clinical — and picks the real leaf. No new column was
needed: **`SUGGESTED_CATEGORY_LVL_0` already records which branch the answer landed in, so the
suggestion IS the scope call.**

Three guarantees, all verified:

| | |
|---|---|
| **The verdict never changes** | An uncategorised line has no existing category to be right or wrong about, so `Uncertain` was already correct. Only the empty suggestion columns are filled |
| **The scope guard is per LINE, not per batch** | An out-of-scope key is accepted only on a line with no category of its own. A line that already carries a category can still only be redirected inside the indirect branches |
| **These lines are in no accuracy figure** | They cannot be `Correct` or `Incorrect`, so nothing is distorted either way |

**Result on the 500 pilot lines:** Non-Clinical 207 (41.4%) · **Clinical 167 (33.4%)** ·
Non-Procurement 2 · no suggestion possible 124 (24.8%). The 33.4% judged clinical against 33.0%
predicted from vendor history is **two independent methods landing 0.4 points apart.**

**The 124 without a suggestion are a finding, not a failure.** Categories missing from *both*
branches at the client concerned: pharmacy dispensing and packaging · oral nutritional supplements
and thickened fluids · continence and ostomy · patient handling and slings · orthopaedic implants at
Northern · intravenous fluids · endoscope reprocessing · regional anaesthesia sets · occupational
health — **and Western has no safety equipment or PPE branch at all.**

---

## 7. What is *not* settled

- **The `Adventist_Taxonomy` generation question above.** Until it is answered, Sydney Adventist's
  88.1% rests on a yardstick that may not be the one in use
- **No golden set exists.** Nothing independent measures whether the judge is right. Override data
  is **not** a golden set — the analyst sees our answer first and is anchored to it, so agreement
  reads higher than the truth. It monitors; it does not calibrate
- **A structurally missing level reads `(no level 0 in this taxonomy)`.** Whether it should instead
  share `(not used at this level)` is unanswered — asked, not yet decided
- **`build_pilot.py` still has no superseded-run purge.** One real incident already
- **Suggestion confidence has nowhere to live.** `confidence` describes the **verdict**, and all 500
  uncategorised lines carry the deterministic `1.0`. The suggestion's own strength is written in
  words at the front of each rationale — `SUGGESTION (strong)` / `(moderate)` / `(weak)` /
  `NO SUGGESTION`. A numeric version needs its own column; overloading one column with two meanings
  would be worse than the words. **Sameer to decide**

---

## 8. Where this lives

| Thing | Path |
|---|---|
| The rules, as executed | `pipeline/judge.py` — `emit_batch()`, instruction block |
| The version stamp — **the live judge** | `qa_line.NIM_PROMPT_VERSION` — **`v5` on all 2,000 rows** |
| The version stamp — Claude's older layer | `qa_line.PROMPT_VERSION` — **`v2` on 1,127 rows, `v3` on 873**. ~~`v3`~~ |
| Which step decided a line | `qa_line.NIM_BASIS` ⚠️ **broken, see § 7** · `qa_line.basis` on the older layer |
| Where the assigned path sits | computed at emit time as `assigned_in_taxonomy`; not stored |
| The dated record | `RUN_LOG.md` Findings 56 and 57; current state in `TRACKER.md` |
| The plan of record | `PLAN.md` |
| Where we are right now | **`TRACKER.md`** |

⚠️ **Corrected 2026-08-18 by measurement.** This table read *"`qa_line.PROMPT_VERSION` — `v3`"*, which
was wrong three ways at once and had been since v5 landed: it named the **older Claude layer** rather
than the live judge, it asserted **one** value where the column actually holds **two**, and it omitted
`NIM_PROMPT_VERSION` entirely. § 0 of this same document said `v5` throughout — **a file contradicting
itself, which is the exact defect v3.43 change 243 struck three times in here already.** The lesson is
not "keep the docs in sync": it is that **a version stamp is a measurement and belongs in a table only
with the query that produced it.**

*(There is no § 9. The numbering has skipped it since the document was written; left as-is rather than
renumbered, because every cross-reference elsewhere points at § 10, § 11 and § 12 by number.)*

---

## 10. `NIM_ACTION` — the verdict says WHAT, the action says SO WHAT

**Live since 2026-08-14.** Written by `pipeline/action_classify.py`, column `qa_line.NIM_ACTION`.
Sameer, 2026-08-14: *"at a later point im going to forget what the actions actually mean, so make a
note so we dont leak any knowledge."* **This section is that note.** The same five definitions live
in the `ACTIONS` dict at the top of `action_classify.py`, and the script prints them beside its
tally so the meaning travels with the numbers rather than sitting in a file nobody opens.

### Why a second column was needed at all

We replaced four hospital taxonomies with one merged tree. **A category can therefore have a new
address without the hospital having done anything wrong.** Measured 2026-08-14 on the pilot:

```
248 lines (12.4%) sit under a level-1 branch the merge moved or renamed
     Rates, Taxes and Adjustments   was level 1   ->  three levels down, under Corporate Services
     General Admin Supplies         was level 1   ->  under Corporate Services
     Maintenance, Repairs and Ops   was level 1   ->  under Facilities Management
28% of those lines came back Incorrect
```

**Telling a hospital it misfiled spend when WE moved the shelf is a false finding**, and it is the
kind that destroys trust in every other finding in the file. The verdict cannot carry the
distinction, because a re-map and a real error both answer *"no, not in the right place"*. So the
action carries it — **beside the verdict, never instead of it.**

### The five values

| Action | Means | Whose issue | What the analyst does |
|---|---|---|---|
| **No change** | Filed correctly and completely | nobody's | nothing |
| **Re-mapped** | Filed correctly — **we** moved the category | **ours** | bulk-approve; it is a migration, not a decision |
| **Incomplete** | Never finished — no category at all, or a top level with placeholders below it. We filled in the detail | theirs, but a **gap**, not an error | fast read; check the detail we added |
| **Miscategorised** | Genuinely the wrong branch, and we say where it belongs | theirs — a **real error** | **this is the queue that needs judgement** |
| **Needs evidence** | We cannot act — either the evidence did not settle it, or we know it is wrong and cannot say where | data quality / judge defect | nothing yet; needs more information |
| **Out of scope** 🆕 | Not an indirect line. The judge placed it in a **Clinical** branch, which is outside this programme | the clinical categorisation project's | nothing — and **do not count it as an error** |

### 🆕 A SIXTH VALUE — `Out of scope`, added 2026-08-17, and the reason is a mistake of mine

Sameer chose five values and this is a sixth; **one word from him removes it.** It exists because
**73 lines were being reported as `Needs evidence` when the judge had answered them clearly.**

⚠️ **I reported those 73 to him as a DEFECT** — *"suggestions pointing at Clinical, not a
destination an analyst can use"*. **That was wrong, and it was a diagnosis error rather than a code
one.** They are the *designed* behaviour: an uncategorised line is shown the client's **full**
taxonomy precisely so it can be filed as clinical, because that is how a line gets recorded as
outside this programme — see § 0's *"`Clinical` is a HANDOFF MARKER, not a category"*, set by
Sameer on 2026-08-14. Measured: **all 73 sit on uncategorised lines; zero sit on a line that
already had a category.**

So the suggestion was right and **the label was wrong**. `Needs evidence` tells an analyst to go and
find information that already exists, on a line whose answer is *"this is clinical — it is not
ours."* **That is the worst kind of queue item: work that looks real and is not.**

### The decision table, in order — and order is the whole design

```
0. suggestion sits in a Clinical branch       -> Out of scope     <- NEW, and it must be FIRST
1. verdict Uncertain                          -> Needs evidence
2. verdict Incorrect and NO suggested key     -> Needs evidence
3. assigned path is placeholders below L1     -> Incomplete
4. suggestion == the crosswalk's target       -> Re-mapped
5. verdict Correct and the category moved     -> Re-mapped
6. verdict Incorrect                          -> Miscategorised
7. otherwise (Correct, nothing moved)         -> No change
```

**Rule 0 sits above rule 1, and it has to.** These lines carry verdict `Uncertain` — an uncategorised
line has no category to be right or wrong about, so the verdict never moves — which means rule 1
catches them first and buries a definite answer under "we could not tell". `Non-Procurement` is
**not** out of scope: it is in scope and identifies the accounting-noise reporting segment.

**Rule 3 sits before rules 4 and 6 deliberately.** A path of placeholders is not a wrong answer, it
is an **absent** one, and it must be classified before anything asks whether the branch is right.
Level 1 is the test, never level 0 — level 0 is the scope gate and was never a categorisation
decision.

**Rule 2 exists because 302 of 614 Incorrect verdicts carry no destination.** Folding them into
`Miscategorised` would put rows an analyst **cannot act on** into the one queue that is supposed to
be actionable, which defeats the entire point of splitting verdict from action.

### 🔒 THE ACTION IS A LOOKUP. NEVER ASK A MODEL FOR IT

*"Is this a rename or a real error"* has a **factual** answer, already written down in
`output/Taxonomy/Indirect Taxonomy - CROSSWALK - <date>.csv`, which maps every old hospital path to
its new home. Put that question to a model and you get a judgement call on a matter of fact — and an
inconsistent one across 2,000 rows, since nothing forces it to answer the same way twice.

`action_classify.py` re-derives the **whole** column on every run. That is safe *only* because it is
a lookup that accumulates nothing; if it ever starts remembering, this property is gone.

### ⚠️ Compare CANONICAL paths, never padded ones — this cost 307 false findings

The first run reported **568 Re-mapped**. Hand-checking five rows — rather than trusting the total —
found:

```
OLD  Logistics > Transport > Patient Transport
NEW  Logistics > Transport > Patient Transport > Patient Transport
```

**Nothing moved.** That is `pad_to_four()` repeating the leaf to fill four levels, and `PLAN.md`
already states that `canonical()` is the single truth for identity while padding is display-only.
Comparing the padded strings would have hung a migration note on **307 lines whose category never
changed**. The fix imports `canonical()` from `merge_taxonomy` — **the existing function, not a
second copy of the logic** — before comparing.

```
Re-mapped 568 -> 261        No change 397 -> 704
```

A genuine insertion still shows, and should:
`Fleet and Vehicles > Parking & Tolls` → `Fleet and Vehicles > Fleet Operating Costs > Parking & Tolls`

### The measured split, 2,000 pilot lines, 2026-08-14

```
  action            Correct  Incorrect  Uncertain    TOTAL
  No change             704          0          0      704
  Re-mapped             200         61          0      261     <- 61 rescued from being FALSE findings
  Incomplete              0         60          0       60
  Miscategorised          0        191          0      191     <- the only queue needing judgement
  Needs evidence          0        302        482      784
  TOTAL                 904        614        482    2,000
```

**The analyst queue is 191 lines, not 614.** ⚠️ `Needs evidence` hides two different problems and
the report always prints the split: **482 Uncertain** (the evidence did not settle it — a data
problem) **+ 302 Incorrect with no destination** (we know the line is wrong and cannot say where —
a **judge** defect, and a bigger one than it looks).

### ⚠️ Where this changes a number, say so

`Incomplete` is neither *"you were right"* nor *"you were wrong"* — it is *"you never finished, and
we have."* Sameer's own worked example lands here rather than where he expected it: Davies Bakery is
assigned `Food and Beverage > Not Yet Categorized > Not Yet Categorized > Not Yet Categorized` —
**one level of four filled** — so it reads **Incorrect + Incomplete**, not Correct + Re-mapped.
Calling it Correct would tell a hospital the line is properly categorised when three levels are
empty.

**Folding `Incomplete` into Correct would move pilot accuracy from ~60% to ~70% without a single
line changing.** That is fine as a decision on the record. It is not fine as a side effect of a
label, because the next reader cannot see it happened.

### 🔒 A `Re-mapped` row MUST say where it moved to — added 2026-08-17 after Sameer found 135 that did not

He read line 825152 (Bunzl, paper cups under Catering Services) and asked: *"why is my suggested
category blank ... if Verdict is correct and Nim action is remapped why have you left those blanks,
it should be filled in from a category from our new indirect taxonomy."* He is right, and the
omission was mine.

**Why it happened, recorded so it is not repeated.** There are two ways a row becomes `Re-mapped`,
and only one of them produces a suggestion:

| | judge said | destination came from | was it filled? |
|---|---|---|---|
| rule 4 | **Incorrect**, and its suggestion matched the crosswalk target | the judge | yes — 32 rows |
| rule 5 | **Correct**, but the crosswalk shows the category moved | **the crosswalk** | **NO — 135 rows** |

**I treated the suggestion columns as belonging to the judge** — *"what the model recommends"*. But a
judge that answers `Correct` offers no suggestion, because there is nothing to correct. So every row
reaching rule 5 had an empty destination, and rule 4's rows looked fine, which is why it went
unnoticed. **A `Re-mapped` row without an address says "this category moved" and not where to,
which is most of the useful information gone.**

**For a `Re-mapped` row the destination never came from the judge in the first place.** It comes from
the crosswalk — a fact we already hold. Filling it is a **lookup, not a verdict**, so it does not
touch the judge's layer; it completes a row the judge was never asked about.

**The guard, so the data never has to be read to find this again.** `action_classify.py` now reports:

```
  Re-mapped rows with NO destination:       0   OK
  Miscategorised rows with NO destination:  0   OK
```

Both must be zero. A `Miscategorised` row without a destination is not a miscategorisation finding
at all — it belongs in `Needs evidence`, which is the bucket for *"wrong, and we cannot say where"*.

⚠️ **`Incomplete` rows are deliberately NOT filled.** The crosswalk maps a *category*, and an
Incomplete line has not got one — only the judge can answer, and where it did not, the blank is
honest rather than an oversight.

⚠️ **ORDER MATTERS: run `action_classify.py` AFTER every judging run, never before.** A re-judge
rewrites `NIM_SUGGESTED_KEY` from the consensus, which is `NULL` for a `Correct` verdict — so it
clears the crosswalk fill, and only a re-classify puts it back. Judge first, classify second, every
time.

**A note on the column name.** `NIM_SUGGESTED_CATEGORY_*` carries two slightly different meanings
depending on the action: for `Miscategorised` it is *"where this should be filed instead"*, for
`Re-mapped` it is *"the new address of a category that was already right"*. `NIM_ACTION` tells the
reader which one they are looking at. Kept in one column deliberately — a second one would be
another place an analyst has to know to look.

### 🚫 `NIM_BASIS` IS BROKEN — DO NOT READ IT

Discovered 2026-08-14 while choosing review columns. It is meant to record **which** evidence step
decided the verdict, which is the standing instruction *"confidence must show which step decided
it."* It does not:

```
no_evidence              1,527
deterministic_*            463
vendor_and_description      10      <- ten. out of two thousand.
```

**1,307 lines carry a firm verdict, a usable description, and a basis of `no_evidence`** — self-
contradictory — while their own rationales plainly cite the evidence (*"Royal Flying Doctor Service
clearly provides patient transport, matching the 'Patient Transport' leaf"*). **The judging is
sound; the label recording how it judged is defaulting.** Left unfixed in v3.40 and **excluded from
every review extract** — reading it would suggest the jury guessed on three-quarters of the file,
which is not true.

---

## 11. `NIM_AGREEMENT` is a TRUST SIGNAL — measured, not assumed

**Measured 2026-08-14** by running the same 2,000 lines through the same three models with the same
prompt at temperature 0, **twice**, and comparing. `RUN_LOG.md` Finding 88.

### The jury contradicts itself on 1 line in 12

```
  identical verdict   1,829 / 2,000   91.5%
  changed               171            8.6%       68 Correct->Incorrect vs 54 the other way
```

Roughly symmetric, so it is **noise, not drift**. And **temperature 0 is not determinism on hosted
infrastructure** — batching, floating-point order and mixture-of-experts routing all vary with
whatever else is in flight. This is a property of the method. It is not a bug waiting to be fixed,
and no prompt change will remove it.

### Agreement predicts which verdicts hold

```
  run-1 agreement   lines    stability on a re-run
  3of3              1,324         98.5%      <- act on these
  2of2                 35         82.9%
  2of3                624         79.0%
  split                17         17.6%      <- a coin toss
```

Confidence works too, less sharply: `0.9-1.0` 95.0% · `0.7-0.9` 90.5% · `under 0.7` 80.5%.

**Two rules follow, and they are binding:**

1. **`NIM_AGREEMENT` appears on every analyst-facing extract.** It costs nothing — it is already on
   the row — and it is the only field that says which individual verdicts to trust.
2. **A `split` row is NEVER presented as a finding.** It resolves to `Uncertain` by design, and now
   we know it holds barely one time in six. It belongs in the review queue, not in a report.

### ⚠️ AGGREGATE IS REPRODUCIBLE. THE LINE IS NOT. Do not conflate them

```
               run 1    run 2    move
  Correct        904      889     -15
  Incorrect      614      624     +10
  accuracy     59.6%    58.8%   -0.8pp
```

**171 individual lines flipped and the headline moved 0.8 points**, because the errors cancel.

- **A hospital-level accuracy figure is reproducible** — quote it, subject to the separate and
  untouched requirement to re-measure on a spread sample first.
- **A line-level verdict is not, unless it is unanimous.** *"This line is miscategorised"* carries a
  ~1-in-12 chance of reading differently next time, and **4-in-5 if the jury split.** An analyst
  told a line is wrong who finds it right will discount the next hundred rows, which is how a true
  finding rate gets thrown away by an unmarked unstable one.

**If line-level verdicts must be dependable, the answer is REPEAT RUNS, not a better prompt** — the
same 2-of-3 logic applied across repeats of the same jury. That triples the run time, so it is a
cost decision and it sits with Sameer (`ACTIONS.md`).


---

## 12. `MSD_COHERENCE` — the MSD's read on the vendor. **A flag beside the vendor name, NEVER a judge input**

Added 2026-08-17 at Sameer's request: *"i just need the 4/5 tab names which are coherent,
inchoherent, inconclusive, unevaluated and no match sitting next to the vendor name col, thats all."*
Written by `pipeline/msd_coherence.py`. `PLAN.md` v3.45, `RUN_LOG.md` Finding 90.

### What the column answers — and what it does not

The MSD (`PI_Master_Supplier_Database_v2`) asks a **different question from ours**:

> *Does this vendor's web-derived description agree with what it actually invoices for?*

That is **step 1 of the evidence hierarchy — "the vendor name sets the neighbourhood"** — answered
independently, by another team, from evidence we do not hold. It says nothing about whether any
particular line is in the right category, and it names no category.

🔒 **IT IS A FLAG, NEVER AN INPUT.** It is not in `emit_batch`'s payload and must never be added.
A verdict resting on vendor coherence is a verdict resting on the **vendor alone** — which is exactly
what § 2 step 1 exists to prevent, and the same trap as agreeing with a vendor-fired rule on vendor
evidence (61.8% of Northern's rules fire on `VENDOR_NAME`).

Its legitimate use is the one the vendor name already has: **detecting contradictions, and telling a
reader how much weight the vendor context deserves.**

### ✅ It does NOT reintroduce the GL

Checked on the **input**, not asserted from the design — because this is the identical shape to the
`rule.fires_on` leak (§ 0 / Finding 89), where deleting the obvious field left the evidence in plain
sight somewhere else. A real coherence prompt was read out of `llm_call_logs`:

> *"You are given (1) a short web summary of what the supplier is/does, and (2) anonymised invoice
> evidence: the supplier's LARGEST line items. The line items describe ONLY what the supplier bills
> for; they say nothing about any buyer..."*

**Web summary plus item descriptions. No GL code, no GL name, no cost centre.** Sameer's rule of
2026-08-17 holds.

### The five values

| Value | Means |
|---|---|
| `coherent` | The MSD looked, and the vendor's billing matches its stated business |
| `incoherent` | The MSD looked, and the two **clearly contradict** each other |
| `inconclusive` | The MSD looked and **could not tell** — the line items were too generic |
| `unevaluated` | The MSD holds the vendor but has **never scored** it |
| `no match` | The vendor is **not in the MSD** under this client at all |

⚠️ **`inconclusive` and `unevaluated` are different facts and are never merged.** "Looked and could
not tell" is evidence about the *vendor*; "never looked" is evidence about the MSD's *coverage*.

### How it is built — two things that are easy to get wrong

**1. The vendor joins VERBATIM, on both sides.** `pi_client_vendors.client_vendor_name` holds the raw
ERP string we already pull, employee numbers and all (`PATEL(95364), MANISHA`). Nothing is trimmed,
case-folded or cleaned on either side — the standing vendor-name rule governs the **join** as much as
the stored value. **1,982 of 2,000 pilot lines match exactly (99.1%).**

**2. ⚠️ `pi_vendors.invoice_coherence` CANNOT be thresholded, despite `MSD_COHERENCE_CUT` existing.**
The decimal does **not** map 1:1 to the verdict word — measured across the whole MSD, `inconclusive`
appears at **0.5 and at 0.25**, and 0.25 sits inside the incoherent range. Reading the score against
the 0.5 cut silently files those vendors as `incoherent`: a wrong answer that looks like a clean one.
The verdict word exists only in `llm_call_logs.raw_output`, so that is what is read, taking the
**latest** coherence call per vendor. **`MSD_COHERENCE_CUT` is deliberately unused by this column.**

### Measured on the pilot — and it says the opposite of the obvious guess

```
coherent       409 vendors   1,526 lines   76.3%
unevaluated    127 vendors     214 lines   10.7%
incoherent      67 vendors     178 lines    8.9%
inconclusive    36 vendors      63 lines    3.1%
no match        10 vendors      19 lines    0.9%
```

⚠️ **An incoherent vendor is NOT more likely to be miscategorised.** It is *less* likely:

```
Miscategorised rate       coherent 11.4%  ·  incoherent 7.9%  ·  unevaluated 1.9%  ·  inconclusive 0.0%
Needs-evidence rate       inconclusive 77.8%  ·  unevaluated 73.8%  ·  incoherent 53.9%  ·  coherent 45.2%
```

What it tracks is our own **`Needs evidence`**, because the MSD's *"I could not tell"* and ours have
the **same cause — thin item descriptions**. A vendor too generic for the MSD to score is a vendor
too generic for our judge.

🔑 **So read it as a DATA-COVERAGE signal, not an error predictor**, and describe it that way to
anyone reading the table. ⚠️ Small n on `inconclusive` (63 lines / 36 vendors) — never quote that
0.0% without the count beside it.

### Refresh and staleness

The column is a **snapshot of another team's live database**; as-at of the current generation is
**2026-08-17 11:15:50**, recorded in `RUN_LOG.md` Finding 90 rather than in a second column (Sameer
has flagged column bloat, and the fix makes it moot). Re-run `pipeline/msd_coherence.py` to refresh.
**The future `qa_line` view resolves it live** — Sameer, 2026-08-17: *"our qa_line table will feed
into a view in the future which will give us a live snapshot"* — at which point the stored column
becomes the fallback rather than the source.
