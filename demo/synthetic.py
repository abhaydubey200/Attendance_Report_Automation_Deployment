"""SYNTHETIC test/demo data. Not real APIS data, and the column names are invented
for testing only -- real schemas must come from inspected Bizom / Pocket HRMS files.

`build_dataset_files(day)` returns {dataset_id: (filename, bytes)} and `SCHEMAS`
holds a matching column mapping per dataset.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from ingestion.schema_definition import SchemaDefinition

DEPARTMENTS = [("SALES", "Sales (synthetic)"), ("FIN", "Finance (synthetic)"), ("OPS", "Operations (synthetic)")]

# code, name, dept, location, joining
EMPLOYEES = [
    ("TEST-0001", "Asha Test", "SALES", "LOC1", "2020-01-01"),
    ("TEST-0002", "Bharat Test", "SALES", "LOC1", "2021-03-15"),
    ("TEST-0003", "Chitra Test", "SALES", "LOC2", "2019-07-01"),
    ("TEST-0004", "Dev Test", "FIN", "LOC1", "2022-02-01"),
    ("TEST-0005", "Esha Test", "FIN", "LOC1", "2018-11-20"),
    ("TEST-0006", "Farhan Test", "OPS", "LOC2", "2023-05-01"),
    ("TEST-0007", "Gita Test", "OPS", "LOC2", "2020-09-09"),
    ("TEST-0008", "Hari Test", "OPS", "LOC1", "2017-04-04"),
]

SCHEMAS: dict[str, SchemaDefinition] = {
    "DEPARTMENT_MASTER": SchemaDefinition(columns={"Dept Code": "department_code", "Dept Name": "department_name"},
                                          primary_key=["department_code"]),
    "HRMS_EMPLOYEE_MASTER": SchemaDefinition(
        columns={"Emp Code": "employee_code", "Emp Name": "employee_name", "Dept": "department_code",
                 "Location": "location_code", "DOJ": "joining_date", "DOE": "exit_date"},
        primary_key=["employee_code"], date_formats=["%d-%m-%Y"]),
    "HOLIDAY_CALENDAR": SchemaDefinition(columns={"Date": "holiday_date", "Holiday": "holiday_name"},
                                         primary_key=["holiday_date"], date_formats=["%d-%m-%Y"]),
    "HRMS_ATTENDANCE": SchemaDefinition(
        columns={"Emp Code": "source_employee_id", "Date": "attendance_date", "Status": "source_status",
                 "In": "first_in_time", "Out": "last_out_time"},
        primary_key=["source_employee_id", "attendance_date"], date_formats=["%d-%m-%Y"],
        value_maps={"source_status": {"Present": "PRESENT", "Absent": "ABSENT", "WFH": "WORK_FROM_HOME",
                                      "Half Day": "HALF_DAY"}}),
    "BIZOM_ATTENDANCE": SchemaDefinition(
        columns={"User Id": "source_employee_id", "User Name": "source_employee_name", "Day": "attendance_date",
                 "Att": "source_status", "Check In": "first_in"},
        primary_key=["source_employee_id", "attendance_date"], date_formats=["%Y-%m-%d"],
        datetime_formats=["%Y-%m-%d %H:%M"], value_maps={"source_status": {"P": "PRESENT", "A": "ABSENT"}}),
    "HRMS_LEAVE": SchemaDefinition(
        columns={"Emp Code": "source_employee_id", "From": "from_date", "To": "to_date", "Type": "leave_type",
                 "Status": "approval_status"},
        date_formats=["%d-%m-%Y"],
        value_maps={"approval_status": {"Approved": "APPROVED", "Pending": "PENDING", "Rejected": "REJECTED",
                                        "Cancelled": "CANCELLED"}}),
    "HRMS_PUNCH": SchemaDefinition(
        columns={"Emp Code": "source_employee_id", "Punch": "punch_time", "Mode": "direction"},
        datetime_formats=["%d-%m-%Y %H:%M"], value_maps={"direction": {"IN": "IN", "OUT": "OUT"}}),
}

SOURCE_OF = {"DEPARTMENT_MASTER": "HR", "HRMS_EMPLOYEE_MASTER": "POCKET_HRMS", "HOLIDAY_CALENDAR": "HR",
             "HRMS_ATTENDANCE": "POCKET_HRMS", "BIZOM_ATTENDANCE": "BIZOM", "HRMS_LEAVE": "POCKET_HRMS",
             "HRMS_PUNCH": "POCKET_HRMS"}


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def build_dataset_files(day: date, variant: int = 0) -> dict[str, tuple[str, bytes]]:
    """A realistic mix for `day`: matches, a conflict, Bizom-only, leave, missing punch."""
    files = {
        "DEPARTMENT_MASTER": ("departments.csv", _csv(["Dept Code", "Dept Name"], [list(d) for d in DEPARTMENTS])),
        "HRMS_EMPLOYEE_MASTER": ("employees.csv", _csv(
            ["Emp Code", "Emp Name", "Dept", "Location", "DOJ", "DOE"],
            [[c, n, d, l, dmy(date.fromisoformat(j)), ""] for c, n, d, l, j in EMPLOYEES])),
        "HOLIDAY_CALENDAR": ("holidays.csv", _csv(["Date", "Holiday"], [["26-01-2027", "Republic Day (synthetic)"]])),
    }
    hrms = [
        ["TEST-0001", dmy(day), "Present", "09:05", "18:10"],
        ["TEST-0002", dmy(day), "Absent", "", ""],
        ["TEST-0004", dmy(day), "WFH", "", ""],
        ["TEST-0006", dmy(day), "Half Day", "09:30", "13:30"],
        ["TEST-0007", dmy(day), "Present" if variant == 0 else "Absent", "09:00", "18:00"],
        ["TEST-0008", dmy(day), "Present", "08:55", "17:45"],
    ]
    files["HRMS_ATTENDANCE"] = ("hrms_attendance.csv", _csv(["Emp Code", "Date", "Status", "In", "Out"], hrms))
    iso = day.isoformat()
    bizom = [
        ["BZ-01", "Asha Test", iso, "P", f"{iso} 09:02"],
        ["BZ-02", "Bharat Test", iso, "P", f"{iso} 10:15"],     # conflicts with HRMS Absent
        ["BZ-03", "Chitra Test", iso, "P", f"{iso} 09:40"],     # Bizom only
        ["BZ-99", "Unknown Person", iso, "P", f"{iso} 09:00"],  # never mapped
    ]
    files["BIZOM_ATTENDANCE"] = ("bizom.csv", _csv(["User Id", "User Name", "Day", "Att", "Check In"], bizom))
    files["HRMS_LEAVE"] = ("leave.csv", _csv(["Emp Code", "From", "To", "Type", "Status"], [
        ["TEST-0003", dmy(day), dmy(day), "CL", "Approved"],
        ["TEST-0005", dmy(day), dmy(day), "SL", "Pending"],
    ]))
    files["HRMS_PUNCH"] = ("punch.csv", _csv(["Emp Code", "Punch", "Mode"], [
        ["TEST-0001", f"{dmy(day)} 09:05", "IN"], ["TEST-0001", f"{dmy(day)} 18:10", "OUT"],
        ["TEST-0008", f"{dmy(day)} 08:55", "IN"],
    ]))
    return files


MASTER_ORDER = ["DEPARTMENT_MASTER", "HRMS_EMPLOYEE_MASTER", "HOLIDAY_CALENDAR"]
DAILY_ORDER = ["HRMS_ATTENDANCE", "BIZOM_ATTENDANCE", "HRMS_LEAVE", "HRMS_PUNCH"]
