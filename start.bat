@echo off
rem ===================================================================
rem  APIS Attendance - START (one click)
rem  Starts the app in the background and opens it in the browser.
rem  Both modules: Head Office (Pocket HRMS) and Field Sales (Bizom).
rem  To stop it: double-click stop.bat
rem ===================================================================
setlocal
cd /d "%~dp0"
set "PORT=8001"
set "URL=http://localhost:%PORT%"
set "PY=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0logs\server_console.log"
set "PIDFILE=%~dp0storage\app.pid"

title APIS Attendance - start

if not exist "%PY%" (
  echo [X] Python environment not found: %PY%
  echo     Create it first:  python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

rem --- already running? just open it ---------------------------------
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
  echo The app is already running on %URL%
  start "" "%URL%"
  exit /b 0
)

rem --- screens: build once if they are missing -----------------------
if not exist "frontend\dist\index.html" (
  echo Building the screens (first run only^)...
  where npm >nul 2>&1 || (echo [X] npm not found - install Node.js, or copy frontend\dist from another PC. & pause & exit /b 1)
  pushd frontend
  call npm install --no-audit --no-fund || (popd & echo [X] npm install failed. & pause & exit /b 1)
  call npm run build || (popd & echo [X] Building the screens failed. & pause & exit /b 1)
  popd
)

rem --- database: apply any new updates (safe to run every time) ------
echo Checking the database...
"%PY%" main.py init-db >nul 2>&1
if errorlevel 1 (
  echo [X] Database check failed. Details:
  "%PY%" main.py init-db
  pause
  exit /b 1
)

rem --- start the server in the background ----------------------------
if not exist "logs" mkdir "logs"
echo Starting APIS Attendance on %URL% ...
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PY%' -ArgumentList 'main.py','serve','--port','%PORT%' -WorkingDirectory '%~dp0.' -WindowStyle Hidden -RedirectStandardOutput '%LOG%' -RedirectStandardError '%LOG%.err' -PassThru; Set-Content -Path '%PIDFILE%' -Value $p.Id"

rem --- wait until it answers (up to 60 s) ----------------------------
powershell -NoProfile -Command ^
  "for ($i = 0; $i -lt 60; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/' | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 (
  echo [X] The app did not start. See logs\server_console.log.err
  pause
  exit /b 1
)

echo [OK] APIS Attendance is running: %URL%
echo      Close this window any time - the app keeps running. Use stop.bat to stop it.
start "" "%URL%"
timeout /t 5 >nul
exit /b 0
