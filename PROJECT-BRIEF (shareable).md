# Hospital **Indirect** Spend — Categorisation Quality Review

**Project brief · updated 14 August 2026 · Sameer Iyer**

> **Safe to share internally.** This is the plain-language version of the project. The detailed
> technical plan is held separately.

---

## In one paragraph

We categorise four hospitals' accounts-payable spend and show it back to them on a dashboard.
Nobody has ever measured how *accurate* that categorisation is. This project measures it — **line by
line, across every in-scope transaction, with no sampling** — and gives each account manager two
things: a defensible accuracy figure they can quote to their client, and a ranked list of exactly
which categorisation rules to change to improve it.

---

## Scope: indirect (non-clinical) spend only

**This is not a review of medical or clinical item categorisation.** It covers indirect spend —
facilities, waste, catering, IT, professional services, maintenance, consumables and similar.

A line is in scope when both are true:

1. it is **not** classified as Clinical
2. it is **not** inter-hospital spend

Lines the categorisation never touched at all are **included** — and they get more than a flag.
For every uncategorised line, the review suggests where it should go. That matters because an
uncategorised line hasn't yet been through the clinical/non-clinical split: treating it as indirect
by default would quietly file clinical suppliers as non-clinical. **Roughly a third of them turn out
to be clinical.** So the judge can also return a verdict of **Clinical** — meaning *this line is not
indirect spend and belongs to the clinical categorisation work, not to this review*. It is handed
over as exactly that, never silently counted as indirect spend, and never given an indirect category
just because one was available.

One further group is reported separately rather than counted in the headline: **accounting entries**
— depreciation, amortisation, bank charges, loans, superannuation, rates and taxes, workers
compensation. Nobody buys these from a supplier, so an accuracy percentage over them means nothing.
They stay visible in the coverage figures; they just don't dilute the number that matters.

Worth flagging while we are here: **Melbourne classifies those accounting entries differently to
Northern and Western.** The same categories sit under *Non-Clinical* at Melbourne and
*Non-Procurement* at the other two. It doesn't affect this review, which handles both, but it does
mean any cross-hospital comparison of "non-clinical spend" is not comparing like with like.

---

## The four clients

| Hospital | Account manager | Total AP lines |
|---|---|---|
| Melbourne Health | Cathy | 3,449,852 |
| Western Health | Dhruv | 2,347,469 |
| Northern Health | Sakule | 1,744,381 |
| Sydney Adventist | Monali | 864,127 |

Each account manager owns their own hospital's review end to end. Sydney Adventist is NSW — this is
not a Victoria-only program.

**All four hospitals have now passed their data checks** — every column, category structure,
taxonomy link and supplier reference confirmed against the live data rather than assumed.

Measured in-scope volumes:

| Hospital | In-scope lines | In-scope spend |
|---|---|---|
| Melbourne Health | 879,109 | $1,447M |
| Northern Health | 875,018 | $2,971M |
| Western Health | 671,200 | $995M |
| Sydney Adventist | 339,204 | $425M |
| **Total under review** | **2,764,531** | **$5,838M** |

*Northern's figure spans three very different populations — genuinely non-clinical spend, spend that
was never classified, and rates and taxes — so its report will break accuracy out by segment rather
than quote one blended number that would describe none of them accurately.*

---

## What each account manager gets

| Deliverable | Purpose |
|---|---|
| **QA Report** — shareable with the client | Accuracy by segment, coverage, the main error themes, and how it was measured |
| **Working File** — internal | Every categorisation error found, the rule that caused it, and a **suggested correct category** for every incorrect and uncategorised line. This is the fix queue |

Both are per hospital. Nobody has to read another hospital's data to work their own.

---

## Every finding says what to do about it, not just what is wrong

A line that is in the wrong place and a line whose **category has been renamed** are not the same
problem, and it would be unfair to report them as though they were. We have consolidated four
hospitals' separate category lists into one shared list — which means a category can end up with a
new name or sit at a different level **without the hospital having done anything wrong.**

So every reviewed line carries two things: a **verdict** (was it right?) and an **action** (so what
do we do?).

| Action | What it means | Who needs to do anything |
|---|---|---|
| **No change** | Filed correctly and completely | nobody |
| **Re-mapped** | Filed correctly — the category itself has a new name or sits at a different level in the shared list | **us, not the hospital.** Nothing was misfiled |
| **Incomplete** | Never finished — either no category at all, or a top-level heading with nothing filled in beneath it. We have supplied the detail | a quick check of the detail we added |
| **Miscategorised** | Genuinely in the wrong place, and we say where it belongs | **this is the real fix queue** |
| **Needs evidence** | We cannot say — either the line has too little information to judge, or we can tell it is wrong but not where it should go | nothing yet |

**Why this matters more than it sounds.** Without the action, a category we renamed would be
reported to a hospital as a mistake they made. That is a false finding, and a false finding does not
just waste time — it puts every true finding beside it in doubt. Separating the two means the fix
queue an account manager works is materially shorter than the raw count of "incorrect" lines, and
everything in it is genuinely actionable.

**The action is worked out by lookup, not by judgement.** Whether a category was renamed is a matter
of record — we hold the full map from every hospital's old category to its new home, and the action
is read from that map. It is not an opinion, and it gives the same answer every time.

---

## How it works

1. **Read** every in-scope line from the hospital's categorised data — the same view that feeds
   their dashboard.
2. **Judge each line** against **the client's own taxonomy**, using the evidence in a fixed order:
   the supplier's name sets what is *plausible* (a traffic-management company does not sell
   catering), the item description then picks the category, and where the description is blank or
   useless the judgement falls back to the general-ledger account and cost centre — at lower
   confidence, and saying so. Where there is no usable evidence at all, the verdict is
   **Uncertain**, never a guess.
3. **Suggest the correct category** for every line judged Incorrect, and for every uncategorised
   line — drawn from the **single consolidated indirect taxonomy**, the one the four hospitals are
   adopting in place of their four separate ones. A suggestion is never taken from another
   hospital's private structure.
4. **Trace** every error back to the specific rule (or lookup) that caused it, in the specific
   rules table that holds it — rules are per-hospital copies, so a fix must name its table.
5. **Rank the fixes by the number of lines they resolve.** Line count needs no judgement calls;
   ranking by spend would mean deciding which extreme amounts are "real", and that decision is the
   client's, not ours.

Identical lines — same supplier, same wording, same category — naturally receive the same
judgement, and the review checks its own consistency on exactly those lines. That, plus judging
every line rather than a sample, is what makes "a verdict on every line" a promise rather than a
slogan.

---

## Two principles worth stating plainly

**The client's own taxonomy is the standard we judge against.** Each hospital uses its own category
structure, and a line is marked right or wrong against *its* definitions — never against a house
view of how spend ought to be categorised. An accuracy figure measured against the wrong yardstick
is worse than useless. **Where a line should go instead is a separate question**, and from August
2026 the answer is drawn from the consolidated indirect taxonomy the four hospitals are adopting —
so a suggestion can be acted on directly, and the same recommendation means the same thing at every
site. Judged against their structure; pointed at the shared one.

And where the data itself uses categories the taxonomy doesn't contain — which happens, see the
findings below — that mismatch is *reported*; we never invent or add categories on a client's
behalf. What to do about it belongs to the account manager.

**The Master Supplier Database corroborates; it never decides.** Where the MSD and the client
categorisation disagree, that is a question, not a verdict — sometimes the categorisation is wrong,
sometimes the MSD record is wrong, and sometimes a supplier legitimately sells into two categories.
Each of those three has a different owner and a different fix.

That corroboration is now **visible on every line**, in a single column beside the supplier name. It
carries one of five plain words — the supplier's billing is *coherent* with its stated business, is
*incoherent* with it, the check was *inconclusive*, the supplier is *unevaluated*, or there is *no
match* for it at all. It is context for the person reading the line. **It is deliberately never shown
to the model that forms the verdict**, for the same reason the supplier name alone is never enough:
a judgement resting on who the supplier is, rather than on what was bought, is not an audit.

**And it is worth saying what that column turned out not to be.** The obvious expectation is that an
incoherent supplier is the one most likely to be filed in the wrong category. Measured on the pilot,
that is not true — incoherent suppliers are misfiled slightly *less* often than coherent ones. What
the column actually tracks is where the line descriptions are too thin to judge at all: the same
missing detail that stops the supplier check from reaching a conclusion stops our review from
reaching one. It is a signal about **where the data is weak**, not a shortlist of likely errors, and
it should be read that way.

---

## The pilot — complete

The full process has been run end to end on **2,000 lines — 500 per hospital, spread across
suppliers rather than taken from the top of the file.** Every one of the 2,000 now carries a
verdict (Correct, Incorrect, or Uncertain), its reasoning, and — where it was wrong or
uncategorised — a suggested correct category.

The pilot ran the **full** process, not a simplified version: the same evidence rules, the same
taxonomy checks, the same tracing back to rules, on all four hospitals at once. Their data differs
in ways that matter — one has no item descriptions on a third of its lines, another has no written
category definitions — and testing against only one would have left those gaps to surface later at
full scale.

**No accuracy percentage is being quoted yet — deliberately.** The pilot's figures exist, but the
brief's own standard applies: no number is published until the account managers have reviewed a
sample of judgements for their hospital and the review's agreement with their judgement has been
measured. That check is the next step.

---

## What we will be able to say at the end

> *"X% of your in-scope indirect spend is correctly categorised. Here is every line marked Correct or
> Incorrect, the specific rules that caused each error, and what to change. Here is what it is worth
> in spend."*

And after fixes are applied, a **regular tracker** showing whether the numbers are improving,
static, or going backwards — including whether a fix that was applied actually worked, which is the
part that usually goes unmeasured.

The intended destination for all of this is the internal PI Data Analytics app rather than emailed
spreadsheets: the analyst sees each finding, agrees or overrides it, and an agreed correction is
drafted as a rule in the hospital's own rule format. That design is documented and costed
separately; nothing is being built until the pilot results have been reviewed.

---

## What this will not tell you

Stated up front so it isn't discovered later:

- **Accuracy is capped by description quality.** Where a line's item description is blank or
  generic, no amount of analysis recovers the intent. Those lines are reported honestly as
  unjudgeable rather than guessed at.
- **Some calls are genuinely arguable.** Whether *medical gas pipeline maintenance* belongs under
  Facilities or Medical Gases is a matter of interpretation. Every judgement carries its reasoning,
  and borderline cases are routed to the account manager rather than decided silently.
- **Uncertain lines are excluded from the accuracy figure entirely** — not quietly counted as
  correct, and not counted as errors. The percentage of spend we could not judge confidently is
  stated alongside the accuracy figure, every time.
- **Western Health will be measured with a wider margin.** Its taxonomy carries no written category
  definitions, so its borderline calls rest on less evidence than the other three. This is stated in
  its report rather than hidden.

---

## Who does what

| Role | Who | What |
|---|---|---|
| Program + shared supplier records | **Sameer** | Runs the project. Owns corrections to any supplier used by more than one client — one correction there can improve several accounts at once, so it sits in one pair of hands |
| Melbourne Health | **Cathy** | Reviews findings, owns her hospital's rule changes, and owns supplier corrections for suppliers only her hospital uses |
| Western Health | **Dhruv** | As above |
| Northern Health | **Sakule** | As above |
| Sydney Adventist | **Monali** | As above |

Categorisation rules are **per hospital, not shared** — so each account manager's fixes are theirs
alone. What *is* shared is the pattern: a defect found at one hospital usually has an equivalent at
another under a different rule. The value across the group is in the diagnosis, not the remedy.

---

## What is needed from each account manager

1. ~~**Confirm which data view your client's dashboard reads.**~~ ✅ **Done — thank you.** All four
   confirmed, and all four matched what we had assumed, so no work was wasted.
2. **Now — review a sample of the pilot's judgements for your hospital.** This calibrates the
   review against your judgement, so the accuracy figure reflects how your hospital actually
   categorises rather than an outside opinion. Once per hospital, before any number is quoted.
3. **Later — a short list of supplier records to correct**, covering only suppliers your hospital
   alone uses, ranked so the ones that matter come first.

---

## Early findings

The review has already surfaced things worth knowing, before any accuracy figure is published:

- **Rules are only part of how spend gets categorised — and now the whole machinery is mapped.**
  Each hospital also runs lookups (rebate codes, clinical product libraries, and at Sydney
  Adventist a food-service catalogue) ahead of its rules, all feeding one refresh that runs
  monthly. Knowing the precedence order matters practically: at Sydney Adventist, a rule change
  can never override the food catalogue, so corrections there have to go to the catalogue itself.
- **The food-service catalogue is also the best performer in the programme.** It looks products up
  rather than pattern-matching names, and on the pilot it made almost no mistakes — while using
  category names that mostly don't exist in the hospital's own taxonomy. That mismatch is reported
  to the account manager; whether to reconcile the two is the client's call, not ours to make.
- **Duplicate rules exist that file the same supplier under different categories** — within one
  hospital's rules, and at one hospital across its two rules tables, sometimes with the clinical /
  non-clinical boundary itself at stake. Which copy wins is decided by the software's tie-break,
  invisibly. These are exact, listable defects, and the review lists them.
- **A meaningful share of rules never fire at all** — at one hospital roughly a third. Dead rules
  are harmless until someone copies one; the list makes a ready-made clean-up when fixes begin.
- **A rule matching the word "sheet" was filing paper hand towels as catering.** It was matching
  `90 SHEET` — a pack quantity — on paper-towel descriptions. The same rule, with the same fault,
  is live at a second hospital: the hospitals share a rule library but each holds its own copy, so
  it needs fixing in both places.
- **"Categorised" sometimes means "filed as not-yet-categorised".** One hospital holds roughly
  370,000 lines in a category literally named *Not Yet Categorized*, which reads as Clinical on
  the dashboard; another files ~97,000 lines the same way. They are counted as categorised while
  saying they are not. How to treat them is a live decision, and it is a conversation about
  category set-up rather than a rule to correct.
- **Some clinical spend sits inside the indirect population at one hospital** — roughly 9% of its
  in-scope lines. The rule that categorised them says clinical, but the clinical flag on the line
  itself is blank, so the scope test lets them through. That hospital's figure will be reported in
  segments rather than as one blended number.
- **Some invoice lines carry impossible amounts.** At Melbourne, a couple of hundred lines out of
  three and a half million hold values larger than the hospital's entire annual spend. They look
  like a posting fault rather than real transactions, and they are reported to the client as
  found — never silently corrected or excluded by us.
- **The same organisation can appear twice under different names.** Health Purchasing Victoria
  became HealthShare Victoria in a 2021 rename, and both names are still live as separate
  suppliers — 357,604 lines under the old name, 3,253 under the new. Easy to merge, easy to miss.

None of these change the plan. They are the kind of thing a line-level review turns up, and they
are reported as they are found rather than held back to the end.

---

## Where it has got to — 6 August

**The pilot is complete and judged.** All 2,000 pilot lines across the four hospitals carry a
verdict with reasoning; every Incorrect line names the rule that caused it and a suggested correct
category; every uncategorised line carries a suggestion drawn from its hospital's full taxonomy.
The review's internal consistency was checked on identically-worded lines and held without
exception.

Alongside the judging, the categorisation machinery of all four hospitals — the views their
dashboards read, their rules tables, and the authoring workbook rules are written in — has been
read and verified against the live data. The review now knows not just *what* is wrong but *where
a fix has to land* for each hospital, which is what the fix queue needed.

**What happens next, in order:** the technical plan's latest changes are reviewed and signed off;
account managers check a sample of judgements for their hospital; only then are accuracy figures
published and full runs scheduled.

---

## Timing

**No end date is being committed yet, deliberately.** The pilot exists partly to size the work
honestly. A schedule for the four full runs will be given once the pilot review has confirmed the
judgements hold, rather than estimated in advance and revised later.
