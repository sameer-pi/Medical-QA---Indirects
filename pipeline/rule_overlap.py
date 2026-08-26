"""Can one RuleID resolve to more than one rules-table row? Measured, not argued.

Sameer's objection: a line in the categorised view carries ONE RuleID or none, so where does a
duplicate come from? He is right about the line. The only place a duplicate can come from is the
LOOKUP - if the same RuleID exists in two of a client's rules tables, or twice within one table,
then one line matches two rows and the join inflates.

Western is the only client with two rules tables, so it is the only one that can collide across
tables - but a duplicate WITHIN a single table would hit any client, so check both, everywhere.

Read-only. Every query runs inside that one client's connection, two-part names only.
"""
import os
import sys

# 🔴 THIS WAS AN ABSOLUTE PATH TO THE LAPTOP THIS FILE WAS WRITTEN ON, and it would have crashed on
# the office desktop the first time anyone ran it from a fresh clone. Fixed 2026-08-27 while
# checking what a clone actually breaks on. Every other script in here already resolves its own
# directory; this one did not, and nothing would have said so until it failed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clientcfg  # noqa: E402
from db import connect_client, load_env  # noqa: E402

env = load_env()

for k in clientcfg.list_clients():
    cfg = clientcfg.load_config(k)
    if not cfg or clientcfg.missing_for_run(cfg):
        continue
    tables = list(clientcfg.rules_tables(cfg))
    print(f"\n=== {k}  ({len(tables)} rules table(s)) ===")

    cn = connect_client(k, env=env, timeout=60)
    cn.timeout = 900
    cur = cn.cursor()

    ids_per_table = {}
    for t in tables:
        cur.execute(f"""SELECT COUNT(*), COUNT(DISTINCT LTRIM(RTRIM(CONVERT(nvarchar(200),[RuleID]))))
                        FROM {t}""")
        n, d = cur.fetchone()
        flag = "" if n == d else f"   <-- {n - d:,} DUPLICATE RuleID row(s) WITHIN this table"
        print(f"  {t:<34} {n:>6,} rows  {d:>6,} distinct RuleID{flag}")

        cur.execute(f"""SELECT LTRIM(RTRIM(CONVERT(nvarchar(200),[RuleID])))
                        FROM {t}
                        WHERE NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200),[RuleID]))),'') IS NOT NULL""")
        ids_per_table[t] = {r[0] for r in cur.fetchall()}

    if len(tables) > 1:
        a, b = tables[0], tables[1]
        both = ids_per_table[a] & ids_per_table[b]
        print(f"  RuleIDs present in BOTH tables: {len(both):,}")
        if both:
            print(f"    examples: {sorted(both)[:8]}")
            print("    -> a join on rule_id alone WOULD fan out for these")
        else:
            print("    -> no overlap. A join on rule_id alone is unambiguous for this client")

    cn.close()

print("\nDONE")
