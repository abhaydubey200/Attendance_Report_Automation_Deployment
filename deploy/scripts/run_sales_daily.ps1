# Task Scheduler: "APIS Field Sales Daily" (daily, after the Bizom files are in the Field Sales inbox).
# Takes yesterday's Bizom Attendance (+ EOD, Call Variance) files from storage\sales_inbox, counts the day and prepares
# the emails (sent automatically only when Field Sales Settings > "Send automatically" is on).
# Exit codes: 0 ok, 1 some emails failed, 3 failed (alert emailed), 4 already running.
. "$PSScriptRoot\common.ps1"
exit (Invoke-App -Name "sales_daily" -Arguments @("sales-run-daily"))
