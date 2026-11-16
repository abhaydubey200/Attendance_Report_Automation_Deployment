# Shared settings for the APIS Attendance scripts. Dot-sourced by the other scripts.
# Change $AppRoot if the application is installed somewhere else.

$ErrorActionPreference = "Stop"
$AppRoot  = if ($env:APIS_APP_ROOT) { $env:APIS_APP_ROOT } else { "D:\APIS_Attendance_Automation\app" }
$Python   = Join-Path $AppRoot ".venv\Scripts\python.exe"
$LogDir   = if ($env:APP_LOG_DIR) { $env:APP_LOG_DIR } else { "D:\APIS_Attendance_Automation\data\logs" }

function Invoke-App {
    <# Runs `python main.py <args>` in the app folder, appends the output to a monthly log, returns the exit code. #>
    param([string]$Name, [string[]]$Arguments)
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $log = Join-Path $LogDir ("{0}_{1:yyyy-MM}.log" -f $Name, (Get-Date))
    Push-Location $AppRoot
    try {
        "==== {0:yyyy-MM-dd HH:mm:ss} {1} {2}" -f (Get-Date), $Name, ($Arguments -join " ") | Out-File -Append -Encoding utf8 $log
        # cmd.exe does the redirection so Python's log lines on stderr are not turned into PowerShell errors.
        $quoted = ($Arguments | ForEach-Object { '"' + $_ + '"' }) -join " "
        cmd.exe /c "`"$Python`" main.py $quoted >> `"$log`" 2>&1"
        $code = $LASTEXITCODE
        "==== exit code $code" | Out-File -Append -Encoding utf8 $log
        return $code
    } finally {
        Pop-Location
    }
}
