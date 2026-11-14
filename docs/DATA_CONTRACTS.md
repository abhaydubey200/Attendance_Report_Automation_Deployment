# Data Contracts

Version **0.1.0-provisional** (`contracts/__init__.py`). Code in `contracts/`.

| Contract | Module | Required fields | Notes |
|---|---|---|---|
| `EmployeeRecord` | `employee.py` | `source_system`, `employee_code` | Exit date cannot precede joining date. Effective-dated |
| `AttendanceRecord` | `attendance.py` | `source_system`, `employee_code`, `attendance_date` | Keeps the raw `source_status`. `record_status` defaults to PROVISIONAL. Out-before-in is allowed (an engine concern) |
| `LeaveRecord` | `leave.py` | `source_system`, `employee_code`, `leave_date` | `approval_status` defaults to UNKNOWN. Only APPROVED counts as approved |
| `PunchEvent` | `punch.py` | `source_system`, `employee_code`, `punch_time` | Every punch is kept. The business date is assigned by shift policy |
| `DepartmentRecord`, `EmployeeOrgAssignment` | `department.py` | codes, `effective_from` | `applies_on(date)` for historical department lookup |

Common rules: models are immutable, unknown fields are rejected, timestamps must be timezone-aware, and every record carries `source_system`, `source_record_id` and `upload_id` for lineage.

Vocabularies: `AttendanceStatus` (10 PRD statuses), `ReconciliationCategory`, `LeaveApprovalStatus`, `UploadState`, `ProcessingState` (with transition tables).

Field sets are confirmed in Phase 4 against inspected sample files. Any change bumps `CONTRACT_VERSION`.
