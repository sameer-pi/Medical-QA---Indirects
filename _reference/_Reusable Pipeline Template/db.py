"""Shared DB helpers: load .env credentials and open a pyodbc connection.

Self-contained for the reusable QA template. `msd.py` imports connect_msd/load_env from here.
The main pipeline (qa_pipeline_template.py) also has its own inline load_env/connect for the
client fact-data connection; this module is what the MSD accessors use.
"""
import os
import pyodbc

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env(path=None):
    """Minimal KEY=VALUE .env parser (no external dependency)."""
    path = path or os.path.join(PROJECT_ROOT, ".env")
    env = {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def connect(env=None, timeout=30, database=None):
    env = env or load_env()
    conn_str = (
        f"DRIVER={{{env['SQL_DRIVER']}}};"
        f"SERVER={env['SQL_SERVER']};"
        f"DATABASE={database or env['SQL_DATABASE']};"
        f"UID={env['SQL_USER']};"
        f"PWD={env['SQL_PASS']};"
        f"TrustServerCertificate=yes;Connection Timeout={timeout}"
    )
    return pyodbc.connect(conn_str)


def connect_msd(env=None, timeout=30):
    """Connect to the Master Supplier Database (MSD): same server/login, different database.
    Requires MSD_DATABASE in .env; MSD_SCHEMA/MSD_TABLE are optional pointers used by callers."""
    env = env or load_env()
    db = env.get("MSD_DATABASE", "").strip()
    if not db:
        raise RuntimeError("MSD_DATABASE is empty in .env — set it to the master-taxonomy database name.")
    return connect(env=env, timeout=timeout, database=db)


def msd_table(env=None):
    """Return the fully-qualified MSD table as [schema].[table] from .env (schema defaults to dbo)."""
    env = env or load_env()
    schema = (env.get("MSD_SCHEMA") or "dbo").strip()
    table = (env.get("MSD_TABLE") or "").strip()
    if not table:
        raise RuntimeError("MSD_TABLE is empty in .env — point me to the table first.")
    return f"[{schema}].[{table}]"
