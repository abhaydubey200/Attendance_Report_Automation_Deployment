"""Module 2 machine learning: usual places (DBSCAN, several per person), unusual days (Isolation Forest on each person's own
normal), the risk score, and the 'Location & selfie checks' part of the emails / Excel / dashboard / month-end.
Synthetic people and places only."""

from __future__ import annotations

import io
import json
from datetime import date, timedelta

from openpyxl import load_workbook

from database.connection import session_scope
from database.models.sales import SalesDayScore, SalesEmployeeDay, SalesLocation
from sales import checks, geo, mail, ml, monthly
from sales.config import get_rules
from tests.integration.test_sales_geo import BASE, day, off  # noqa: F401  (day = fixture)

HOME, HQ = BASE, off(0, 8)                        # two usual places 8 km apart


def test_usual_places_two_bases_and_travellers():
    pts = [HOME] * 10 + [HQ] * 8 + [off(40, 40)]           # one odd trip is not a place
    places = ml.places_of(pts)
    assert len(places) == 2 and places[0].days == 10 and places[1].days == 8
    d, p = ml.nearest(places, off(0.1, 7.9))
    assert d < 0.5 and p is places[1]
    travels = [off(i * 15, 0) for i in range(20)] + [HOME] * 4  # many towns: a far start is normal for this person
    tp = ml.places_of(travels)
    assert tp and tp[0].travel_km > 20 and ml.away_limit(tp[0], _rules()) > 60


def _rules():
    from sales.config import SalesRules
    return SalesRules()


def _history(s, code: str, days: int, end: date, base=HOME, other=HQ):
    for i in range(1, days + 1):
        d = end - timedelta(days=i)
        at = base if i % 2 else other
        s.add(SalesLocation(code=code, day=d, kind="ATT", lat=at[0], lng=at[1], time="09:00", source="HISTORY"))


def test_unusual_day_risk_and_emails(day):
    end = date(2026, 11, 18)
    with session_scope(day) as s:
        _history(s, "SL00005", 25, end, base=off(-5), other=off(-5, 8))          # Esha: two bases, always 9:00
        # Esha's 18-Nov: attendance at 15:40, 60 km from both bases
        loc = s.query(SalesLocation).filter_by(code="SL00005", day=end, kind="ATT").one()
        loc.lat, loc.lng, loc.time = *off(60, 30), "15:40"
        s.flush()
        geo.check_day(s, end)
        r = ml.rescore(s, end)
        assert r["scored"] >= 30
        sc = s.query(SalesDayScore).filter_by(code="SL00005", day=end).one()
        reasons = json.loads(sc.reasons or "[]")
        assert sc.unusual and any("later than usual" in x for x in reasons) and any("km from the usual places" in x for x in reasons)
        esha = s.query(SalesEmployeeDay).filter_by(code="SL00005").one()
        assert "GEO_START_AWAY" in (esha.geo_flags or "") and "nearest usual place (2 usual places" in esha.geo_evidence
        asha = s.query(SalesDayScore).filter_by(code="SL00001", day=end).one()
        assert asha.risk >= 60                                                   # several high location signs
        # the emails: each team head sees only their team; risk first; text, Excel and dashboard carry it
        ch = checks.day_checks(s, end, None)
        assert ch[0]["risk"] >= ch[-1]["risk"] and {c["code"] for c in ch} >= {"SL00001", "SL00005"}
        assert {c["code"] for c in checks.day_checks(s, end, {"SL00005"})} == {"SL00005"}
        item = next(i for i in mail.items_for(s, end) if i.recipient_key == "hod2@example.com")
        # Esha's signs compare the day with what was LEARNED: not in a HOD email until HR's reviews prove them ...
        html, text, files = mail.render(s, item)
        assert "Esha Fine (risk" not in html
        from sales import learning
        st = learning.state(s)
        st.setdefault("signs", {}).update({"UNUSUAL_DAY": {"action": 9, "ok": 1}, "GEO_START_AWAY": {"action": 9, "ok": 1}})
        learning._save(s, st)
        # ... then they are (right 9 of 10 times, 8+ reviews)
        html, text, files = mail.render(s, item)
        # build brief: counts, then only the people needing attention (grouped by territory); Esha's proven serious check lists her
        assert "Needs attention" in html and "Esha Fine" in html and "Asha" not in html
        assert "Needs attention" in text and "fraud" not in (html + text).lower() and "Absent / did not mark" not in text
        wb = load_workbook(io.BytesIO(next(f for f in files if f.filename.endswith(".xlsx")).content))
        assert "Location & selfie checks" in wb.sheetnames and "Proof" in wb.sheetnames          # HOD: proof sheet with map links
        proof_ws = wb["Proof"]
        assert proof_ws.cell(5, 2).value.startswith("Esha Fine") and proof_ws.cell(5, 6).hyperlink.target.startswith("https://www.google.com/maps?q=")
        # a team head gets the checks but no photos / map links
        th = next(i for i in mail.items_for(s, end) if i.role == "Team head")
        _, _, tfiles = mail.render(s, th)
        assert "Proof" not in load_workbook(io.BytesIO(next(f for f in tfiles if f.filename.endswith(".xlsx")).content)).sheetnames
        assert '"checks"' in next(f for f in files if f.filename.endswith(".html")).content.decode()
        # month-end: repeated patterns become reasons in 'Needs a conversation'
        v = monthly.build_view(s, "2026-11", None, "company", "HR")
        asha_m = next(p for p in v["people"] if p["code"] == "SL00001")
        assert asha_m["checks"]["location_days"] == 1 and asha_m["checks"]["max_risk"] >= 60
        wbm = load_workbook(io.BytesIO(monthly.excel(v)))
        assert "Location & selfie checks" in wbm.sheetnames


def test_switch_off_keeps_emails_as_before(day):
    from sales.config import save_rules
    with session_scope(day) as s:
        save_rules(s, get_rules(s).model_copy(update={"geo_in_emails": False}), "tester")
        assert checks.day_checks(s, date(2026, 11, 18), None) == []
        item = next(i for i in mail.items_for(s, date(2026, 11, 18)) if i.recipient_key == "hod1@example.com")
        html, _, _ = mail.render(s, item)
        assert "Location &amp; selfie checks" not in html
