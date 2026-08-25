#!/usr/bin/env python
"""Indirect QA — ANSWER KEY workbook. The first check of the judge against a human.

Sameer, 2026-08-17: *"can i extract the table in an excel file, and do a check and give my answers
in that, and all you need from me is either A or B?"*

WHAT THIS IS FOR
----------------
Every accuracy figure this project has produced so far is the judge marking its own homework. There
is no human answer key, so "58.1% accurate" means only "58.1% of the time the judge agreed with the
rule that was already there" - it says nothing about whether the JUDGE was right. This workbook is
the first thing that changes that.

⚠️ IT IS DE-ANCHORED ON PURPOSE, and that is the single most important design decision here.
`CLAUDE.md`: *"Override data is NOT a golden set - the analyst sees our answer first and is anchored
to it, so agreement reads higher than the truth."* So sheet 1 shows the vendor, the item and where
the line is filed **now**, and NOT our verdict or our suggested destination. Those live on sheet 2,
to be opened afterwards. An anchored answer key cannot be un-anchored later, and this is the only
human pass we are likely to get.

WHY ONE ROW IS NOT ONE LINE. The 200 Miscategorised lines are 149 distinct decisions and the set is
concentrated - one rule drives 29 lines, one vendor 43. Reviewing lines would mean answering the
same question up to seven times. Each row here is a distinct (client, vendor, item text, filed path,
our destination) and carries LINES_THIS_COVERS so the weight is visible.

THE THREE ANSWERS. Sameer asked for two; the third exists so that "checked and agreed" is
distinguishable from "did not get to it". A blank is not evidence of agreement, and treating it as
such would inflate the score exactly the way anchoring does.

    OK  the line IS miscategorised and our destination is right
    A   the original filing was FINE - our verdict is wrong        (a FALSE ALARM)
    B   it IS miscategorised, but our destination is wrong         (a BAD SUGGESTION)

A and B are different defects with different fixes, and the letter is the only thing separating
them - which is why a bare "wrong" is not enough.

🔒 A COMPLETED WORKBOOK IS NOT REGENERABLE. Sameer's answers exist nowhere else until ingested.
This script REFUSES to overwrite a file that already has answers typed into it - it writes ` v2`
instead. Same rule as the taxonomy DECISIONS workbook, for the same reason.
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpyxl import Workbook, load_workbook                      # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill          # noqa: E402
from openpyxl.utils import get_column_letter                      # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation      # noqa: E402

from db import connect_qa, load_env                               # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "output", "QA_LINE_TEST")
# "Indirect" in the name, always - the folder is Medical QA - Indirects and without the qualifier a
# future reader concludes we QA'd medical items, the opposite of the truth.
BASENAME = "Indirect QA Answer Key - Miscategorised"

# 🔒 REWRITTEN 2026-08-21 AFTER THE FIRST COMPLETED WORKBOOK CAME BACK UNREADABLE.
#
# It used to be OK / A / B:
#     OK  it IS miscategorised and OUR DESTINATION is right
#     A   the original filing was FINE - our verdict is wrong
#     B   it IS miscategorised, but OUR DESTINATION is wrong
#
# ⚠️ TWO OF THOSE THREE ASK ABOUT OUR DESTINATION, WHICH SHEET 1 DELIBERATELY HIDES. The
# de-anchoring is correct and stays; the answer codes were the mistake. Sameer answered `B` on all
# 69 rows - read literally, "your destination is wrong, 69 times out of 69". The pairs refute it
# flatly: we said `Food & Beverages > Poultry > Egg > Egg`, he wrote `EGGS`. He was not disagreeing
# with our destination. He could not see it. He was writing his own answer from scratch, which is
# exactly what the blind sheet asks for.
#
# 🔑 A REVIEWER MUST ONLY BE ASKED WHAT THEY CAN SEE. So the sheet now asks the two questions the
# blind view actually supports, and OK/A/B is DERIVED at scoring time instead of being asked for:
#
#     RIGHT + we said Miscategorised            -> we raised a FALSE ALARM   (the old A)
#     WRONG + his destination MATCHES ours      -> we were RIGHT             (the old OK)
#     WRONG + his destination DIFFERS from ours -> a BAD SUGGESTION          (the old B)
#
# Same three outcomes, none of them requiring him to see our answer first.
ANSWERS = ("RIGHT", "WRONG")

HEAD = PatternFill("solid", fgColor="1F3864")
ANSWER_FILL = PatternFill("solid", fgColor="FFF2CC")
NOTE_FILL = PatternFill("solid", fgColor="F2F2F2")
WHITE_BOLD = Font(bold=True, color="FFFFFF", size=11)

# Sheet 1 - what Sameer decides FROM. No verdict, no destination, no rationale.
Q_BLIND = """
SELECT  MIN(UNIT_KEY)                          AS CHECK_ID,
        COUNT(*)                               AS LINES_THIS_COVERS,
        CLIENT_CODE                            AS HOSPITAL,
        SUPPLIER_NAME                          AS VENDOR,
        ITEM_DESCRIPTION                       AS WHAT_WAS_BOUGHT,
        CONCAT(CATEGORY_LVL_1,' > ',CATEGORY_LVL_2,' > ',CATEGORY_LVL_3,
               ' > ',CATEGORY_LVL_4)           AS FILED_HERE_NOW,
        MSD_COHERENCE                          AS VENDOR_CHECK
FROM    qa_line
WHERE   NIM_ACTION = 'Miscategorised' {extra}
GROUP BY CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION,
         CATEGORY_LVL_1, CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4,
         NIM_SUGGESTED_CATEGORY_LVL_1, NIM_SUGGESTED_CATEGORY_LVL_2,
         NIM_SUGGESTED_CATEGORY_LVL_3, NIM_SUGGESTED_CATEGORY_LVL_4, MSD_COHERENCE
ORDER BY COUNT(*) DESC, SUPPLIER_NAME
"""

# Sheet 2 - the same rows, WITH our answer. Same GROUP BY, so the row order is identical and
# CHECK_ID lines them up.
#
# 🔒 CHECK_ID IS `UNIT_KEY`, NOT `QA_LINE_ID`. It was the identity column until 2026-08-21, and
# `CLAUDE.md` had warned in terms: "if any becomes an identity column, the Excel status re-attach
# and the movement tracker both break silently." It did. The pilot was rebuilt, the destroyed
# generation's ids were 825,228-825,900, the new rows 827,013-829,012, ZERO overlap - so the ingest
# matched nothing and said nothing. `unit_key` is a deterministic SHA-256 of client + supplier +
# item text + assigned category: it survives a rebuild, which is the entire point of it existing.
#
# ⚠️ Where ONE unit received TWO different suggestions (the Case B situation - same vendor, same
# text, filed the same way, sent to two destinations) two rows share a CHECK_ID. That is correct and
# must stay: they are genuinely two decisions. The ingest re-matches on the WHOLE group key
# including the suggestion, so they never collide.
Q_OURS = """
SELECT  MIN(UNIT_KEY)                          AS CHECK_ID,
        SUPPLIER_NAME                          AS VENDOR,
        ITEM_DESCRIPTION                       AS WHAT_WAS_BOUGHT,
        CONCAT(CATEGORY_LVL_1,' > ',CATEGORY_LVL_2,' > ',CATEGORY_LVL_3,
               ' > ',CATEGORY_LVL_4)           AS FILED_HERE_NOW,
        CONCAT(NIM_SUGGESTED_CATEGORY_LVL_1,' > ',NIM_SUGGESTED_CATEGORY_LVL_2,' > ',
               NIM_SUGGESTED_CATEGORY_LVL_3,' > ',NIM_SUGGESTED_CATEGORY_LVL_4)
                                               AS WE_SAY_IT_BELONGS_HERE,
        MIN(NIM_RATIONALE)                     AS WHY_WE_SAY_SO,
        MIN(NIM_AGREEMENT)                     AS MODELS_AGREEING,
        MIN(RULE_ID)                           AS RULE_THAT_FILED_IT
FROM    qa_line
WHERE   NIM_ACTION = 'Miscategorised' {extra}
GROUP BY CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION,
         CATEGORY_LVL_1, CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4,
         NIM_SUGGESTED_CATEGORY_LVL_1, NIM_SUGGESTED_CATEGORY_LVL_2,
         NIM_SUGGESTED_CATEGORY_LVL_3, NIM_SUGGESTED_CATEGORY_LVL_4, MSD_COHERENCE
ORDER BY COUNT(*) DESC, SUPPLIER_NAME
"""

STRONGEST = " AND NIM_AGREEMENT = '3of3' AND DESCRIPTION_USABLE = 'Y' "


def header(ws, names, widths):
    for i, (n, w) in enumerate(zip(names, widths), start=1):
        cell = ws.cell(row=1, column=i, value=n)
        cell.fill, cell.font = HEAD, WHITE_BOLD
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30


def instructions(wb, n_rows, n_lines, strongest):
    ws = wb.create_sheet("READ THIS FIRST", 0)
    ws.column_dimensions["A"].width = 112
    lines = [
        ("Indirect QA — Answer Key, Miscategorised lines", True),
        ("", False),
        (f"{n_rows} rows to check. They cover {n_lines} lines of the pilot.", False),
        ("One row is one DECISION, not one line — the same question repeats up to 7 times in the "
         "data, so it has been de-duplicated. LINES_THIS_COVERS shows the weight.", False),
        ("", False),
        ("WHAT TO DO", True),
        ("1. Go to the sheet 'ANSWER HERE'. For each row, read the vendor, what was bought, and "
         "where it is filed now.", False),
        ("2. Put RIGHT or WRONG in the YOUR_ANSWER column — just about the filing you can see:", False),
        ("       RIGHT   it is filed correctly where it is. Nothing needs to move.", False),
        ("       WRONG   it is filed in the wrong place.", False),
        ("3. If WRONG, put where it SHOULD go in WHERE_IT_SHOULD_GO. A category name is enough — "
         "you do not need the full path. If you are not sure where, WRONG on its own is still "
         "useful.", False),
        ("", False),
        ("You are NOT being asked whether our answer is right — you cannot see it, and that is "
         "deliberate. Just tell us what you think, and we will compare afterwards.", False),
        ("4. Leave a row blank if you did not get to it. Blank is NOT the same as RIGHT — please "
         "don't use it to mean agreement.", False),
        ("", False),
        ("WHY OUR ANSWER IS NOT ON THAT SHEET", True),
        ("If you see our answer first you will agree with it more than you otherwise would. That "
         "is not a criticism — it happens to everyone, and it would make the score come out "
         "flatter than the truth.", False),
        ("This is the only human answer key we are likely to get, and once it is anchored it "
         "cannot be un-anchored. So please answer on 'ANSWER HERE' first.", False),
        ("Our answer, our reasoning, the rule that filed it and how many models agreed are all on "
         "the sheet 'OUR ANSWER (open after)'. CHECK_ID lines the two sheets up.", False),
        ("", False),
        ("WHAT THIS BUYS US", True),
        ("Right now every accuracy figure we have is the judge marking its own homework. Your "
         "answers are the first real yardstick.", False),
        ("A and B are different faults with different fixes: A is a FALSE ALARM (we send an "
         "analyst to fix something that was never broken, which is the fastest way to lose their "
         "trust), B is a BAD SUGGESTION (we spot the error but point at the wrong shelf).", False),
        ("It also tells us whether '3 models agreed' is safe to auto-approve at full scale. That "
         "is the difference between an analyst reading everything and reading a fraction.", False),
        ("", False),
        ("This file is NOT regenerable once you have typed in it — your answers exist nowhere "
         "else. Do not let anything overwrite it.", True),
    ]
    if strongest:
        lines.insert(4, ("Filtered to the strongest set: all three models agreed AND the item "
                         "description was usable. If we are wrong HERE, we are worse everywhere "
                         "else — so this is the right place to start.", False))
    for i, (text, bold) in enumerate(lines, start=1):
        cell = ws.cell(row=i, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if bold:
            cell.font = Font(bold=True, size=12 if i == 1 else 11)
        elif not text:
            continue
        else:
            cell.fill = NOTE_FILL
    return ws


def build(qcur, path, strongest):
    extra = STRONGEST if strongest else ""
    qcur.execute(Q_BLIND.format(extra=extra))
    blind_cols = [d[0] for d in qcur.description]
    blind = qcur.fetchall()
    qcur.execute(Q_OURS.format(extra=extra))
    ours_cols = [d[0] for d in qcur.description]
    ours = qcur.fetchall()
    if len(blind) != len(ours):
        raise SystemExit(f"  the two sheets disagree on row count ({len(blind)} vs {len(ours)}) - "
                         f"the GROUP BYs have drifted apart. STOP.")

    wb = Workbook()
    wb.remove(wb.active)

    ws = wb.create_sheet("ANSWER HERE")
    names = blind_cols + ["YOUR_ANSWER", "WHERE_IT_SHOULD_GO", "YOUR_NOTE"]
    header(ws, names, [11, 9, 18, 34, 62, 54, 13, 14, 40, 34])
    for r, row in enumerate(blind, start=2):
        for ci, v in enumerate(row, start=1):
            c = ws.cell(row=r, column=ci, value=v)
            c.alignment = Alignment(vertical="top", wrap_text=ci in (4, 5, 6))
        for ci in range(len(blind_cols) + 1, len(names) + 1):
            ws.cell(row=r, column=ci).fill = ANSWER_FILL
    ws.freeze_panes = "C2"
    ans_col = get_column_letter(len(blind_cols) + 1)
    dv = DataValidation(type="list", formula1=f'"{",".join(ANSWERS)}"', allow_blank=True,
                        showDropDown=False)
    dv.error = ("Use RIGHT or WRONG - or leave it blank if you have not reviewed this row.\n\n"
                "RIGHT = filed correctly where it is.  WRONG = filed in the wrong place; "
                "put where it should go in the next column.")
    dv.errorTitle = "RIGHT or WRONG"
    ws.add_data_validation(dv)
    dv.add(f"{ans_col}2:{ans_col}{len(blind) + 1}")

    ws2 = wb.create_sheet("OUR ANSWER (open after)")
    header(ws2, ours_cols, [11, 34, 62, 54, 54, 76, 15, 18])
    for r, row in enumerate(ours, start=2):
        for ci, v in enumerate(row, start=1):
            c = ws2.cell(row=r, column=ci, value=v)
            c.alignment = Alignment(vertical="top", wrap_text=ci in (2, 3, 4, 5, 6))
    ws2.freeze_panes = "B2"

    n_lines = sum(r[1] for r in blind)
    instructions(wb, len(blind), n_lines, strongest)
    wb.active = 0
    wb.save(path)
    return len(blind), n_lines


def has_answers(path):
    """True if anyone has typed an answer into an existing workbook. A file with answers is not
    regenerable and must never be overwritten."""
    if not os.path.exists(path):
        return False
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        if "ANSWER HERE" not in wb.sheetnames:
            return False
        ws = wb["ANSWER HERE"]
        head = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        if "YOUR_ANSWER" not in head:
            return False
        i = head.index("YOUR_ANSWER")
        for row in ws.iter_rows(min_row=2, values_only=True):
            if i < len(row) and row[i] not in (None, ""):
                return True
    except Exception as ex:                                        # noqa: BLE001
        # Cannot read it -> assume it holds answers. The failure that costs someone an afternoon
        # of typing is the one where we guessed "probably empty" and overwrote it.
        print(f"  could not read {os.path.basename(path)} ({type(ex).__name__}) - "
              f"treating it as ANSWERED so it is not overwritten")
        return True
    return False


def ingest(qa, qcur, path, strongest):
    """Read a completed workbook into the REVIEW layer. Never touches our layer.

    🔒 `REVIEW_OVERRIDE_VERDICT` IS DELIBERATELY LEFT NULL, and this matters. Sameer answered `B`
    on 69 of 76 rows, but `B` means *"the destination differs"* - and on 33 of them his destination
    turned out to be the SAME as ours. Writing those as an override verdict would record him as
    contradicting a finding he actually agreed with, and the override rate is supposed to be a live
    measurement of the judge (`CLAUDE.md`). What is stored is what he actually said: his own
    destination, in his own words, plus his note.

    ⚠️ AND HIS WORDS ARE STORED VERBATIM, not resolved to a taxonomy key. Three of his answers are
    requests for categories that DO NOT EXIST YET ("need a level for Cutlery"), so there is no key
    to resolve them to. Mapping his free text onto the nearest existing leaf would silently convert
    a request to CHANGE the taxonomy into agreement with the taxonomy as it stands.

    One workbook row is one DECISION covering up to 7 lines, so the answer is written to every line
    in that group - the same grouping the workbook was built from.
    """
    wb = load_workbook(path, data_only=True)
    ws = wb["ANSWER HERE"]
    head = [c.value for c in ws[1]]
    answers = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        row = dict(zip(head, r))
        a = (row.get("YOUR_ANSWER") or "").strip().upper()
        if not a:
            continue
        # Accept the retired OK/A/B on any workbook issued before 2026-08-21, mapped to what the
        # reviewer could actually have MEANT on a blind sheet. `B` cannot be taken at face value -
        # it asserts our destination is wrong, and sheet 1 never showed it (see the note on
        # ANSWERS above). Both OK and B reduce to "it is misfiled"; only the DESTINATION he wrote
        # separates them, and that is now decided by comparison rather than by his letter.
        a = {"OK": "WRONG", "B": "WRONG", "A": "RIGHT"}.get(a, a)
        if a not in ANSWERS:
            print(f"  ** row {row.get('CHECK_ID')}: unrecognised answer {a!r} - SKIPPED")
            continue
        answers[row["CHECK_ID"]] = (a, (row.get("WHERE_IT_SHOULD_GO") or "").strip() or None,
                                    (row.get("YOUR_NOTE") or "").strip() or None)
    if not answers:
        print("  no answers in that workbook - nothing to ingest")
        return 0

    # Rebuild the same groups, so a decision reaches every line it covers.
    extra = STRONGEST if strongest else ""
    qcur.execute(f"""
        SELECT MIN(UNIT_KEY) AS CHECK_ID,
               CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION,
               CATEGORY_LVL_1, CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4,
               NIM_SUGGESTED_CATEGORY_LVL_1, NIM_SUGGESTED_CATEGORY_LVL_2,
               NIM_SUGGESTED_CATEGORY_LVL_3, NIM_SUGGESTED_CATEGORY_LVL_4, MSD_COHERENCE
        FROM qa_line WHERE NIM_ACTION = 'Miscategorised' {extra}
        GROUP BY CLIENT_CODE, SUPPLIER_NAME, ITEM_DESCRIPTION,
                 CATEGORY_LVL_1, CATEGORY_LVL_2, CATEGORY_LVL_3, CATEGORY_LVL_4,
                 NIM_SUGGESTED_CATEGORY_LVL_1, NIM_SUGGESTED_CATEGORY_LVL_2,
                 NIM_SUGGESTED_CATEGORY_LVL_3, NIM_SUGGESTED_CATEGORY_LVL_4, MSD_COHERENCE""")
    groups = qcur.fetchall()
    stamp = __import__("datetime").datetime.now().replace(microsecond=0)
    writes, lines = [], 0
    for g in groups:
        if g[0] not in answers:
            continue
        a, dest, note = answers[g[0]]
        # ⚠️ THE RE-MATCH MUST USE THE **WHOLE** GROUP KEY, INCLUDING THE SUGGESTED CATEGORY.
        # First version stopped at the assigned levels and wrote 120 answers onto 112 lines - two
        # groups collided. They are real: 825781 and 825797 are the SAME Bunzl continence pants with
        # the same filing, which our judge sent to two DIFFERENT destinations. That is precisely the
        # inconsistency this exercise exists to surface, so the two must stay separate rows and the
        # second must not silently overwrite the first.
        # ...AND the same population filter the workbook was built from. Without `{extra}` the
        # re-match reached lines OUTSIDE the 3of3 subset that happened to share the key - 110 lines
        # written for a set that only ever covered 101. An answer applied to a line the reviewer
        # never saw is fabricated review data, which is worse than no review data.
        qcur.execute(f"""SELECT QA_LINE_ID FROM qa_line WHERE NIM_ACTION='Miscategorised' {extra}
                        AND CLIENT_CODE=? AND SUPPLIER_NAME=? AND ITEM_DESCRIPTION=?
                        AND ISNULL(CATEGORY_LVL_1,'')=ISNULL(?,'')
                        AND ISNULL(CATEGORY_LVL_2,'')=ISNULL(?,'')
                        AND ISNULL(CATEGORY_LVL_3,'')=ISNULL(?,'')
                        AND ISNULL(CATEGORY_LVL_4,'')=ISNULL(?,'')
                        AND ISNULL(NIM_SUGGESTED_CATEGORY_LVL_1,'')=ISNULL(?,'')
                        AND ISNULL(NIM_SUGGESTED_CATEGORY_LVL_2,'')=ISNULL(?,'')
                        AND ISNULL(NIM_SUGGESTED_CATEGORY_LVL_3,'')=ISNULL(?,'')
                        AND ISNULL(NIM_SUGGESTED_CATEGORY_LVL_4,'')=ISNULL(?,'')
                        AND ISNULL(MSD_COHERENCE,'')=ISNULL(?,'')""", *g[1:13])
        for (lid,) in qcur.fetchall():
            writes.append((f"answer_key {a}", dest, note, "Sameer", stamp, lid))
            lines += 1
    qcur.fast_executemany = False
    qcur.executemany("""UPDATE qa_line SET REVIEW_STATUS=?, REVIEW_OVERRIDE_CATEGORY=?,
                        REVIEW_NOTE=?, REVIEWED_BY=?, REVIEWED_AT=? WHERE QA_LINE_ID=?""", writes)
    qa.commit()
    print(f"ingested {len(answers)} decisions onto {lines} lines")
    qcur.execute("""SELECT COUNT(*) FROM qa_line WHERE VERDICT IS NULL OR NIM_VERDICT IS NULL""")
    print(f"  our layer untouched (rows missing a verdict): {qcur.fetchone()[0]}   "
          f"REVIEW_OVERRIDE_VERDICT left NULL by design")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Build the Miscategorised answer-key workbook.")
    ap.add_argument("--all", action="store_true",
                    help="every Miscategorised decision, not just the 3of3 + usable-text set")
    ap.add_argument("--ingest", metavar="XLSX",
                    help="read a COMPLETED workbook into the review layer instead of building one")
    args = ap.parse_args()

    if args.ingest:
        qa = connect_qa(pilot=True, env=load_env())
        rc = ingest(qa, qa.cursor(), args.ingest, strongest=not args.all)
        qa.close()
        return rc

    qa = connect_qa(pilot=True, env=load_env())
    qcur = qa.cursor()
    qcur.execute("SELECT COUNT(DISTINCT run_id) FROM qa_line")
    if qcur.fetchone()[0] != 1:
        raise SystemExit("  qa_line holds more than one run_id. STOP.")

    os.makedirs(OUT_DIR, exist_ok=True)
    suffix = " (all)" if args.all else " (3of3)"
    path = os.path.join(OUT_DIR, f"{BASENAME}{suffix} - {date.today():%Y-%m-%d}.xlsx")
    if has_answers(path):
        path = path.replace(".xlsx", " v2.xlsx")
        print("  ** the existing workbook has answers in it - writing v2 rather than overwriting **")

    n_rows, n_lines = build(qcur, path, strongest=not args.all)
    print(f"{n_rows} decisions covering {n_lines} lines")
    print(f"-> {path}")
    print("\nSheets: 'READ THIS FIRST' | 'ANSWER HERE' (no verdict shown) | "
          "'OUR ANSWER (open after)'")
    print("Answers: OK / A / B in YOUR_ANSWER. Blank means not reviewed, never agreement.")
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
