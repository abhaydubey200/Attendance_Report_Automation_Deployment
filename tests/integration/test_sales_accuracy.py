"""Module 2 accuracy: HQ / outstation work (Bizom Present_Type) in the location checks, the calibration review with reasons,
track records next to signs, and switching weak signs off. Synthetic people only."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from database.connection import session_scope
from database.models.sales import SalesEmployeeDay
from sales import bizom, geo, learning, service
from sales.config import get_rules
from tests.integration.test_sales_geo import H, day, history_csv  # noqa: F401  (day = fixture)

D = date(2026, 11, 18)


def test_work_place():
    assert bizom.work_place("Retailing EX-HQ") == "EXHQ" and bizom.work_place("Joint Working EX-HQ") == "EXHQ"
    assert bizom.work_place("Retailing HQ") == "HQ" and bizom.work_place("Other Activity HQ") == "HQ"
    assert bizom.work_place("") is None and bizom.work_place("JC Meeting") is None


def _chetan(s, present_type):
    r = s.query(SalesEmployeeDay).filter_by(code="SL00003").one()
    r.present_type = present_type
    s.flush()
    geo.check_day(s, D)
    import json
    return set((r.geo_flags or "").split(",")), " ".join(json.loads(r.geo_evidence or "{}").values())


def test_hq_and_outstation_days(day):
    with session_scope(day) as s:
        service.import_history(s, "AttendanceReport.csv", history_csv())          # Chetan usually starts at base; 18-Nov is 50 km away
        flags, ev = _chetan(s, None)
        assert "GEO_START_AWAY" in flags and "HQ / outstation information was recorded" in ev
        flags, ev = _chetan(s, "Retailing HQ")
        assert "GEO_AWAY_AT_HQ" in flags and "GEO_START_AWAY" not in flags and 'Recorded as "Retailing HQ"' in ev
        flags, _ = _chetan(s, "Retailing EX-HQ")
        assert not {"GEO_AWAY_AT_HQ", "GEO_START_AWAY"} & flags                   # outstation: far from base is expected


def test_calibration_reasons_records_and_switching_off(day, settings, tmp_path):
    with session_scope(day) as s:
        cal = geo.calibration(s, date(2026, 11, 1), date(2026, 11, 30), None, n=10)
        assert len(cal["cases"]) == 3 and cal["sign_kinds"] >= 2                 # every kind of main sign is in the sample
        geo.review(s, "SL00003", D, "OK", "On a planned route", "hr", reason="APPROVED_TOUR")
        with pytest.raises(ValueError):
            geo.review(s, "SL00002", D, "OK", None, "hr", reason="BECAUSE")
        assert geo.case_dict(s.query(geo.SalesCase).filter_by(code="SL00003").one(), "SL00003", D)["reason"] == "APPROVED_TOUR"
        for code in ("SL00001", "SL00002"):
            geo.review(s, code, D, "OK", None, "hr", reason="GPS_ERROR")
        st = learning.state(s)
        assert learning.record(st, "GEO_TOGETHER") == "right 0 of 2 times when checked" or learning.record(st, "GEO_TOGETHER") is None
        assert geo.calibration(s, date(2026, 11, 1), date(2026, 11, 30), None)["reviewed_with_reason"] == 3
    with TestClient(create_app(settings, day, frontend_dist=tmp_path / "x")) as api:
        assert api.get("/api/v1/sales/calibration").status_code == 200
        r = api.post("/api/v1/sales/learning/switch", headers=H, json={"code": "GEO_OFF_BEAT", "off": True})
        assert r.status_code == 200 and next(x for x in r.json()["signs"] if x["code"] == "GEO_OFF_BEAT")["switched_off"]
        assert api.post("/api/v1/sales/learning/switch", headers=H, json={"code": "NOPE", "off": True}).status_code == 422
        assert api.put(f"/api/v1/sales/cases/{D}/SL00003", headers=H, json={"status": "ACTION", "reason": "REAL_ISSUE"}).json()["reason"] == "REAL_ISSUE"
    with session_scope(day) as s:
        assert "GEO_OFF_BEAT" in get_rules(s).disabled_signs
        assert "GEO_OFF_BEAT" not in (s.query(SalesEmployeeDay).filter_by(code="SL00003").one().geo_flags or "")
