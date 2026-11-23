"""Field Sales self-check: every upload is compared with Bizom's file by a separate reader; a difference holds the emails."""

from __future__ import annotations

import json
from datetime import date

from database.connection import session_scope
from database.models.sales import SalesEmployee, SalesEmployeeDay, SalesMailItem
from sales import mail, service, staff, verify
from tests.integration.test_sales_backfill import attendance
from tests.integration.test_sales_geo import PEOPLE, STAFF_HEAD


def _staff(s):
    staff.import_rows(s, [STAFF_HEAD] + [[c, n, "SO", "Z1", "Ravi", "ravi@example.com", "Hod One", "hod1@example.com", "Active"]
                                        for c, n in PEOPLE.items()], "tester", "test")


def test_clean_day_passes_and_a_wrong_row_holds_every_email(engine):
    with session_scope(engine) as s:
        _staff(s)
        up = service.process(s, [("Attendancereport.csv", attendance("2026-11-18", missing={"SL00005"}))], "tester", plan_mail=False)
        v = json.loads(up.summary)["verify"]
        assert v["checked"] == len(PEOPLE) and v["mismatch_count"] == 0
        assert all(i.status != mail.HELD or "self-check" not in (i.note or "") for i in mail.plan(s, up))
        # a stored row that no longer matches Bizom's file
        row = s.query(SalesEmployeeDay).filter_by(upload_id=up.upload_id, code="SL00001").one()
        row.status = "ABSENT"
        res = verify.check(date(2026, 11, 18), attendance("2026-11-18", missing={"SL00005"}),
                           list(s.query(SalesEmployeeDay).filter_by(upload_id=up.upload_id)),
                           {e.code: e for e in s.query(SalesEmployee)}, None)
        assert res["mismatch_count"] == 1 and "SL00001: stored ABSENT, Bizom says PRESENT" in res["mismatches"][0]
        summary = json.loads(up.summary)
        summary["verify"] = res
        up.summary = json.dumps(summary)
        for i in s.query(SalesMailItem).all():
            s.delete(i)
        items = mail.plan(s, up)
        assert items and all(i.status == mail.HELD and i.note.startswith("Held by the self-check") for i in items)


def test_reader_handles_bizom_time_formats():
    assert [verify._hhmm(x) for x in ("10:03:48", "9:7", "08:00 PM", "12:05 AM", "")] == ["10:03", "09:07", "20:00", "00:05", None]


def test_holiday_waits_for_hr_and_emails_follow_the_decision(engine):
    from sales import calendar
    day = "2026-10-20"
    with session_scope(engine) as s:
        _staff(s)
        few = attendance(day, missing=set(list(PEOPLE)[1:]))                 # 1 of 5 marked: looks like a holiday
        up = service.process(s, [("Attendancereport.csv", few)], "tester")
        assert json.loads(up.summary)["off_day_unconfirmed"] is True
        assert all(i.status == mail.HELD and "looks like a holiday" in i.note for i in mail.items_for(s, date(2026, 10, 20)))
        assert calendar.state(s)["waiting"][0]["date"] == day
        out = calendar.decide(s, date(2026, 10, 20), "holiday", "Diwali", "tester")
        assert out["off_day"] == "Holiday – Diwali" and not out["off_day_unconfirmed"] and calendar.state(s)["waiting"] == []
        items = mail.items_for(s, date(2026, 10, 20))
        assert items and all("looks like a holiday" not in (i.note or "") for i in items)
        out = calendar.decide(s, date(2026, 10, 20), "working", "", "tester")
        assert out["off_day"] is None and out["counts"]["ABSENT"] == len(PEOPLE) - 1


def test_staff_who_never_use_bizom_are_not_absent_and_listed_for_hr(engine):
    from datetime import timedelta

    from sales import staffcheck
    with session_scope(engine) as s:
        _staff(s)
        start = date(2026, 10, 1)
        d, n = start, 0
        while n < 22:                                                          # 22 working days; SL00005 never in Bizom
            if d.weekday() != 6:
                service.process(s, [("a.csv", attendance(d.isoformat(), missing={"SL00005"} | ({"SL00004"} if n >= 5 else set())))],
                                "tester", plan_mail=False, rescore=False)
                n += 1
            d += timedelta(days=1)
        res = staffcheck.reconcile(s)
        assert res["people"] == 1                                             # only SL00005 (SL00004 was seen on the first days)
        last = service.current_upload(s, d - timedelta(days=1))
        rows = {r.code: r.status for r in s.query(SalesEmployeeDay).filter_by(upload_id=last.upload_id)}
        assert "SL00005" not in rows and rows["SL00004"] == "ABSENT"
        issues = staffcheck.issues(s, last.report_date)
        assert [x["code"] for x in issues["never_in_bizom"]] == ["SL00005"] and [x["code"] for x in issues["possibly_left"]] == ["SL00004"]
        assert "last seen in Bizom on" in issues["possibly_left"][0]["proof"]
        # the next upload already leaves SL00005 out
        nxt = service.process(s, [("a.csv", attendance((d + timedelta(days=1)).isoformat(), missing={"SL00005"}))], "tester", plan_mail=False)
        assert json.loads(nxt.summary)["not_bizom_users"] == 1 and json.loads(nxt.summary)["verify"]["mismatch_count"] == 0
