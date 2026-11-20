@echo off
rem ===================================================================
rem  APIS Attendance - STOP (one click)
rem  Stops the app started with start.bat (main.py serve on port 8001).
rem ===================================================================
setlocal
cd /d "%~dp0"
set "PORT=8001"
set "PIDFILE=%~dp0storage\app.pid"

title APIS Attendance - stop

powershell -NoProfile -Command ^
  "$procs = @(Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -match 'main\.py\s+serve\s+--port\s+%PORT%(\s|$)' });" ^
  "foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "Remove-Item '%PIDFILE%' -ErrorAction SilentlyContinue;" ^
  "$up = $true; for ($i = 0; $i -lt 15; $i++) { $c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); $c.Close(); Start-Sleep -Seconds 1 } catch { $c.Close(); $up = $false; break } };" ^
  "if ($up) { Write-Host '[X] Port %PORT% is still in use by another program.'; exit 1 }" ^
  "elseif ($procs.Count) { Write-Host '[OK] APIS Attendance stopped.' } else { Write-Host 'APIS Attendance was not running.' }"
set "RC=%errorlevel%"
"%SystemRoot%\System32\timeout.exe" /t 3 >nul
exit /b %RC%
