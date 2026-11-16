# Task Scheduler: "APIS Monthly Summary" (default: 1st of the month, 10:00 -> the previous month).
# To run for a specific month: .\run_monthly_report.ps1 -Month 2026-11
param([string]$Month)
. "$PSScriptRoot\common.ps1"
$cmdArgs = @("monthly")
if ($Month) { $cmdArgs += @("--month", $Month) }
exit (Invoke-App -Name "monthly" -Arguments $cmdArgs)
