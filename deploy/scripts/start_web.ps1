# Task Scheduler: "APIS Attendance Web" (at system start-up, restarts on failure).
# Runs the FastAPI app (which also serves the built React UI) on 127.0.0.1:8000. IIS forwards to it.
. "$PSScriptRoot\common.ps1"
exit (Invoke-App -Name "web" -Arguments @("serve", "--host", "127.0.0.1", "--port", "8000"))
