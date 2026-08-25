"""Per-client configuration loader.

The governing rule for this project: pipeline/ contains no client names, clients/ contains no
code. Everything hospital-specific lives in clients/<key>/config.yaml and is loaded through here.

Two schema decisions worth knowing, both forced by what the live data turned out to look like:

  * The line's description is a LIST of columns tried in priority order, not one column name.
    Sydney Adventist has no ITEM_DESCRIPTION at all (it uses INVOICE DESCRIPTION), and Melbourne
    has PO/invoice text that fills gaps where ITEM_DESCRIPTION is blank.

  * The clinical gate keys off `Category Level 0`, which already carries
    Clinical / Non-Clinical / Non-Procurement / Inter-Hospital Spend in all four clients.
    Keyword-based clinical exclusion is REJECTED by this loader - substring matching on
    descriptions silently deletes in-scope indirect spend ("clinical waste removal", "theatre
    HVAC maintenance", "patient meal trolley") and corrupts the accuracy denominator.

A config may be a half-filled stub: profiling runs against whatever is present and reports what's
missing. Only a full pipeline run demands a complete config, and it names the absent keys rather
than raising a KeyError three modules deep.
"""
import os

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(PROJECT_ROOT, "clients")

# Internal column names the pipeline uses. Each client's config maps its own column names onto
# these. The line description is handled separately - see description_fields().
#
# Grouped by what they are FOR, because the groups have different failure modes:
#
#   judged      - the categorisation under test. Absent = nothing to QA.
#   identity    - lineage back to the source line, so an owner can find the row in their system.
#                 No single column does this for all four clients: Western has no RowID, Sydney
#                 Adventist has no INVOICE ID. See line_identity_fields().
#   evidence    - what the judge reads when the description is thin. GL account name and cost
#                 centre are the fallback signal, so their FILL RATE caps judge quality; they are
#                 measured per client rather than assumed present.
#   segmenting  - drives report breakdowns and the movement tracker.
INTERNAL_COLUMNS = [
    # judged
    "supplier", "spend", "rule_id", "method",
    "cat_l0", "cat_l1", "cat_l2", "cat_l3", "cat_l4",
    # identity
    "source_row_id", "invoice_number", "invoice_line_number", "invoice_id",
    # evidence
    "gl_account", "gl_account_name", "cost_centre", "cost_centre_description",
    "abn", "supplier_number", "unspsc",
    # segmenting
    "invoice_date", "posting_date", "taxonomy_key",
]
REQUIRED_COLUMNS = ["supplier", "spend", "cat_l0", "cat_l2"]

# Needed to produce a QA report, as opposed to merely profiling. Absence is reported as a named
# capability gap rather than a crash - three of the four clients are missing at least one.
REPORT_COLUMNS = [
    "invoice_number", "invoice_date", "gl_account_name", "cost_centre_description", "taxonomy_key",
]


def list_clients():
    """Every client key (folder name) under clients/."""
    if not os.path.isdir(CLIENTS_DIR):
        return []
    return sorted(
        d for d in os.listdir(CLIENTS_DIR)
        if os.path.isdir(os.path.join(CLIENTS_DIR, d)) and not d.startswith((".", "_"))
    )


def client_dir(client_key):
    return os.path.join(CLIENTS_DIR, client_key)


def config_path(client_key):
    return os.path.join(client_dir(client_key), "config.yaml")


def load_config(client_key):
    """Load clients/<key>/config.yaml. Returns {} if absent or empty."""
    path = config_path(client_key)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        return yaml.safe_load(fh) or {}


def column_map(cfg):
    """{internal_name: client_column_name} for every column the client has mapped."""
    cols = ((cfg.get("source") or {}).get("columns") or {})
    return {k: str(v).strip() for k, v in cols.items()
            if k in INTERNAL_COLUMNS and v and str(v).strip()}


def description_fields(cfg):
    """Ordered list of columns to read the line's description from, first non-blank wins."""
    fields = ((cfg.get("source") or {}).get("description_fields") or [])
    return [str(f).strip() for f in fields if f and str(f).strip()]


def source_table(cfg):
    return ((cfg.get("source") or {}).get("table") or "").strip()


def taxonomy_table(cfg):
    """The client's own taxonomy table, e.g. MH_Taxonomy. Optional."""
    return ((cfg.get("source") or {}).get("taxonomy_table") or "").strip()


def taxonomy_join_column(cfg):
    """The TAXONOMY-side column that the line's taxonomy_key joins to.

    Differs per client and is confirmed by match count, never by name similarity - an earlier
    session asserted `MASTER CATEGORY ID -> Category ID` because the names looked alike and it
    was wrong (zero matches; the real key is `Master ID`, 2,380,203 matches).
    """
    return ((cfg.get("source") or {}).get("taxonomy_join_column") or "").strip()


# --- category levels ---------------------------------------------------------------------------
#
# MAX_CATEGORY_LEVEL is the width the SCHEMA carries: 0-5. Every client gets all six columns.
# DEEPEST_OBSERVED is what the four client taxonomies actually populate today - all four stop at
# Level 4. The two are deliberately different numbers: a client that later gains a Level 5 (Sydney
# Adventist's new Master_Taxonomy uses Category Level 1-5) must not require a schema change, and a
# reader must never have to guess whether a blank Level 5 means "absent" or "empty".
#
# Hence the markers below. A blank cell is ambiguous; these are not.
MAX_CATEGORY_LEVEL = 5
DEEPEST_OBSERVED_LEVEL = 4
CATEGORY_LEVELS = [f"cat_l{i}" for i in range(MAX_CATEGORY_LEVEL + 1)]

NO_SUCH_LEVEL = "(no level {} in this taxonomy)"   # the column does not exist for this client
NO_TAXONOMY_MATCH = "(no taxonomy match)"          # the line never resolved to a taxonomy row

# A blank category level means two completely different things depending on the level, and one
# label for both was misleading. Sameer, 2026-08-04: "under assigned cat level change from blank at
# this line to Uncategorised."
#
#   Level 0 blank  -> the line was never categorised at all. "Uncategorised" is the plain truth.
#   Level 1-4 blank -> the line IS categorised; its path is simply shallower than four levels.
#                      Calling that "Uncategorised" would swap one wrong word for another - only
#                      137 of 1,999 units are blank at Level 0, but 368 are blank SOMEWHERE.
LEVEL_UNCATEGORISED = "Uncategorised"              # Level 0 empty - never categorised
LEVEL_NOT_USED = "(not used at this level)"        # deeper level empty - path is shallower

LEVEL_BLANK = LEVEL_UNCATEGORISED  # back-compat alias; prefer the two explicit names above


def assert_same_database(cfg, client_key):
    """Reject any table reference that could reach into ANOTHER client's database.

    This is the guard behind a hard project rule: a taxonomy row belonging to one hospital must
    never resolve a line belonging to another. It is not a theoretical risk - the taxonomy keys
    COLLIDE across clients while meaning different things. Measured 2026-07-31:

        Melbourne vs Northern          260 shared keys, 46.5% mean something DIFFERENT
        Melbourne vs Sydney Adventist  260 shared keys, 47.3% mean something DIFFERENT
        Northern  vs Sydney Adventist  1,409 shared keys, 2.0% differ

        key 379   Melbourne: Non-Clinical > Food and Beverage > Dairy Products > Cheese > Cheese
                  Northern : Non-Clinical > Facilities Management > Soft Facilities Management > ...

    Resolving Melbourne's key 379 against Northern's taxonomy would silently relabel cheese as
    facilities management, and the accuracy figure would be measured against the wrong yardstick
    with nothing visibly wrong. So: every table must be a one- or two-part name, resolved inside
    the connection already opened for THIS client. Three-part names are refused.
    """
    problems = []
    for label, ref in (("source.table", source_table(cfg)),
                       ("source.taxonomy_table", taxonomy_table(cfg)),
                       ("source.rules_table", rules_table(cfg))):
        if not ref:
            continue
        parts = [p for p in ref.replace("[", "").replace("]", "").split(".") if p]
        if len(parts) > 2:
            problems.append(
                f"{label} = {ref!r} is a {len(parts)}-part name. Cross-database references are "
                f"refused: it could resolve another hospital's taxonomy against {client_key}'s "
                f"lines. Use [dbo].[Table] and let the per-client connection scope it.")
    return problems


def rules_table(cfg):
    """The PRIMARY rules table. Prefer rules_tables() - a client may have more than one."""
    return (rules_tables(cfg) or [""])[0]


def rules_tables(cfg):
    """EVERY rules table needed to resolve this client's RuleIDs, primary first.

    Not always one table, and getting this wrong produces the worst possible failure: a fix queue
    that comes back BLANK and reads as "nothing to fix". Measured at Western 2026-07-31 -
    **139,244 in-scope lines (20.7%) carry a RuleID that is not in `PMML_Rules` at all.** They live
    in `PMML_Medical_Rules`, which the config had dismissed as out of scope because the project is
    indirects only.

    The name misleads. `PMML_Medical_Rules` is not "rules about medical items" - it is a rule set
    that happens to categorise a fifth of Western's NON-clinical spend, e.g.

        WH-MD1961   ACCOUNT NAME CONTAINS 'CONTRACT S&W-NURSING'
        WH-MD0664   VENDOR_NAME CONTAINS ','          <- matches any vendor name with a comma

    Scope is decided by `Category Level 0` on the line, never by the name of the table the rule
    came from.
    """
    src = cfg.get("source") or {}
    many = src.get("rules_tables") or []
    out = [str(t).strip() for t in many if t and str(t).strip()]
    if out:
        return out
    one = (src.get("rules_table") or "").strip()
    return [one] if one else []


def msd_client_code(cfg):
    return ((cfg.get("msd") or {}).get("client_code") or "").strip()


def display_name(cfg, client_key):
    return ((cfg.get("client") or {}).get("name") or "").strip() or client_key


def account_manager(cfg):
    return ((cfg.get("client") or {}).get("account_manager") or "").strip()


def clinical_exclusions(cfg):
    """Values of the clinical-gate column that are OUT of scope."""
    g = cfg.get("clinical_gate") or {}
    return [str(v).strip() for v in (g.get("exclude_values") or []) if str(v).strip()]


def scope_exclusions(cfg):
    """Values of cat_l0 excluded by the scope gate (intercompany / own-entity)."""
    g = cfg.get("scope_gate") or {}
    return [str(v).strip() for v in (g.get("exclude_cat_l0") or []) if str(v).strip()]


def line_identity_fields(cfg):
    """Ordered internal field names that together identify one source line for this client.

    NOT the same for every client, and not inferable from names - measured 2026-07-31:

      Melbourne / Northern / Sydney Adventist   RowID, 100% filled -> single-column identity
      Western                                   HAS NO RowID -> composite of invoice id +
                                                line number + distribution id, each 100% filled

    Melbourne is the trap: it HAS `INVOICE LINE NUMBER` and `INVOICE ID`, but both are only 27%
    filled, so a composite built from them would be null for three lines in four. Its RowID is
    the only thing that identifies a Melbourne line.

    Falls back to whatever identity columns are mapped, so a half-filled config still profiles.
    """
    explicit = ((cfg.get("source") or {}).get("line_identity") or [])
    explicit = [str(f).strip() for f in explicit if f and str(f).strip()]
    if explicit:
        return explicit
    cols = column_map(cfg)
    if "source_row_id" in cols:
        return ["source_row_id"]
    return [f for f in ("invoice_id", "invoice_number", "invoice_line_number") if f in cols]


def missing_for_report(cfg):
    """Report-grade columns this client cannot supply. Empty list = full report possible.

    Separate from missing_for_run() on purpose: these degrade a report, they do not stop a run.
    The pipeline must still produce a verdict for a client missing all of them.
    """
    cols = column_map(cfg)
    return [c for c in REPORT_COLUMNS if c not in cols]


def missing_for_run(cfg, client_key="this client"):
    """What still has to be filled in before a full pipeline run. Empty list = ready."""
    problems = list(assert_same_database(cfg, client_key))
    if not source_table(cfg):
        problems.append("source.table")

    cols = column_map(cfg)
    for c in REQUIRED_COLUMNS:
        if c not in cols:
            problems.append(f"source.columns.{c}")

    if not description_fields(cfg):
        problems.append("source.description_fields (the judge has nothing to read without these)")

    gate = cfg.get("clinical_gate") or {}
    if gate.get("enabled") and not clinical_exclusions(cfg):
        problems.append("clinical_gate.exclude_values (gate enabled but nothing to exclude)")

    # Guard the defect this whole project exists to avoid.
    if gate.get("exclude_keywords"):
        problems.append(
            "clinical_gate.exclude_keywords is set - keyword exclusion is rejected by design; "
            "the clinical split is Category Level 0, use clinical_gate.exclude_values"
        )
    return problems
