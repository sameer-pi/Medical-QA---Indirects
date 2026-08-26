#!/usr/bin/env python
"""Indirect QA — THE SUPERVISOR. Restarts the judge when it trips, and NEVER runs two.

    python pipeline/supervise.py --production --top 100      # the real run
    python pipeline/supervise.py                             # the pilot
    python pipeline/supervise.py --production --dry-run      # prove the interlocks, launch nothing

WHY THIS EXISTS. 2026-08-26, measured and not feared: the pilot judge ran for two hours and died on
a dropped database connection - `08S01 / 10054, an existing connection was forcibly closed by the
remote host`. nim_judge.py opens ONE connection in main() and holds it for the entire run: no
reconnect, no OperationalError handler, no database-side retry anywhere in the file. The retry
ladder that does exist is for the MODEL HTTP calls, which is why hours of throttling never killed a
run and made this look robust. RUN_LOG Finding 133.

  ~2 HOURS TO FIRST FAILURE. THE PRODUCTION RUN IS ~40 DAYS.

✅ A TRIP COSTS NO DATA. Selection is `NIM_VERDICT IS NULL`, so a re-run resumes exactly where it
stopped and re-judges nothing. **The entire cost is the idle time between the trip and someone
pressing start.** At ~50 lines/min: 15 minutes at a desk is nothing; 2am to 9am is ~21,000 lines and
seven hours added to the run. That gap - not the crash - is what this file removes.

  🔑 AND IT IS THE ONLY LINK IN THE RECOVERY CHAIN THAT DOES NOT NEED A HUMAN AWAKE. The chain is
  monitor goes red -> email -> a person -> restart. The email link does not work yet (no app
  password), so overnight that chain is currently broken end to end.

  🔑 IT ALSO MEASURES THE THING NOBODY CAN MEASURE TODAY. The evidence for all of the above is ONE
  crash. n=1. Every restart is logged with its timestamp, exit code and how many lines the attempt
  managed, so after a week the failure rate is a number instead of an anecdote. Building this is
  how the guess gets replaced.

🔒 THE REAL DANGER IS NOT A FAILED RESTART - IT IS A DOUBLE LAUNCH. Two judges on one queue is far
worse than a trip: both would select the same `NIM_VERDICT IS NULL` rows, spend twice, and race each
other's writes. `CLAUDE.md` says ONE JUDGE AT A TIME. So there are FOUR independent interlocks, and
⚠️ EVERY ONE OF THEM FAILS CLOSED - if a check cannot be performed, this refuses to launch rather
than assuming the coast is clear. A guard that fails open is the defect that let the GL through v4.

    1. SUPERVISOR SINGLETON.  A lock file holding this process's PID. A second supervisor finds it,
       finds that PID alive, and exits without launching anything.
    2. NO JUDGE ALREADY RUNNING.  Before EVERY launch - not just the first - the live process list
       is scanned for any python running nim_judge.py. One found, and this stops. That catches a
       judge someone started by hand, which the lock file cannot see.
    3. OWN CHILD FULLY EXITED.  A relaunch happens only after wait() has returned for the previous
       child. Its exit code is a fact, not a poll.
    4. THE SCAN ITSELF MUST WORK.  If the process query errors or returns nothing parseable, that
       is treated as "cannot prove it is safe" and the run stops. Never as "nothing found".

⚠️ WHAT THIS DOES NOT FIX, stated so nobody believes otherwise: a judge that HANGS without exiting
(the process is alive, so nothing here fires - only the monitor's stall clock catches that), a
machine that reboots, or a wrong verdict. It restarts a process that has died. That is all it does.

🔒 IT NEVER PIPES THE CHILD. Finding 133's second half: `nim_judge.py ... | tail -60` reported EXIT
CODE 0 on an unhandled exception, because a shell pipeline returns the LAST command's status. The
child's stdout goes to a FILE and its returncode is read directly from the process object, so a
crash can never be read as success here.
"""
import argparse
import io
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from db import connect_qa, load_env                                     # noqa: E402

LOCK = os.path.join(ROOT, "output", "logs", "supervise.lock")
LOGDIR = os.path.join(ROOT, "output", "logs")
JUDGE = os.path.join(HERE, "nim_judge.py")

# A judge process is any python whose command line names nim_judge.py. Matching on the FILE NAME and
# not on a full path on purpose: it must catch `python pipeline/nim_judge.py`, an absolute path, and
# a relative one from another directory, because a hand-started judge is exactly what interlock 2
# exists to find.
JUDGE_MARK = "nim_judge.py"


def say(msg, log=None):
    line = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if log:
        with io.open(log, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# --------------------------------------------------------------------------------------------------
# INTERLOCK 2 + 4 - is any judge running, and can we even tell?
# --------------------------------------------------------------------------------------------------

def running_judges():
    """PIDs of every live process whose command line names nim_judge.py.

    🔒 RAISES rather than returning [] when it cannot tell. An empty list from this function is a
    POSITIVE statement that nothing is running, and the caller launches on the strength of it. A
    failed query that returned [] would read exactly like a clear coast - which is how a guard
    fails open, and how two judges would end up on one queue.
    """
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
          "Where-Object { $_.CommandLine -like '*" + JUDGE_MARK + "*' } | "
          "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
    except Exception as e:                                              # noqa: BLE001
        raise RuntimeError("cannot list processes (%s) - refusing to launch" % str(e)[:120])
    if out.returncode != 0:
        raise RuntimeError("process query failed rc=%s %s - refusing to launch"
                           % (out.returncode, (out.stderr or "").strip()[:120]))
    return [int(x) for x in re.findall(r"^\s*(\d+)\s*$", out.stdout or "", re.M)]


def pid_alive(pid):
    """Is this PID a live python? Same fail-closed rule: unsure counts as alive."""
    ps = ("Get-CimInstance Win32_Process -Filter \"ProcessId = %d\" | "
          "ForEach-Object { $_.ProcessId }" % pid)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return True
        return bool(re.search(r"\d", out.stdout or ""))
    except Exception:                                                   # noqa: BLE001
        return True


# --------------------------------------------------------------------------------------------------
# INTERLOCK 1 - one supervisor
# --------------------------------------------------------------------------------------------------

def take_lock():
    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)
    if os.path.exists(LOCK):
        try:
            old = int(io.open(LOCK, encoding="utf-8").read().strip().split()[0])
        except Exception:                                               # noqa: BLE001
            old = None
        if old and pid_alive(old):
            raise SystemExit(
                "\n  STOP - another supervisor is already running (PID %s).\n"
                "  Lock: %s\n"
                "  Two supervisors would each restart the judge and put TWO on one queue.\n"
                "  If you are certain that PID is dead, delete the lock file by hand.\n" % (old, LOCK))
        say("stale lock from PID %s (not running) - taking it over" % old)
    io.open(LOCK, "w", encoding="utf-8").write("%d  %s\n" % (os.getpid(), datetime.now()))


def drop_lock():
    try:
        if os.path.exists(LOCK):
            os.remove(LOCK)
    except Exception:                                                   # noqa: BLE001
        pass


# --------------------------------------------------------------------------------------------------
# progress - the only thing that decides "done" and "getting nowhere"
# --------------------------------------------------------------------------------------------------

def unjudged(production, client=None):
    """How many in-scope lines still have no verdict. SELECT only."""
    qa = connect_qa(pilot=not production, production=production, env=load_env(), timeout=120)
    try:
        cur = qa.cursor()
        if client:
            cur.execute("SELECT COUNT(*) FROM qa_line WITH (NOLOCK) "
                        "WHERE NIM_VERDICT IS NULL AND CLIENT_CODE = ?", client)
        else:
            cur.execute("SELECT COUNT(*) FROM qa_line WITH (NOLOCK) WHERE NIM_VERDICT IS NULL")
        return cur.fetchone()[0] or 0
    finally:
        qa.close()


def main():
    ap = argparse.ArgumentParser(
        description="Restart the judge when it trips. Never runs two.")
    ap.add_argument("--production", action="store_true",
                    help="run against PI_Medical_QA_Indirect. Without it, the 2,000-row pilot")
    ap.add_argument("--client", help="one hospital only. Omit for the GLOBAL spend order")
    ap.add_argument("--top", type=int, help="stop after the top N vendors (the stop-and-look slice)")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--max-restarts", type=int, default=200,
                    help="hard ceiling on relaunches. A backstop against a runaway loop, set far "
                         "above any plausible real run")
    ap.add_argument("--give-up-after", type=int, default=5,
                    help="consecutive attempts that judge ZERO new lines before stopping. This is "
                         "the guard against spinning against a real outage - restarting into a "
                         "dead server forever is not resilience, it is a busy loop with a log")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every interlock and print what WOULD happen. Launches nothing")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)
    log = os.path.join(LOGDIR, "supervise-%s.log" % stamp)

    say("supervisor starting  (%s)" % ("PRODUCTION" if a.production else "pilot"), log)
    say("log: %s" % log, log)

    # INTERLOCK 2, before anything else. A judge already running means STOP, not "join in".
    try:
        alive = running_judges()
    except RuntimeError as e:
        raise SystemExit("\n  STOP - %s\n" % e)
    if alive:
        raise SystemExit(
            "\n  STOP - a judge is ALREADY RUNNING (PID %s).\n"
            "  This supervisor will not start a second one. ONE JUDGE AT A TIME.\n"
            "  Stop that process first, or let it finish.\n" % ", ".join(str(p) for p in alive))
    say("interlock: no judge process running  OK", log)

    take_lock()
    say("interlock: supervisor lock taken (PID %d)" % os.getpid(), log)

    cmd = [sys.executable, "-u", JUDGE, "--queue"]
    if a.production:
        cmd.append("--production")
    for flag, val in (("--client", a.client), ("--top", a.top),
                      ("--workers", a.workers), ("--batch", a.batch)):
        if val is not None:
            cmd += [flag, str(val)]
    say("judge command: %s" % " ".join(cmd[1:]), log)

    try:
        left = unjudged(a.production, a.client)
    except Exception as e:                                              # noqa: BLE001
        drop_lock()
        raise SystemExit("\n  STOP - cannot read the database: %s\n" % str(e)[:200])
    say("unjudged at start: {:,}".format(left), log)

    if a.dry_run:
        say("DRY RUN - every interlock passed, launching nothing.", log)
        drop_lock()
        return 0

    attempts = barren = 0
    t0 = time.time()
    try:
        while left > 0:
            if attempts >= a.max_restarts:
                say("** STOPPING - hit --max-restarts %d **" % a.max_restarts, log)
                break

            # INTERLOCK 2 AGAIN, EVERY TIME. Not just at startup: someone may have started a judge
            # by hand while this was sleeping between restarts, and the lock file cannot see that.
            try:
                alive = running_judges()
            except RuntimeError as e:
                say("** STOPPING - %s **" % e, log)
                break
            if alive:
                say("** STOPPING - a judge appeared outside this supervisor (PID %s). "
                    "ONE JUDGE AT A TIME. **" % ", ".join(str(p) for p in alive), log)
                break

            attempts += 1
            before = left
            out = os.path.join(LOGDIR, "judge-%s-%03d.log" % (stamp, attempts))
            say("--- attempt %d: launching judge, output -> %s" % (attempts, os.path.basename(out)),
                log)

            # 🔒 NO PIPE. stdout goes to a FILE and the returncode comes off the process object.
            # Finding 133: piping through tail reported exit 0 on an unhandled exception.
            with io.open(out, "w", encoding="utf-8") as fh:
                proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
                rc = proc.wait()            # INTERLOCK 3 - the child is definitively finished

            try:
                left = unjudged(a.production, a.client)
            except Exception as e:                                      # noqa: BLE001
                say("cannot read the database after the attempt (%s) - waiting" % str(e)[:120], log)
                time.sleep(60)
                continue

            did = before - left
            say("attempt %d finished: exit %s, judged {:,} line(s), {:,} still unjudged"
                .format(did, left) % (attempts, rc), log)

            if left <= 0:
                break
            # A "success" that judged nothing is not success. Counting BARREN attempts rather than
            # failed ones is deliberate: a judge that exits 0 having done nothing would otherwise
            # relaunch forever and the log would read like progress.
            barren = 0 if did > 0 else barren + 1
            if barren >= a.give_up_after:
                say("** STOPPING - %d consecutive attempts judged ZERO lines. Something is wrong "
                    "that restarting does not fix. **" % barren, log)
                break

            wait = min(300, 30 * (2 ** min(barren, 3)))
            say("restarting in %ds  (elapsed %.1f h, %d attempt(s) so far)"
                % (wait, (time.time() - t0) / 3600.0, attempts), log)
            time.sleep(wait)

        if left <= 0:
            say("** QUEUE EMPTY - nothing left unjudged. %d attempt(s), %.1f hours. **"
                % (attempts, (time.time() - t0) / 3600.0), log)
        else:
            say("** STOPPED with {:,} line(s) still unjudged after %d attempt(s). **".format(left)
                % attempts, log)
    except KeyboardInterrupt:
        say("interrupted - stopping. The judge child (if any) is left to finish its batch.", log)
    finally:
        drop_lock()
        say("supervisor lock released", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
