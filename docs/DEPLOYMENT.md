# Deploying APIS Daily Attendance on the Windows Server

Target: one internal **Windows Server (8 GB RAM, 200 GB SSD)**, SQLite, IIS in front, Windows Task Scheduler for the unattended jobs. No Docker, Kubernetes, Redis or separate database server.

```
                   APIS WINDOWS SERVER
     +---------------------+----------------------------+
     | IIS (HTTPS)         | Windows Task Scheduler     |
     |  attendance.apis... |  APIS Attendance Web  (start-up, always on)
     |        |            |  APIS Daily Attendance (09:30 IST)
     |        v            |  APIS Database Backup (23:30)
     |  127.0.0.1:8000     |  APIS Monthly Summary (1st of month, 10:00)
     |  FastAPI + React UI |        |
     +--------+------------+--------+-------------------+
              |                     |
              +------ SQLite (WAL) -+---- data\files (uploads, reports, outbox, archive, backups)
                                    +---- data\inbox  (the day's Pocket HRMS exports)
                                    +---- Gmail API (the only way email is sent)
```

The web app and the jobs are **separate processes**: restarting or stopping the web app never stops the 09:30 job, and a failing job never takes the web app down. Both use the same code and the same database.

## 1. Folders

```
D:\APIS_Attendance_Automation\
  app\                 <- this repository (code + frontend\dist + .venv + .env)
  data\
    database\attendance.db
    inbox\             <- drop the day's AttendanceSummary + PermissionReportAdmin here (processed\ after use)
    files\             <- uploads\, outbox\, archive\ (monthly), backups\, locks\
    logs\              <- app.log + one log per job and month
```

Data never lives inside the code folder, so updating the app is "replace `app\`, run install".

## 2. One-time setup

1. Install **Python 3.12** (all users, "Add to PATH"), **IIS** with **URL Rewrite** and **Application Request Routing**.
2. Set the server time zone to India Standard Time: `tzutil /s "India Standard Time"`.
3. On the developer PC: `npm --prefix frontend run build`, then copy the repository (including `frontend\dist`, excluding `.venv`, `storage`, `.env`) to `D:\APIS_Attendance_Automation\app`.
4. In an elevated PowerShell:
   ```powershell
   cd D:\APIS_Attendance_Automation\app
   .\deploy\scripts\install.ps1          # first run creates .env from deploy\env\.env.production.example and stops
   notepad .env                          # fill APP_SECRET_KEY, folders, mail secrets
   .\deploy\scripts\install.ps1          # installs packages, checks the config, creates/migrates the database
   .\.venv\Scripts\python.exe main.py create-user --username hr.admin --display-name "HR Admin"   # the one application user
   .\.venv\Scripts\python.exe main.py gmail-auth --login-hint attendance@apisindia.com   # sign in as the sender mailbox
   ```
   For Gmail, add `http://localhost:8765/oauth2callback` to the OAuth client's redirect URIs and open the sign-in link **on the server**.
5. Scheduled tasks (use a service account with read/write on `D:\APIS_Attendance_Automation`):
   ```powershell
   .\deploy\scripts\register_tasks.ps1 -User "APIS\svc_attendance"
   Start-ScheduledTask -TaskName "APIS Attendance Web"
   ```
6. IIS: new site (e.g. `attendance.apis.local`), physical path = an empty folder containing `deploy\iis\web.config`, HTTPS binding with the internal certificate. Enable the ARR proxy (IIS Manager -> server -> Application Request Routing Cache -> Server Proxy Settings -> Enable proxy).
7. Open the site, sign in, then:
   - **Employees -> Import** the routing workbook (or Upload page, box 1).
   - **Settings -> Email**: Director and HR mailboxes, sender, mode **test** first.
   - **Settings -> Testing**: a test address (and CC) while you check everything.

## 3. Every day

- Before 09:30, the Pocket HRMS exports for **yesterday** (Attendance Summary + Permission Report) are saved into `data\inbox` (by HR, or later by the Pocket HRMS API connector).
- 09:30 **APIS Daily Attendance** runs `main.py run-daily`:
  1. takes a lock (a second start is refused), records a job run;
  2. reads yesterday's files from the inbox (new files only: the same file twice is not re-processed);
  3. validates, analyses, routes every employee (team lead / HOD / Director / HR exceptions);
     if the Permission Report is not there and Settings "wait for the Permission Report" (or `jobs.permission_required`) is on,
     it stops here, alerts, and the next run (once the file is dropped) prepares the emails;
  4. builds every email and its attachments **before** sending any;
  5. sends (Auto) or prepares them for Approve emails (Manual - when Settings preview mode is on);
  6. records the result; moves the files to `inbox\processed\<date>\`.
- Running it again (Task Scheduler retry, or "Run daily job" on the **Automation** screen) never re-sends an email that already went out; it sends only the ones still unsent or failed.
- Failures (no file, emails failed, exception) email an alert to `jobs.alert_emails` or the HR mailbox, and show on the Automation screen. Exit codes: 0 ok, 1 some emails failed, 3 failed, 4 already running.

## 4. Month-end

- 1st of the month 10:00 **APIS Monthly Summary** runs `main.py monthly` for the previous month:
  monthly report per team lead / HOD (+ company view for the Director) with average attendance, absences, leave, OD, WFH, late arrivals, missing punches, daily trend, recurring patterns and next-month planning notes; a permanent summary; an archive `.xlsx` of every daily row of the month.
- Another day? Run it from the **Automation** screen or `.\deploy\scripts\run_monthly_report.ps1 -Month 2026-11`.
- **Cleanup** is deliberately manual (Automation -> Check cleanup -> Clean up, or `main.py cleanup --month 2026-10 --confirm`). It is refused unless:
  - the month is older than the `jobs.keep_months` kept months (default 2: current + previous),
  - its monthly archive exists and is unchanged,
  - a database backup succeeded after the archive was written.
  It then removes that month's daily employee rows and stored upload files. Employees, routing, settings, monthly summaries, email and job logs are kept.

## 5. Backups and recovery

- 23:30 **APIS Database Backup**: online SQLite backup (safe while the app runs), integrity-checked, kept `jobs.backup_keep_days` days in `data\files\backups`. Copy that folder off the server too (company backup).
- Restore: stop the "APIS Attendance Web" task, copy a backup over `data\database\attendance.db` (and delete any `attendance.db-wal` / `-shm`), start the task again.

## 6. Security

- The Python app listens only on `127.0.0.1:8000`; users reach it through IIS (HTTPS).
- Production refuses to start without sign-in (`AUTH_MODE=local`), a secret key and HTTPS cookies. **One user** (HR) runs the application; team leads, HODs and the Director only receive emails and never log in.
- Secrets only in `app\.env` (readable by the service account and administrators only). Never commit it.
- Every recipient gets only their own people; test mode (one address) for any change to routing or reports.

## 7. Environments

| Environment | Where | Email |
|---|---|---|
| Development | Developer laptop | test mode (outbox) or Settings -> Testing |
| Testing | Server, `APP_ENV=production`, Settings -> Testing set to a few people | live, redirected |
| Production | Server | live, real recipients |

Deploy the same package to each; only `.env` and the Settings differ.

## 8. Updating

```powershell
Stop-ScheduledTask -TaskName "APIS Attendance Web"
# replace D:\APIS_Attendance_Automation\app with the new version (keep .env), then
.\deploy\scripts\install.ps1         # installs packages + migrates the database
Start-ScheduledTask -TaskName "APIS Attendance Web"
```

## 9. Pocket HRMS API (later)

The daily job reads the inbox folder; a connector that downloads yesterday's Attendance Summary and Permission Report from the Pocket HRMS API only has to write the same files (or produce the same rows) - the rest of the pipeline stays unchanged. Needed from Pocket HRMS: the **attendance** and **permission** endpoints and their response format (the EmployeeMaster endpoint only returns employees).
