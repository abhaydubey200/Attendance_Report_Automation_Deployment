# APIS Daily Attendance

A small automation tool for APIS India Limited:

**Upload one day's Pocket HRMS "Attendance Summary" export → see the insights → each team's manager (and HR/Directors) automatically receive an email with the highlights, an Excel report and an interactive HTML dashboard.**

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

The app opens with no login page (this PC only). Four screens:

| Screen | What it does |
|---|---|
| **Upload** | Drop the Attendance Summary file. It is analysed and the report emails go out automatically. |
| **Insights** | KPIs, highlights, charts, team comparison, trend across days, searchable employee list; download the Excel or HTML dashboard; preview or resend the emails. |
| **Emails** | Every email sent, to whom, and whether it was delivered. |
| **Settings** | Who gets which report, how attendance is counted, email server. |

First time: open **Settings**, add the managers (one per team, plus HR/Directors under "All employees"), and switch Email from *test* to *live* once the SMTP details are in. In test mode emails are saved to `storage/outbox/` instead of being sent.

**Try it with synthetic data:** `python main.py demo` then `python main.py serve --demo --port 8010`.

**Automate the upload** (e.g. Windows Task Scheduler after the HRMS export is saved): `python main.py upload "C:\path\AttendanceSummary.xlsx"`.

## How a day is counted (change in Settings)

| Pocket HRMS shows | Counted as |
|---|---|
| In and out punch | Present (late if first punch after 09:30; left early if last punch before 18:00) |
| One punch only | Missing punch (counted present, listed for regularisation) |
| Type = LD | On duty (counts as present) |
| Type = PL, SL, CL… | Leave (Half day if the Day column says half) |
| No punch, shift assigned | Absent |
| No punch, "Shift Not Assigned" | Not tracked (mostly field Sales; left out of attendance %) |
| Codes test, DUMMY, CAND-, A001 | Skipped (test records) |

Attendance % = (present + on duty + missing punch + half of half-days) ÷ tracked employees.

## What managers receive

- **Email:** KPI tiles, highlights in plain words, a team table (full-company email only), and the attachments.
- **Excel:** Summary (figures + highlights + counting notes), All Employees, Absent, Late Arrivals, Left Early, Missing Punch, Leave & On Duty, Short Hours, Not Tracked.
- **HTML dashboard:** a single self-contained file that opens in any browser: KPIs, highlights, status/arrival/team charts, and a searchable, filterable, sortable employee table.

Each team manager gets only their team's data; "All employees" recipients get everything.

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
