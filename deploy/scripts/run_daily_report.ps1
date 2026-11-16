# Task Scheduler: "APIS Daily Attendance" (daily 09:30 IST).
# Takes yesterday's Pocket HRMS files from the inbox, analyses, verifies and sends the emails.
# Exit codes: 0 ok, 1 some emails failed (retried next run / Approve emails), 3 failed (alert emailed), 4 already running.
. "$PSScriptRoot\common.ps1"
exit (Invoke-App -Name "daily" -Arguments @("run-daily"))
