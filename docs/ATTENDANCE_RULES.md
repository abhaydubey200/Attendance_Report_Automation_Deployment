# Attendance Rules

**Status: NOT APPROVED. Rule version `0.0.0-draft`.**

The engine (Phase 5) will read `config/attendance_rules.yaml` and `config/source_authority.yaml`.
Every value below is `null` until HR decides. A calculation that depends on a null rule is reported as PROVISIONAL or UNRESOLVED.

## Decisions required from HR

| # | Question | Config key | Decision | Approved by / date |
|---|---|---|---|---|
| 1 | Authoritative source for office attendance | `source_authority.domains.OFFICE_ATTENDANCE` | pending | |
| 2 | Authoritative source for field attendance | `…FIELD_ATTENDANCE` (proposed: Bizom) | pending | |
| 3 | Authoritative source for employee master | `…EMPLOYEE_MASTER` (proposed: Pocket HRMS) | pending | |
| 4 | Authoritative source for approved leave | `…APPROVED_LEAVE` (proposed: Pocket HRMS) | pending | |
| 5 | Half-day value | `calculation.half_day_equivalent` | pending | |
| 6 | Is WFH counted as present? | `calculation.wfh_counts_as_present` | pending | |
| 7 | Approved leave in the denominator? | `calculation.approved_leave_in_denominator` | pending | |
| 8 | Weekly offs excluded? | `calculation.include_weekly_off_in_denominator` | pending | |
| 9 | Holidays excluded? | `calculation.include_holidays_in_denominator` | pending | |
| 10 | Contractor treatment | `calculation.contractor_treatment` | pending | |
| 11 | New joiner treatment | `calculation.new_joiner_treatment` | pending | |
| 12 | Exit treatment | `calculation.exit_treatment` | pending | |
| 13 | Overnight shifts | `calculation.overnight_shift_policy` | pending | |
| 14 | D-1 = previous calendar day or previous working day? | `calculation.reporting_period_d_minus_1` | pending | |
| 15 | Who receives HOD reports? | `recipients.yaml` | pending | |
| 16 | What employee details can Directors see? | `security.yaml` (DIRECTOR role) | default: aggregates only | |
| 17 | Exception approval workflow | Phase 6 | pending | |

## Additional rule settings added in v0.4.0

| Setting | Meaning | Value |
|---|---|---|
| `calculation.weekly_off_days` | Which weekdays are weekly offs (work schedule) | pending |
| `calculation.no_record_status` | Status for an eligible employee with no record at all (e.g. ABSENT) | pending |
| `calculation.time_conflict_tolerance_minutes` | First-in difference between Bizom and Pocket HRMS that counts as a time conflict | pending |

## Provisional classification order (mechanism, not policy)

The engine (`data_engine/attendance_processor.py`) applies this order. HR should confirm or change it:

1. An approved exception adjustment.
2. Approved leave: full day -> APPROVED_LEAVE, half day -> HALF_DAY. Pending or unknown leave never counts as approved.
3. Holiday or weekly off, unless a source reports work that day.
4. Source statuses: agreeing sources -> that status. Conflict -> the approved authority (`OFFICE_ATTENDANCE`) decides; with none approved -> UNRESOLVED.
5. Pending leave -> PENDING_APPROVAL.
6. Incomplete punch sequence -> MISSING_PUNCH. Complete punches without a status -> UNRESOLVED.
7. No record -> `no_record_status`, else UNRESOLVED.

Eligibility uses only the objective employment window (joined on or before the date, not exited before it). Attendance % and absenteeism % stay blank until every rule they use is approved.

## Pocket HRMS AttendanceSummary labels (edit in Dataset Registry -> value map for source_status)

| Label | Seeded proposal | Needs HR |
|---|---|---|
| PUNCH_IN_OUT | PRESENT | Confirm |
| PUNCH_SINGLE | MISSING_PUNCH | Confirm |
| LEAVE:PL, LEAVE:SL | APPROVED_LEAVE | Confirm that a Type code means approved leave |
| LEAVE:LD | unmapped (UNRESOLVED) | What is LD? |
| NO_PUNCH | unmapped (UNRESOLVED) | Absent? |
| NO_PUNCH_NO_SHIFT | unmapped (UNRESOLVED) | Absent, or field staff not tracked by punches? (most Sales staff) |
| Test codes (A001, test, SL0DUMMY, CAND-...) | not excluded | Exclude? (Dataset Registry -> exclusion list) |

## Change procedure

1. HR records the decision in writing.
2. Update the YAML value, bump `rule_version`, and set `approved_by` and `approved_on`.
3. Add a regression test case for the decision.
4. Earlier processing results keep their original rule version (PRD 22).
