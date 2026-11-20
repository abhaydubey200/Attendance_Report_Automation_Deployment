@echo off
rem ===================================================================
rem  APIS Attendance - STOP (one click)
rem  Stops the app started with start.bat (whatever is serving port 8001).
rem ===================================================================
setlocal
cd /d "%~dp0"
set "PORT=8001"
set "PIDFILE=%~dp0storage\app.pid"

title APIS Attendance - stop

powershell -NoProfile -Command ^
  "$ids = @(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess);" ^
  "if (Test-Path '%PIDFILE%') { $ids += [int](Get-Content '%PIDFILE%' -ErrorAction SilentlyContinue) };" ^
  "$ids = $ids | Where-Object { $_ -gt 0 } | Sort-Object -Unique;" ^
  "$stopped = 0;" ^
  "foreach ($id in $ids) { $p = Get-Process -Id $id -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $id -Force; $stopped++ } };" ^
  "Remove-Item '%PIDFILE%' -ErrorAction SilentlyContinue;" ^
  "for ($i = 0; $i -lt 15; $i++) { if (-not (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Seconds 1 };" ^
  "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { Write-Host '[X] Something is still using port %PORT%.'; exit 1 }" ^
  "elseif ($stopped) { Write-Host '[OK] APIS Attendance stopped.' } else { Write-Host 'APIS Attendance was not running.' }"
set "RC=%errorlevel%"
"%SystemRoot%\System32\timeout.exe" /t 3 >nul
exit /b %RC%
