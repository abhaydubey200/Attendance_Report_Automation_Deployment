"""Schema and content validation (PRD 5.5, Phase 3).

Produces structured errors/warnings and, for valid rows, typed values ready for the
adapters. A file can only enter processing when its status is not REJECTED and the
user has confirmed it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum

from core.timeutils import IST
from ingestion.file_reader import Table
from ingestion.schema_definition import DATASET_KIND, PERIOD_FIELD, TARGET_FIELDS, VALUE_MAP_TARGETS, SchemaDefinition

MAX_STORED_ISSUES = 5000


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    REJECTED = "REJECTED"


@dataclass
class Issue:
    code: str
    severity: Severity
    message: str
    row_number: int | None = None
    column_name: str | None = None

    def as_dict(self) -> dict:
        return {"row_number": self.row_number, "column_name": self.column_name, "code": self.code,
                "severity": self.severity.value, "message": self.message}


@dataclass
class TypedRow:
    row_number: int
    values: dict[str, object]


@dataclass
class ValidationResult:
    status: ValidationStatus
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    empty_rows: int = 0
    warning_count: int = 0
    issues: list[Issue] = field(default_factory=list)
    typed_rows: list[TypedRow] = field(default_factory=list)
    invalid_row_numbers: set[int] = field(default_factory=set)

    def summary(self) -> dict:
        return {
            "status": self.status.value,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_rows": self.duplicate_rows,
            "empty_rows": self.empty_rows,
            "warning_count": self.warning_count,
            "error_count": sum(1 for i in self.issues if i.severity is Severity.ERROR),
            "issues_by_code": dict(Counter(i.code for i in self.issues)),
        }


def _parse(value: str, kind: str, schema: SchemaDefinition):
    formats = {"date": schema.date_formats, "datetime": schema.datetime_formats, "time": schema.time_formats}[kind]
    # Excel cells arrive as ISO strings from the reader; accept those as well.
    extra = {"date": ["%Y-%m-%d"], "datetime": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"], "time": ["%H:%M:%S"]}[kind]
    for fmt in [*formats, *extra]:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if kind == "date":
            return parsed.date()
        if kind == "time":
            return parsed.time()
        return parsed.replace(tzinfo=IST)     # source timestamps are IST wall-clock times
    raise ValueError(value)


def _map_value(field_name: str, raw: str, schema: SchemaDefinition) -> str | None:
    mapping = schema.value_maps.get(field_name)
    key = raw.strip()
    if mapping:
        lowered = {k.strip().lower(): v for k, v in mapping.items()}
        return lowered.get(key.lower())
    upper = key.upper().replace(" ", "_")
    return upper if upper in VALUE_MAP_TARGETS[field_name] else None


def validate_table(
    table: Table,
    dataset_id: str,
    schema: SchemaDefinition,
    reporting_date: date,
    daily: bool,
) -> ValidationResult:
    kind = DATASET_KIND[dataset_id]
    fields = TARGET_FIELDS[kind]
    issues: list[Issue] = []
    result = ValidationResult(status=ValidationStatus.VALID)

    # ---- schema level
    missing = [src for src in schema.columns if src not in table.columns]
    for src in missing:
        issues.append(Issue("MISSING_COLUMN", Severity.ERROR, f"Mapped column '{src}' is not in the file.", column_name=src))
    for col in table.columns:
        if col not in schema.columns:
            issues.append(Issue("UNEXPECTED_COLUMN", Severity.WARNING,
                                f"Column '{col}' is not in the approved schema and will be ignored.", column_name=col))
    if not table.rows:
        issues.append(Issue("EMPTY_FILE", Severity.ERROR, "The file has a header but no data rows."))
    if any(i.severity is Severity.ERROR for i in issues):
        result.status = ValidationStatus.REJECTED
        result.issues = issues
        result.total_rows = len(table.rows)
        result.warning_count = sum(1 for i in issues if i.severity is Severity.WARNING)
        return result

    period_field = PERIOD_FIELD.get(kind) if (daily and schema.check_reporting_period) else None
    seen_rows: set[tuple] = set()
    seen_keys: dict[tuple, int] = {}

    for raw, row_number in zip(table.rows, table.row_numbers):
        mapped = {target: raw.get(source, "").strip() for source, target in schema.columns.items()}
        if not any(raw.values()) or all(not v.strip() for v in raw.values()):
            result.empty_rows += 1
            continue
        result.total_rows += 1

        fingerprint = tuple(raw.get(c, "") for c in table.columns)
        if fingerprint in seen_rows:
            result.duplicate_rows += 1
            issues.append(Issue("DUPLICATE_ROW", Severity.WARNING, "Exact duplicate of an earlier row; ignored.", row_number))
            continue
        seen_rows.add(fingerprint)

        row_errors: list[Issue] = []
        typed: dict[str, object] = {}
        for target, raw_value in mapped.items():
            ftype, required = fields[target]
            if not raw_value:
                typed[target] = None
                if required:
                    row_errors.append(Issue("MISSING_VALUE", Severity.ERROR, f"'{target}' is required.", row_number,
                                            schema.target_to_source[target]))
                continue
            if ftype == "str":
                typed[target] = raw_value
                continue
            try:
                typed[target] = _parse(raw_value, ftype, schema)
            except ValueError:
                code = {"date": "INVALID_DATE", "datetime": "INVALID_DATETIME", "time": "INVALID_TIME"}[ftype]
                row_errors.append(Issue(code, Severity.ERROR, f"'{raw_value}' is not a valid {ftype} for '{target}'.",
                                        row_number, schema.target_to_source[target]))

        for value_field in VALUE_MAP_TARGETS:
            raw_value = typed.get(value_field)
            if isinstance(raw_value, str) and raw_value:
                mapped_value = _map_value(value_field, raw_value, schema)
                typed[f"{value_field}_mapped"] = mapped_value
                if mapped_value is None:
                    issues.append(Issue("UNMAPPED_VALUE", Severity.WARNING,
                                        f"Value '{raw_value}' for '{value_field}' has no mapping; it will be treated as unresolved.",
                                        row_number, schema.target_to_source.get(value_field)))

        # Composite fields: a time column combined with the record date.
        if kind == "ATTENDANCE":
            for t_field, dt_field in (("first_in_time", "first_in"), ("last_out_time", "last_out")):
                if isinstance(typed.get(t_field), time) and typed.get(dt_field) is None and isinstance(typed.get("attendance_date"), date):
                    typed[dt_field] = datetime.combine(typed["attendance_date"], typed[t_field], tzinfo=IST)
        if kind == "PUNCH" and typed.get("punch_time") is None:
            if isinstance(typed.get("punch_date"), date) and isinstance(typed.get("punch_clock"), time):
                typed["punch_time"] = datetime.combine(typed["punch_date"], typed["punch_clock"], tzinfo=IST)
            elif not row_errors:
                row_errors.append(Issue("MISSING_VALUE", Severity.ERROR, "Punch time is required.", row_number))
        if kind == "LEAVE" and typed.get("leave_date") is None:
            start, end = typed.get("from_date"), typed.get("to_date")
            if not (isinstance(start, date) and isinstance(end, date)):
                if not row_errors:
                    row_errors.append(Issue("MISSING_VALUE", Severity.ERROR, "Leave date (or from/to dates) is required.", row_number))
            elif end < start:
                row_errors.append(Issue("INVALID_RANGE", Severity.ERROR, "Leave 'to' date is before 'from' date.", row_number))
            elif (end - start).days > 366:
                row_errors.append(Issue("INVALID_RANGE", Severity.ERROR, "Leave range is longer than one year.", row_number))
        if kind == "EMPLOYEE":
            j, x = typed.get("joining_date"), typed.get("exit_date")
            if isinstance(j, date) and isinstance(x, date) and x < j:
                row_errors.append(Issue("INVALID_RANGE", Severity.ERROR, "Exit date is before joining date.", row_number))

        # Reporting-period check for daily datasets.
        if period_field and not row_errors:
            row_date = typed.get(period_field)
            if row_date is None and kind == "PUNCH" and isinstance(typed.get("punch_time"), datetime):
                row_date = typed["punch_time"].date()
                if row_date != reporting_date:
                    issues.append(Issue("PERIOD_MISMATCH", Severity.WARNING,
                                        f"Punch on {row_date} differs from reporting date {reporting_date} (overnight shift?).", row_number))
                row_date = None
            if isinstance(row_date, date) and row_date != reporting_date:
                row_errors.append(Issue("PERIOD_MISMATCH", Severity.ERROR,
                                        f"Row date {row_date} differs from the reporting date {reporting_date}.", row_number,
                                        schema.target_to_source.get(period_field)))

        # Business-key duplicates.
        if schema.primary_key and not row_errors:
            key = tuple(typed.get(k) for k in schema.primary_key)
            if key in seen_keys:
                row_errors.append(Issue("DUPLICATE_KEY", Severity.ERROR,
                                        f"Business key {key} repeats row {seen_keys[key]}.", row_number))
            else:
                seen_keys[key] = row_number

        if row_errors:
            issues.extend(row_errors)
            result.invalid_rows += 1
            result.invalid_row_numbers.add(row_number)
        else:
            result.valid_rows += 1
            result.typed_rows.append(TypedRow(row_number, typed))

    if result.empty_rows:
        issues.append(Issue("EMPTY_ROW", Severity.WARNING, f"{result.empty_rows} empty row(s) skipped."))
    result.issues = issues
    result.warning_count = sum(1 for i in issues if i.severity is Severity.WARNING)
    if result.valid_rows == 0:
        result.status = ValidationStatus.REJECTED
    elif result.invalid_rows or result.warning_count:
        result.status = ValidationStatus.REQUIRES_REVIEW
    return result
