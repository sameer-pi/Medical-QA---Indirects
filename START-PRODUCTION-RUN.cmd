@echo off
setlocal
cd /d "%~dp0"

REM ==================================================================================================
REM  USE THE PROJECT'S VIRTUAL ENVIRONMENT, IF THERE IS ONE.
REM
REM  Added 2026-09-16. This file calls bare `python` four times. A venv created in C:\QA is NOT
REM  active when the file is double-clicked from Explorer, so every one of those calls would have
REM  used the system interpreter - which on the office desktop is the WINDOWS STORE STUB, and does
REM  not run Python at all. The failure is not a traceback; it is a Store advert, at the gate of a
REM  40-day run. Found by the desktop Claude session before launch, not by anyone here.
REM
REM  Activating here makes double-click and "run it from an activated window" behave identically,
REM  which is the point: the correct way to start this must not depend on remembering a step.
REM ==================================================================================================
if exist ".venv\Scriptsctivate.bat" (
    call ".venv\Scriptsctivate.bat"
    echo   Virtual environment: .venv
) else if exist "venv\Scriptsctivate.bat" (
    call "venv\Scriptsctivate.bat"
    echo   Virtual environment: venv
) else (
    echo   Virtual environment: none found - using the system Python
)

REM --- PROVE python actually runs before anything depends on it. The Store stub exits non-zero
REM --- here, so this turns "an advert opened" into a sentence that says what to do.
python -c "import sys; sys.exit(0)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ** STOPPED - `python` on this machine does not run.
    echo.
    echo      Most likely the Windows Store stub rather than a real Python.
    echo      If you made a virtual environment, check it is called .venv or venv
    echo      and sits directly inside this folder. Nothing has been started.
    echo.
    pause
    exit /b 1
)

REM --- Say WHICH interpreter is about to judge 2.79m lines. One line, and it ends the entire
REM --- class of "it says pyodbc is missing but I installed it" confusion.
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do echo   Python:              %%P

REM ==================================================================================================
REM  START THE INDIRECTS JUDGING RUN - the office desktop, production, ~40 days.
REM
REM  Sameer, 2026-08-27, on how the move to the desktop should feel:
REM    "i clone the repo, run a few easy commands that you ask me to do, and the judge starts judging"
REM
REM  This IS those commands. Double-click it, or run it from a terminal.
REM
REM  WHY A FILE AND NOT A CHANGED DEFAULT. The alternative was to make --production the default so
REM  there is no flag to forget. Rejected: db.py's second lock is "production must be asked for on
REM  purpose", pinned by 20 checks in test_guards.py, and the tool that WRITES 2.79M rows would have
REM  needed the flag anyway. So the flag is written down ONCE, here, where it can be read and
REM  reviewed - rather than typed from memory three times or hidden in a default.
REM
REM  Run it twice by accident and nothing bad happens: supervise.py has four interlocks and will
REM  refuse to start a second judge.
REM ==================================================================================================

echo.
echo   ================================================================
echo    INDIRECTS QA - PRODUCTION JUDGING RUN
echo   ================================================================
echo.

REM --- 1. Is the machine ready? This is the step that catches a bad .env, a missing ODBC driver,
REM ---    an unreachable server or an unbuilt queue - in about ten seconds, with a message.
echo   [1/4] Checking this machine...
echo.
python pipeline\preflight.py --production
if errorlevel 1 (
    echo.
    echo   ** STOPPED - preflight did not pass. Nothing has been started.
    echo      Fix what it named above and run this again.
    echo.
    pause
    exit /b 1
)

REM --- 2. One confirmation. This commits roughly 40 days of compute against the real database;
REM ---    a single keypress is proportionate to that, and it is the last point of no return.
REM ---    🔴 THIS SCREEN USED TO SAY "2,786,018 lines ... about 40 days". IT WAS WRONG, and wrong
REM ---    in the one place built to tell you what you are committing to. This launches --top 100:
REM ---    483,313 lines and about a day. Sameer found it on 2026-09-16 by asking which numbered
REM ---    step starts the 2M-line run - the answer being that none of them does. A confirmation
REM ---    gate that overstates its own job trains the reader to stop reading it.
echo.
echo   ================================================================
echo    DATABASE   PI_Medical_QA_Indirect            (PRODUCTION)
echo    THIS RUN   the top 100 vendors of 29,469
echo               483,313 lines of 2,786,018  (17.3%%)
echo               about ONE DAY, then it STOPS on purpose.
echo.
echo    THIS IS LAUNCH 1 OF 2. It does NOT judge everything.
echo    The remaining ~2.3m lines need a second launch, and you decide
echo    that one after looking at these verdicts. Nothing is wasted:
echo    launch 2 skips the finished vendors in under a second.
echo   ================================================================
echo.
echo    If the database above does not say PI_Medical_QA_Indirect,
echo    answer anything but YES.
echo.
set /p GO="   Type YES to start launch 1, anything else to cancel: "
if /i not "%GO%"=="YES" (
    echo.
    echo   Cancelled. Nothing was started.
    echo.
    pause
    exit /b 0
)

if not exist "output\logs" mkdir "output\logs"

REM --- 3. The supervisor, in its own window. NOT PIPED: a pipe reports exit code 0 on a crash,
REM ---    which is how a real crash was missed on 2026-08-26 (Finding 133). Its own window means
REM ---    closing THIS one does not kill the run.
echo.
echo   [2/4] Starting the judge under its supervisor...
start "Indirects JUDGE (do not close)" cmd /k "python pipeline\supervise.py --production --top 100 > output\logs\run.log 2>&1"

REM --- 4. The monitor, read-only, in its own window. Separate on purpose: the watcher must be
REM ---    disposable and the judge must not be. Killing the monitor never touches the judge.
echo   [3/4] Starting the run monitor...
start "Indirects MONITOR (safe to close)" cmd /k "python pipeline\monitor.py --production"

REM --- 5. Give the monitor a moment to bind the port, then open the page.
timeout /t 4 /nobreak >nul
echo   [4/4] Opening the dashboard...
start "" "http://127.0.0.1:8000"

echo.
echo   ================================================================
echo    RUNNING.
echo.
echo    Dashboard    http://127.0.0.1:8000
echo    Judge log    output\logs\run.log
echo    Restarts     output\logs\supervise-*.log
echo.
echo    The JUDGE window must stay open. The MONITOR window can be
echo    closed and reopened whenever you like - it only watches.
echo.
echo    CHECK THE PAGE SAYS "PRODUCTION" AND NAMES
echo    PI_Medical_QA_Indirect. If it says pilot, stop and ask.
echo.
echo   ----------------------------------------------------------------
echo    WHEN THIS FINISHES (about a day) THE JUDGE EXITS ON PURPOSE.
echo    That is not a crash - it is the end of launch 1, the top 100
echo    vendors. The dashboard will sit at roughly 17%% and stay there.
echo.
echo    Look at the verdicts, THEN start launch 2 for the rest:
echo.
echo        python pipeline\supervise.py --production ^> output\logs\run.log 2^>^&1
echo.
echo    Same command, WITHOUT --top 100. Run it in its own window and
echo    never through a pipe. It resumes at vendor 101 and re-judges
echo    nothing. That one is the ~40 day run.
echo   ================================================================
echo.
pause
