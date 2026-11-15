# APIS Daily Attendance

A small automation tool for APIS India Limited:

**Upload one day's attendance (Pocket HRMS "Attendance Summary" + Bizom attendance report) → see the insights → each HOD (for their own people) and HR/Directors (whole company) automatically receive an email with the highlights, an Excel report and an interactive HTML dashboard.**

Three datasets, joined on **EMP_CODE**:

| Dataset | What it gives |
|---|---|
| Pocket HRMS Attendance Summary (daily) | Biometric punches, shift, leave |
| Bizom attendance report (daily) | Field sales status: P, A, WO (week off), leave codes |
| Employee master (HR's Employee Amendment Excel, kept on the Employees screen) | Department, HOD, team, reporting manager, HOD email |

HR keeps the **employee master** (HOD → Team → Reporting manager → Employee) on the Employees screen: import HR's Excel, add, edit, mark as Left and restore employees.

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

The app opens with no login page (this PC only). Seven screens:

| Screen | What it does |
|---|---|
| **Upload** | Drop the Pocket HRMS and Bizom files of the day (together or one after the other; the type is recognised automatically). Once both are in, the report emails go out automatically. |
| **Insights** | KPIs, highlights, charts, team comparison, trend across days, searchable employee list; download the Excel or HTML dashboard; preview or resend the emails. |
| **Emails** | Every email sent, to whom, and whether it was delivered. |
| **Attendance report** | Any date range, filtered by HOD, department, team, reporting manager, category, status or source; by employee or day by day; Excel download; the page link carries the filters, so it can be shared. |
| **Employee report** | One employee's attendance day by day over a date range (status strip, totals, in/out, source), with Excel download. |
| **Employees** | The employee master: search and filter by HOD, department, team, reporting manager and status; HOD cards and teams; add, edit, mark as Left / restore; change history; import and export Excel. |
| **Settings** | HR/Director recipients, how attendance is counted, email server. |

First time:
1. **Employees → Import Excel** with HR's Employee Amendment file (columns `EMPLOYEE CODE, Employee Name, Department, DOJ, HOD, Email ID - HOD, Sub split ID, Reporting Manager`; the header row is found automatically).
2. **Settings**: add HR and Directors under "All employees", and switch Email from *test* to *live* once the SMTP details are in. In test mode emails are saved to `storage/outbox/` instead of being sent.

**Try it with synthetic data:** `python main.py demo` then `python main.py serve --demo --port 8010`.

**Automate the upload** (e.g. Windows Task Scheduler after the exports are saved): `python main.py upload "C:\path\AttendanceSummary.xlsx" "C:\path\Bizom.csv"`.

## How a day is counted (change in Settings)

| Pocket HRMS shows | Counted as |
|---|---|
| In and out punch | Present (late if first punch after 09:30; left early if last punch before 18:00) |
| One punch only | Missing punch (counted present, listed for regularisation) |
| Type = LD | On duty (counts as present) |
| Type = PL, SL, CL… | Leave (Half day if the Day column says half) |
| No punch, shift assigned | Absent |
| No punch, "Shift Not Assigned" | Not tracked (mostly field Sales; left out of attendance %) |
| No punch, Bizom says P | Present (source: Bizom) |
| No punch, Bizom says A | Absent |
| Bizom says WO | Week off (left out of attendance %) |
| Bizom PL / SL / CL… | Leave |
| HRMS leave but Bizom P | Present ("present in either source counts") |
| Only in Bizom | Reported if in the employee master or an AP promoter code (Settings → "Bizom-only users to include") |
| Codes test, DUMMY, CAND-, A001, Vacant_…, Bizom rows without Employee_Id | Skipped |

Attendance % = (present + on duty + missing punch + half of half-days) ÷ tracked employees (everyone except not tracked and week off).

By default the emails wait until **both** files of the day are uploaded (Settings → Email); "Send emails" on Insights sends at any time. Each row records its source (Pocket HRMS, Bizom, or both). The Bizom IMEI column is never read or stored.

## Employee master

- **Matching:** attendance rows are linked to the master by employee code (SL…, HO…, RK…). Name, department, HOD, team and reporting manager on reports come from the master.
- **Team** = the part of the team lead's email ("Sub split ID") before `@`; blank means *Direct to HOD*.
- **Import = add and update only.** New codes are added, changed details updated; nobody is removed. Employees marked Left stay Left. Bad values (e.g. an invalid email) are dropped and listed; the rest of the row is kept. `NA`, `-` and similar mean blank. One spelling per HOD (`AMIT ANAND` = `Amit Anand`).
- **Delete = Mark as Left** with the last working day. From the next day they are left out of attendance and reports; their history stays and they can be restored.
- Every change (add, edit, Left, restore, import) is kept with old and new values (Change history in the employee panel).
- **Export Excel** gives the same columns as the import file, so HR can edit it and import it back.
- Insights warns when the attendance file has employees missing from the master (their HOD will not get them until added).

## What people receive

- **Email:** KPI tiles, highlights in plain words, a table by department (by team for an HOD with one department), and the attachments.
- **Excel:** Summary (figures + highlights + department table + counting notes), All Employees, Absent, Late Arrivals, Left Early, Missing Punch, Leave & On Duty, Short Hours, Not Tracked; every list shows Department, HOD, Team and Reporting manager.
- **HTML dashboard:** a single self-contained file that opens in any browser: KPIs, highlights, status/arrival/department charts, and a searchable, filterable, sortable employee table.

Each HOD gets only their own people (HOD email from the employee master; can be switched off in Settings). "All employees" recipients get everything. A Pocket HRMS category (Sales, Plant…) gets a report only if someone is added for it in Settings.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend test
```

## Security notes

- No login page is allowed only on `127.0.0.1` and never in production; set `AUTH_MODE=local` to serve other PCs (users via `main.py create-user --role ADMIN|HR|VIEWER`).
- The SMTP password lives only in the `.env` file (`SMTP_PASSWORD`), never in the app or database.
- Uploaded files, reports and the email outbox stay under `storage/` and are not committed to git.
- The Remarks column of the HRMS export (free text) is not stored.

The earlier PRD-scale system (14-phase MIS platform) is preserved at git tag `v0.5.0-full`.
