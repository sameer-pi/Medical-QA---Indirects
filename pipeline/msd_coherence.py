#!/usr/bin/env python
"""MSD_COHERENCE — put the MSD's vendor-coherence status beside the vendor on every qa_line row.

Sameer, 2026-08-17: *"i just need the 4/5 tab names which are coherent, inchoherent, inconclusive,
unevaluated and no match sitting next to the vendor name col, thats all ... our qa_line table will
feed into a view in the future which will give us a live snapshot."*

WHAT THIS IS
------------
The MSD (`PI_Master_Supplier_Database_v2`) asks a different question from ours: *does this vendor's
web-derived description agree with what it actually invoices for?* That is the JUDGE'S STEP 1 —
"the vendor name sets the neighbourhood" — answered independently, by another team, from evidence
we do not hold.

🔒 IT IS A FLAG, NEVER AN INPUT. This column tells a reader how much to trust the vendor as
context. It must never be fed to the judge and must never pick a category: a verdict resting on
vendor coherence is a verdict resting on the vendor alone, which is the exact failure the evidence
hierarchy's step 1 exists to prevent (61.8% of Northern's rules fire on VENDOR_NAME — agreeing with
a vendor-fired rule on vendor evidence is the judge confirming the rule's own input).

⚠️ AND IT DOES NOT REINTRODUCE THE GL. Checked before building, not assumed — because this is the
same shape as the `rule.fires_on` leak (PLAN v3.44 change 241), where deleting the obvious field
left the evidence in plain sight somewhere else. A real coherence prompt was read from
`llm_call_logs`: it is given a web summary of the supplier plus the supplier's largest invoice LINE
ITEM DESCRIPTIONS, explicitly anonymised, and told the items "say nothing about any buyer". No GL
code, no GL name, no cost centre. Sameer's rule of 2026-08-17 survives.

THE FIVE VALUES — Sameer's own words, kept verbatim so the column reads the same as the tab he
knows it from:

    coherent       the MSD looked, and the vendor's billing matches its stated business
    incoherent     the MSD looked, and they CLEARLY contradict each other
    inconclusive   the MSD looked and could not tell — the line items were too generic
    unevaluated    the MSD has the vendor but has never scored it
    no match       the vendor is not in the MSD under this client at all

⚠️ `inconclusive` and `unevaluated` are DIFFERENT FACTS and are not merged. "Looked and couldn't
tell" is evidence about the vendor; "never looked" is evidence about the MSD's coverage. Collapsing
them would hide which of the two a gap is.

HOW THE VENDOR IS MATCHED — VERBATIM, both sides
------------------------------------------------
`pi_client_vendors.client_vendor_name` holds the RAW ERP string, the same one we pull. Melbourne's
employee-number format arrives intact on both sides (`PATEL(95364), MANISHA`), so no normalising is
needed and none is done — the standing rule that the vendor name is never trimmed, case-folded or
cleaned applies to the JOIN as much as to the stored value. Measured on the pilot: 1,982 of 2,000
lines match exactly, 99.1%.

WHY THE VERDICT WORD IS NOT READ FROM `pi_vendors.invoice_coherence`
--------------------------------------------------------------------
Because it cannot be. The score does NOT map 1:1 to the verdict — measured across the whole MSD,
`inconclusive` appears at 0.5 AND at 0.25, and 0.25 sits inside the incoherent range. Thresholding
the decimal (which is what MSD_COHERENCE_CUT would do) silently files those rows as incoherent.
The verdict word exists only in `llm_call_logs.raw_output`, so that is where it is read from, taking
the LATEST coherence call per vendor. `MSD_COHERENCE_CUT` is deliberately NOT used here.

READ-ONLY, ALWAYS. This script issues SELECTs against the MSD and writes to `qa_line` only.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clientcfg import list_clients, load_config, msd_client_code  # noqa: E402
from db import connect_msd, connect_qa, load_env  # noqa: E402

COLUMN = "MSD_COHERENCE"
DECL = "varchar(16) NULL"

# The MSD's own three verdict words, plus our two. Anything the MSD emits that is not in this map is
# reported rather than silently bucketed — a new verdict word is a change in another team's model
# and we should hear about it, not absorb it.
MSD_VERDICTS = {"coherent", "incoherent", "inconclusive"}
NO_MATCH = "no match"
UNEVALUATED = "unevaluated"

VERDICT_RE = re.compile(r'"verdict"\s*:\s*"([a-z]+)"', re.I)


def verdict_of(raw):
    """Pull the verdict word out of a coherence call's raw JSON output.

    Parsed with a regex first because `raw_output` is not guaranteed to be clean JSON — some rows
    carry the model's prose around it. json.loads is tried as the stricter path and wins when it
    works.
    """
    if not raw:
        return None
    try:
        v = json.loads(raw).get("verdict")
        if isinstance(v, str) and v.strip().lower() in MSD_VERDICTS:
            return v.strip().lower()
    except Exception:  # noqa: BLE001 - prose around the JSON is expected, not exceptional
        pass
    m = VERDICT_RE.search(raw)
    if m and m.group(1).lower() in MSD_VERDICTS:
        return m.group(1).lower()
    return None


def ensure_column(qa, qcur, name, decl):
    qcur.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME='qa_line' AND COLUMN_NAME=?""", name)
    if qcur.fetchone()[0]:
        return False
    qcur.execute(f"ALTER TABLE qa_line ADD {name} {decl}")
    qa.commit()
    return True


def pilot_vendors(qcur):
    """(client_code, supplier_name) -> line count, straight from qa_line. VERBATIM, untrimmed."""
    qcur.execute("""SELECT CLIENT_CODE, SUPPLIER_NAME, COUNT(*)
                    FROM qa_line GROUP BY CLIENT_CODE, SUPPLIER_NAME""")
    return [(r[0], r[1], r[2]) for r in qcur.fetchall()]


def msd_status(mcur, msd_code, names):
    """Resolve one client's vendor names to their coherence status.

    Two steps, because the verdict word is not on `pi_vendors` (see module docstring):
      1. name -> pi_vendor_id, via pi_client_vendors, matched VERBATIM within this client_code
      2. pi_vendor_id -> latest coherence verdict, via llm_call_logs

    Only the pilot's own vendors are resolved, not the client's whole book — 649 names instead of
    29,608, which is the difference between seconds and minutes.
    """
    out = {}
    if not names:
        return out
    todo = [n for n in names if n is not None]
    vid_of = {}
    for i in range(0, len(todo), 900):
        chunk = todo[i:i + 900]
        ph = ",".join("?" * len(chunk))
        mcur.execute(
            f"""SELECT client_vendor_name, MAX(pi_vendor_id)
                FROM pi_client_vendors
                WHERE client_code = ? AND client_vendor_name IN ({ph})
                GROUP BY client_vendor_name""",
            [msd_code] + chunk)
        for nm, vid in mcur.fetchall():
            vid_of[nm] = vid

    ids = sorted({v for v in vid_of.values() if v is not None})
    word_of = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        ph = ",".join("?" * len(chunk))
        # Latest coherence call per vendor. A vendor may be re-scored; the newest is the live answer.
        mcur.execute(
            f"""SELECT l.pi_vendor_id, l.raw_output
                FROM llm_call_logs l
                JOIN (SELECT pi_vendor_id, MAX(log_id) AS mx
                        FROM llm_call_logs
                       WHERE call_type = 'coherence' AND pi_vendor_id IN ({ph})
                       GROUP BY pi_vendor_id) t
                  ON t.pi_vendor_id = l.pi_vendor_id AND t.mx = l.log_id""", chunk)
        for vid, raw in mcur.fetchall():
            w = verdict_of(raw)
            if w:
                word_of[vid] = w

    for nm in names:
        if nm is None or nm not in vid_of:
            out[nm] = NO_MATCH                      # not in the MSD under this client
        else:
            vid = vid_of[nm]
            if vid is None:
                out[nm] = UNEVALUATED               # linked to no PI vendor, so nothing to score
            else:
                out[nm] = word_of.get(vid, UNEVALUATED)
    return out


def main():
    ap = argparse.ArgumentParser(description="Write MSD_COHERENCE onto every qa_line row.")
    ap.add_argument("--dry-run", action="store_true",
                    help="measure and report, write nothing")
    ap.add_argument("--production", action="store_true",
                    help="⚠️ run against PI_Medical_QA_Indirect, not the pilot.")
    args = ap.parse_args()

    env = load_env()
    as_at = datetime.now().replace(microsecond=0)

    code_of = {}
    for key in list_clients():
        mc = (msd_client_code(load_config(key)) or "").strip()
        if not mc:
            print(f"  ! {key}: no msd.client_code in config — its lines will read '{NO_MATCH}'",
                  flush=True)
        code_of[key] = mc

    qa = connect_qa(pilot=not args.production, production=args.production, env=env)
    qcur = qa.cursor()

    qcur.execute("SELECT COUNT(DISTINCT run_id) FROM qa_line")
    n_runs = qcur.fetchone()[0]
    if n_runs != 1:
        print(f"STOP: qa_line holds {n_runs} run_ids, expected 1. "
              f"A superseded generation is still in the table.", flush=True)
        return 1

    # ⚠️ AFTER the dry-run gate, never before it. --dry-run means WRITE NOTHING, and an ALTER TABLE
    # is a write: the first version of this script added the column during a dry run, which is
    # exactly the "a killed process is not a process that did nothing" failure in miniature.
    if not args.dry_run:
        added = ensure_column(qa, qcur, COLUMN, DECL)
        print(f"column {COLUMN}: {'ADDED' if added else 'already present'}", flush=True)

    pv = pilot_vendors(qcur)
    by_client = defaultdict(list)
    for c, s, _n in pv:
        by_client[c].append(s)
    print(f"pilot vendors to resolve: {len(pv)} across {len(by_client)} clients", flush=True)

    msd = connect_msd(env=env)
    mcur = msd.cursor()
    mcur.execute("SELECT DB_NAME()")
    print(f"MSD (read-only): {mcur.fetchone()[0]}   as-at {as_at:%Y-%m-%d %H:%M:%S}", flush=True)

    status = {}
    for client, names in sorted(by_client.items()):
        mc = code_of.get(client, "")
        if not mc:
            for nm in names:
                status[(client, nm)] = NO_MATCH
            continue
        res = msd_status(mcur, mc, names)
        for nm in names:
            status[(client, nm)] = res.get(nm, NO_MATCH)
    msd.close()

    tally = Counter()
    lines = Counter()
    per_client = defaultdict(Counter)
    lines_of = {(c, s): n for c, s, n in pv}
    for (c, s), v in status.items():
        tally[v] += 1
        lines[v] += lines_of[(c, s)]
        per_client[c][v] += lines_of[(c, s)]

    total_lines = sum(lines.values())
    print(f"\n=== {COLUMN} — {total_lines:,} pilot lines ===", flush=True)
    for v, n in lines.most_common():
        print(f"   {v:<14} vendors={tally[v]:>4}   lines={n:>5}  "
              f"({n / total_lines * 100:5.1f}%)", flush=True)
    print("\n   per client, by lines:", flush=True)
    for c in sorted(per_client):
        print(f"     {c:<18} " + "  ".join(f"{v}={n}" for v, n in per_client[c].most_common()),
              flush=True)

    if args.dry_run:
        print("\n--dry-run: nothing written.", flush=True)
        qa.close()
        return 0

    # Write. One UPDATE per (client, vendor) — 649 statements, not 2,000.
    n_rows = 0
    for (c, s), v in status.items():
        if s is None:
            qcur.execute(f"UPDATE qa_line SET {COLUMN}=? WHERE CLIENT_CODE=? AND SUPPLIER_NAME IS NULL",
                         v, c)
        else:
            qcur.execute(f"UPDATE qa_line SET {COLUMN}=? WHERE CLIENT_CODE=? AND SUPPLIER_NAME=?",
                         v, c, s)
        n_rows += qcur.rowcount
    qa.commit()
    print(f"\nwrote {COLUMN} on {n_rows:,} rows", flush=True)

    # --- guards: the column must be complete, and hold nothing but the five values -------------
    qcur.execute(f"SELECT COUNT(*) FROM qa_line WHERE {COLUMN} IS NULL")
    n_null = qcur.fetchone()[0]
    print(f"rows with no {COLUMN}: {n_null}   {'OK' if n_null == 0 else '** INCOMPLETE **'}",
          flush=True)

    allowed = MSD_VERDICTS | {NO_MATCH, UNEVALUATED}
    qcur.execute(f"SELECT DISTINCT {COLUMN} FROM qa_line WHERE {COLUMN} IS NOT NULL")
    found = {r[0] for r in qcur.fetchall()}
    rogue = found - allowed
    print(f"values present: {sorted(found)}", flush=True)
    print(f"unexpected values: {sorted(rogue) if rogue else 'none'}   "
          f"{'OK' if not rogue else '** the MSD emitted a verdict word we do not know **'}",
          flush=True)

    qcur.execute("SELECT COUNT(*), COUNT(DISTINCT run_id) FROM qa_line")
    r = qcur.fetchone()
    print(f"qa_line: {r[0]:,} rows / {r[1]} run_id   "
          f"{'OK' if r[1] == 1 else '** more than one generation, investigate **'}", flush=True)
    print(f"\nas-at {as_at:%Y-%m-%d %H:%M:%S} — this is a SNAPSHOT of a live database owned by "
          f"another team.\nRe-run this script to refresh it; the future qa_line view can resolve it "
          f"live instead.", flush=True)

    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
