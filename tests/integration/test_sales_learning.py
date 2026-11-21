"""Module 2: learning from HR's reviews - sign reliability (Beta beliefs), learned risk, exploration, and the trained model.
Synthetic people only."""

from __future__ import annotations

from datetime import date

from database.connection import session_scope
from database.models.sales import SalesDayScore
from sales import geo, learning, ml
from tests.integration.test_sales_geo import day  # noqa: F401  (fixture)

D = date(2026, 11, 18)


def test_starting_beliefs_match_the_levels():
    st = {"signs": {}, "model": None}
    assert learning.risk(st, [("GEO_SAME_SPOT", "high")], None, False) == 60
    assert learning.risk(st, [("GEO_SAME_SPOT", "high"), ("GEO_KM_VS_ROUTE", "medium")], None, False) == 72
    assert learning.risk(st, [], None, False) == 0
    assert learning.risk(st, [("GEO_SAME_SPOT", "high")], None, False, explore=True) > 60          # optimistic while unreviewed
    assert learning.needs_reviews(st, [("GEO_SAME_SPOT", "high")], False)


def test_reviews_change_the_weights_and_the_order(day):
    with session_scope(day) as s:
        ml.rescore(s, D)
        before = {x.code: x.risk for x in s.query(SalesDayScore).filter_by(day=D)}
        cases = {c["code"]: c for c in geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None)}
        assert cases["SL00003"]["learning"] and cases["SL00003"]["explore"] >= cases["SL00003"]["risk"]
        # HR checks Chetan (KM vs route, off beat, day end away) and finds nothing wrong; Asha's day needed action
        geo.review(s, "SL00003", D, "OK", "Long route, explained", "hr")
        geo.review(s, "SL00001", D, "ACTION", "Spoke to her", "hr")
        st = learning.state(s)
        assert st["labels"] == 2 and st["signs"]["GEO_OFF_BEAT"] == {"action": 0, "ok": 1}
        assert learning.reliability(st, "GEO_OFF_BEAT", "low") < 0.1 < learning.reliability(st, "GEO_SAME_SPOT", "high") - 0.5
        after = {x.code: x.risk for x in s.query(SalesDayScore).filter_by(day=D)}
        assert after["SL00003"] < before["SL00003"] and after["SL00001"] > before["SL00001"]
        sm = learning.summary(s)
        assert sm["mode"] == "feedback" and sm["labels"] == 2 and sm["signs"][0]["reviewed"] >= 1


def test_model_takes_over_with_enough_reviews():
    rows = [({"GEO_SAME_SPOT"}, 0.9)] * 30 + [({"PHOTO_POOR"}, 0.1)] * 30
    ys = [1] * 30 + [0] * 30
    m = learning._train(rows, ys)
    assert m["trained_on"] == 60 and m["auc"] > 0.9
    st = {"signs": {}, "model": m}
    assert learning.risk(st, [("GEO_SAME_SPOT", "high")], 0.9, False) > 80 > 20 > learning.risk(st, [("PHOTO_POOR", "low")], 0.1, False)
