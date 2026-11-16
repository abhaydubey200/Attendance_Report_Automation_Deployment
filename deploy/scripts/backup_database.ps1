# Task Scheduler: "APIS Database Backup" (daily 23:30). Online SQLite backup, integrity-checked, old copies pruned.
. "$PSScriptRoot\common.ps1"
exit (Invoke-App -Name "backup" -Arguments @("backup"))
