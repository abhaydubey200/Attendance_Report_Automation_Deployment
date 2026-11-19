# Task Scheduler: "APIS Field Sales Monthly" (1st of every month): prepares last month's Field Sales month-end emails.
# They wait in the app (Field Sales > Automation > Month-end) for Approve.
. "$PSScriptRoot\common.ps1"
exit (Invoke-App -Name "sales_monthly" -Arguments @("sales-monthly"))
