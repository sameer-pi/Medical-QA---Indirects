"""Indirect QA — THE LIVE RUN MONITOR. A read-only window onto the judging run.

    python pipeline/monitor.py                    # the pilot, http://127.0.0.1:8000
    python pipeline/monitor.py --production       # the real run
    python pipeline/monitor.py --production --poll 15 --every-lines 1 --stall 15

Serves ONE page on localhost that answers three questions while the judge runs for ~40 days on the
office desktop: IS IT ALIVE, HOW FAR THROUGH ARE WE, and WHAT ARE WE FINDING. It refreshes itself.

WHO IT IS FOR. Sameer and his manager, both at the office desktop (2026-08-26). It binds to
127.0.0.1 and is NOT on the office network - everyone who needs it has access to that machine, so a
LAN binding would only widen who can quote a provisional number.

🔒 THIS IS NOT THE APP SAMEER KILLED ON 2026-08-21. Stages 7-app and 4b stay DEAD. What died was an
app the ANALYST works in, that WRITES to the database, and that is a CLIENT DELIVERABLE. This is
none of those: read-only, internal, no analyst, no write path, thrown away when the run ends. If it
ever grows a review screen, an override, or a client login, it has become that app - stop and ask.
APP.md holds the reasoning and the open decisions.

WHY IT POLLS INSTEAD OF BEING TOLD. Sameer asked for a refresh "after every 500 lines". The judge
commits one batch (default 10 lines) at a time, so at ~50 lines/min the database moves every ~12
seconds and 500 lines is ONE REDRAW EVERY ~10 MINUTES - slower than "live" sounds. So this polls a
cheap count instead and redraws when it moves (--every-lines 500 restores the literal behaviour).

  🔑 THE REAL REASON IS NOT THE CADENCE. Polling needs ZERO CHANGES TO nim_judge.py. Every
  alternative trigger - a heartbeat row, the judge calling this, a database trigger - puts new code
  inside the one thing that must survive 40 unattended days. This watches; the judge never learns
  it exists. That is worth more than any refresh interval.

COST - AND THE FIRST FIGURE I GAVE FOR THIS WAS WRONG. Measured 2026-08-26 on production
(2,786,018 rows, qa_line is 4,214 MB on disk, WITH (NOLOCK)):

    every query WARM      22 - 145 ms      whole panel ~1 s
    the SAME queries COLD    up to 47.6 s  once measured at 18.2 s, once at 6.1 s

  🔑 THE VARIANCE IS THE FINDING, NOT THE AVERAGE. Every read here is a full scan of a 4.2 GB table.
  When those pages are in the buffer pool it is a tenth of a second; when they are not, it is the
  time to pull 4.2 GB off disk. I first quoted "~0.5 s" from a warm measurement and presented it as
  the cost - the project's own error of quoting a number without the conditions that produced it.
  ⚠️ THE COLD CASE IS NOT HYPOTHETICAL: the nightly FULL backup at 00:15 reads the whole database
  and evicts the cache, so the first refresh after ~00:30 every night will be slow.

  SO THIS IS BUILT TO SURVIVE A SLOW READ RATHER THAN TO ASSUME A FAST ONE:
    - the reads run on a BACKGROUND thread; the page is served from the last good snapshot and
      never blocks on the database;
    - one refresh at a time, so a 40 s read simply means fewer refreshes, never a pile-up;
    - the page prints how long the last refresh actually took, so this stops being a guess;
    - if the database cannot be reached the page says STALE and names the last good read, rather
      than showing an old number that looks current.

  ⚠️ AND ALL OF IT WAS MEASURED WITH THE NIM LAYER ENTIRELY NULL. NIM_RATIONALE is nvarchar(2000)
  across ~30 columns; once they fill, qa_line grows well beyond 4.2 GB and every figure above moves.
  RE-MEASURE at ~100k judged and record it in APP.md § 3. The refresh timer on the page is there so
  that re-measurement is a glance rather than a task.

  NO INDEX WAS ADDED. An index on NIM_VERDICT / NIM_JUDGED_AT would make the warm case slightly
  faster and the cold case much faster - but it is a schema change to a 4.2 GB production table
  that is about to take 40 days of writes, made to serve a WATCHER. That is precisely the line this
  file is not supposed to cross. If the cold case turns out to hurt in practice, it is a decision
  to put to Sameer with the measurement, not one to take quietly. APP.md decision 8.

🔒 IT ISSUES SELECT AND NOTHING ELSE, AND THAT IS ENFORCED IN CODE. Every statement goes through
_ro(), which refuses any SQL containing a write verb. A monitor that could write is one careless
line from damaging the table the run is filling. The connection is short-lived, one per refresh,
and every read is WITH (NOLOCK) so it can never block the judge's commit.
  ⚠️ THE REAL GUARANTEE IS A PERMISSION, NOT THIS CODE. [Claude] holds db_datawriter. A
  db_datareader-only login is APP.md decision 5 and needs db_owner, which we deliberately lack.
  _ro() is the belt; that login is the braces, and it is still open.

FOUR THINGS THIS FILE REFUSES TO DO - inherited from dashboard.py, which paid for each one:
  1. It reads NIM_* - the live three-model jury - and NEVER the older Claude verdict columns. Two
     verdict layers coexist in qa_line and mixing them on one screen is how the wrong one gets
     quoted. state_audit.py reported only the old one until 2026-08-18.
  2. 'Out of scope' IS NOT AN ERROR. It is a scope finding owned by the hospital's clinical
     categorisation, and folding it in inflates every rate on the page.
  3. It does NOT compute a "% with a destination". NIM_SUGGESTED_KEY is NULL BY DESIGN on a Correct
     verdict, so that ratio undercounts by exactly the lines we got right (RUN_LOG Finding 96).
  4. It does NOT touch qa_rule.ERROR_RATE, which is derived from the OLD verdict layer.

AND FOUR OF ITS OWN:
  5. ERROR RATE IS Incorrect / (Correct + Incorrect). Uncertain is excluded from BOTH sides and
     stated as its own headline - it is the size of the manual analyst queue, a finding in itself.
     Incorrect / everything is a different, smaller, WRONG number.
  6. IT RANKS BY LINE COUNT, NEVER BY SPEND. Ranking by spend requires deciding which rows are
     real, and 237 Melbourne lines carry $24.5bn gross against $433M net. Line count needs no
     threshold and no judgement.
  7. A RULE ROW ALWAYS NAMES ITS TABLE. A rule ID names independent COPIES: fixing MEL-0881 in
     Northern's table does nothing to Melbourne's.
  8. NO EXPORT BUTTON. The moment a screenshot leaves the building the banner is all that travels
     with the number. Making it easy to lift the figure is making it easy to lose the caveat.

🔒 AND THE NUMBER THIS PAGE MUST NEVER BE READ WITHOUT ITS BANNER. A mid-run error rate is THE
LARGEST VENDORS' error rate, not the hospital's - the run order is spend-weighted, which is the
exact opposite of a spread sample. TRACKER.md records that accuracy has never been measured on a
spread sample, so no per-client figure is client-facing. The banner is permanent, at the top, and
every rate carries its own denominator on the tile rather than in a tooltip.

SPEND IS SIGNED AND AS-IS - no threshold, no netting, no absolute values. Shown as figures, never as
a stacked proportion bar, because such a bar cannot draw a negative segment and quietly switching to
absolute would look identical while breaking the standing rule.

NIM_JUDGED_AT IS NOT A TRANSACTION DATE. It is when the judge wrote the row, never when the hospital
bought anything. The judge writes it from ITS OWN clock (datetime.now() in nim_judge.write), so the
"minutes since" figures here are only right when this runs on the same machine as the judge - which
is the deployment Sameer chose. If that ever changes, the two clocks must be reconciled.
"""
import argparse
import html
import json
import os
import re
import smtplib
import sys
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clientcfg                                                        # noqa: E402
import dashboard                                                        # noqa: E402
from db import connect_qa, load_env                                     # noqa: E402
from judge import VERDICTS                                              # noqa: E402

# 🔴 THE VALID VERDICT VOCABULARY, IMPORTED FROM judge.py AND NEVER RETYPED. Correct / Incorrect /
# Uncertain. A second hardcoded copy here would drift the day a fourth verdict is added, and this
# page would then quietly re-classify real answers as junk.
_V = "','".join(VERDICTS)
IN_VERDICTS = "IN ('" + _V + "')"
NOT_VERDICT = "{col} IS NOT NULL AND {col} NOT IN ('" + _V + "')"

# The six NIM_ACTION values, their colours and their meanings come from dashboard.py so there is ONE
# place a value's colour and description are defined. A second copy is a second thing that drifts,
# and 'Out of scope' being NEUTRAL rather than red is a decision, not a styling choice.
ACTIONS = dashboard.ACTIONS
ERROR_ACTIONS = dashboard.ERROR_ACTIONS
money = dashboard.money

# Any of these in a statement and it does not run. A blocklist would be the wrong shape for a
# filter on untrusted input, but this input is not untrusted - it is the constant SQL in this file,
# and the check exists to catch a careless EDIT to that SQL, not an attacker.
WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE", "TRUNCATE",
               "GRANT", "REVOKE", "EXEC", "SP_", "BACKUP", "RESTORE", "INTO ")


def _ro(sql):
    """Refuse anything that is not a plain SELECT. Called on every statement, every time."""
    up = " " + re.sub(r"\s+", " ", sql.upper()).strip() + " "
    if not up.strip().startswith("SELECT"):
        raise RuntimeError("monitor: statement does not start with SELECT")
    for v in WRITE_VERBS:
        if v in up:
            raise RuntimeError("monitor: REFUSING - statement contains %r. This process reads." % v)
    return sql


def q(cur, sql, *args):
    cur.execute(_ro(sql), *args)
    return cur.fetchall()


# --------------------------------------------------------------------------------------------------
# THE READS. Each one is a whole-table aggregate; see the cost note at the top of the file.
# --------------------------------------------------------------------------------------------------

def heartbeat(cur):
    """THE CHEAP ONE - runs on every poll. Is it alive, has anything moved, and how fast?

    Separate from panel() on purpose. The health strip must refresh even when the judged count has
    NOT moved, because a count that stops moving IS the signal. Folded into the expensive query, a
    stall would be the one situation in which the page stopped updating.

    🔑 ONE SCAN, NOT THREE. The count, the timestamp and both throughput windows are conditional
    aggregates over the same pass. This is the project's own lesson - 'Merge scans. Profiling ran
    two full passes for figures obtainable in one' - and at one poll every 15 s for ~40 days the
    difference is 230,000 avoidable scans of 2.79M rows.

    The two cutoffs are computed from THIS machine's clock, matched to NIM_JUDGED_AT which the judge
    writes from its own. Same machine in the chosen deployment; see the clock note at the top."""
    now = datetime.now()
    c15, c60 = now - timedelta(minutes=15), now - timedelta(minutes=60)
    r = q(cur, """SELECT COUNT(*),
                         SUM(CASE WHEN NIM_VERDICT IS NOT NULL THEN 1 ELSE 0 END),
                         MAX(NIM_JUDGED_AT),
                         SUM(CASE WHEN NIM_JUDGED_AT >= ? THEN 1 ELSE 0 END),
                         SUM(CASE WHEN NIM_JUDGED_AT >= ? THEN 1 ELSE 0 END),
                         MIN(CASE WHEN NIM_JUDGED_AT >= ? THEN NIM_JUDGED_AT END),
                         MIN(CASE WHEN NIM_JUDGED_AT >= ? THEN NIM_JUDGED_AT END)
                  FROM qa_line WITH (NOLOCK)""", c15, c60, c15, c60)[0]
    return {"lines": r[0] or 0, "judged": r[1] or 0, "last_at": r[2],
            "n15": r[3] or 0, "n60": r[4] or 0, "first15": r[5], "first60": r[6],
            "at": now}


def rate(n, first_at, window, now):
    """Lines per minute - divided by the span the data ACTUALLY covers, not the nominal window.

    🔴 FOUND BY WATCHING A REAL JUDGE, 2026-08-26, and it could not have been found any other way.
    The first version divided by the window: 22 lines four minutes into a run became 22/15 = 1.5,
    and over the 60-minute window 22/60 = 0.37, which rounded to a displayed **0 lines/min while
    the judge was visibly working**. That is the single most misleading thing this page could say -
    it is the number someone checks to decide whether the run is healthy, and it read zero on a
    healthy run.

    Two faults, both fixed here. The denominator is now the time from the EARLIEST verdict inside
    the window to now, so a window that is not yet full is not treated as though it were; and the
    value is formatted with a decimal below 10 so a real rate can never round away to nothing.

    A judge that stopped part-way through the window still divides by the full span, which is
    correct: the rate is per wall-clock minute, idle time included, because that is what an ETA
    has to be built on. Whether it is working RIGHT NOW is the stall tile's job, not this one."""
    if not n or not first_at:
        return 0.0
    span = min(float(window), max((now - first_at).total_seconds() / 60.0, 1.0 / 60.0))
    return n / span if span > 0 else 0.0


def fmt_rate(r):
    """Never round a real rate down to '0'. Below 10/min one decimal is the difference between
    'crawling' and 'stopped', and those need different responses."""
    if r <= 0:
        return "0"
    return "%.1f" % r if r < 10 else "{:,}".format(int(round(r)))


def panel(cur):
    """THE EXPENSIVE ONE - only when the judged count has moved. ~0.5 s, measured."""
    d = {}

    # 1. per client: progress, the verdict mix, jury health, spend covered. One scan.
    for r in q(cur, """
            SELECT CLIENT_CODE,
                   COUNT(*),
                   SUM(CASE WHEN NIM_VERDICT IS NOT NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN NIM_VERDICT='Correct'   THEN 1 ELSE 0 END),
                   SUM(CASE WHEN NIM_VERDICT='Incorrect' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN NIM_VERDICT='Uncertain' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN NIM_AGREEMENT='3of3' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN NIM_MODELS_RESPONDED IS NOT NULL
                             AND NIM_MODELS_RESPONDED < 3 THEN 1 ELSE 0 END),
                   SUM(CAST(SPEND AS float)),
                   SUM(CASE WHEN NIM_VERDICT IS NOT NULL THEN CAST(SPEND AS float) ELSE 0 END),
                   MAX(NIM_JUDGED_AT)
            FROM qa_line WITH (NOLOCK) GROUP BY CLIENT_CODE"""):
        d[r[0]] = dict(lines=r[1], judged=r[2] or 0, correct=r[3] or 0, incorrect=r[4] or 0,
                       uncertain=r[5] or 0, three=r[6] or 0, thin=r[7] or 0,
                       spend=r[8] or 0.0, spend_judged=r[9] or 0.0, last_at=r[10], acts={})

    # 2. the action mix - what should HAPPEN to each judged line
    for cc, act, n, spend in q(cur, """
            SELECT CLIENT_CODE, NIM_ACTION, COUNT(*), SUM(CAST(SPEND AS float))
            FROM qa_line WITH (NOLOCK) WHERE NIM_VERDICT IS NOT NULL
            GROUP BY CLIENT_CODE, NIM_ACTION"""):
        if cc in d:
            # ⚠️ NULL here is not an error - action_classify.py runs AFTER judging, so an
            # in-progress run legitimately has no action on any line. Named rather than dropped.
            d[cc]["acts"][act or "not classified yet"] = (n, spend or 0.0)

    # 3. VENDORS FINISHED - MEASURED FROM THE LINES, NEVER FROM qa_vendor_queue.QUEUE_STATUS.
    #
    # 🔴 THAT COLUMN IS STALE AND STRUCTURALLY UNDER-REPORTS. Measured 2026-08-26 with the pilot
    # fully judged: QUEUE_STATUS said western_health 6 done / 179 pending while qa_line said 0
    # unjudged of 500, and sydney_adventist still carried 12 vendors stuck at 'in_progress' from
    # the crash in Finding 133. The page read "vendors 6/185" beside "100.00% judged" - not a
    # cosmetic wrinkle, it reads as "we have barely started Western".
    #
    # THE CAUSE, corrected 2026-08-26 by grepping for the writer instead of assuming one:
    # ⚠️ NOTHING EVER UPDATES IT. `vendor_queue.py` line 125 derives it from qa_line ONCE, at build
    # time; `nim_judge.py` does not contain the string QUEUE_STATUS at all. It is a PHOTOGRAPH OF
    # THE MOMENT THE QUEUE WAS BUILT, not a live gauge - so it is correct for exactly as long as it
    # takes the judge to write its first verdict, and then drifts for the rest of the run.
    #
    # I first wrote here that judge_queue's `if not n: skipped += 1; continue` skipped a vendor
    # before marking it done. WRONG - there is no marking step to skip. Kept, struck, because the
    # error is the project's recurring one: a mechanism inferred from reading the loop that looked
    # like it should update the column, rather than measured by asking what writes it.
    #
    # ONE-DIRECTIONAL, which matters for the pending `QUEUE_STATUS <> 'done'` decision: judging is
    # forward-only, so a row that read 'done' at build time IS still done. It is 'pending' and
    # 'in_progress' that rot. The 12 sydney_adventist rows stuck at 'in_progress' are simply the
    # vendors that were half-judged at the instant of the last build.
    #
    # 🔑 So this counts vendors with ZERO unjudged lines, from qa_line itself. A measurement rather
    # than a stored flag: it needs no change to nim_judge.py and it cannot go stale. Same reasoning
    # as jury health - a check built on a column that lies, lies. The queue table remains the source
    # of the ORDER; it is simply no longer trusted for PROGRESS.
    queue, current = {}, []
    for cc, done, total in q(cur, """
            SELECT CLIENT_CODE,
                   SUM(CASE WHEN unj = 0 THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM (SELECT CLIENT_CODE, SUPPLIER_NAME,
                         SUM(CASE WHEN NIM_VERDICT IS NULL THEN 1 ELSE 0 END) AS unj
                  FROM qa_line WITH (NOLOCK)
                  GROUP BY CLIENT_CODE, SUPPLIER_NAME) v
            GROUP BY CLIENT_CODE"""):
        queue[cc] = {"done": done or 0, "pending": (total or 0) - (done or 0)}
    for r in q(cur, """SELECT TOP 5 CLIENT_CODE, SUPPLIER_NAME, GLOBAL_RANK, VENDOR_RANK, LINES_TOTAL
                       FROM qa_vendor_queue WITH (NOLOCK) WHERE QUEUE_STATUS='in_progress'
                       ORDER BY GLOBAL_RANK"""):
        current.append(dict(client=r[0], vendor=r[1], grank=r[2], vrank=r[3], lines=r[4]))

    # 4. where the errors cluster. RANKED BY LINE COUNT, never by spend - see refusal 6.
    #    SUPPLIER_NAME is VERBATIM: not trimmed, cased or normalised, here or anywhere.
    vendors = [dict(client=r[0], vendor=r[1], n=r[2], spend=r[3] or 0.0) for r in q(cur, """
            SELECT TOP 15 CLIENT_CODE, SUPPLIER_NAME, COUNT(*), SUM(CAST(SPEND AS float))
            FROM qa_line WITH (NOLOCK) WHERE NIM_VERDICT='Incorrect'
            GROUP BY CLIENT_CODE, SUPPLIER_NAME ORDER BY COUNT(*) DESC""")]

    # 5. and which RULES. The rules table is not optional - see refusal 7.
    rules = [dict(client=r[0], rule=r[1], table=r[2] or "(unresolved)", n=r[3]) for r in q(cur, """
            SELECT TOP 15 l.CLIENT_CODE, l.RULE_ID, MAX(r.RULES_TABLE), COUNT(*)
            FROM qa_line l WITH (NOLOCK)
            LEFT JOIN qa_rule r WITH (NOLOCK)
                   ON r.RUN_ID=l.RUN_ID AND r.CLIENT_CODE=l.CLIENT_CODE AND r.RULE_ID=l.RULE_ID
            WHERE l.NIM_VERDICT='Incorrect' AND l.RULE_ID IS NOT NULL
            GROUP BY l.CLIENT_CODE, l.RULE_ID ORDER BY COUNT(*) DESC""")]

    # 6. 🔒 PROMPT VERSIONS IN FLIGHT. More than one is a STOP: verdicts either side of a prompt
    #    bump are not comparable, and v3 -> v4 is not comparable at all on lines with no usable
    #    item text. This was impossible to see from qa_line_view until 2026-08-26.
    versions = [(r[0] or "(none)", r[1]) for r in q(cur, """
            SELECT NIM_PROMPT_VERSION, COUNT(*) FROM qa_line WITH (NOLOCK)
            WHERE NIM_VERDICT IS NOT NULL GROUP BY NIM_PROMPT_VERSION ORDER BY COUNT(*) DESC""")]

    # 7. 🔴 THE JURY PANEL - how much the three graders DISAGREE. It is NOT an accuracy table and
    #    must never be labelled one: there is NO GROUND TRUTH in this database. Measured
    #    2026-08-26 on the pilot - REVIEW_OVERRIDE_VERDICT, REVIEW_STATUS and REVIEWED_AT are
    #    populated on ZERO rows, and the human answer key is orphaned. Anything here called
    #    "accuracy" would be invented.
    #
    #    WHAT IT DOES SHOW, and why it earns its place. Measured on the pilot the same day:
    #        seat 1  nvidia/nemotron-3-super-120b   Correct 47.3%  Incorrect 21.3%
    #        seat 2  openai/gpt-oss-120b            Correct 29.3%  Incorrect 50.8%
    #    SEAT 2 CALLS A LINE WRONG 2.4x MORE OFTEN THAN SEAT 1. These are not three readings of one
    #    standard, they are three different graders - so the headline error rate is substantially
    #    decided by WHICH TWO OF THE THREE happen to agree. Anyone about to quote that rate should
    #    see this first.
    #
    #    🔴 AND IT IS HOW A REAL DEFECT WAS FOUND. google/gemma-4-31b-it returns 'Uncategorised'
    #    (81) and 'categorised' (5) - neither is a verdict. vote() correctly discards them, so the
    #    CONSENSUS is unharmed, but nim_judge.responded() counts any non-empty string, so those
    #    lines are stamped NIM_MODELS_RESPONDED = 3. 86 of 1,801 judged pilot lines (4.78%) claim a
    #    full jury and had two valid votes. See the valid-vote count below.
    #
    #    ONE SCAN, not three. Every figure here is a conditional aggregate over the same pass.
    seats, jury = [], None
    sel, nv = [], []
    for i in (1, 2, 3):
        c = "NIM_%d_VERDICT" % i
        sel += ["MAX(NIM_%d_MODEL)" % i, "COUNT(DISTINCT NIM_%d_MODEL)" % i]
        sel += ["SUM(CASE WHEN %s='%s' THEN 1 ELSE 0 END)" % (c, v) for v in VERDICTS]
        sel += ["SUM(CASE WHEN %s IS NULL THEN 1 ELSE 0 END)" % c,
                "SUM(CASE WHEN %s THEN 1 ELSE 0 END)" % NOT_VERDICT.format(col=c),
                "SUM(CASE WHEN %s = NIM_VERDICT THEN 1 ELSE 0 END)" % c]
        nv.append("CASE WHEN %s %s THEN 1 ELSE 0 END" % (c, IN_VERDICTS))
    # 🔑 THE HONEST JURY COUNT: lines with fewer than three VALID votes, computed from the votes
    # themselves rather than trusting NIM_MODELS_RESPONDED. This needs no change to nim_judge.py.
    sel += ["SUM(CASE WHEN (%s) < 3 THEN 1 ELSE 0 END)" % " + ".join(nv), "COUNT(*)"]
    row = q(cur, "SELECT " + ", ".join(sel)
            + " FROM qa_line WITH (NOLOCK) WHERE NIM_VERDICT IS NOT NULL")[0]
    k = 0
    for i in (1, 2, 3):
        model, nmodels = row[k], row[k + 1]
        counts = dict(zip(VERDICTS, row[k + 2:k + 2 + len(VERDICTS)]))
        k += 2 + len(VERDICTS)
        seats.append({"seat": i, "model": model or "(none)", "models_seen": nmodels or 0,
                      "counts": {a: (b or 0) for a, b in counts.items()},
                      "silent": row[k] or 0, "invalid": row[k + 1] or 0,
                      "agrees": row[k + 2] or 0})
        k += 3
    jury = {"thin_valid": row[k] or 0, "judged": row[k + 1] or 0}

    # 8. THROUGHPUT OVER TIME. One bar per hour, newest last. The reason this earns space: watching
    #    the pilot on 2026-08-26 the rate fell from ~10/min to 2.3/min inside an hour as the queue
    #    reached the long tail of tiny vendors - and that was only noticed because someone happened
    #    to be staring at the number. Over ~40 days this is the strip that says the ETA is drifting
    #    and roughly why. It is also the only view here with a MEMORY; every other tile is now.
    #    🔴 EVERY HOUR IN THE WINDOW GETS A BAR, INCLUDING THE EMPTY ONES. The first version drew
    #    only the hours that had activity, so five bars sat shoulder to shoulder across two days and
    #    a 20-hour outage was invisible - the chart silently closed the gap. A gap drawn as
    #    adjacency is a lie, and on a 40-day unattended run the gaps ARE the story. So the window is
    #    a fixed 48 hours back from now and missing hours are filled with zero, which is what makes
    #    a night the judge spent dead show up as a trough instead of disappearing.
    now_h = datetime.now().replace(minute=0, second=0, microsecond=0)
    since = now_h - timedelta(hours=47)
    got = {(str(r[0]), int(r[1])): r[2] for r in q(cur, """
            SELECT CONVERT(date, NIM_JUDGED_AT), DATEPART(hour, NIM_JUDGED_AT), COUNT(*)
            FROM qa_line WITH (NOLOCK) WHERE NIM_JUDGED_AT >= ?
            GROUP BY CONVERT(date, NIM_JUDGED_AT), DATEPART(hour, NIM_JUDGED_AT)""", since)}
    hours = []
    for k in range(48):
        t = since + timedelta(hours=k)
        hours.append((t.strftime("%Y-%m-%d"), t.hour, got.get((t.strftime("%Y-%m-%d"), t.hour), 0)))

    started = q(cur, "SELECT MIN(NIM_JUDGED_AT) FROM qa_line WITH (NOLOCK)")[0][0]
    runs = [r[0] for r in q(cur, "SELECT DISTINCT RUN_ID FROM qa_line WITH (NOLOCK)")]
    return {"clients": d, "queue": queue, "current": current, "vendors": vendors,
            "rules": rules, "versions": versions, "started": started, "runs": runs,
            "seats": seats, "jury": jury, "hours": hours}


# --------------------------------------------------------------------------------------------------
# THE ALERT. Sameer, 2026-08-26: "Red on the page AND an email to you".
# --------------------------------------------------------------------------------------------------

def mail_config(env):
    """Read the alert settings from .env. ABSENT IS NOT AN ERROR - the page still works and says so.

    🔒 NOTHING FROM .env IS EVER PRINTED OR SERVED. Only whether it is configured, and the TO
    address, ever reach the page."""
    c = {k: (env.get("MONITOR_" + k) or "").strip() for k in
         ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_FROM", "ALERT_TO")}
    c["ready"] = bool(c["SMTP_HOST"] and c["ALERT_TO"] and c["ALERT_FROM"])
    # 🔴 A USER WITH NO PASSWORD IS NOT READY, IT IS A GUARANTEED FAILURE AT 2AM.
    # Caught 2026-08-26 the moment five of the six keys were filled in: the first version called
    # that state "armed", because it only checked host/from/to. It would have logged in with an
    # empty password, been refused, and reported the failure on the ONE occasion anyone needed the
    # email to work. A monitor that says it is armed when it cannot fire is worse than one that
    # says nothing - the whole point of this page is that it does not claim what it has not
    # verified. (SMTP_USER blank is a different, legitimate case: an internal relay that needs no
    # authentication at all. That still counts as ready.)
    c["why"] = ""
    if not c["ready"]:
        c["why"] = "not configured"
    elif c["SMTP_USER"] and not c["SMTP_PASS"]:
        c["ready"] = False
        c["why"] = ("MONITOR_SMTP_PASS is blank. It needs an app password. The page still reddens; "
                    "no email will be sent")
    return c


def send_alert(cfg, subject, body):
    """One email. Returns (ok, message) and NEVER raises - a broken mailbox must not stop the page."""
    if not cfg["ready"]:
        return False, cfg.get("why") or "not configured"
    try:
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = subject, cfg["ALERT_FROM"], cfg["ALERT_TO"]
        m.set_content(body)
        port = int(cfg["SMTP_PORT"] or 587)
        with smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=30) as s:
            s.starttls()
            if cfg["SMTP_USER"]:
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(m)
        return True, "sent %s" % datetime.now().strftime("%H:%M:%S")
    except Exception as e:                      # noqa: BLE001 - deliberately swallowing everything
        return False, "FAILED: %s" % str(e)[:200]


# --------------------------------------------------------------------------------------------------
# THE STATE. One object, one lock, refreshed by the poller thread and read by the handler.
# --------------------------------------------------------------------------------------------------

class Monitor(object):
    def __init__(self, args, env):
        self.args, self.env = args, env
        self.mail = mail_config(env)
        self.lock = threading.Lock()
        self.hb = self.pnl = None
        self.rate15 = self.rate60 = 0
        self.dbname = "?"
        self.last_panel_judged = -1
        self.last_ok = None                 # when we last reached the database at all
        self.err = None                     # what went wrong, shown instead of a stale-looking page
        self.stalled = False
        self.alerted = False                # one email per stall EPISODE, not per poll
        self.last_ms = 0                    # how long the last refresh took, shown on the page
        self.slow_ms = 0                    # the worst one so far, so a bad night is not forgotten
        self.full = False                   # was the last refresh a full panel or just a heartbeat
        self.mail_note = self.mail["why"] or ("armed → " + self.mail["ALERT_TO"])

    # ---- the refresh -----------------------------------------------------------------------------
    def refresh(self):
        qa = None
        t0 = time.time()
        try:
            qa = connect_qa(production=self.args.production, env=self.env, timeout=180)
            cur = qa.cursor()
            self.dbname = q(cur, "SELECT DB_NAME()")[0][0]
            hb = heartbeat(cur)
            # THE FULL PANEL ONLY WHEN THE COUNT HAS MOVED (or on the first pass, or when the
            # operator asked for a fixed quantum with --every-lines).
            need = (self.pnl is None
                    or hb["judged"] - self.last_panel_judged >= self.args.every_lines)
            pnl = panel(cur) if need else None
            with self.lock:
                self.hb = hb
                self.rate15 = rate(hb["n15"], hb["first15"], 15, hb["at"])
                self.rate60 = rate(hb["n60"], hb["first60"], 60, hb["at"])
                if pnl is not None:
                    self.pnl, self.last_panel_judged = pnl, hb["judged"]
                self.last_ok, self.err = datetime.now(), None
                # 🔑 HOW LONG THAT ACTUALLY TOOK, ON THE PAGE. Measured cold reads of this table
                # ranged from 0.9 s to 47.6 s, so the honest thing is to show the real number every
                # time rather than quote an average that was true once.
                self.last_ms = int((time.time() - t0) * 1000)
                self.slow_ms = max(self.slow_ms, self.last_ms)
                self.full = pnl is not None
        except Exception as e:                  # noqa: BLE001
            with self.lock:
                self.err = str(e)[:300]
                self.last_ms = int((time.time() - t0) * 1000)
        finally:
            if qa is not None:
                try:
                    qa.close()
                except Exception:               # noqa: BLE001
                    pass
        self.check_stall()

    def age(self):
        """Minutes since the last verdict was written, or None if nothing has been judged."""
        with self.lock:
            hb = self.hb
        if not hb or not hb["judged"] or not hb["last_at"]:
            return None
        return (datetime.now() - hb["last_at"]).total_seconds() / 60.0

    def check_stall(self):
        """🔴 A STALLED RUN AND A FINISHED ONE BOTH STOP MOVING. This is what tells them apart, and
        it is the reason this page exists at all: over 40 unattended days the expensive failure is
        the judge dying at 2am on day 6 and nobody noticing until day 9."""
        a = self.age()
        with self.lock:
            hb = self.hb
        done = bool(hb and hb["judged"] and hb["judged"] >= hb["lines"])
        now_stalled = bool(a is not None and a >= self.args.stall and not done)
        was = self.stalled
        self.stalled = now_stalled

        if now_stalled and not self.alerted:
            self.alerted = True
            ok, note = send_alert(
                self.mail,
                "[Indirect QA] JUDGE MAY BE DOWN - no verdict for %.0f minutes" % a,
                ("The Indirects judging run has written no verdict for %.0f minutes.\n\n"
                 "  database        %s\n  judged          %s of %s lines\n"
                 "  last verdict    %s\n\nThis is the run monitor on the office desktop.\n"
                 "A stalled run and a finished one both stop moving - this says it is NOT finished.\n"
                 "Check the judge process before assuming it is a slow batch.\n"
                 % (a, self.dbname, "{:,}".format(hb["judged"]), "{:,}".format(hb["lines"]),
                    hb["last_at"])))
            self.mail_note = ("stall alert " + note) if ok else ("stall alert " + note)
        elif was and not now_stalled:
            self.alerted = False
            ok, note = send_alert(
                self.mail, "[Indirect QA] judging resumed",
                "Verdicts are being written again on %s. Last verdict %s.\n"
                % (self.dbname, hb["last_at"] if hb else "?"))
            self.mail_note = ("recovery " + note) if self.mail["ready"] else self.mail_note

    def loop(self):
        while True:
            self.refresh()
            time.sleep(self.args.poll)


# --------------------------------------------------------------------------------------------------
# THE PAGE. Rendered in Python so it can be read and reasoned about; the browser only swaps innerHTML.
# --------------------------------------------------------------------------------------------------

_NAMES = {}


def name_of(cc):
    """Client display name, cached. Read from clients/<key>/config.yaml, never hardcoded here -
    NO CLIENT NAMES ANYWHERE IN pipeline/, ever. Cached because the vendor and rule tables call this
    30 times per redraw and it would otherwise re-read and re-parse a YAML file each time."""
    if cc not in _NAMES:
        try:
            _NAMES[cc] = clientcfg.display_name(clientcfg.load_config(cc), cc)
        except Exception:                       # noqa: BLE001 - a moved config must not kill the page
            _NAMES[cc] = cc.replace("_", " ").title()
    return _NAMES[cc]


def pct(n, d, dp=1):
    return ("{:." + str(dp) + "f}%").format(100.0 * n / d) if d else "—"


def ago(mins):
    if mins is None:
        return "never"
    if mins < 1:
        return "%.0f sec ago" % (mins * 60)
    if mins < 90:
        return "%.0f min ago" % mins
    return "%.1f hours ago" % (mins / 60.0)


def health_strip(m):
    """🔴 THE STRIP NOBODY ASKED FOR, AND THE MOST VALUABLE ONE ON THE PAGE.

    Rewritten 2026-08-26 for legibility - Sameer: *"the viewer wont know exactly what to look at"*.
    The VALUE comes first and large, the label sits underneath in small caps, and colour means one
    thing only: green fine, amber watch, red act. A tile is only coloured when it is saying
    something; a page where everything is coloured is a page where nothing is.
    """
    with m.lock:
        hb, r15, r60, err, pnl = m.hb, m.rate15, m.rate60, m.err, m.pnl
    a = m.age()
    if err:
        return ('<div class="strip"><div class="tile bad"><div class="v">UNREACHABLE</div>'
                '<div class="k">database · last good read {}</div></div>'
                '<div class="tile"><div class="v" style="font-size:12.5px">{}</div>'
                '<div class="k">what the server said</div></div></div>').format(
                    m.last_ok.strftime("%H:%M:%S") if m.last_ok else "never",
                    html.escape(err))
    if not hb:
        return '<div class="strip"><div class="tile"><div class="v">starting…</div></div></div>'

    thin = sum(c["thin"] for c in (pnl or {}).get("clients", {}).values())
    seen = sum(c["judged"] for c in (pnl or {}).get("clients", {}).values())
    thin_valid = ((pnl or {}).get("jury") or {}).get("thin_valid", thin)
    vers = (pnl or {}).get("versions", [])
    runs = (pnl or {}).get("runs", [])

    if not hb["judged"]:
        state, cls = "NOT STARTED", ""
    elif m.stalled:
        state, cls = "JUDGE MAY BE DOWN", "bad"
    elif hb["judged"] >= hb["lines"]:
        state, cls = "COMPLETE", "good"
    else:
        state, cls = "RUNNING", "good"

    # jury health earns amber at all, red past 1% - the rate check from Finding 95, now on a
    # number counted from the votes rather than from the column that over-reports.
    jr = (100.0 * thin_valid / seen) if seen else 0.0
    jcls = "good" if not thin_valid else ("bad" if jr > 1.0 else "amber")

    tiles = [(state, "run state", cls),
             (ago(a), "last verdict written", "bad" if m.stalled else ""),
             (fmt_rate(r15), "lines/min · 15 min", ""),
             (fmt_rate(r60), "lines/min · 60 min", ""),
             ("{:,}".format(thin_valid) + (" · " + pct(thin_valid, seen, 2) if seen else ""),
              "jury under 3 valid votes", jcls),
             (" · ".join(html.escape(str(v)) for v, _ in vers) or "—",
              "prompt version", "bad" if len(vers) > 1 else "")]
    # ⚠️ "judging now" reads qa_vendor_queue.QUEUE_STATUS='in_progress', which a crash leaves
    # behind: the pilot carried 12 stale in_progress rows for hours after its judge had died. So it
    # is shown ONLY while the judge is demonstrably alive and there is work left. A stale vendor
    # name beside a dead judge is worse than no vendor name at all, because it reads as activity.
    cur = (pnl or {}).get("current") or []
    if cur and not m.stalled and hb["judged"] < hb["lines"]:
        c = cur[0]
        tiles.append(('<span style="font-size:12.5px">{}</span>'.format(
            html.escape(str(c["vendor"] or "(no vendor name)"))[:38]),
            "judging now · " + html.escape(name_of(c["client"])), ""))

    warn = ""
    gap = thin_valid - thin
    if gap > 0:
        bad = [x for x in (pnl or {}).get("seats", []) if x["invalid"]]
        warn += ('<div class="warn"><b>{:,} lines ({}) are recorded as a full jury but hold two '
                 'valid votes.</b> {}. <code>NIM_MODELS_RESPONDED</code> counts any non-empty '
                 'answer as a vote. Verdicts are unaffected; the recorded jury health is not.'
                 '</div>').format(gap, pct(gap, seen, 2),
                                  " · ".join("<code>{}</code> returned {:,} non-verdicts".format(
                                      html.escape(str(x["model"])), x["invalid"]) for x in bad))
    if len(vers) > 1:
        warn += ('<div class="warn"><b>STOP: two prompt versions in one run.</b> Verdicts either '
                 'side of a prompt change are not comparable.</div>')
    if len(runs) > 1:
        warn += ('<div class="warn"><b>STOP: more than one run_id in qa_line.</b> Every figure on '
                 'this page is double-counting.</div>')
    return ('<div class="strip">'
            + "".join('<div class="tile {}"><div class="v">{}</div><div class="k">{}</div></div>'
                      .format(t[2], t[0], t[1]) for t in tiles)
            + "</div>" + warn)


KEY = ('<div class="key"><span class="dim"><b style="background:transparent"></b>'
       'colour&nbsp;means:</span>'
       '<span><b style="background:var(--ok)"></b>fine</span>'
       '<span><b style="background:var(--amber)"></b>watch</span>'
       '<span><b style="background:var(--red)"></b>act now</span>'
       '<span class="dim">· error rate excludes <b>Uncertain</b> from both sides '
       '· tables rank by <b>line count</b>, never spend '
       '· spend is <b>signed, as held</b></span></div>')


def progress_block(m):
    """THE HERO ROW. Two numbers big enough to read across a desk, and nothing else competing."""
    with m.lock:
        hb, pnl, r15, r60 = m.hb, m.pnl, m.rate15, m.rate60
    if not hb or not pnl:
        return ""
    lines, judged = hb["lines"], hb["judged"]
    left = max(0, lines - judged)
    r, window = (r60, "hour") if r60 > 0 else (r15, "15 min")
    if not left:
        eta, ecls, esub = "done", "ok", "nothing left unjudged"
    elif r > 0:
        days = left / (r * 60.0 * 24.0)
        eta = "{:.0f}".format(days) if days >= 10 else "{:.1f}".format(days)
        ecls = ""
        esub = "days left · finishes {} · at {}/min over the last {}".format(
            (datetime.now() + timedelta(days=days)).strftime("%a %d %b"), fmt_rate(r), window)
    else:
        eta, ecls, esub = "—", "amber", "no rate yet · nothing judged in the last 15 minutes"

    started = pnl.get("started")
    el = "" if not started else " · first verdict {:.1f} days ago".format(
        (datetime.now() - started).total_seconds() / 86400.0)

    # 🔴 NO PERCENTAGE OF SPEND, AND THIS WAS A BUG BEFORE IT WAS A DECISION.
    # The first version of this hero showed "signed spend covered 100.4%" on the pilot - judged
    # $2,499,837.95 against a total of $2,489,724.83 - because the 16 lines still unjudged carried a
    # NET NEGATIVE spend. A share of a signed total is not a meaningful quantity: it can exceed 100%
    # while work remains, and it would read as "finished" to anyone glancing at it.
    #
    # 🔑 The standing rule already said this and I walked past it. Spend is reported EXACTLY as the
    # data holds it - no threshold, no netting, no absolute values - and the moment you divide one
    # signed total by another you have done arithmetic the data does not support. Both figures are
    # shown instead, with the line counts beside them in the tile to the left, which is precisely
    # what "always report line counts alongside spend" is for.
    sj = sum(c["spend_judged"] for c in pnl["clients"].values())
    st = sum(c["spend"] for c in pnl["clients"].values())
    qq = pnl.get("queue") or {}
    vd = sum(v.get("done", 0) for v in qq.values())
    vt = sum(v.get("done", 0) + v.get("pending", 0) for v in qq.values())

    return ('<div class="hero">'
            '<div class="hbox"><div class="lab">lines judged</div>'
            '<div class="big">{p}</div>'
            '<div class="pbar"><i style="width:{w:.4f}%"></i></div>'
            '<div class="sub">{j} of {t}{el}</div></div>'
            '<div class="hbox {ecls}"><div class="lab">estimated</div>'
            '<div class="big">{eta}</div><div class="sub">{esub}</div></div>'
            '<div class="hbox"><div class="lab">signed spend judged</div>'
            '<div class="big" style="font-size:23px">{sjm}</div>'
            '<div class="sub">of {stm} total &middot; <b>no percentage</b>: spend is signed, and a '
            'share of a signed total is not a meaningful figure</div></div>'
            '<div class="hbox"><div class="lab">vendors finished</div>'
            '<div class="big">{vp}</div><div class="sub">{vd} of {vt} vendors have no unjudged '
            'lines left</div></div>'
            '</div>').format(
                p=pct(judged, lines, 2), w=100.0 * judged / lines if lines else 0,
                j="{:,}".format(judged), t="{:,}".format(lines), el=el,
                eta=eta, ecls=ecls, esub=esub,
                sjm=money(sj), stm=money(st),
                vp=pct(vd, vt) if vt else "—", vd="{:,}".format(vd), vt="{:,}".format(vt))


def card(cc, d, queue, hue):
    """One hospital. Three KPIs big, the denominator small underneath each - never as prose.

    The denominators STAY, they just stop being a paragraph. Sameer, 2026-08-26: *"theres more text
    and the viewer wont know exactly what to look at"*. A rate whose denominator is buried in a
    sentence is a rate people quote without it, which is the thing this whole page guards against;
    a rate with the denominator printed under it in small type is one they cannot.
    """
    judged = d["judged"]
    firm = d["correct"] + d["incorrect"]     # 🔒 Uncertain is in NEITHER side. See refusal 5.
    needs = sum(d["acts"].get(a, (0, 0))[0] for a in ERROR_ACTIONS)
    qd = queue.get(cc, {})
    qdone, qtot = qd.get("done", 0), qd.get("done", 0) + qd.get("pending", 0)

    kpis = [("", pct(judged, d["lines"], 2), "judged",
             "{:,} of {:,}".format(judged, d["lines"])),
            ("err", pct(d["incorrect"], firm), "error rate",
             "{:,} of {:,} firm".format(d["incorrect"], firm)),
            ("unc", pct(d["uncertain"], judged), "uncertain",
             "{:,} of {:,} judged".format(d["uncertain"], judged))]

    # 🔴 EVERY JUDGED LINE MUST APPEAR IN THIS BREAKDOWN, INCLUDING ONES WITH NO ACTION YET.
    # Found 2026-08-26 by looking at a real card: the loop drew only the six known NIM_ACTION
    # values, so a generation where action_classify.py has not run yet - which is EXACTLY the state
    # of a run in progress - rendered an EMPTY bar and an EMPTY table beside "500 judged". Five
    # hundred lines silently vanished from the one panel that is supposed to account for all of
    # them, and nothing looked broken.
    #
    # 🔑 A BREAKDOWN THAT DOES NOT RECONCILE TO ITS OWN TOTAL IS WORSE THAN NO BREAKDOWN. Anything
    # not in ACTIONS is now drawn in neutral grey and named, so the segments always sum to the
    # judged count, and the assertion below says so out loud if they ever do not.
    segs, rows, drawn = [], [], 0
    extra = [k for k in sorted(d["acts"]) if k not in dict((a2, 1) for a2, _, _ in ACTIONS)]
    for label, colour, _ in list(ACTIONS) + [(k, "var(--line)", "") for k in extra]:
        n, spend = d["acts"].get(label, (0, 0.0))
        if not n:
            continue
        drawn += n
        segs.append('<i style="width:{:.4f}%;background:{}" title="{}: {:,} lines"></i>'.format(
            100.0 * n / judged if judged else 0, colour, html.escape(label), n))
        rows.append('<tr><td><b style="background:{}"></b>{}</td><td class="n">{:,}</td>'
                    '<td class="n">{}</td><td class="n money">{}</td></tr>'.format(
                        colour, html.escape(label), n, pct(n, judged), money(spend)))
    if judged and drawn != judged:
        rows.append('<tr><td colspan="4" class="bad">** {:,} judged line(s) are missing from this '
                    'breakdown. It does not reconcile **</td></tr>'.format(judged - drawn))
    thin = ('<div class="warn" style="margin:11px 0 0">{:,} line(s) judged by fewer than 3 models '
            '&middot; re-run with <code>--topup</code></div>'.format(d["thin"])) if d["thin"] else ""

    return """<article class="card" style="border-top:4px solid {hue}">
  <div class="band" style="background:{hue}">
    <h2>{name}</h2>
    <div class="who">{judged:,} of {lines:,} lines &nbsp;·&nbsp; {qdone:,}/{qtot:,} vendors finished</div>
  </div>
  <div class="kpis">{kpis}</div>
  <div class="blab">what should happen to the judged lines</div>
  <div class="stack">{segs}</div>
  <table class="brk">{rows}</table>
  {thin}
  <div class="foot">signed spend covered <b>{sj}</b> of {st} &nbsp;·&nbsp;
     needs an analyst <b>{needs:,}</b></div>
</article>""".format(
        name=html.escape(name_of(cc)), hue=hue,
        judged=judged, lines=d["lines"], qdone=qdone, qtot=qtot,
        kpis="".join('<div class="kpi {}"><div class="v">{}</div><div class="k">{}</div>'
                     '<div class="d">{}</div></div>'.format(c, v, k, den)
                     for c, v, k, den in kpis),
        segs="".join(segs) or '<i style="width:100%;background:var(--line)"></i>',
        rows="".join(rows) or '<tr><td class="dim" colspan="4">nothing judged yet</td></tr>',
        thin=thin, sj=money(d["spend_judged"]), st=money(d["spend"]), needs=needs)


# 🔒 HOSPITAL IDENTITY COLOURS, AND WHY THEY ARE NOT ANY OF THE OTHER COLOURS ON THIS PAGE.
# Sameer, 2026-08-26: *"for the 4 hospital wrappers can you add some color and center the names"*.
#
# ⚠️ COLOUR ON THIS PAGE ALREADY MEANS SEVERITY - green fine, amber watch, red act - and that is
# stated in the key at the top. A second colour scale is a real risk: a card washed in a hue that
# happens to sit near amber reads as a warning about that hospital, and then BOTH scales stop being
# trusted. So these are deliberately chosen OUTSIDE the severity range - blue, teal, violet,
# magenta, with no green, no amber and no red anywhere near them - and they are applied only to a
# HEADER BAND, which reads as a label, never to the card body or to any number.
#
# 🔒 AND THEY ARE ASSIGNED BY POSITION, NEVER BY NAME. `NO CLIENT NAMES ANYWHERE IN pipeline/, EVER`
# - so there is no map from a hospital to a colour anywhere in this file. The Nth client in sorted
# client_code order takes the Nth hue: deterministic, stable between runs, collision-free for up to
# six clients, and it stays correct if a fifth hospital is ever added.
CLIENT_HUES = ["#33608f", "#146b6b", "#6b4f96", "#8f3a6b", "#3f5f7a", "#5a5f8f"]


SEAT_COLOUR = {"Correct": "#3f9d54", "Incorrect": "#c9453d", "Uncertain": "#8b8b8b"}


def jury_panel(pnl):
    """🔴 HOW MUCH THE THREE GRADERS DISAGREE. Deliberately NOT an accuracy table.

    There is no ground truth in this database - REVIEW_OVERRIDE_VERDICT, REVIEW_STATUS and
    REVIEWED_AT are populated on zero rows and the answer key is orphaned - so no model here can be
    scored for correctness, and a tile claiming to would be inventing its numbers. The subtitle on
    the page says so in one line; the full reasoning is in the footer. What was a paragraph is now a
    sentence, and NOTHING it guarded against was dropped.
    """
    seats = pnl.get("seats") or []
    if not seats:
        return ""
    judged = (pnl.get("jury") or {}).get("judged", 0)
    rows = []
    for s_ in seats:
        tot = sum(s_["counts"].values()) or 1
        bar = "".join(
            '<i style="width:{:.3f}%;background:{}" title="{}: {:,}"></i>'.format(
                100.0 * s_["counts"][v] / tot, SEAT_COLOUR[v], v, s_["counts"][v])
            for v in VERDICTS if s_["counts"][v])
        flags = []
        if s_["invalid"]:
            flags.append('<span class="bad">{:,} non-verdicts</span>'.format(s_["invalid"]))
        if s_["models_seen"] > 1:
            flags.append('<span class="bad">{} MODELS IN THIS SEAT</span>'.format(
                s_["models_seen"]))
        rows.append(
            '<tr><td><code>{model}</code>{flags}</td>'
            '<td class="n">{c}</td><td class="n">{i}</td><td class="n">{u}</td>'
            '<td><div class="stack">{bar}</div></td>'
            '<td class="n">{drop}</td><td class="n">{agree}</td></tr>'.format(
                model=html.escape(str(s_["model"])),
                flags=("<br>" + " ".join(flags)) if flags else "",
                c=pct(s_["counts"]["Correct"], judged), i=pct(s_["counts"]["Incorrect"], judged),
                u=pct(s_["counts"]["Uncertain"], judged), bar=bar or "",
                drop=pct(s_["silent"], judged, 2),
                agree=pct(s_["agrees"], judged - s_["silent"] if judged > s_["silent"] else 0)))

    inc = [x["counts"]["Incorrect"] for x in seats]
    spread = ""
    if min(inc) > 0:
        spread = ('<div class="warn" style="background:var(--amberbg);color:var(--amber);'
                  'border-left-color:var(--amber)"><b>{:.1f}× apart</b> on how often they call a '
                  'line <b>Incorrect</b> ({} to {}). They are not three readings of one standard, so '
                  'the headline error rate depends on <b>which two of the three agree</b>.'
                  '</div>').format(float(max(inc)) / min(inc),
                                   pct(min(inc), judged), pct(max(inc), judged))
    return ('<section class="tbl"><h3>How much the three graders disagree</h3>'
            '<div class="dim"><b>Not an accuracy table.</b> No line has been reviewed by a person, '
            'so no model here can be scored for correctness. “Agrees with consensus” is conformity, '
            'not correctness.</div>'
            '<table><thead><tr><th>model</th><th class="n">Correct</th><th class="n">Incorrect</th>'
            '<th class="n">Uncertain</th><th>mix</th><th class="n">never answered</th>'
            '<th class="n">agrees w/ consensus</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table>' + spread + '</section>')


def throughput_strip(pnl):
    """ONE BAR PER HOUR. The only view on this page with a memory.

    Every other tile answers "now". Watching the pilot on 2026-08-26 the rate fell from ~10/min to
    2.3/min inside an hour as the vendor queue reached its long tail of tiny suppliers — and that
    was caught only because someone happened to be watching the number at the time. Over ~40 days
    this is the strip that shows the ETA drifting, and roughly when it started.
    """
    hours = pnl.get("hours") or []
    if not hours:
        return ""
    peak = max(n for _, _, n in hours) or 1
    # An IDLE hour draws a flat dead-grey stub, not a missing bar. It has to occupy the same
    # horizontal space as a busy one or the time axis stops being a time axis.
    bars = "".join(
        '<i class="{}" style="height:{:.1f}%" title="{} {:02d}:00 &middot; {}"></i>'.format(
            "idle" if not n else "", 3.0 if not n else max(4.0, 100.0 * n / peak), d, h,
            "nothing judged" if not n else "{:,} lines ({:.1f}/min)".format(n, n / 60.0))
        for d, h, n in hours)
    live = [x for x in hours if x[2]]
    idle = len(hours) - len(live)
    first, last = hours[0], hours[-1]
    return ('<section class="tbl"><h3>Lines judged per hour &middot; last 48 hours</h3>'
            '<div class="dim">Newest on the right. Tallest bar = {:,} lines in an hour '
            '({:.1f}/min). <b>Every hour gets a bar, including empty ones.</b> An idle hour is a '
            'flat grey stub, so downtime shows as a trough instead of vanishing.</div>'
            '<div class="spark">{}</div>'
            '<div class="dim" style="margin-top:5px">{} {:02d}:00 → {} {:02d}:00 · '
            '<b>{}</b> hour(s) with judging, <b>{}</b> idle</div></section>').format(
                peak, peak / 60.0, bars, first[0], first[1], last[0], last[1], len(live), idle)


def tables(pnl):
    """Where the errors cluster. Ranked by LINE COUNT, never by spend - see refusal 6."""
    def block(title, note, head, rows):
        return ('<section class="tbl"><h3>{}</h3><div class="dim">{}</div>'
                '<table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></section>').format(
                    html.escape(title), note,
                    "".join('<th class="{}">{}</th>'.format("n" if h.startswith("#") else "",
                                                            html.escape(h.lstrip("#")))
                            for h in head),
                    rows or '<tr><td class="dim" colspan="%d">nothing yet</td></tr>' % len(head))

    v = "".join('<tr><td class="rank">{}</td><td>{}</td><td>{}</td><td class="n">{:,}</td>'
                '<td class="n money">{}</td></tr>'.format(
                    i + 1, html.escape(name_of(x["client"])),
                    html.escape(str(x["vendor"] or "(no vendor name)")), x["n"], money(x["spend"]))
                for i, x in enumerate(pnl["vendors"]))
    r = "".join('<tr><td class="rank">{}</td><td>{}</td><td><code>{}</code></td>'
                '<td><code>{}</code></td><td class="n">{:,}</td></tr>'.format(
                    i + 1, html.escape(name_of(x["client"])), html.escape(str(x["rule"])),
                    html.escape(str(x["table"])), x["n"])
                for i, x in enumerate(pnl["rules"]))
    return (block("Where the errors cluster: by vendor",
                  "Ranked by <b>line count</b>, never spend. Vendor names verbatim.",
                  ["", "hospital", "vendor", "#incorrect lines", "#signed spend"], v)
            + block("Where the errors cluster: by rule",
                    "A rule ID names independent <b>copies</b>, so the table is named beside it.",
                    ["", "hospital", "rule", "rules table", "#incorrect lines"], r))


def body(m):
    with m.lock:
        pnl, hb = m.pnl, m.hb
    if not pnl or not hb:
        return health_strip(m)          # no panel yet: the health tiles are all there is to show
    # sorted() twice over, deliberately: the ORDER of the cards and the ASSIGNMENT of hues both
    # come from the same sorted client_code list, so a hospital keeps its colour between refreshes
    # and between runs. Nothing here knows a hospital's name.
    order = sorted(pnl["clients"])
    cards = "".join(card(cc, pnl["clients"][cc], pnl["queue"],
                         CLIENT_HUES[i % len(CLIENT_HUES)])
                    for i, cc in enumerate(order))
    legend = "".join('<span><b style="background:{}"></b>{}: {}</span>'.format(
        c, html.escape(l), html.escape(d)) for l, c, d in ACTIONS)
    # 🔑 THE PAGE IS NOW FIVE BLOCKS, NOT ONE SCROLL. Sameer, 2026-08-26: *"it does look a bit too
    # white"*. Each lower section sits on its own tinted panel so the eye can find where one ends
    # and the next begins. ⚠️ The tints carry NO meaning and are deliberately far from the
    # ok/amber/red palette: severity is the only colour on this page that means anything, and a
    # decorative tint that could be mistaken for a warning would cost more than a white page ever did.
    return (progress_block(m) + KEY + health_strip(m)
            + '<div class="panel">' + throughput_strip(pnl) + '</div>'
            + '<div class="legend">' + legend + '</div>'
            + '<div class="grid">' + cards + '</div>'
            + '<div class="panel alt">' + jury_panel(pnl) + '</div>'
            + '<div class="panel">' + tables(pnl) + '</div>')


BANNER = ("<b>INTERNAL · not client-facing.</b> {judged} of {lines} judged ({p}). <b>Largest vendors first</b>, so these are the biggest suppliers' rates, not each hospital's. Why this matters, and why the hospitals do not advance together: see the foot of the page.")


EXTRA_CSS = """
/* ── ONE COLOUR SYSTEM, THREE MEANINGS, AND A LEGEND THAT SAYS SO ────────────────────────────────
   Sameer, 2026-08-26: "the viewer wont know exactly what to look at". So colour on this page
   carries exactly one meaning and never decorates:
       GREEN  fine, nothing to do          AMBER  watch it          RED  act now
   The six NIM_ACTION colours are a SEPARATE, categorical scale imported from dashboard.py - they
   name a category, never a severity, and 'Out of scope' is deliberately neutral because it is not
   an error. Mixing a severity scale with a categorical one is how a reader learns to ignore both. */
:root{--ok:#2f7d43;--okbg:#eaf5ec;--amber:#9a6b00;--amberbg:#fdf3e0;
      --red:#b3312a;--redbg:#fdecea;--hero:#0b57a4;
      /* SECTION TINTS. Sameer, 2026-08-26: "it does look a bit too white". These carry NO meaning -
         they group the page into blocks so the eye can find the edge of a section. Severity colour
         (ok/amber/red) is the ONLY palette that means anything, and these are kept far enough from
         it that a tinted panel can never be mistaken for a warning. */
      --panel:#f5f8fb;--panel2:#f8f6f2;--panelbd:#dfe6ee;--page:#fbfcfd}
@media (prefers-color-scheme:dark){
 :root{--ok:#5fbf78;--okbg:#16261a;--amber:#e0b055;--amberbg:#2c2413;
       --red:#f0736a;--redbg:#2e1917;--hero:#74b3ff;
       --panel:#161a1f;--panel2:#1a1816;--panelbd:#2b3138;--page:#0f1113}}
:root[data-theme=dark]{--ok:#5fbf78;--okbg:#16261a;--amber:#e0b055;--amberbg:#2c2413;
       --red:#f0736a;--redbg:#2e1917;--hero:#74b3ff;--panel:#161a1f;--panel2:#1a1816;--panelbd:#2b3138;--page:#0f1113}
:root[data-theme=light]{--ok:#2f7d43;--okbg:#eaf5ec;--amber:#9a6b00;--amberbg:#fdf3e0;
       --red:#b3312a;--redbg:#fdecea;--hero:#0b57a4;--panel:#f5f8fb;--panel2:#f8f6f2;--panelbd:#dfe6ee;--page:#fbfcfd}

body{font-size:14px;background:var(--page)}
h1{font-size:15px;font-weight:650}
.wrap{max-width:1500px;margin:0 auto}
header{background:var(--card);border-bottom:1px solid var(--panelbd)}

/* ── SECTION WRAPPERS. Each block sits on its own tinted panel with a border, so the page reads
      as four or five areas rather than one long white scroll. ─────────────────────────────────── */
.panel{margin:14px 22px;padding:15px 17px;border:1px solid var(--panelbd);border-radius:12px;
   background:var(--panel)}
.panel.alt{background:var(--panel2)}
.panel>h3:first-child{margin-top:0}
.panel .tbl{margin:0}
.panel .tbl+.tbl{margin-top:22px;padding-top:18px;border-top:1px solid var(--panelbd)}

/* ── the banner: ONE line. The full reasoning moved to the footer, where it does not compete with
      the numbers. It is still permanent and still first. ─────────────────────────────────────── */
.banner{margin:12px 22px 0;padding:9px 13px;border-radius:8px;font-size:12.5px;
   background:var(--redbg);color:var(--red);border:1px solid transparent}

/* ── HERO: the two things a manager reads, at a size you can read across a desk ───────────────── */
.hero{display:grid;grid-template-columns:minmax(280px,1.4fr) repeat(auto-fit,minmax(150px,1fr));
   gap:12px;margin:12px 22px 0}
.hbox{border:1px solid var(--panelbd);border-radius:11px;padding:14px 16px;background:var(--card);
   box-shadow:0 1px 2px rgba(0,0,0,.04)}
.hbox .lab{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
   font-weight:600}
.hbox .big{font-size:34px;font-weight:680;letter-spacing:-.025em;line-height:1.05;margin-top:5px;
   font-variant-numeric:tabular-nums}
.hbox .sub{font-size:11.5px;color:var(--dim);margin-top:5px;line-height:1.4}
.hbox.ok .big{color:var(--ok)} .hbox.amber .big{color:var(--amber)} .hbox.red .big{color:var(--red)}
.hbox.red{background:var(--redbg);border-color:var(--red)}
.hbox.amber{background:var(--amberbg);border-color:var(--amber)}
.pbar{height:10px;border-radius:6px;background:var(--line);overflow:hidden;margin-top:11px}
.pbar i{display:block;height:100%;background:var(--hero)}

/* ── the key: what the colours mean. Stated once, near the top, not in a tooltip ──────────────── */
.key{margin:12px 22px 0;display:flex;gap:8px 20px;flex-wrap:wrap;align-items:center;
   font-size:11.5px;color:var(--dim);padding:8px 13px;border:1px dashed var(--line);
   border-radius:8px}
.key b{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;
   vertical-align:baseline}
.key span{display:inline-flex;align-items:center}

/* ── health tiles: value first and large, label small underneath ──────────────────────────────── */
.strip{margin:12px 22px 0;display:grid;gap:10px;
   grid-template-columns:repeat(auto-fit,minmax(148px,1fr))}
.tile{border:1px solid var(--panelbd);border-radius:9px;padding:10px 12px;background:var(--card)}
.tile .v{font-size:17px;font-weight:640;letter-spacing:-.01em;font-variant-numeric:tabular-nums;
   line-height:1.2;word-break:break-word}
.tile .k{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
   margin-top:4px;font-weight:600}
.tile.bad{background:var(--redbg);border-color:var(--red)} .tile.bad .v{color:var(--red)}
.tile.good .v{color:var(--ok)}
.tile.amber{background:var(--amberbg);border-color:var(--amber)} .tile.amber .v{color:var(--amber)}

.warn{margin:10px 22px 0;padding:11px 14px;border-radius:8px;background:var(--redbg);
   color:var(--red);font-size:12.5px;line-height:1.5;border-left:4px solid var(--red)}
.warn code{background:transparent;font-size:11.5px}

/* ── client cards ─────────────────────────────────────────────────────────────────────────────── */
/* TWO PER ROW, ALWAYS. Sameer, 2026-08-26: "melbourne health and northern health and just below
   that have syndey and western". auto-fit gave one, two or three per row depending on the window,
   so the pairing moved about; this fixes it. The ORDER already lands correctly on its own - the
   cards are sorted by client_code, which is melbourne, northern, sydney, western. Collapses to one
   column under 820px, because two 345px cards plus the margins do not fit below that. */
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:14px 22px;padding:0}   /* padding:0 resets dashboard.CSS .grid, which sets padding AND would double-indent */
@media (max-width:820px){.grid{grid-template-columns:1fr}}
.card{border:1px solid var(--panelbd);border-radius:11px;padding:15px 16px;background:var(--card);
   box-shadow:0 1px 2px rgba(0,0,0,.04)}
/* The coloured header band. White text on a mid-tone hue reads in both themes without a second
   palette, and CENTRING the name is what Sameer asked for: four cards scanned side by side are
   easier to tell apart when the labels line up down the middle rather than ragging left. */
.card{padding:0;overflow:hidden}
.band{padding:11px 14px 10px;text-align:center;color:#fff}
.card h2{margin:0 0 2px;font-size:14.5px;font-weight:650;color:#fff;letter-spacing:-.005em}
.card .who{color:rgba(255,255,255,.86);font-size:11.5px;font-variant-numeric:tabular-nums}
.card .kpis,.card .blab,.card .stack,.card .brk,.card .foot,.card .warn{margin-left:16px;
   margin-right:16px}
.card .kpis{margin-top:0;padding-top:13px}
.card .foot{padding-bottom:15px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0 2px;
   padding:11px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.kpi .v{font-size:21px;font-weight:660;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .k{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
   margin-top:2px;font-weight:600}
.kpi .d{font-size:10.5px;color:var(--dim);margin-top:2px;font-variant-numeric:tabular-nums}
.kpi.err .v{color:var(--red)} .kpi.unc .v{color:var(--amber)}
.blab{color:var(--dim);font-size:10.5px;margin-top:13px;text-transform:uppercase;
   letter-spacing:.06em;font-weight:600}
.stack{display:flex;height:13px;border-radius:7px;overflow:hidden;margin-top:6px;
   background:var(--line)}
.stack i{display:block}
.brk{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px}
.brk td{padding:5px 8px 5px 0;border-bottom:1px solid var(--line)}
.brk td+td{border-left:1px solid var(--line);padding-left:8px}
.brk tr:last-child td{border-bottom:none}
.brk b{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:8px}
.foot{margin-top:11px;color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums}

/* ── tables: numbers right, tabular, zebra, and a readable size ───────────────────────────────── */
.n{text-align:right;font-variant-numeric:tabular-nums}
.money{font-variant-numeric:tabular-nums;white-space:nowrap}
.dim{color:var(--dim)}
.tbl{margin:20px 22px}
.tbl h3{margin:0 0 3px;font-size:14px;font-weight:650}
.tbl>.dim{font-size:11.5px;line-height:1.5;max-width:105ch}
.tbl table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:10px}
/* GRIDLINES. Sameer asked for them at the foot of the page, and they earn their place there:
   these tables are five columns of names and figures, and without a vertical rule the eye loses
   which number belongs to which column two rows in. The header rule is heavier than the row rules
   so the head reads as a head. */
.tbl table{border:1px solid var(--panelbd);border-radius:9px;overflow:hidden;background:var(--card)}
.tbl th{text-align:left;color:var(--dim);font-weight:600;border-bottom:2px solid var(--panelbd);
   border-right:1px solid var(--panelbd);padding:7px 11px;font-size:10px;text-transform:uppercase;
   letter-spacing:.06em;white-space:nowrap;background:var(--band)}
.tbl th:last-child,.tbl td:last-child{border-right:none}
.tbl th.n{text-align:right}
.tbl td{padding:7px 11px;border-bottom:1px solid var(--panelbd);
   border-right:1px solid var(--panelbd);vertical-align:top}
.tbl tbody tr:last-child td{border-bottom:none}
.tbl tbody tr:nth-child(even){background:var(--band)}
.tbl code{font-size:11.5px}
.rank{color:var(--dim);font-variant-numeric:tabular-nums;width:2ch}

/* ── throughput ───────────────────────────────────────────────────────────────────────────────── */
.spark{display:flex;align-items:flex-end;gap:2px;height:82px;margin-top:10px;padding:7px 9px;
   background:var(--band);border:1px solid var(--line);border-radius:9px;overflow-x:auto}
.spark i{flex:1 0 8px;min-width:8px;background:var(--hero);border-radius:2px 2px 0 0;display:block;
   opacity:.9}
.spark i:last-child{opacity:1;background:var(--ok)}
.spark i.idle{background:var(--line);opacity:1}
.spark i.idle:last-child{background:var(--line)}
.tbl .stack{height:11px;margin-top:0;min-width:110px}

/* ── the prose lives here now, folded away, so the numbers get the page ───────────────────────── */
.bad{color:var(--red);font-size:11px;font-weight:600}
footer{margin:26px 22px 40px;color:var(--dim);font-size:11.5px;line-height:1.65;
   border-top:1px solid var(--line);padding-top:14px}
footer details{margin-top:8px}
footer summary{cursor:pointer;color:var(--fg);font-weight:600;font-size:12px;padding:4px 0}
footer details[open] summary{margin-bottom:6px}
footer p{margin:0 0 9px;max-width:100ch}
"""

JS = """
let fails = 0;
async function tick(){
  try{
    const r = await fetch('/api/status', {cache:'no-store'});
    const j = await r.json();
    document.getElementById('body').innerHTML = j.html;
    document.getElementById('banner').innerHTML = j.banner;
    document.getElementById('stamp').textContent = j.stamp;
    // 🔴 THE TAB TITLE CARRIES THE ALARM. A pinned tab shows a stall without anyone clicking it.
    document.title = (j.stalled ? '\\u{1F534} JUDGE DOWN \\u2014 ' : '') + j.title;
    fails = 0;
  }catch(e){
    fails++;
    if(fails > 2){ document.getElementById('stamp').textContent =
      'page cannot reach the monitor (' + fails + ' tries) \\u2014 is monitor.py still running?'; }
  }
}
tick(); setInterval(tick, %POLL%);
"""


def page(m):
    """The shell. Everything inside #body is re-rendered by the poller; this is served once.

    🔑 THE PROSE LIVES IN THE FOOTER NOW, FOLDED AWAY - and it is all still here. Sameer, 2026-08-26:
    *"theres more text and the viewer wont know exactly what to look at"*. Every caveat this page
    carried is still carried; what changed is that it no longer sits between a reader and the
    numbers. ⚠️ NOTHING WAS DELETED TO TIDY UP. The banner is still permanent and still first, every
    rate still prints its own denominator beside it, and there is still no export button - those
    three are the guarantees, and shortening a sentence is not the same as dropping one.
    """
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Indirect QA &middot; run monitor</title><style>{css}{extra}</style></head><body>
<div class="wrap">
<header><h1>Indirect QA &middot; live run monitor</h1>
<div class="sub" id="stamp">starting…</div></header>
<div class="banner" id="banner"></div>
<div id="body"></div>
<footer>
<b>Read this before quoting any number above.</b>

<details open><summary>Why the error rate here is not the hospital's error rate</summary>
<p>The run judges the <b>largest suppliers first</b>, by signed spend. So a mid-run error rate is the
error rate <i>of the biggest vendors</i>, the exact opposite of a spread sample. Accuracy has never
been measured on a spread sample, so <b>no per-client figure on this page is client-facing</b>.</p>
<p>The hospitals also do <b>not</b> advance together, and a per-hospital bar that looks stalled
usually is not: at the global top 100 vendors, Northern sits at 86.2% of its signed spend and Sydney
Adventist at 32.7%. It evens out by around the top 500. That is the order working, not a fault.</p>
</details>

<details><summary>How each number is defined</summary>
<p><b>Error rate = Incorrect ÷ (Correct + Incorrect).</b> <b>Uncertain is excluded from both sides</b>
and reported on its own, because it is the size of the manual analyst queue rather than a defect
rate. Incorrect ÷ everything is a different, smaller, wrong number.</p>
<p>&ldquo;Needs an analyst&rdquo; is <b>Miscategorised</b> only. <b>Out of scope is not an error</b>:
it is a scope finding the hospital's clinical categorisation owns. <b>Re-mapped</b> is a migration we
caused, not a hospital mistake. <b>Incomplete</b> is a gap, not an error.</p>
<p>Tables rank by <b>line count, never by spend</b>. Ranking by spend would mean deciding which rows
are real, and 237 Melbourne lines carry $24.5bn gross against $433M net. Spend is <b>signed, exactly
as the data holds it</b>: no threshold, no netting, no absolute values. A rule ID names independent
<b>copies</b> between hospitals, so the rules table is always printed beside it.</p>
<p><code>NIM_JUDGED_AT</code> is when the <b>judge</b> wrote the row, never a transaction date.</p>
</details>

<details><summary>Why the jury table is not an accuracy table</summary>
<p>There is <b>no ground truth in this database</b>: <code>REVIEW_OVERRIDE_VERDICT</code>,
<code>REVIEW_STATUS</code> and <code>REVIEWED_AT</code> are populated on zero rows, and the human
answer key is orphaned. No model can be scored for correctness here, so nothing on this page claims
to. <b>&ldquo;Agrees with consensus&rdquo; measures conformity, not correctness</b>: a model that
dissents may be the one that is right.</p>
<p><b>Jury health is counted from the votes themselves</b>, not from
<code>NIM_MODELS_RESPONDED</code>, which counts any non-empty answer as a vote and so over-reports a
full jury when a model returns a word that is not a verdict.</p>
</details>

<details><summary>What this page is, and what it deliberately cannot do</summary>
<p>Figures come from the live three-model jury (<code>NIM_*</code>), never the older single-model
layer. This page is served <b>read-only</b> by <code>pipeline/monitor.py</code> on
<code>127.0.0.1</code>: it issues <code>SELECT</code> and nothing else, and there is <b>no export
button</b>, because a screenshot leaves the building without its caveats, so lifting the figure is
deliberately not made easy.</p>
<p>Current state and what is gated on whom: <code>TRACKER.md</code>. Why this page exists and what is
still undecided: <code>APP.md</code>.</p>
</details>
</footer>
</div>
<script>{js}</script></body></html>""".format(
        css=dashboard.CSS, extra=EXTRA_CSS,
        js=JS.replace("%POLL%", str(int(m.args.poll * 1000))))


def status_json(m):
    with m.lock:
        hb, err = m.hb, m.err
    judged = hb["judged"] if hb else 0
    lines = hb["lines"] if hb else 0
    stamp = ("{}  ·  {}  ·  refreshed {} in {} ms{}  ·  slowest so far {} ms  ·  "
             "poll {}s  ·  email {}").format(
        m.dbname, "PRODUCTION" if m.args.production else "pilot",
        m.last_ok.strftime("%H:%M:%S") if m.last_ok else "never",
        "{:,}".format(m.last_ms), " (full panel)" if m.full else " (heartbeat only)",
        "{:,}".format(m.slow_ms), m.args.poll, m.mail_note)
    if err:
        stamp += "  ·  ⚠ STALE, last read failed: " + err[:120]
    return {"html": body(m),
            "banner": BANNER.format(judged="{:,}".format(judged), lines="{:,}".format(lines),
                                    p=pct(judged, lines, 2)),
            "stamp": stamp, "stalled": bool(m.stalled),
            "title": "Indirect QA \u00b7 run monitor"}


class Handler(BaseHTTPRequestHandler):
    mon = None

    def _send(self, code, ctype, payload):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):                                                   # noqa: N802
        p = self.path.split("?")[0]
        if p == "/api/status":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(status_json(self.mon)).encode("utf-8"))
        elif p == "/":
            self._send(200, "text/html; charset=utf-8", page(self.mon).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def log_message(self, *a):
        """Silent. 40 days x one poll every 15 s is 230,000 log lines nobody reads."""


def main():
    ap = argparse.ArgumentParser(description="Read-only live monitor for the Indirects judging run.")
    ap.add_argument("--production", action="store_true",
                    help="watch PI_Medical_QA_Indirect. Without it, the 2,000-row pilot")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--poll", type=int, default=15,
                    help="seconds between reads. The cheap heartbeat runs every time; the full "
                         "panel only when the judged count has moved")
    ap.add_argument("--every-lines", type=int, default=1,
                    help="redraw the full panel once this many new lines are judged. 1 = whenever "
                         "it moves. 500 restores the literal 'every 500 lines' (~10 min at ~50/min)")
    ap.add_argument("--stall", type=int, default=15,
                    help="minutes with no new verdict before the page goes red and the email fires. "
                         "The judge commits every ~12 s at ~50 lines/min, so 15 is ~75x normal")
    # 🔒 NO --host. Sameer, 2026-08-26: localhost on the office desktop, which everyone who needs it
    # can already reach. A LAN flag is one keystroke from a page of provisional, explicitly
    # non-client-facing numbers being bookmarked by someone who never saw the banner.
    args = ap.parse_args()

    env = load_env()
    m = Monitor(args, env)
    print("Indirect QA run monitor. READ ONLY, SELECT only")
    m.refresh()
    if m.err:
        raise SystemExit("\n  STOP. Could not read the database:\n  %s\n" % m.err)
    print("  database    %s  (%s)" % (m.dbname, "PRODUCTION" if args.production else "pilot"))
    print("  lines       {:,}   judged {:,}".format(m.hb["lines"], m.hb["judged"]))
    print("  poll        every %ss, full redraw every %s new line(s), stall after %s min"
          % (args.poll, args.every_lines, args.stall))
    if m.mail["ready"]:
        print("  email       armed → %s  (via %s:%s)"
              % (m.mail["ALERT_TO"], m.mail["SMTP_HOST"], m.mail["SMTP_PORT"] or "587"))
    else:
        print("  email       ** NOT ARMED ** %s" % m.mail["why"])
        print("              The run and the page are unaffected. Keys live in .env as "
              "MONITOR_SMTP_HOST / _PORT / _USER / _PASS / MONITOR_ALERT_FROM / _TO.")

    threading.Thread(target=m.loop, daemon=True).start()
    Handler.mon = m
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("\n  OPEN  http://127.0.0.1:%d      (Ctrl-C to stop; this does not touch the judge)\n"
          % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped. Nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
