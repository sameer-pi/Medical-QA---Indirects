@echo off
setlocal
cd /d "%~dp0"

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
echo.
echo   ================================================================
echo    This starts judging 2,786,018 lines on PI_Medical_QA_Indirect.
echo    It runs for about 40 days and restarts itself if it crashes.
echo   ================================================================
echo.
set /p GO="   Type YES to start, anything else to cancel: "
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
echo   ================================================================
echo.
pause
