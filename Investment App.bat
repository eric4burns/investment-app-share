@echo off
rem Double-click to start the Investment App on Windows. It runs on this
rem computer and opens in your browser. Close this window to stop it.
rem
rem Phone: if Tailscale is installed and signed in on this PC, the app also
rem listens on the PC's Tailscale address - a private link between your own
rem devices - and the address to open on the phone is printed below. It never
rem listens on the Wi-Fi network as a whole: the app has no password.
cd /d "%~dp0"
rem Windows opens a zip as if it were a folder without extracting it, and a
rem .bat double-clicked in there runs alone in a temp folder with no app
rem beside it - and closes before anyone can read why.
if not exist app\web.py (
  echo This file has to stay inside the investment-app folder from the zip.
  echo Right-click the zip, choose "Extract All...", then double-click this file inside the folder it makes.
  pause
  exit /b 1
)
rem Python, without asking anybody to install Python: a real 3.11+ if one is
rem here, otherwise a private copy fetched with uv (astral.sh's free tool)
rem into this user's profile - no admin rights, no PATH edits, about a
rem minute the first time and nothing after.
set PY=
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set PY=py -3
if "%PY%"=="" python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set PY=python
if not "%PY%"=="" goto havepy
rem No blocks with %VAR% inside them below: cmd expands a variable inside
rem ( ... ) before the block runs, so a value set in the block is never seen.
set UV=
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV goto haveuv
where uv >nul 2>&1 && set UV=uv
if defined UV goto haveuv
echo Python is not installed. Fetching a private copy for this app - one time, about a minute...
powershell -ExecutionPolicy ByPass -NoProfile -c "irm https://astral.sh/uv/install.ps1 | iex" >nul 2>&1
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV goto haveuv
echo That did not work - no internet? Install Python 3.12 from the page that opens, tick "Add python.exe to PATH", then double-click this file again.
start https://www.python.org/downloads/windows/
pause
exit /b 1
:haveuv
set PY="%UV%" run --no-project --python 3.12 python
:havepy
set INVESTMENT_APP_RELOAD=0
set TS=
set TSIP=
if exist "C:\Program Files\Tailscale\tailscale.exe" set "TS=C:\Program Files\Tailscale\tailscale.exe"
if not defined TS (where tailscale >nul 2>&1 && set TS=tailscale)
if defined TS for /f "usebackq tokens=1" %%i in (`"%TS%" ip -4 2^>nul`) do (
  if not defined TSIP set TSIP=%%i
)
if defined TSIP set INVESTMENT_APP_HOST=127.0.0.1,%TSIP%
if not exist data\fidelity mkdir data\fidelity
if not exist data\robinhood mkdir data\robinhood
if not exist data\bank mkdir data\bank
if not exist data\cards mkdir data\cards
if not exist data\payroll mkdir data\payroll
if not exist data\budget mkdir data\budget
rem Double-clicked twice: the app is already up, so open the browser on it.
powershell -NoProfile -c "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8737/) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo The Investment App is already running - opening it in your browser.
  start http://127.0.0.1:8737/
  pause
  exit /b 0
)
echo Starting the Investment App ...
start "Investment App server" /min %PY% -m app.web
timeout /t 4 /nobreak >nul
start http://127.0.0.1:8737/
echo The app is open in your browser at http://127.0.0.1:8737/
echo Leave the minimised "Investment App server" window open while you use it. Close it to stop the app.
echo.
if defined TSIP (
  echo On your phone: install Tailscale, sign in to the SAME account as this PC,
  echo switch it on, and open
  echo.
  echo     http://%TSIP%:8737/
) else (
  echo To use it on your phone as well: install Tailscale ^(https://tailscale.com/download^)
  echo on this PC and on the phone, sign in to the same account on both, then
  echo double-click this file again - it will print the address to open.
)
pause
