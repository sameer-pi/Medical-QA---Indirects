"""MSD (Master Supplier Database) accessors for the line-level QA.

The MSD (PI_Master_Supplier_Database_v2) holds a per-client vendor master. For a client we pull one
enriched row per vendor: its MSD category (L0-L4), business identity (description / industry tags),
and the coherence signal used to decide how far to trust the MSD.

Coherence label (reproduced from the staging UI — NOT stored in the DB; derived from invoice_coherence):
    Coherent    = invoice_coherence >= cut (default 0.5)   -> trust MSD identity/category
    Incoherent  = invoice_coherence <  cut (not null)      -> don't trust -> fallback + review list
    Unevaluated = invoice_coherence IS NULL                -> not yet enriched -> fallback only

Usage:
    from msd import load_vendor_master, resolve_client_id
    cid, code = resolve_client_id()          # MSD_CLIENT_CODE -> pi_client_id
    vm = load_vendor_master(client_id=cid)   # DataFrame, one row per normalized vendor name
"""
import os
import pandas as pd
from db import connect_msd, load_env


def coherence_cut(env=None):
    env = env or load_env()
    try:
        return float(env.get("MSD_COHERENCE_CUT", "0.5"))
    except ValueError:
        return 0.5


def coherence_label(ic, cut=0.5):
    """Coherent / Incoherent / Unevaluated from an invoice_coherence value."""
    if ic is None or (isinstance(ic, float) and pd.isna(ic)):
        return "Unevaluated"
    return "Coherent" if float(ic) >= cut else "Incoherent"


def resolve_client_id(env=None):
    """Resolve pi_client_id from MSD_CLIENT_CODE (e.g. NUFARM -> 14)."""
    env = env or load_env()
    code = (env.get("MSD_CLIENT_CODE") or "").strip()
    if not code:
        raise RuntimeError("MSD_CLIENT_CODE is empty in .env (e.g. NUFARM).")
    cn = connect_msd(env=env)
    try:
        cur = cn.cursor()
        cur.execute("SELECT pi_client_id FROM dbo.pi_clients WHERE UPPER(client_code)=UPPER(?)", code)
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"MSD_CLIENT_CODE '{code}' not found in dbo.pi_clients.")
        return int(row[0]), code
    finally:
        cn.close()


def _norm(s):
    return s.astype(str).str.strip().str.upper()


def load_vendor_master(env=None, client_id=None):
    """One enriched MSD row per client vendor, deduped to one row per normalized name.

    Columns: nm (UPPER-trimmed join key), client_vendor_name, vendor_id, normalized_name,
      msd_l0..msd_l4, msd_description, industry_tags, invoice_coherence, coherence_label,
      enrichment_status, match_confidence, analyst_approved, spend_total.
    Dedup preference on collisions: Coherent > Incoherent > Unevaluated, then highest spend_total.
    """
    env = env or load_env()
    cut = coherence_cut(env)
    if client_id is None:
        client_id, _ = resolve_client_id(env)
    sql = """
        SELECT cv.client_vendor_name, cv.vendor_id, cv.normalized_name,
               cv.category_l0 AS msd_l0, cv.category_l1 AS msd_l1, cv.category_l2 AS msd_l2,
               cv.category_l3 AS msd_l3, cv.category_l4 AS msd_l4,
               cv.spend_total, cv.match_confidence,
               v.pi_vendor_description AS msd_description, v.pi_vendor_industry_tags AS industry_tags,
               v.invoice_coherence, v.enrichment_status, v.analyst_approved
        FROM dbo.pi_client_vendors cv
        LEFT JOIN dbo.pi_vendors v ON cv.pi_vendor_id = v.pi_vendor_id
        WHERE cv.pi_client_id = ? AND cv.is_current = 1
    """
    cn = connect_msd(env=env)
    df = pd.read_sql(sql, cn, params=[client_id])
    cn.close()
    df["nm"] = _norm(df["client_vendor_name"])
    df["spend_total"] = pd.to_numeric(df["spend_total"], errors="coerce").fillna(0.0)
    df["coherence_label"] = df["invoice_coherence"].map(lambda x: coherence_label(x, cut))
    # dedup to one row per normalized name: prefer scored/coherent, then highest spend
    pref = {"Coherent": 0, "Incoherent": 1, "Unevaluated": 2}
    df["_pref"] = df["coherence_label"].map(pref)
    df = (df.sort_values(["_pref", "spend_total"], ascending=[True, False])
            .drop_duplicates("nm").drop(columns="_pref").reset_index(drop=True))
    return df


if __name__ == "__main__":
    # smoke test / summary
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    cid, code = resolve_client_id()
    print(f"Client {code} -> pi_client_id {cid}")
    vm = load_vendor_master(client_id=cid)
    print(f"Vendor master rows (deduped by name): {len(vm):,}")
    print("Coherence split:")
    for lab, g in vm.groupby("coherence_label"):
        print(f"   {lab:12} vendors={len(g):6,}  spend_total=${g['spend_total'].sum():,.0f}")
