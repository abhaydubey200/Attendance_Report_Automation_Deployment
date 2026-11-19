# Registers the Field Sales (Module 2, Bizom) scheduled tasks. Separate from register_tasks.ps1 (Module 1), which is unchanged.
# Run once in an elevated PowerShell:
#   .\deploy\scripts\register_sales_tasks.ps1 -User "APIS\svc_attendance"
param(
    [Parameter(Mandatory = $true)][string]$User,
    [string]$DailyTime = "10:00",
    [string]$MonthlyTime = "10:30"
)
$ErrorActionPreference = "Stop"
$Scripts = $PSScriptRoot
$cred = Get-Credential -UserName $User -Message "Password for the account that runs the APIS Attendance tasks"
$pw = $cred.GetNetworkCredential().Password

function New-PsAction([string]$script) {
    New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Scripts\$script`""
}
$jobSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "APIS Field Sales Daily" -Action (New-PsAction "run_sales_daily.ps1") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $DailyTime) -Settings $jobSettings -User $User -Password $pw -RunLevel Limited -Force | Out-Null

Register-ScheduledTask -TaskName "APIS Field Sales Monthly" -Action (New-PsAction "run_sales_monthly.ps1") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $MonthlyTime) -Settings $jobSettings -User $User -Password $pw -RunLevel Limited -Force | Out-Null
$svc = New-Object -ComObject "Schedule.Service"; $svc.Connect()
$def = $svc.GetFolder("\").GetTask("APIS Field Sales Monthly").Definition
$def.Triggers.Clear()
$t = $def.Triggers.Create(4)                 # monthly
$t.StartBoundary = (Get-Date -Day 1 -Hour ([int]$MonthlyTime.Split(":")[0]) -Minute ([int]$MonthlyTime.Split(":")[1]) -Second 0).ToString("s")
$t.DaysOfMonth = 1
$t.MonthsOfYear = 4095
$svc.GetFolder("\").RegisterTaskDefinition("APIS Field Sales Monthly", $def, 6, $User, $pw, 1) | Out-Null

Get-ScheduledTask -TaskName "APIS Field Sales *" | Select-Object TaskName, State | Format-Table
