"""Prove production's tables are IDENTICAL to the pilot's. Run after any schema change.

    python pipeline/verify_schema_parity.py

Also called automatically by apply_schema.py --production, so it cannot be skipped there.

NOT compared against schema.sql. schema.sql is what we THINK we asked for, and it was 30 columns
adrift from reality until this morning without anyone noticing - so it is exactly the wrong
yardstick. Both sides here are read from INFORMATION_SCHEMA on the live servers: the pilot, which
has produced every figure this project trusts, and production, which must behave identically or the
pilot proved nothing transferable.

Read-only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect, load_env, qa_database_names                # noqa: E402

def main():
    env = load_env()
    names = qa_database_names(env)
    PILOT, PROD = names[False], names[True]


    def columns(db):
        cn = connect(env=env, database=db, timeout=60)
        c = cn.cursor()
        c.execute("""SELECT LOWER(TABLE_NAME), LOWER(COLUMN_NAME), DATA_TYPE,
                            CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
                     FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME LIKE 'qa[_]%'
                     ORDER BY TABLE_NAME, ORDINAL_POSITION""")
        out = {}
        for t, col, dt, clen, prec, scale, nullable in c.fetchall():
            if clen is not None:
                typ = "{}({})".format(dt, "max" if clen == -1 else clen)
            elif dt in ("decimal", "numeric"):
                typ = "{}({},{})".format(dt, prec, scale)
            else:
                typ = dt
            out.setdefault(t, {})[col] = (typ, nullable)
        cn.close()
        return out


    p, q = columns(PILOT), columns(PROD)
    print("pilot      [{}]".format(PILOT))
    print("production [{}]\n".format(PROD))

    bad = 0
    for tbl in sorted(set(p) | set(q)):
        pc, qc = p.get(tbl, {}), q.get(tbl, {})
        only_p = sorted(set(pc) - set(qc))
        only_q = sorted(set(qc) - set(pc))
        diff = sorted(c for c in set(pc) & set(qc) if pc[c] != qc[c])

        status = "IDENTICAL" if not (only_p or only_q or diff) else "** DIFFERS **"
        print("  {:<14} pilot {:>3} cols   production {:>3} cols   {}".format(
            tbl, len(pc), len(qc), status))
        for c in only_p:
            print("      missing from production : {} {}".format(c, pc[c][0])); bad += 1
        for c in only_q:
            print("      extra in production     : {} {}".format(c, qc[c][0])); bad += 1
        for c in diff:
            print("      TYPE/NULLABILITY differs : {}  pilot {} {}  production {} {}".format(
                c, pc[c][0], pc[c][1], qc[c][0], qc[c][1])); bad += 1

    # indexes and the primary key travel with the schema too - a matching column list on a table with
    # no PK is not the same table.
    print()
    for label, db in (("pilot", PILOT), ("production", PROD)):
        cn = connect(env=env, database=db, timeout=60)
        c = cn.cursor()
        c.execute("""SELECT LOWER(t.name), LOWER(i.name), i.is_primary_key
                     FROM sys.indexes i JOIN sys.tables t ON i.object_id=t.object_id
                     WHERE i.name IS NOT NULL AND t.name LIKE 'qa[_]%' ORDER BY 1,2""")
        idx = [(a, b, bool(k)) for a, b, k in c.fetchall()]
        cn.close()
        print("  {:<11} {} indexes/keys: {}".format(
            label, len(idx), ", ".join(b + ("(pk)" if k else "") for _, b, k in idx)))
        if label == "pilot":
            pilot_idx = idx
        else:
            if idx != pilot_idx:
                print("      ** INDEX SETS DIFFER **")
                bad += 1

    print("\n{}".format("PRODUCTION MATCHES THE PILOT" if not bad
                        else "** {} DIFFERENCE(S) - production is NOT the pilot **".format(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
