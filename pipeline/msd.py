"""MSD (Master Supplier Database) accessors for the line-level QA.

Ported from the Nufarm template (_reference/msd.py). One change: `resolve_client_id` now takes
an explicit `code`, because this project runs several clients and the code comes from each
client's config.yaml rather than a single MSD_CLIENT_CODE in .env.

The MSD (PI_Master_Supplier_Database_v2) holds a per-client vendor master. For a client we pull
one enriched row per vendor: its MSD category (L0-L4), business identity (description / industry
tags), and the coherence signal used to decide how far to trust the MSD.

!!! KNOWN-WRONG AS OF 2026-08-10 - coherence_label() BELOW MUST NOT BE USED IN A RUN !!!
    The claim under it, that the label is not stored in the DB, is FALSE. It is stored in
    llm_call_logs where call_type='coherence': `outcome` holds the verdict and `raw_output`
    holds the JSON the PIDA vendor-detail panel renders. It was missed because pi_vendors has
    no such column and that was generalised to the whole database.

    THE SCORE IS NOT THE VERDICT. Across the four hospitals' 23,222 vendors the 0.5 cut
    disagrees with the stored label on 41 of them, and mislabels 1,127 'inconclusive' vendors
    as never-evaluated. NATIONWIDE CREDIT CONTROL scores 1.00 and is labelled 'incoherent' -
    no threshold on the number recovers that.

    Fix: read the latest coherence row per pi_vendor_id and return `outcome` VERBATIM (six
    values: coherent / incoherent / inconclusive / ok / failed / needs_review, plus no-call).
    Never collapse them. Trust is a SEPARATE binary flag: trusted = (label == 'coherent').
    Retire MSD_COHERENCE_CUT with it. See PLAN.md v3.26 changes 149-153, RUN_LOG Finding 67.

Coherence label (SUPERSEDED - derived from invoice_coherence, see the warning above):
    Coherent    = invoice_coherence >= cut (default 0.5)   -> trust MSD identity/category
    Incoherent  = invoice_coherence <  cut (not null)      -> don't trust -> fallback + review
    Unevaluated = invoice_coherence IS NULL                -> not yet enriched -> fallback only

IMPORTANT (this project): the coherence lane and MSD category are CORROBORATION for the judge,
never the standard. The MSD holds one category per vendor, so a legitimately multi-category
vendor (e.g. Cleanaway -> waste management AND hazardous waste) will disagree with the client's
category on lines that are perfectly correct. See pipeline/enrich.py.
"""
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


def resolve_client_id(code, env=None):
    """Resolve pi_client_id from an MSD client code (e.g. NUFARM -> 14).

    Returns None if the code isn't in the MSD yet — that's an expected state for a new hospital
    client, and callers should fall back rather than fail.
    """
    env = env or load_env()
    code = (code or "").strip()
    if not code:
        return None
    cn = connect_msd(env=env)
    try:
        cur = cn.cursor()
        cur.execute(
            "SELECT pi_client_id FROM dbo.pi_clients WHERE UPPER(client_code)=UPPER(?)", code
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        cn.close()


def list_msd_clients(env=None):
    """Every client code in the MSD — used by profiling to see which hospitals are enriched."""
    env = env or load_env()
    cn = connect_msd(env=env)
    try:
        return pd.read_sql(
            "SELECT pi_client_id, client_code, client_name FROM dbo.pi_clients ORDER BY client_code",
            cn,
        )
    finally:
        cn.close()


def _norm(s):
    return s.astype(str).str.strip().str.upper()


def load_vendor_master(client_id, env=None):
    """One enriched MSD row per client vendor, deduped to one row per normalized name.

    Columns: nm (UPPER-trimmed join key), client_vendor_name, vendor_id, normalized_name,
      msd_l0..msd_l4, msd_description, industry_tags, invoice_coherence, coherence_label,
      enrichment_status, match_confidence, analyst_approved, spend_total.
    Dedup preference on collisions: Coherent > Incoherent > Unevaluated, then highest spend_total.
    """
    env = env or load_env()
    cut = coherence_cut(env)
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
    if df.empty:
        return df
    df["nm"] = _norm(df["client_vendor_name"])
    df["spend_total"] = pd.to_numeric(df["spend_total"], errors="coerce").fillna(0.0)
    df["coherence_label"] = df["invoice_coherence"].map(lambda x: coherence_label(x, cut))
    # dedup to one row per normalized name: prefer scored/coherent, then highest spend
    pref = {"Coherent": 0, "Incoherent": 1, "Unevaluated": 2}
    df["_pref"] = df["coherence_label"].map(pref)
    df = (
        df.sort_values(["_pref", "spend_total"], ascending=[True, False])
        .drop_duplicates("nm")
        .drop(columns="_pref")
        .reset_index(drop=True)
    )
    return df


def coherence_summary(vm):
    """Vendors and spend by coherence lane — the headline number for profiling."""
    if vm.empty:
        return pd.DataFrame(columns=["coherence_label", "vendors", "spend_total"])
    return (
        vm.groupby("coherence_label")
        .agg(vendors=("nm", "size"), spend_total=("spend_total", "sum"))
        .reset_index()
        .sort_values("spend_total", ascending=False)
    )
