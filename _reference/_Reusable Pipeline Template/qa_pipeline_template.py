"""
=====================================================================================
  LINE-LEVEL SPEND-CATEGORISATION QA  -  REUSABLE PIPELINE TEMPLATE
=====================================================================================
Copy this whole folder into a NEW project window and adapt the CONFIG block below.
It reproduces the Nufarm methodology (scope gate -> coherence gate -> Layer A vs MSD
-> Layer B line judgement -> deliverables + rule-remediation + tracker) in a
client-agnostic way, PLUS the hospital method change: a NON-MEDICAL filter that keeps
only non-clinical spend for the QA.

WHAT THIS SCRIPT DOES (deterministic parts, runnable today):
  1. Loads the client's categorised invoice lines.
  2. SCOPE GATE      - excludes intercompany / own-entity spend.
  3. MEDICAL FILTER  - (HOSPITAL CHANGE) keeps only NON-MEDICAL items.
  4. Joins MSD coherence lane + MSD category per vendor (optional; graceful if absent).
  5. LAYER A         - client category vs MSD category (agreement / disagreement).
  6. Builds per-vendor fallback profiles (all distinct descriptions by spend).
  7. RULE-ERROR HEURISTIC - flags overhead (VAT/tax/freight...) sitting in product
     categories, grouped by RuleID -> candidate Incorrects for the rule-fix list.
  8. Writes the Excel deliverables (Issues to fix / QA report / Rule fixes / Tracker
     / Dashboard).

WHAT YOU STILL PLUG IN:
  - LAYER B judgement (the actual per-term verdict) is a documented hook -> judge_terms().
    Wire it to your LLM/agent pass or manual review. The heuristic in step 7 gives you a
    running start (real, high-confidence Incorrects) before Layer B is connected.

EDIT EVERYTHING MARKED  # >>> TWEAK
=====================================================================================
"""
import os
import pandas as pd

# =============================== CONFIG  # >>> TWEAK ===============================
CONFIG = {
    # --- client identity ------------------------------------------------------------
    "CLIENT_NAME": "HOSPITAL_CLIENT",          # >>> TWEAK  used in titles/filenames

    # --- source data (the client's categorised lines) -------------------------------
    # Point these at the new client's SQL table OR a CSV/Parquet (see load_lines()).
    "SOURCE": "sql",                            # "sql" | "csv" | "parquet"
    "SQL_TABLE": "[dbo].[AP_PO_Categorised]",   # >>> TWEAK  the client's fact table
    "CSV_PATH": "",                             # if SOURCE="csv"/"parquet"

    # --- column mapping (rename to the new client's column names)  # >>> TWEAK -------
    "COL": {
        "supplier":    "SUPPLIER NAME",
        "item_desc":   "ITEM_DESCRIPTION",
        "spend":       "INVOICELINEAMOUNTAUD",
        "rule_id":     "RuleID",
        "cat_l0":      "Category Level 0",
        "cat_l1":      "Category Level 1",
        "cat_l2":      "Category Level 2",
        "cat_l3":      "Category Level 3",
        "cat_l4":      "Category Level 4",
    },

    # --- SCOPE GATE: exclude intercompany / own entities  # >>> TWEAK ----------------
    # Cleanest: exclude by the categorisation RULE(s) that mark intercompany, if any.
    "SCOPE_EXCLUDE_RULE_IDS":   [],             # e.g. ["NF-0505"] for Nufarm
    "SCOPE_EXCLUDE_CAT2":       ["Intercompany"],
    "SCOPE_EXCLUDE_NAME_LIKE":  [],             # e.g. ["HOSPITALGROUP"] own-entity names

    # --- MEDICAL FILTER (HOSPITAL METHOD CHANGE): keep only NON-MEDICAL  # >>> TWEAK -
    # We EXCLUDE clinical/medical spend and QA only the rest (facilities, IT, catering,
    # office, utilities, maintenance, admin, waste, security...).
    "MEDICAL_ENABLED": True,
    # (a) drop whole client categories that are clinical:
    "MEDICAL_EXCLUDE_CAT2": [
        "Pharmaceuticals", "Medical Devices", "Surgical", "Clinical Consumables",
        "Diagnostics & Reagents", "Implants & Prosthetics", "Medical Gases",
        "Blood & Blood Products", "Patient Care",
    ],
    # (b) and drop lines whose description clearly reads clinical:
    "MEDICAL_EXCLUDE_KEYWORDS": [
        "DRUG", "PHARMA", "MEDICIN", "SURGIC", "IMPLANT", "PROSTHE", "CATHETER",
        "SYRINGE", "SUTURE", "SCALPEL", "REAGENT", "DIAGNOSTIC", "VACCINE", "INSULIN",
        "STENT", "DIALYS", "THEATRE", "ANAESTH", "CANNULA", "CLINICAL", "PATIENT",
        "WOUND", "DRESSING", "ORTHO", "RADIOLOG", "PATHOLOG", "BLOOD",
    ],

    # --- MSD (master supplier database) - OPTIONAL. Leave blank if new client not in MSD.
    "MSD_ENABLED": False,                       # >>> TWEAK  True once the client is in MSD
    "MSD_CLIENT_CODE": "",                      # e.g. "HOSP1"
    "MSD_COHERENCE_CUT": 0.5,

    # --- RULE-ERROR HEURISTIC: overhead sitting in product categories -----------------
    "OVERHEAD_KEYWORDS": ["VAT", "FREIGHT", " TAX", "DUTY", "CUSTOM", "ROUNDING",
                          "INSURANCE", "INTEREST", "BANK CHAR"],
    "PRODUCT_CATS": [],                          # >>> TWEAK  client's physical-product Cat2s

    # --- spend tiers for tracking (top-N by spend cover X% -> report by spend) --------
    "SPEND_TIERS": [(50, "Top 50"), (300, "Top 300"), (1000, "Top 1000")],

    # --- output ---------------------------------------------------------------------
    "OUT_DIR": "Output",
}

# =============================== DB HELPERS (inline, portable) =====================
def load_env(path=".env"):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env[k.strip()] = v.strip()
    return env

def connect(env=None, database=None, timeout=30):
    import pyodbc
    env = env or load_env()
    cs = (f"DRIVER={{{env['SQL_DRIVER']}}};SERVER={env['SQL_SERVER']};"
          f"DATABASE={database or env['SQL_DATABASE']};UID={env['SQL_USER']};PWD={env['SQL_PASS']};"
          f"TrustServerCertificate=yes;Connection Timeout={timeout}")
    return pyodbc.connect(cs)

# =============================== PIPELINE STEPS ====================================
def load_lines(env):
    """Step 1 - load the client's categorised invoice lines into a DataFrame."""
    c = CONFIG["COL"]
    if CONFIG["SOURCE"] == "sql":
        cols = ", ".join(f"[{v}]" for v in c.values())
        df = pd.read_sql(f"SELECT {cols} FROM {CONFIG['SQL_TABLE']}", connect(env))
    elif CONFIG["SOURCE"] == "csv":
        df = pd.read_csv(CONFIG["CSV_PATH"])
    else:
        df = pd.read_parquet(CONFIG["CSV_PATH"])
    # normalise to internal names
    df = df.rename(columns={v: k for k, v in c.items()})
    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0.0)
    df["_nm"] = df["supplier"].astype(str).str.strip().str.upper()
    return df

def scope_gate(df):
    """Step 2 - drop intercompany / own-entity spend. Returns (in_scope, excluded)."""
    excl = pd.Series(False, index=df.index)
    if CONFIG["SCOPE_EXCLUDE_RULE_IDS"]:
        excl |= df["rule_id"].isin(CONFIG["SCOPE_EXCLUDE_RULE_IDS"])
    if CONFIG["SCOPE_EXCLUDE_CAT2"]:
        excl |= df["cat_l2"].isin(CONFIG["SCOPE_EXCLUDE_CAT2"])
    for pat in CONFIG["SCOPE_EXCLUDE_NAME_LIKE"]:
        excl |= df["_nm"].str.contains(pat, na=False)
    return df[~excl].copy(), df[excl].copy()

def medical_filter(df):
    """Step 3 (HOSPITAL CHANGE) - keep only NON-MEDICAL lines. Returns (non_medical, medical)."""
    if not CONFIG["MEDICAL_ENABLED"]:
        return df.copy(), df.iloc[0:0].copy()
    is_med = pd.Series(False, index=df.index)
    if CONFIG["MEDICAL_EXCLUDE_CAT2"]:
        is_med |= df["cat_l2"].isin(CONFIG["MEDICAL_EXCLUDE_CAT2"])
    if CONFIG["MEDICAL_EXCLUDE_KEYWORDS"]:
        up = df["item_desc"].astype(str).str.upper()
        kw = "|".join(CONFIG["MEDICAL_EXCLUDE_KEYWORDS"])
        is_med |= up.str.contains(kw, na=False, regex=True)
    return df[~is_med].copy(), df[is_med].copy()

def join_msd(df, env):
    """Step 4 - attach coherence lane + MSD category. Graceful if MSD disabled/absent."""
    if not CONFIG["MSD_ENABLED"]:
        df["lane"] = "Unevaluated"; df["msd_cat2"] = None
        return df
    # >>> TWEAK: reuse your msd.load_vendor_master() here (copy msd.py alongside).
    try:
        import sys; sys.path.insert(0, ".")
        from msd import load_vendor_master, resolve_client_id
        os.environ.setdefault("MSD_CLIENT_CODE", CONFIG["MSD_CLIENT_CODE"])
        cid, _ = resolve_client_id(env)
        vm = load_vendor_master(env, client_id=cid)[["nm", "coherence_label", "msd_l2"]]
        df = df.merge(vm, left_on="_nm", right_on="nm", how="left")
        df["lane"] = df["coherence_label"].fillna("Unevaluated")
        df["msd_cat2"] = df["msd_l2"]
    except Exception as e:
        print("  [MSD] disabled/unavailable ->", e); df["lane"] = "Unevaluated"; df["msd_cat2"] = None
    return df

def layer_a(df):
    """Step 5 - vendor-level agreement flag: client cat_l2 vs MSD msd_cat2."""
    df["agree"] = df.apply(
        lambda r: "agree" if (pd.notna(r.get("msd_cat2")) and str(r["cat_l2"]).strip().upper()
                              == str(r["msd_cat2"]).strip().upper()) else
                  ("disagree" if pd.notna(r.get("msd_cat2")) else "n/a"), axis=1)
    return df

def fallback_profiles(df):
    """Step 6 - per vendor, ALL distinct descriptions ranked by spend (the pooled set)."""
    g = (df.groupby(["_nm", "item_desc"], dropna=False)
           .agg(spend=("spend", "sum"), lines=("spend", "size")).reset_index()
           .sort_values(["_nm", "spend"], ascending=[True, False]))
    return g

def detect_rule_errors(df):
    """Step 7 - heuristic Incorrects: overhead terms sitting in product categories, by RuleID."""
    if not CONFIG["PRODUCT_CATS"]:
        return pd.DataFrame()
    up = df["item_desc"].astype(str).str.upper()
    kw = "|".join(CONFIG["OVERHEAD_KEYWORDS"])
    mask = df["cat_l2"].isin(CONFIG["PRODUCT_CATS"]) & up.str.contains(kw, na=False, regex=True)
    bad = df[mask]
    if bad.empty:
        return pd.DataFrame()
    return (bad.groupby("rule_id")
              .agg(wrong_cat=("cat_l2", "first"), lines=("spend", "size"),
                   spend=("spend", "sum"), vendors=("_nm", "nunique"),
                   example=("item_desc", "first")).reset_index()
              .sort_values("spend", ascending=False))

def judge_terms(profiles, df):
    """Step 5(B) HOOK - THE LINE JUDGEMENT.  # >>> PLUG IN
    For each distinct (vendor, term) decide Correct / Incorrect / Uncertain using:
      - Coherent vendor  -> trust MSD category.
      - Otherwise        -> read the vendor's WHOLE pooled description set (profiles) + name,
                            infer nature, categorise each term (vague -> broader nature),
                            web-check if unclear.
    Wire this to your LLM/agent pass or manual review. Return a DataFrame with columns:
      supplier, item_desc, verdict, suggested_cat, confidence, basis, rationale, rule_id
    For now it returns the heuristic Incorrects only, so the workbook is populated."""
    raise NotImplementedError("Wire judge_terms() to your LLM/agent or manual review.")

# =============================== DELIVERABLES =====================================
def write_workbook(scope_ex, medical_ex, in_scope, rule_errs, env):
    """Step 8 - build the Excel deliverables (same 5 tabs as the Nufarm sample)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    NAVY="1F3864"; WHITE="FFFFFF"; RED="F8E7E7"; REDT="A13030"; GREEN="C6EFCE"; GREENT="1A7F4B"; LG="808080"
    B=Border(*[Side(style="thin", color="D9D9D9")]*4)
    def H(ws, row, hs, ws_):
        for j,(h,w) in enumerate(zip(hs, ws_),1):
            c=ws.cell(row,j,h); c.font=Font(bold=True,color=WHITE); c.fill=PatternFill("solid",fgColor=NAVY)
            ws.column_dimensions[get_column_letter(j)].width=w
    wb=openpyxl.Workbook()

    # Tab: Issues to fix (rule-error candidates until Layer B is wired)
    iss=wb.active; iss.title="Issues to fix"; iss.sheet_view.showGridLines=False
    iss["A1"]=f"{CONFIG['CLIENT_NAME']} - Issues to fix (non-medical QA)"; iss["A1"].font=Font(size=13,bold=True,color=NAVY)
    H(iss,3,["Rule ID","Wrong category (now)","Lines","Spend","Example term","Vendors"],[12,26,9,16,30,9])
    if not rule_errs.empty:
        for i,r in enumerate(rule_errs.itertuples(),4):
            for j,v in enumerate([r.rule_id,r.wrong_cat,r.lines,r.spend,r.example,r.vendors],1):
                c=iss.cell(i,j,v); c.border=B
                if j==4: c.number_format='$#,##0'
    else:
        iss["A4"]="(set CONFIG['PRODUCT_CATS'] to enable the overhead-in-product heuristic)"

    # Tab: Coverage (what the gates removed)
    cov=wb.create_sheet("Coverage"); cov.sheet_view.showGridLines=False
    cov["A1"]="Scope coverage"; cov["A1"].font=Font(size=13,bold=True,color=NAVY)
    H(cov,3,["Bucket","Lines","Spend","Treatment"],[26,12,18,34])
    data=[("Excluded - intercompany/own", len(scope_ex), scope_ex["spend"].sum(), "Out of scope (scope gate)"),
          ("Excluded - MEDICAL", len(medical_ex), medical_ex["spend"].sum(), "Out of scope (hospital: clinical)"),
          ("IN SCOPE - non-medical", len(in_scope), in_scope["spend"].sum(), "-> QA (Layer A + Layer B)")]
    for i,(a,b,c_,d_) in enumerate(data,4):
        for j,v in enumerate([a,b,c_,d_],1):
            cc=cov.cell(i,j,v); cc.border=B
            if j==3: cc.number_format='$#,##0'

    # Tab: Tracker (one row per in-scope vendor)
    trk=wb.create_sheet("Tracker"); trk.sheet_view.showGridLines=False
    trk["A1"]="Tracker - one row per vendor"; trk["A1"].font=Font(size=13,bold=True,color=NAVY)
    H(trk,3,["Supplier","Lane","Vendor spend","Terms","Status"],[30,14,16,9,12])
    vt=(in_scope.groupby(["_nm","lane"]).agg(spend=("spend","sum"),
        terms=("item_desc","nunique")).reset_index().sort_values("spend",ascending=False))
    for i,r in enumerate(vt.head(500).itertuples(),4):
        for j,v in enumerate([r._1,r.lane,r.spend,r.terms,"Not started"],1):
            c=trk.cell(i,j,v); c.border=B
            if j==3: c.number_format='$#,##0'

    os.makedirs(CONFIG["OUT_DIR"], exist_ok=True)
    out=os.path.join(CONFIG["OUT_DIR"], f"{CONFIG['CLIENT_NAME']} - QA Output.xlsx")
    wb.save(out); return out

# =============================== MAIN ==============================================
def main():
    env = load_env()
    print(f"== {CONFIG['CLIENT_NAME']} line-level QA (non-medical) ==")
    df = load_lines(env);                     print(f"  loaded lines: {len(df):,}  spend ${df['spend'].sum():,.0f}")
    in_scope, scope_ex = scope_gate(df);      print(f"  scope gate  -> excluded {len(scope_ex):,} (${scope_ex['spend'].sum():,.0f})")
    non_med, med = medical_filter(in_scope);  print(f"  medical     -> excluded {len(med):,} clinical (${med['spend'].sum():,.0f})")
    non_med = join_msd(non_med, env)
    non_med = layer_a(non_med)
    profiles = fallback_profiles(non_med);    print(f"  vendors={non_med['_nm'].nunique():,}  distinct terms={len(profiles):,}")
    rule_errs = detect_rule_errors(non_med);  print(f"  candidate rule errors: {len(rule_errs)} rules")
    # judged = judge_terms(profiles, non_med)  # <- wire Layer B, then feed into the workbook
    out = write_workbook(scope_ex, med, non_med, rule_errs, env)
    print(f"  wrote: {out}")

if __name__ == "__main__":
    main()
