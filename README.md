# APIS Daily Attendance

A small automation tool for APIS India Limited:

**Upload one day's attendance (Pocket HRMS "Attendance Summary" + "Permission Report") → the app works out who reports to whom → each team lead and HOD gets ONE email with their own team's attendance (counts first, then only the people needing attention; their full list attached), the Director gets the company summary, and HR gets the records that could not be routed.**

**Pocket HRMS is the only source** (Bizom is no longer used). Datasets, joined on **EMP_CODE** (never on names):

| Dataset | What it gives |
|---|---|
| Pocket HRMS Attendance Summary (daily) | One row per employee: In Time / Out Time ("Unswipe" = no punch, "Invalid" = missing punch), shift, Type (A / P / leave code), Department, Designation |
| Pocket HRMS Permission Report (daily) | Short-leave permissions: date, time window, Pending/Approved |
| Employee master (HR's routing workbook `APIS_Email_Routing_Master.xlsx`, or the Employee Amendment Excel; kept on the Employees screen) | Department, HOD + email, team lead (Sub split ID), reporting manager, status, routing issues |

Python 3.12 (FastAPI) + React (Vite). SQLite database on a single PC; SQL Server optional for a shared server.

## Run it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
.\.venv\Scripts\python.exe main.py init-db
.\.venv\Scripts\python.exe main.py serve          # open http://127.0.0.1:8000
```

After updating to a new version, run `main.py init-db` again (it applies database changes and access rights).

The app opens with no login page (this PC only). Screens:

| Screen | What it does |
|---|---|
| **Upload** | Three boxes: **1. Employee master** (optional, only when it changed; imported first), **2. Attendance Summary**, **3. Permission Report** (together or one after the other; each file is checked to be the right type, columns and date are validated). Choose **Manual** (emails wait on Approve emails) or **Auto** (emails are sent as soon as the files are processed) for each upload; the default comes from Settings. |
| **Insights** | KPIs, highlights, charts, team comparison, trend across days, searchable employee list; download the Excel or HTML dashboard. |
| **Approve emails** | The day's emails: recipient, role, To/CC, how many employees, how many need attention, status. Preview each email and its attachments; **Approve & send all** or approve selected; resend (admin). **Routing check** tab: who gets whom, coverage totals, records held for HR, switch a recipient on/off. |
| **Email log** | Audit log: every email, recipient, date, status, time, who approved it. |
| **Attendance report** | Any date range, filtered by HOD, department, team, reporting manager, category, status or source; by employee or day by day; Excel; shareable link. |
| **Employee report** | One employee's attendance day by day over a date range, with Excel. |
| **Employees** | The employee master: filters by HOD, department, team, manager and status; HOD cards and teams; add, edit, mark as Left / restore; routing issue; change history; import and export Excel. |
| **Automation** | Scheduled jobs: history (status, duration, details), run the daily job / a backup now, month-end reports (generate, preview, approve, archive) and the guarded cleanup. |
| **Settings** | Director and HR mailboxes, routing switches, Gmail sender, testing address, preview mode, counting rules. |

First time:
1. **Employees → Import Excel** with HR's routing workbook. The `Employee_Master` sheet updates the employees; `Recipient_Master` sets each recipient on/off; `Email_Routing_Config` sets the report switches and sender; the app's routing is checked against `Employee_Coverage` and any difference is shown.
2. **Settings → Who gets the daily emails**: enter the Director email(s) and the HR attendance mailbox, and switch on the report types (the workbook currently has them all DISABLED until the addresses are confirmed).
3. **Settings → Sending**: the Gmail sender mailbox (one central company mailbox, e.g. `attendance@…`, connected once with `main.py gmail-auth`), then switch Email from *test* to *live*. In test mode emails are saved to `storage/outbox/` instead of being delivered.

**Try it with synthetic data:** `python main.py demo` then `python main.py serve --demo --port 8010`.

**Production (Windows Server):** see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): IIS -> the app on 127.0.0.1:8000, plus Windows Task Scheduler jobs:
`main.py run-daily` (09:30, yesterday's files from the inbox folder -> emails; idempotent, locked, alerts on failure; with Settings "wait for the Permission Report" on, it prepares nothing and alerts until that file is in the inbox too),
`main.py backup` (daily SQLite backup), `main.py monthly` (month-end reports + archive), `main.py cleanup --month YYYY-MM --confirm` (guarded).

**Automate the upload:**
- `python main.py upload "C:\path\AttendanceSummary.xlsx" "C:\path\PermissionReportAdmin.xlsx" --send auto` (add `--master workbook.xlsx` to import the employee master first; `--send manual` to wait for approval; e.g. from Windows Task Scheduler), or
- `python main.py watch "D:\Attendance\Drop"`: every new .xlsx/.csv saved in that folder is processed and moved to `processed\` (or `failed\` with a note). `--once` checks once and exits, for Task Scheduler.

## Who gets what (routing)

Per employee in the master:

1. **Team detail** goes to the **Sub split ID** email; if blank, to the **HOD email**; if there is no HOD, to the **Director** (Director Office staff).
2. **Department summary**: every HOD gets a summary of everyone under them, by team (e.g. Arun Mishra: 511 employees, as a summary, not a list).
3. **One email per recipient per day.** A team lead who is also an HOD gets one combined email (team detail + department summary).
4. Records flagged `HOD_EMAIL_CONFLICT` (or with an invalid/ambiguous address) are **held for HR**, never sent to an assumed person. Clear the flag on the Employees screen once HR confirms the address.
5. Attendance codes not in the employee master go to the **HR exception email**. No manager is guessed.
6. The Reporting Manager name is informational only; the Sub split ID email decides who receives mail.

With today's workbook: 29 people (25 team leads + HODs) + Director + HR exception email = 31 emails; HR's only goes out on days with something to fix.

## The emails

- **Subject:** `Daily Attendance | 13-Nov-2026 | <recipient> | 2 absent · 3 late · 1 missing punch` (the most useful counts; "all present" when nobody needs attention, "N record(s) to fix" for HR)
- **Body:** counts first (total, present, absent, leave, on duty, WFH, late, missing punch), then **only the employees needing attention** (absent, late, missing punch, left early, no attendance record). HODs also get the department summary by team; the Director the company summary by HOD.
- **Attachments:** that recipient's full list (.xlsx, people needing attention first; HODs also get the department summary and roster) and an interactive HTML dashboard of the same people.
- **Privacy:** each email has exactly one recipient in To and contains only that recipient's people. HOD CC on team emails is off unless HR approves it (Settings).
- **Manual or Auto, per upload:** *Manual* (default, preview mode) prepares the emails and they wait on **Approve emails** until someone approves; *Auto* sends them as soon as the files are processed. The Upload page asks every time; the default is set in Settings (preview mode).
- **Safety:** each recipient is sent at most once per day (re-uploading a day prepares the emails again but sends nothing new; an admin can deliberately **Resend**). Failed deliveries are retried (3 attempts by default) and can be approved again. Addresses are validated; a missing Director/HR address holds that email. Every send is in the Email log.
- **Email is sent only through the Gmail API**, from one central sender mailbox. Secrets live only in the `.env` file: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` and `GMAIL_REFRESH_TOKEN` (written by `main.py gmail-auth`, see below).

## Connect Gmail (once)

APIS sends through the **Gmail API** from one central sender mailbox. Every day HR uploads **yesterday's** attendance and the emails go to the team leads / HODs.

1. In Google Cloud Console (project `apis-attendance-mis`) → APIs & Services:
   - enable the **Gmail API**;
   - Credentials → the OAuth client → **Authorized redirect URIs**: add `http://localhost:8765/oauth2callback`;
   - OAuth consent screen: user type **Internal** (Google Workspace), or publish it *In production*. In *Testing* mode Google expires the refresh token after 7 days.
2. `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` are in the local `.env` (git-ignored). Or pass the downloaded JSON: `--client-json client_secret.json`.
3. Run `.\.venv\Scripts\python.exe main.py gmail-auth --login-hint attendance@apisindia.com` and sign in **as the sender mailbox**; allow "Send email on your behalf" (scope `gmail.send` only: the app cannot read mail).
4. The refresh token is written to `.env` (never shown), and that mailbox becomes the sender in Settings. Restart the app, send a test email from Settings, then switch Email to *live*.

**Test before going live:** Settings → Testing → "Send every email only to" (e.g. your own address). Every email (team leads, HODs, Director, HR) then goes only there, subject `[TEST] …` with a red banner naming the real recipient. Test sends do not count as "already sent", so after clearing the field the real managers still get the day's email. The same goes for Email = *test*: emails only saved to the outbox do not count once Email is switched to *live* - approve them again (or let the daily job run) and they are delivered.

Gmail sends as the signed-in mailbox, so the sender in Settings must be that mailbox (or one of its verified "Send mail as" aliases).

## How a day is counted (change in Settings)

| Pocket HRMS shows | Counted as |
|---|---|
| In and out punch | Present |
| First punch up to 11:00 (office opens 09:30) | On time |
| First punch after 11:00 | Late, minutes counted from 11:00 (11:20 = late 20 min) |
| Out − in under 8 h (8 h are mandatory for everyone, counted from their own punch-in) | Short hours |
| Left before 19:30 **and** under 8 h | Left early (minutes short of 8 h) |
| One punch only | Missing punch (counted present, listed for regularisation) |
| Type = LD / OD | On duty (counts as present) |
| Type = WFH, or Remarks say "wfh" / "work from home" | Work from home (counts as present; the remark text is not stored) |
| Type = A / P | Pocket HRMS's own verdict - the app decides from the punches and shift (rows below) |
| Type = WO | Week off (left out of attendance %) |
| "Invalid" in / out time | Missing punch (a lone out-punch is not counted as a late arrival) |
| Type = PL, SL, CL… | Leave (Half day if the Day column says half) |
| No punch, shift assigned | Absent |
| No punch, "Shift Not Assigned" | Not tracked (mostly field Sales, who don't punch in Pocket HRMS; left out of attendance %) |
| Permission Report: **Approved** short leave | Late arrival / early leaving inside the permission window (±15 min) is excused |
| Permission Report: **Pending** | Nothing excused; shown as “permission pending HH:MM-HH:MM” next to the person |
| Permission Report: Rejected / cancelled | Ignored |
| Directors HO0034, HO0077, HO0098 (Settings → "Always counted as present") | Always present: never absent, late, left early or missing punch (a recorded leave still shows) |
| Codes test, DUMMY, CAND-, A001 | Skipped |

Attendance % = (present + on duty + WFH + missing punch + half of half-days) ÷ tracked employees (everyone except not tracked and week off).

## Employee master

- **Import = add and update only.** New codes are added, changed details updated; nobody is removed. `Employee_Status` = Inactive/Left marks the employee Left. Employees marked Left stay Left. Bad values are dropped and listed; the rest of the row is kept. `NA`, `-` and similar mean blank. One spelling per HOD (`AMIT ANAND` = `Amit Anand`).
- **Delete = Mark as Left** with the last working day. From the next day they are left out of attendance and emails; history stays; they can be restored.
- **Team** = the part of the team lead's email before `@`; blank means *Direct to HOD*.
- Every change (add, edit, Left, restore, import) is kept with old and new values.
- **Export Excel** gives the import columns, so HR can edit and re-import.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend test
```

## Security notes

- No login page is allowed only on `127.0.0.1` and never in production; set `AUTH_MODE=local` to serve other PCs. **The application has one user** (HR) who does everything: `main.py create-user --username hr.admin`. Team leads, HODs and the Director never log in - they only receive their emails.
- Mail secrets live only in the `.env` file, never in the app or database.
- Uploaded files, reports and the email outbox stay under `storage/` and are not committed to git.
- The free-text Remarks (Attendance Summary) and Reason (Permission Report) are not stored.
- Email previews and dashboard attachments are served sandboxed (no scripts in previews; dashboards cannot reach the network).

The earlier PRD-scale system (14-phase MIS platform) is preserved at git tag `v0.5.0-full`.
