# Data Dictionary

**Pending discovery.** No sample files have been supplied yet. All 8 dataset categories in `config/datasets.yaml` have `schema_status: PENDING_DISCOVERY` and empty column lists. This is deliberate: source column names must not be guessed.

For each sample file, record here:

| Dataset | Column (as in file) | Type | Nullable | Example (synthetic) | Maps to contract field | Notes |
|---|---|---|---|---|---|---|

Then set `required_columns`, `primary_key_columns` and `date_column`, and switch `schema_status: DEFINED`.

## How schemas are defined (v0.4.0)

1. Dataset Registry -> choose the dataset -> **Define** -> upload a real sample file.
2. The app reads the file's own columns and sample values (nothing is assumed).
3. Map each column to an internal field (`ingestion/schema_definition.py` lists them per dataset), choose the business key, date formats, and value maps (e.g. source status `P` -> PRESENT).
4. Save. Each save is a new version; earlier uploads keep the version they used.

Synthetic schemas used by the demo and tests live in `demo/synthetic.py` and are **not** real column names.

## Pocket HRMS AttendanceSummary (dataset HRMS_ATTENDANCE_SUMMARY)

Learned from the first real sample (14-Nov-2026). Layout: 4 preamble rows (generator, address, title, Run Date), header row, then two rows per employee and date.

| File column | Meaning | Internal field |
|---|---|---|
| Code | Employee code (prefixes seen: SL, HO, RK, NA) | `source_employee_id` |
| Name | Employee name (spaces normalised) | `source_employee_name` |
| Category | Sales / Head Office / Plant / AONE; used as the reporting group | `category` |
| Date | dd/mm/yyyy | `attendance_date` |
| Shift Name | "General Shift" or "Shift Not Assigned" | `shift_name` |
| In-Out Time | HH:MM; first row = in, second row = out | paired into `first_in_time`, `last_out_time`, `punch_count` |
| Type | Leave or duty code (PL, SL, LD seen) | `leave_type` |
| Day | e.g. "Full Day" | `day_portion` |
| Remarks | Free text; **not stored** (data minimisation) | - |

Derived label (`source_status`), facts only: `LEAVE:<Type>` if Type is set; else `PUNCH_IN_OUT` (2+ times), `PUNCH_SINGLE` (1 time), `NO_PUNCH` (no time, shift assigned), `NO_PUNCH_NO_SHIFT` (no time, shift not assigned).
