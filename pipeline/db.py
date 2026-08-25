"""Shared DB helpers: load .env credentials and open pyodbc connections.

Ported from the Nufarm template (_reference/) with one addition: this project runs several
hospital clients off the same credentials, so `connect_client()` resolves the database (and
optionally the server) per client from .env:

    DB_MELBOURNE_HEALTH=...          # required, per client
    SERVER_MELBOURNE_HEALTH=...      # optional, only if that client is on a different server

`msd.py` imports connect_msd/load_env from here.
"""
import os

import pyodbc

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path=None):
    """Minimal KEY=VALUE .env parser (no external dependency)."""
    path = path or os.path.join(PROJECT_ROOT, ".env")
    env = {}
    if not os.path.exists(path):
        raise RuntimeError(
            f"No .env at {path}. Copy .env.example to .env and fill it in."
        )
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def connect(env=None, timeout=30, database=None, server=None):
    env = env or load_env()
    database = database or env.get("SQL_DATABASE", "").strip()
    if not database:
        raise RuntimeError("No database given and SQL_DATABASE is empty in .env.")
    conn_str = (
        f"DRIVER={{{env['SQL_DRIVER']}}};"
        f"SERVER={server or env['SQL_SERVER']};"
        f"DATABASE={database};"
        f"UID={env['SQL_USER']};"
        f"PWD={env['SQL_PASS']};"
        f"TrustServerCertificate=yes;Connection Timeout={timeout}"
    )
    return pyodbc.connect(conn_str)


def _client_env_key(client_key):
    """melbourne_health -> MELBOURNE_HEALTH"""
    return client_key.strip().upper().replace("-", "_").replace(" ", "_")


def connect_client(client_key, env=None, timeout=30):
    """Connect to one hospital client's database, resolved from .env by client key.

    client_key is the folder name under clients/ (e.g. "melbourne_health").
    """
    env = env or load_env()
    key = _client_env_key(client_key)
    database = (env.get(f"DB_{key}") or "").strip()
    if not database:
        raise RuntimeError(
            f"DB_{key} is empty in .env — set it to {client_key}'s database name."
        )
    # optional per-client server override; falls back to the shared SQL_SERVER
    server = (env.get(f"SERVER_{key}") or "").strip() or None
    return connect(env=env, timeout=timeout, database=database, server=server)


# The only two databases this pipeline may ever WRITE to. Everything else - the four client
# databases and the MSD - is read-only, always.
#
# WHY AN ALLOWLIST AND NOT A NAME PATTERN. Until 2026-08-18 the guard everywhere was
# `"pilot" not in name -> stop`, which was right while one database existed and became wrong the
# moment production was created: production has no "pilot" in its name, so every guarded script
# refused to speak to it. The naive fix is to drop the check. That is the wrong fix, because the
# check was never really about the pilot - IT IS ABOUT NEVER WRITING TO A CLIENT DATABASE. This
# pipeline writes. A typo in .env, a stale environment, or a copied command is all it takes to
# point a writing script at a hospital's live data, and nothing downstream would notice.
#
# So: the target must be a name we KNOW (below), and production must additionally be asked for
# ON PURPOSE (production=True). Two independent locks, the same shape as the pair they replace -
# one stops the wrong database, the other stops the right one being hit by accident.
QA_ENV_KEYS = {False: "QA_DATABASE_PILOT", True: "QA_DATABASE"}


def qa_database_names(env=None):
    """The pilot and production names as configured. Either may be blank."""
    env = env or load_env()
    return {k: (env.get(v) or "").strip() for k, v in QA_ENV_KEYS.items()}


def assert_writable_qa_database(name, production, env=None):
    """Refuse any database that is not the configured QA target for this mode.

    Raises rather than returns. Called by connect_qa and again by scripts that then re-read
    DB_NAME() from the live connection - deliberately belt and braces, because the .env value and
    the database the driver actually opened are two different facts.
    """
    names = qa_database_names(env)
    want = names[bool(production)]
    key = QA_ENV_KEYS[bool(production)]
    label = "production" if production else "pilot"

    if not want:
        raise RuntimeError(
            f"{key} is empty in .env, so the {label} database has no configured name.\n"
            "  Set it deliberately - this is the step that lets the pipeline reach that database."
        )
    if (name or "").strip().lower() != want.lower():
        other = names[not bool(production)]
        extra = (f"\n  ({other} is the {'pilot' if production else 'production'} database - "
                 f"pass the other mode if that is what you meant.)") if other else ""
        raise RuntimeError(
            f"REFUSING [{name}]: it is not the configured {label} QA database [{want}].\n"
            f"  This pipeline WRITES. The four client databases and the MSD are read-only, "
            f"always.{extra}"
        )
    return want


def connect_qa(pilot=True, production=None, env=None, timeout=30):
    """Connect to a QA database — the only databases this pipeline writes to.

    production=False (the default) -> QA_DATABASE_PILOT, the proving ground
    production=True               -> QA_DATABASE, the real run

    `pilot=` is the original argument and still works, so no existing caller changes behaviour:
    every one of them passes pilot=True or nothing, and both still mean the pilot. Reaching
    production requires production=True, which no caller does by default and which every entry
    point exposes as an explicit --production flag.

    THE DEFAULT IS THE SAFE ONE ON PURPOSE. A caller that forgets to say which database it wants
    gets the 2,000-row pilot, where a mistake costs 16 minutes.
    """
    env = env or load_env()
    if production is None:
        production = not pilot
    db = assert_writable_qa_database(qa_database_names(env)[bool(production)], production, env)
    return connect(env=env, timeout=timeout, database=db)


def connect_msd(env=None, timeout=30):
    """Connect to the Master Supplier Database (MSD): same login, different database.
    Requires MSD_DATABASE in .env."""
    env = env or load_env()
    db = (env.get("MSD_DATABASE") or "").strip()
    if not db:
        raise RuntimeError("MSD_DATABASE is empty in .env — set it to the MSD database name.")
    return connect(env=env, timeout=timeout, database=db)
