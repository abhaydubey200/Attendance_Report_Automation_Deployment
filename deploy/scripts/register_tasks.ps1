# Registers the Windows Task Scheduler tasks. Run once in an elevated PowerShell:
#   .\deploy\scripts\register_tasks.ps1 -User "APIS\svc_attendance"
# The account needs read/write on D:\APIS_Attendance_Automation and must be allowed to "log on as a batch job".
# Tasks run whether or not anyone is logged on; a new instance is never started while one is still running.
param(
    [Parameter(Mandatory = $true)][string]$User,
    [string]$DailyTime = "09:30",
    [string]$BackupTime = "23:30",
    [string]$MonthlyTime = "10:00"
)
$ErrorActionPreference = "Stop"
$Scripts = $PSScriptRoot
$cred = Get-Credential -UserName $User -Message "Password for the account that runs the APIS Attendance tasks"

function New-PsAction([string]$script) {
    New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Scripts\$script`""
}
$base = @{ AllowStartIfOnBatteries = $true; DontStopIfGoingOnBatteries = $true; StartWhenAvailable = $true; MultipleInstances = "IgnoreNew" }

# 1. Web application: at start-up, restarted if it stops.
$webSettings = New-ScheduledTaskSettingsSet @base -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "APIS Attendance Web" -Action (New-PsAction "start_web.ps1") -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Settings $webSettings -User $User -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null

# 2. Daily attendance emails (server clock must be India Standard Time).
$jobSettings = New-ScheduledTaskSettingsSet @base -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "APIS Daily Attendance" -Action (New-PsAction "run_daily_report.ps1") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $DailyTime) -Settings $jobSettings -User $User -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null

# 3. Database backup.
Register-ScheduledTask -TaskName "APIS Database Backup" -Action (New-PsAction "backup_database.ps1") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $BackupTime) -Settings $jobSettings -User $User -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null

# 4. Month-end: 1st of every month -> previous month's reports + archive (cleanup stays a manual, checked step).
$monthly = New-ScheduledTaskTrigger -Daily -At $MonthlyTime
$monthlyTask = Register-ScheduledTask -TaskName "APIS Monthly Summary" -Action (New-PsAction "run_monthly_report.ps1") `
    -Trigger $monthly -Settings $jobSettings -User $User -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force
# PowerShell has no monthly trigger cmdlet: switch the trigger to "monthly, day 1" through the COM object.
$svc = New-Object -ComObject "Schedule.Service"; $svc.Connect()
$def = $svc.GetFolder("\").GetTask("APIS Monthly Summary").Definition
$def.Triggers.Clear()
$t = $def.Triggers.Create(4)                 # 4 = TASK_TRIGGER_MONTHLY
$t.StartBoundary = (Get-Date -Day 1 -Hour ([int]$MonthlyTime.Split(":")[0]) -Minute ([int]$MonthlyTime.Split(":")[1]) -Second 0).ToString("s")
$t.DaysOfMonth = 1
$t.MonthsOfYear = 4095                       # every month
$svc.GetFolder("\").RegisterTaskDefinition("APIS Monthly Summary", $def, 6, $User, $cred.GetNetworkCredential().Password, 1) | Out-Null

Get-ScheduledTask -TaskName "APIS *" | Select-Object TaskName, State | Format-Table
Write-Host "Registered. Check the server time zone is India Standard Time:  tzutil /g"
