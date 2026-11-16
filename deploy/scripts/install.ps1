# One-time install / update on the Windows Server. Run in an elevated PowerShell from the app folder:
#   cd D:\APIS_Attendance_Automation\app ; .\deploy\scripts\install.ps1
# Needs Python 3.12 on the server. The React UI is built on the developer PC (frontend\dist is copied with the app).
. "$PSScriptRoot\common.ps1"

Push-Location $AppRoot
try {
    if (-not (Test-Path $Python)) {
        Write-Host "Creating the Python environment..."
        py -3.12 -m venv .venv
    }
    & $Python -m pip install --upgrade pip | Out-Null
    & $Python -m pip install -r requirements.txt
    if (-not (Test-Path ".env")) {
        Copy-Item "deploy\env\.env.production.example" ".env"
        Write-Warning "Created .env from the template - fill in APP_SECRET_KEY, folders and mail secrets, then run this script again."
        exit 2
    }
    foreach ($d in "D:\APIS_Attendance_Automation\data\database", "D:\APIS_Attendance_Automation\data\inbox",
                   "D:\APIS_Attendance_Automation\data\files", "D:\APIS_Attendance_Automation\data\logs") {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
    if (-not (Test-Path "frontend\dist\index.html")) { Write-Warning "frontend\dist is missing - build it on the developer PC (npm run build) and copy it here." }
    & $Python main.py check
    & $Python main.py init-db
    Write-Host "Done. Next: .\deploy\scripts\register_tasks.ps1 (scheduled tasks) and the IIS site (deploy\iis\web.config)."
} finally {
    Pop-Location
}
