"""Module 2 expense claim checks: reading the Bizom Claim report, every claim warning sign, the case list, the day map and
the API. Synthetic people, places and amounts only."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from database.connection import session_scope
from database.models.sales import SalesClaim
from sales import claims, geo, service
from sales.config import get_rules, save_rules
from tests.integration.test_sales_geo import BASE, H, PEOPLE, csv_bytes, day, off  # noqa: F401  (day = fixture)

HEAD = ["Employee_code", "User_Name", "Designation", "Claim_Date", "Claim Submit Date", "Claimdetail_Id", "Claim_Id", "Claim_Type",
        "Present_type", "Mode Of Travel", "From_Place", "To_Place", "Claim_Amount", "Level_1_Approved_Amount", "Level_2_Approved_Amount",
        "L2_Approval_status", "Claim_Approval_Status", "First_level_Approver", "Document", "Bill_Image 1", "Bill_Image 2",
        "Odometer Image of Start", "Odometer Image of End", "TC", "PC", "Total secondary Value", "Time_Spent_in_Market"]
N = [0]


def line(code, d, typ, amt, present="Retailing HQ", frm="", to="", tc="6", market="06:00:00", bill=""):
    N[0] += 1
    return [code, PEOPLE[code], "SO", d, d, str(1000 + N[0]), str(500 + N[0]), typ, present, "", frm, to, str(amt), str(amt), str(amt),
            "Pending", "Pending - 2nd Approval", "Ravi", "", bill, "", "", "", tc, "1" if tc else "", "1000" if tc else "", market]


def claims_csv() -> bytes:
    N[0] = 0
    ex = "EX–HQ"                                                                  # Bizom writes an en dash
    rows = [
        line("SL00005", "2026-11-10", "HQ-LOCAL TRAVEL", 100),                         # on leave that day
        line("SL00004", "2026-11-12", f"{ex} TRAVEL ALLOWANCE", 500, "Retailing EX-HQ", "Agra", "Mathura"),
        line("SL00004", "2026-11-12", f"{ex} TRAVEL ALLOWANCE", 500, "Retailing EX-HQ", "Agra", "Mathura"),    # same line twice
        line("SL00004", "2026-11-13", f"{ex} DEARNESS ALLOWANCE", 300, "Retailing EX-HQ"),
        line("SL00004", "2026-11-13", f"{ex} DEARNESS ALLOWANCE", 250, "Retailing EX-HQ"),                     # DA twice
        line("SL00002", "2026-11-14", "MISC CLAIM", 60, bill="https://bills.example.com/b1.jpg"),
        line("SL00003", "2026-11-15", "MISC CLAIM", 70, bill="https://bills.example.com/b1.jpg"),              # same bill photo
        line("SL00003", "2026-11-16", f"{ex} DEARNESS ALLOWANCE", 300, "Retailing HQ"),                       # outstation at HQ
        line("SL00001", D18, f"{ex} DEARNESS ALLOWANCE", 300, "Retailing EX-HQ"),                             # never left base
        line("SL00002", "2026-11-17", "HQ-LOCAL TRAVEL", 80, tc="", market=""),                               # no activity
        line("SL00002", "2026-11-16", "HQ-LOCAL TRAVEL", 80, tc="2", market="00:30:00"),                      # 30 min in market
        line("SL00005", "2026-11-12", "HQ-LOCAL TRAVEL", 2000),                                                # far above usual
        line("SL00005", "2026-11-13", "HQ-LOCAL TRAVEL", 90),
        line("SL00003", "2026-11-11", f"{ex} DEARNESS ALLOWANCE", 300, "Retailing EX-HQ"),                     # half day
        line("SL00004", "2026-11-14", "HQ-LOCAL TRAVEL", 90),
        line("SL00004", "2026-11-14", f"{ex} TRAVEL ALLOWANCE", 400, "Retailing EX-HQ", "Agra", "Etah"),     # local + outstation
        line("SL00005", "2026-11-14", "MOBILE & INTERNET ALLOWANCE", 300),                                     # monthly: never flagged
    ]
    return csv_bytes(HEAD, rows)


D18 = "2026-11-18"


def history_csv() -> bytes:
    head = ["Zone", "Reporting To", "User_ID", "User Name", "Emp Id", "Designation", "Phone Number", "Status", "Attendance Image",
            "Attendance Time", "EOD_Time", "For Date", "Attendance", "Present_Type", "IMEI", "Leave Details", "Location", "Variance_Kms"]
    rows = []
    for d in range(5, 18):
        for c, n in PEOPLE.items():
            at = {"SL00003": BASE, "SL00004": off(5, 5), "SL00005": off(-5)}.get(c, BASE)
            att, leave = "present", ""
            if (c, d) == ("SL00005", 10):
                att, leave = "absent", "Privilege Leave"
            if (c, d) == ("SL00003", 11):
                att = "halfday"
            rows.append(["Z1", "Ravi", "1", n, c, "SO", "", "Marked", "", "09:00:00", "18:00:00", f"2026-11-{d:02d}", att, "",
                         f"35{c[-1]}11122233344", leave, f"{at[0]},{at[1]}", "0"])
    return csv_bytes(head, rows)


@pytest.fixture
def loaded(day):
    with session_scope(day) as s:
        save_rules(s, get_rules(s).model_copy(update={"claim_high_min_peers": 3}), "tester")
        service.import_history(s, "AttendanceReport.csv", history_csv())
        res = service.import_claims(s, "APISCLAIMReport.csv", claims_csv(), "tester")
    return day, res


def signs(s, **where) -> list[set[str]]:
    return [set((c.flags or "").split(",")) - {""} for c in s.query(SalesClaim).filter_by(**where).order_by(SalesClaim.detail_id)]


def test_each_claim_sign(loaded):
    engine, res = loaded
    assert res["rows"] == 17 and res["added"] == 17 and res["from"] == "2026-11-10" and res["to"] == D18
    with session_scope(engine) as s:
        assert signs(s, code="SL00005", day=date(2026, 11, 10)) == [{"CLAIM_NO_ATTENDANCE"}]
        assert signs(s, code="SL00004", day=date(2026, 11, 12)) == [{"CLAIM_DUPLICATE"}, {"CLAIM_DUPLICATE"}]
        assert signs(s, code="SL00004", day=date(2026, 11, 13)) == [{"CLAIM_ALLOWANCE_TWICE"}] * 2
        assert {"CLAIM_IMAGE_REUSED"} in signs(s, code="SL00002", day=date(2026, 11, 14))
        assert {"CLAIM_IMAGE_REUSED"} in signs(s, code="SL00003", day=date(2026, 11, 15))
        assert signs(s, code="SL00003", day=date(2026, 11, 16)) == [{"CLAIM_EXHQ_AT_HQ"}]
        assert "CLAIM_EXHQ_AT_BASE" in signs(s, code="SL00001", day=date(2026, 11, 18))[0]
        assert signs(s, code="SL00002", day=date(2026, 11, 17)) == [{"CLAIM_NO_ACTIVITY"}]
        assert signs(s, code="SL00002", day=date(2026, 11, 16)) == [{"CLAIM_SHORT_MARKET"}]
        assert signs(s, code="SL00005", day=date(2026, 11, 12)) == [{"CLAIM_HIGH_AMOUNT"}]
        assert signs(s, code="SL00005", day=date(2026, 11, 13)) == [set()]
        assert signs(s, code="SL00003", day=date(2026, 11, 11)) == [{"CLAIM_HALF_DAY"}]
        assert {"CLAIM_LOCAL_AND_EXHQ"} in signs(s, code="SL00004", day=date(2026, 11, 14))
        assert signs(s, code="SL00005", day=date(2026, 11, 14)) == [set()]                     # mobile allowance
        c = s.query(SalesClaim).filter_by(code="SL00004", day=date(2026, 11, 12)).first()
        assert c.claim_type == "EX-HQ TRAVEL ALLOWANCE" and "Agra to Mathura" in json.loads(c.evidence)["CLAIM_DUPLICATE"]
        # importing the same file again updates, never duplicates
        assert service.import_claims(s, "again.csv", claims_csv(), "tester")["added"] == 0
        assert s.query(SalesClaim).count() == 17


def test_cases_map_overview_and_purge(loaded):
    engine, _ = loaded
    with session_scope(engine) as s:
        cs = geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None, kind="claims")
        assert {(c["code"], c["date"]) for c in cs} >= {("SL00005", "2026-11-10"), ("SL00004", "2026-11-12"), ("SL00001", D18)}
        leave_day = next(c for c in cs if c["date"] == "2026-11-10")
        assert leave_day["claim_signs"][0]["code"] == "CLAIM_NO_ATTENDANCE" and leave_day["claim_amount"] == 100
        both = next(c for c in geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None) if c["code"] == "SL00001" and c["date"] == D18)
        assert both["signs"] and both["claim_signs"]                                            # location and claim signs together
        m = geo.day_map(s, date(2026, 11, 12), "SL00004")                                       # history-only day still opens
        assert m is not None and len(m["claims"]) == 2 and m["calls"] == []
        ov = claims.overview(s, date(2026, 11, 1), date(2026, 11, 30), None)
        assert ov["lines"] == 17 and ov["flagged_lines"] == 14 and ov["signs"][0]["level"] == "high"
        only = claims.overview(s, date(2026, 11, 1), date(2026, 11, 30), None, sign="CLAIM_DUPLICATE")
        assert only["shown"] == 2
        assert claims.overview(s, date(2026, 11, 1), date(2026, 11, 30), {"SL00005"})["lines"] == 4
        assert claims.purge_images(s, date(2027, 1, 1)) == 2
        assert not s.query(SalesClaim).filter(SalesClaim.images.is_not(None)).count()


def test_claims_api(loaded, settings, tmp_path):
    engine, _ = loaded
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as api:
        ov = api.get("/api/v1/sales/claims?start=2026-11-01&end=2026-11-30").json()
        assert ov["lines"] == 17 and ov["flagged_amount"] > 0
        assert api.get("/api/v1/sales/cases?kind=claims&start=2026-11-01&end=2026-11-30").json()["cases"]
        r = api.post("/api/v1/sales/claims/import", headers=H, files={"file": ("c.csv", claims_csv(), "text/csv")})
        assert r.status_code == 200 and r.json()["updated"] == 17
        bad = api.post("/api/v1/sales/claims/import", headers=H, files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
        assert bad.status_code == 422
        assert api.post("/api/v1/sales/upload", headers=H, files=[("files", ("c.csv", claims_csv(), "text/csv"))]).status_code == 422
        m = api.get("/api/v1/sales/map/2026-11-13/SL00004").json()
        assert len(m["claims"]) == 2 and m["claims"][0]["signs"][0]["code"] == "CLAIM_ALLOWANCE_TWICE"
