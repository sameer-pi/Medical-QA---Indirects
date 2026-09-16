# DESKTOP — START HERE

**You are on the office desktop. This machine runs the judge, and it runs it for about 40 days.**

If you are reading this on the laptop, this is not your file — the laptop *watches* the run.
`ACTIONS.md` is yours.

> **As at 16 September 2026.** Everything below was proven on the laptop against the real production
> database. Nothing below has been proven on *this* machine — that is what step 4 is for.

---

## 🤖 IF YOU ARE THE CLAUDE SESSION ON THIS MACHINE, READ THIS BOX FIRST

1. **Read `CLAUDE.md` (operating rules), then `TRACKER.md` (where the programme is), then the tail of
   `RUN_LOG.md`.** In that order. `README.md` describes the *pilot era* and its status section has
   been removed for that reason — do not reconstruct project state from it.
2. **The run is designed and tested. Do not redesign it.** `START-PRODUCTION-RUN.cmd` is the launch.
   Every part of it was argued out and written down; if something looks wrong, say so and stop —
   do not improve it mid-launch.
3. 🔴 **NEVER start the judge inside your own shell.** A judge that is a child of a Claude session
   dies when the session closes. Use the `.cmd`, which puts the judge in its own detached window.
   Your job is steps 1–4 and reading what they print. Step 5 is a double-click.
4. 🔴 **EVERY TOOL DEFAULTS TO THE PILOT. If you type a command without `--production`, you will
   judge 2,000 rows and it will look like it worked.** Read the next section before you type
   anything. Do not "helpfully" start the judge with a hand-typed command.
5. **You may not have a full picture.** The last `RUN_LOG.md` entry is 2026-08-27 and today is later
   than that. **Measure before asserting** — do not tell Sameer the run has or has not started until
   you have looked.

---

## 🔴 PILOT OR PRODUCTION — the one that will catch you

**Sameer, 2026-09-16:** *"when i tell the claude session to start i hope it will begin with the 2M
lines and not the pilot."*

**It depends entirely on HOW it is started, and the default is the PILOT.**

| How you start it | What it judges |
|---|---|
| **`START-PRODUCTION-RUN.cmd`** (double-click) | ✅ **PRODUCTION — 2,786,018 lines.** The flag is written into the file |
| `python pipeline\supervise.py --production` | ✅ Production |
| `python pipeline\supervise.py` | 🔴 **THE PILOT — 2,000 rows.** Finishes in minutes and looks like success |

**This is deliberate, not a bug.** `db.py`: *"THE DEFAULT IS THE SAFE ONE ON PURPOSE. A caller that
forgets to say which database it wants gets the 2,000-row pilot, where a mistake costs 16 minutes."*
Production has to be **asked for on purpose** — a lock `test_guards.py` pins with 20 checks.

🔴 **So: use the `.cmd`. Do not let anyone — including a Claude session trying to be helpful — start
the judge with a hand-typed command.** That is the single way to end up judging 2,000 rows while
believing 2.79M are under way.

### It announces itself in three places. Check at least one.

```
1  THE YES PROMPT      DATABASE   PI_Medical_QA_Indirect            (PRODUCTION)
                       If that line does not name PI_Medical_QA_Indirect,
                       answer anything but YES.

2  THE JUDGE WINDOW    "supervisor starting  (PRODUCTION)"
                       It prints the word. If it does not say PRODUCTION, close it.

3  THE DASHBOARD       the page names its own database.
                       PRODUCTION / PI_Medical_QA_Indirect - or stop and ask.
```

⚠️ **That prompt used to read *"This starts judging 2,786,018 lines ... about 40 days"* and it was
WRONG** — the launcher runs `--top 100`, which is 483,313 lines and about a day. Corrected
2026-09-16. If you are ever looking at a copy that still says 40 days, you have an old clone.

⚠️ **A pilot page reads 100% complete and perfectly healthy while production sits untouched.** That
is the one way this whole set-up can mislead you, which is why it is checked three times.

---

## Before you touch anything — is it already running?

Three weeks passed between the last log entry and this file. **A second judge against the same
database is the worst outcome available here** — both would select the same unjudged rows, spend
twice, and race each other's writes.

⚠️ **The supervisor's interlocks scan the LOCAL process list only. They cannot see a judge running on
the laptop, or one left running on this desktop under a different window.** That check is human.

**Do this first:**

```
python pipeline\monitor.py --production
```

Open `http://127.0.0.1:8000`. **If the judged count is moving, a judge is already running — stop and
find it.** If it is static and greater than zero, a run started and stopped; that is fine, the
supervisor resumes. If it is zero, nothing has ever run.

The monitor is read-only and safe to start and kill at any time. It never touches the judge.

---

## The five steps

```
1   git clone https://github.com/sameer-pi/Medical-QA---Indirects.git

        Clone to a NON-SYNCED path. C:\QA\ is fine.
        NOT OneDrive, NOT the Teams folder. A sync client rewriting files under a
        running judge is a failure nobody would ever diagnose.

2   Copy .env into the folder BY HAND (Teams).

        It is not in the repo and never will be. .env.example shows the shape but
        holds no values. Without it, step 4 stops and tells you so.

3   pip install -r requirements.txt

        pyodbc + PyYAML. That is all the run needs.
        pip CANNOT install the ODBC driver. "ODBC Driver 17 for SQL Server" has to
        already be on this machine. Step 4 is what tells you whether it is.

4   python pipeline\preflight.py --production

        Ten seconds. Checks Python, pyodbc, the ODBC driver, .env, the SQL connection,
        the data, and that NVIDIA answers. It prints GO or NO-GO with the blocking
        problems named. It writes nothing and prints no credentials.

        If it says NO-GO, fix what it named and run it again. Nothing has been started.

5   START-PRODUCTION-RUN.cmd          <- double-click it
```

The `.cmd` re-runs preflight, refuses to start anything if it fails, asks you to type `YES`, then
opens **two windows** and the dashboard.

---

## What you should see after step 5

| Window | Title | Can I close it? |
|---|---|---|
| Judge | `Indirects JUDGE (do not close)` | 🔴 **No.** Closing it stops the run |
| Monitor | `Indirects MONITOR (safe to close)` | ✅ Yes, any time. It only watches |
| Browser | `http://127.0.0.1:8000` | ✅ Yes |

🔴 **Check the page says `PRODUCTION` and names `PI_Medical_QA_Indirect`.**

It labels its own database. **If it says *pilot*, stop and ask.** A pilot page reads 100% complete
and perfectly healthy while production sits untouched — that is the one way this misleads you.

---

## The three things that kill a 40-day run

1. **Signing out of Windows.** Log off and Windows terminates everything in your session. **Lock the
   screen (Win+L). Never Sign out.** You have confirmed you will not sign out — this is here so that
   whoever reads it next also knows.
2. **Closing the JUDGE window.** Nothing is lost — the judge resumes exactly where it stopped and
   re-judges nothing — but the hours between the close and someone noticing are gone.
3. **A second judge.** One judge at a time, across *both* machines. See the box above.

None of these corrupts data. All three cost time.

---

## 🔴 Launch 1 stops at 100 vendors. A second launch is required.

This is the thing most likely to confuse you, so it is stated as plainly as possible.

The launcher runs `--top 100`. The judge finishes those 100 vendors, prints a summary, and **exits**.
Vendor 101 is never touched. Left alone it sits at 17.3% for ever. **That is correct behaviour, not a
crash** — you chose it: *"yeah lets do the top 100 first, keep it as is."*

```
                        launch 1 (--top 100)              launch 2 (no --top)
vendors            100 of 29,469      0.34%                    29,469
lines          483,313 of 2,786,018   17.3%                 2,786,018
signed spend    $3.93bn of $5.87bn    66.9%                    $5.87bn
time                   ~1 day                                 ~40 days
```

**0.34% of vendors carries 66.9% of the signed spend** — the spend-weighted order doing its job.

**When launch 1 finishes, look at the verdicts before launching 2.** That is the whole point of the
slice. Then:

```
python pipeline\supervise.py --production > output\logs\run.log 2>&1
```

— the same command as the launcher, with `--top 100` dropped. **Launch 2 wastes nothing:** the resume
skips the 100 finished vendors in 0.41 seconds and starts at vendor 101.

⚠️ Run it **detached and unpiped**, in its own window. Never through `tail`, `head`, `more` or a bare
`tee` — a pipe reported exit code 0 on a real crash on 2026-08-26.

---

## When something looks wrong

| What you see | What it means | What to do |
|---|---|---|
| Page is **red**, `JUDGE MAY BE DOWN` | No new verdict for 15 minutes | Look at the judge window and `output\logs\run.log`. The supervisor usually restarts it on its own |
| Judge window **gone** | Crashed hard, or was closed | Re-run `START-PRODUCTION-RUN.cmd`. It resumes, losing nothing |
| Page says **pilot** | Wrong database | 🔴 Stop. Ask. Do not let it run |
| Lines/min reads **0** early on | Normal in the first minutes | Wait. It is measured over the span the data covers |
| `preflight` says **NO-GO** | It names the blocking problem | Fix that one thing, run it again |
| Judged count **not moving**, no red yet | Under 15 minutes since the last verdict | Wait for the stall clock |

**The supervisor restarts the judge when it dies** — up to 200 times, stopping if five consecutive
attempts judge zero new lines (that is a real outage, not a blip). Every restart is logged to
`output\logs\supervise-*.log`, which is also how we finally measure how often it actually trips.

---

## ⚠️ What is NOT armed

**`MONITOR_SMTP_PASS` is blank, so no stall email will be sent.** The page still turns red; nothing
lands in your inbox. The monitor says so out loud rather than pretending to be armed.

This blocks nothing — the judge never reads those keys. But **overnight, the alert chain is broken
end to end**: monitor red → email → a person → restart. The supervisor is the only link in that chain
that does not need a human awake, which is why it exists.

To fix it: generate an **app password** on the account (needs MFA), paste it into **this machine's**
`.env` without the spaces Microsoft shows, restart the monitor, and tell me — I will fire a
deliberate test alert. The mail server has already been proven to offer `AUTH LOGIN` on port 587, so
an app password should be enough with no IT ticket.

⚠️ **Port 587 was proven from the LAPTOP.** It may be filtered here and preflight does not check it.
Re-run `scratchpad/fire_alert.py` on this machine before trusting the alert.

---

## Where everything lives

**`CLAUDE.md` is the authority on this** and every file is listed there. The short version:

| File | What it is |
|---|---|
| `TRACKER.md` | **Where the programme is.** The only place status lives |
| `RUN_LOG.md` | Dated record of every run and finding. Append-only |
| `ACTIONS.md` | Sameer's to-do list |
| `PLAN.md` | The technical reasoning |
| `APP.md` | The monitor — what it does and what it deliberately does not |
| `CLAUDE.md` | Operating rules. Read it before changing anything |
| `README.md` | Project orientation. ⚠️ Written in the pilot era — for status, use `TRACKER.md` |

🔴 **`.env` never goes into git.** It holds live SQL logins for five databases and the NVIDIA key.
It is copied by hand, once, and `.gitignore` has blocked it since before the first push.

---

## One last thing

**This desktop is the run machine, not the editing machine.** Edits, analysis and documents stay on
the laptop and travel by git. This machine's job is uptime.

If you find yourself about to change code here mid-run, stop and ask first.
