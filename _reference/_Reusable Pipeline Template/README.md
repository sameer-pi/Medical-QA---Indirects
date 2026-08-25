# Line-Level Categorisation QA — Reusable Pipeline Template

A client-agnostic starter for running the same QA we built for Nufarm, adapted for a new
client. **Includes the hospital method change: a non-medical filter** so you QA only
non-clinical spend.

## What's in this folder
- `qa_pipeline_template.py` — the pipeline (edit the `CONFIG` block at the top).
- `.env.example` — copy to `.env`, fill in the client's SQL (and MSD, if enriched).
- `msd.py` — MSD accessors (`load_vendor_master` / `resolve_client_id`). **Bundled.** Only
  used when `MSD_ENABLED=True`; otherwise ignored.
- `db.py` — connection helpers (`connect`, `connect_msd`) that `msd.py` uses. **Bundled.**

## The pipeline (same shape as Nufarm)
1. **Load** the client's categorised lines.
2. **Scope gate** — drop intercompany / own-entity spend.
3. **Medical filter (HOSPITAL CHANGE)** — keep only **non-medical** lines; drop clinical.
4. **MSD join** — attach coherence lane + MSD category *(optional; graceful if the client
   isn't in the MSD yet — then everything runs on the fallback)*.
5. **Layer A** — client category vs MSD category (agree / disagree).
6. **Fallback profiles** — per vendor, all distinct descriptions ranked by spend.
7. **Rule-error heuristic** — overhead (VAT/tax/freight…) sitting in product categories,
   grouped by `RuleID` → candidate Incorrects (a running start before Layer B).
8. **Workbook** — Issues to fix / Coverage / Tracker (extend to full 5 tabs as needed).

## Setup in a new project window
1. Copy this folder in (`db.py` + `msd.py` are already bundled). `pip install pandas openpyxl pyodbc`.
2. `cp .env.example .env` and fill in the client SQL.
3. Open `qa_pipeline_template.py` and edit every `# >>> TWEAK`:
   - `CLIENT_NAME`, `SQL_TABLE`, and the **`COL`** column-name mapping (the new client's
     columns will differ from Nufarm's).
   - **Scope gate** — the intercompany rule IDs / category / own-entity name patterns.
   - **Medical filter** — `MEDICAL_EXCLUDE_CAT2` (clinical categories in the client's
     taxonomy) and `MEDICAL_EXCLUDE_KEYWORDS` (refine for this hospital's item text).
   - `PRODUCT_CATS` — the client's physical-product categories (enables the overhead
     heuristic).
   - `MSD_ENABLED` / `MSD_CLIENT_CODE` — turn on once the client exists in the MSD.
4. `python qa_pipeline_template.py` → writes `Output/<CLIENT_NAME> - QA Output.xlsx`.

## What you still wire in
- **Layer B (the actual per-term verdict)** is the hook `judge_terms()`. Connect it to
  your LLM/agent pass or manual review. Until then, step 7's heuristic already gives you
  real, high-confidence Incorrects (tax/overhead in product categories) with their Rule IDs.

## The two big differences vs Nufarm
| | Nufarm | Hospital |
|---|---|---|
| Scope gate | exclude intercompany (`RuleID NF-0505`) | exclude intercompany/own entities |
| **Extra filter** | — | **exclude MEDICAL/clinical → QA non-medical only** |
| Taxonomy | agrochemical | hospital indirect (facilities/IT/catering/admin) |
| MSD | enriched (Coherent/Incoherent/Unevaluated) | likely mostly Unevaluated at first → fallback-heavy |

## Notes
- The **non-medical filter is a two-part switch**: category-based (drops whole clinical
  categories) *and* keyword-based (drops clinical-looking descriptions). Start broad, then
  tighten by reviewing what it excluded — same discipline as the Nufarm scope gate.
- If the hospital client isn't in the MSD, expect a **fallback-heavy** run (read the
  vendor's own lines). That's fine — coverage is still ~100%; it's just less MSD-corroborated.
- Every **Incorrect must carry its Rule ID** (so you fix the rule, not the line) — the
  Issues/Rule-fix outputs are keyed on `RuleID`.
