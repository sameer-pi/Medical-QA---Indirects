"""PHASE 0 - per-hospital pre-flight. PASS / FAIL in seconds.

    python pipeline/verify_client.py                    # all configured clients
    python pipeline/verify_client.py northern_health

The loop this exists to support: **you configure a hospital, this tells you whether it actually
resolves.** Every check is read-only and cheap - no full table scans, so it can be re-run freely
after every config edit.

It also guards against a failure mode seen on 2026-07-30: a client database was rebuilt during
working hours and its dashboard view stopped compiling mid-session. A structure fingerprint is
printed on every run so "the numbers moved" stays separable from "the ground moved".

Checks, in order of what they cost:
  1  config loads, and clientcfg agrees it is complete
  2  the database connects
  3  the source view exists and COMPILES  (a view can exist and still be broken)
  4  every mapped column exists, and every description field exists
  5  Category Level 0 holds the expected values - the clinical split depends on it
  6  the taxonomy table reads, and the join key is confirmed BY MATCH COUNT, never by name
  7  the rules table reads and is NON-EMPTY  (Western's PMML_Rules_Ordered is empty - that trap)
  8  the MSD client code resolves, with the coherence split
  9  structure fingerprint
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg  # noqa: E402
import msd as msdmod  # noqa: E402
from db import connect_client, load_env  # noqa: E402

# Values Category Level 0 is expected to hold. Anything else is reported, not assumed wrong -
# Sydney Adventist may move to a Category Level 1-5 scheme during its migration.
EXPECTED_CAT0 = {"Clinical", "Non-Clinical", "Non-Procurement", "Inter-Hospital Spend", "Tail Spend"}

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"
_SYM = {PASS: "[ok]  ", FAIL: "[FAIL]", WARN: "[warn]", INFO: "      "}


class Report:
    def __init__(self, client):
        self.client, self.rows, self.failed, self.warned = client, [], 0, 0

    def add(self, level, check, detail=""):
        self.rows.append((level, check, detail))
        if level == FAIL:
            self.failed += 1
        elif level == WARN:
            self.warned += 1
        print(f"  {_SYM[level]} {check:34} {detail}")
        return level != FAIL

    @property
    def verdict(self):
        return FAIL if self.failed else (WARN if self.warned else PASS)


def _bare(table):
    return table.replace("[", "").replace("]", "").split(".")[-1]


def verify(client_key, env):
    r = Report(client_key)
    print(f"\n== {client_key} " + "=" * max(4, 58 - len(client_key)))

    cfg = clientcfg.load_config(client_key)
    if not cfg:
        r.add(FAIL, "config", "clients/%s/config.yaml missing or empty" % client_key)
        return r

    # Cross-client isolation, checked before anything else touches the database. The taxonomy keys
    # COLLIDE across hospitals while meaning different things - Melbourne's key 379 is
    # 'Dairy Products > Cheese', Northern's is 'Facilities Management' - so a config that could
    # reach another hospital's database is refused outright rather than warned about.
    leaks = clientcfg.assert_same_database(cfg, client_key)
    r.add(PASS if not leaks else FAIL, "single-database isolation",
          "all table refs are 1-2 part names" if not leaks else leaks[0][:96])

    problems = clientcfg.missing_for_run(cfg, client_key)
    if problems:
        r.add(FAIL, "config complete", problems[0])
        for p in problems[1:]:
            r.add(INFO, "", p)
        return r
    r.add(PASS, "config complete", f"owner: {clientcfg.account_manager(cfg) or '(unset)'}")

    try:
        cn = connect_client(client_key, env=env)
    except Exception as e:
        r.add(FAIL, "database connects", str(e).strip().splitlines()[0][:110])
        return r
    cur = cn.cursor()
    r.add(PASS, "database connects")

    table = clientcfg.source_table(cfg)
    name = _bare(table)

    # A view can exist in metadata and still fail to compile - this is what happened at Sydney
    # Adventist when its taxonomy table was replaced underneath it. SELECT TOP 0 forces binding
    # without reading data.
    try:
        cur.execute(f"SELECT TOP 0 * FROM {table}")
        cur.fetchall()
        r.add(PASS, "source view compiles", table)
    except Exception as e:
        r.add(FAIL, "source view compiles", str(e).split("]")[-1].strip()[:110])
        cn.close()
        return r

    cur.execute("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?""", name)
    live = {x[0] for x in cur.fetchall()}

    cols = clientcfg.column_map(cfg)
    missing = sorted(c for c in cols.values() if c not in live)
    r.add(PASS if not missing else FAIL, "mapped columns exist",
          f"{len(cols)} mapped" if not missing else f"MISSING: {', '.join(missing)}")

    fields = clientcfg.description_fields(cfg)
    missing_d = [f for f in fields if f not in live]
    r.add(PASS if not missing_d else FAIL, "description fields exist",
          " -> ".join(fields) if not missing_d else f"MISSING: {', '.join(missing_d)}")

    # Report-grade columns. A gap here degrades the deliverable; it does not stop a run, so this
    # is a WARN by design - three of the four clients are missing at least one, and a FAIL would
    # make the pre-flight useless. See smoke_test.py for the measured fill matrix.
    gaps = clientcfg.missing_for_report(cfg)
    r.add(PASS if not gaps else WARN, "report columns mapped",
          f"{len(clientcfg.REPORT_COLUMNS)} present" if not gaps
          else "unmapped: " + ", ".join(gaps))

    # Line identity. Not a given: one client has no RowID and its distribution id repeats on
    # byte-identical rows, so its per-line figures need de-duplication before they are quoted.
    ident = clientcfg.line_identity_fields(cfg)
    r.add(PASS if ident else WARN, "line identity resolvable",
          " + ".join(ident) if ident else "NO identity columns mapped - lines cannot be traced back")

    # --- Category Level 0: the clinical split depends entirely on this ---
    #
    # Compared on TRIMMED values, deliberately. Sydney Adventist stores 'Clinical ' with a trailing
    # space where the other three store 'Clinical'. SQL Server pads on comparison so a SQL filter
    # matches anyway - but Python's == does not, so a pandas-side gate would have let 524,923
    # clinical lines into the in-scope population with nothing to show for it. Whitespace is
    # reported separately as a data-quality warning rather than being allowed to fail the gate.
    c0 = cols.get("cat_l0")
    if c0 and c0 in live:
        cur.execute(f"SELECT DISTINCT CONVERT(nvarchar(80), [{c0}]) FROM {table}")
        raw = [v[0] for v in cur.fetchall()]
        padded = sorted(x for x in raw if x and x != x.strip())
        vals = {(x.strip() if x else "(null)") for x in raw}
        unexpected = sorted(v for v in vals if v != "(null)" and v not in EXPECTED_CAT0)
        excl = {e.strip() for e in
                set(clientcfg.clinical_exclusions(cfg)) | set(clientcfg.scope_exclusions(cfg))}
        absent = sorted(e for e in excl if e not in vals)
        r.add(PASS if not absent else FAIL, "clinical gate values present",
              ", ".join(sorted(excl)) if not absent
              else f"config excludes {absent} but the column never holds it")
        if padded:
            r.add(WARN, "cat_l0 has padded values",
                  "; ".join(repr(x) for x in padded)[:70] + "  -> gates MUST trim")
        if unexpected:
            r.add(WARN, "unexpected cat_l0 values", ", ".join(unexpected)[:90])

    # --- taxonomy join: confirmed by match count, never inferred from column names ---
    tx = clientcfg.taxonomy_table(cfg)
    if tx:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tx}")
            n = cur.fetchone()[0]
            r.add(PASS if n else FAIL, "taxonomy readable", f"{tx} -> {n:,} rows")
            line_key = next((k for k in ("MASTER CATEGORY ID", "CATEGORY ID") if k in live), None)
            if line_key and n:
                cur.execute("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                               WHERE TABLE_NAME=?""", _bare(tx))
                tx_cols = {x[0] for x in cur.fetchall()}
                best, best_n = None, -1
                for cand in ("Master ID", "Category ID"):
                    if cand not in tx_cols:
                        continue
                    cur.execute(f"""SELECT COUNT(*) FROM {table} v JOIN {tx} t
                                    ON t.[{cand}] = v.[{line_key}]""")
                    m = cur.fetchone()[0]
                    if m > best_n:
                        best, best_n = cand, m
                r.add(PASS if best_n > 0 else FAIL, "taxonomy join confirmed",
                      f"[{line_key}] -> {tx}.[{best}] = {best_n:,} matches" if best_n > 0
                      else f"[{line_key}] matches NOTHING in {tx}")
        except Exception as e:
            r.add(FAIL, "taxonomy readable", str(e).split("]")[-1].strip()[:100])

    # --- rules: existing but EMPTY is the trap (Western's PMML_Rules_Ordered) ---
    rt = clientcfg.rules_table(cfg)
    if rt:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {rt}")
            n = cur.fetchone()[0]
            r.add(PASS if n else FAIL, "rules table non-empty",
                  f"{rt} -> {n:,} rules" if n
                  else f"{rt} EXISTS BUT IS EMPTY - the fix queue would come back blank")
            if n:
                cur.execute(f"""SELECT TOP 4 ISNULL([Source],'(null)'), COUNT(*)
                                FROM {rt} GROUP BY [Source] ORDER BY COUNT(*) DESC""")
                tiers = cur.fetchall()
                r.add(INFO, "  rule source tiers",
                      " | ".join(f"{s} {c:,}" for s, c in tiers)[:96])
        except Exception as e:
            r.add(FAIL, "rules table non-empty", str(e).split("]")[-1].strip()[:100])

    # --- structure fingerprint: catches the database moving under us between runs ---
    cur.execute("""SELECT COUNT(*), CHECKSUM_AGG(CHECKSUM(COLUMN_NAME, DATA_TYPE))
                   FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?""", name)
    ncols, fp = cur.fetchone()
    r.add(INFO, "structure fingerprint", f"{ncols} cols, checksum {fp}")
    cn.close()

    # --- MSD ---
    code = clientcfg.msd_client_code(cfg)
    if not code:
        r.add(WARN, "MSD client code", "not set - vendor identity falls back to name matching")
    else:
        try:
            cid = msdmod.resolve_client_id(code, env=env)
            if cid is None:
                r.add(FAIL, "MSD client code", f"'{code}' does not resolve in pi_clients")
            else:
                vm = msdmod.load_vendor_master(cid, env=env)
                r.add(PASS, "MSD client code", f"{code} (id {cid}) -> {len(vm):,} vendors")
        except Exception as e:
            r.add(WARN, "MSD client code", f"{type(e).__name__}: {str(e)[:80]}")
    return r


def main():
    env = load_env()
    wanted = sys.argv[1:] or clientcfg.list_clients()
    reports = [verify(k, env) for k in wanted]

    print("\n" + "=" * 62)
    for r in reports:
        note = ""
        if r.verdict == FAIL:
            note = "  <- " + next((d or c for lv, c, d in r.rows if lv == FAIL), "")
        print(f"  {_SYM[r.verdict]} {r.client:24} {r.verdict}{note[:60]}")
    bad = [r.client for r in reports if r.verdict == FAIL]
    print("=" * 62)
    print("Not ready: " + ", ".join(bad) if bad else "All configured clients ready.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
