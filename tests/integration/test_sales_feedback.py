"""Field Sales pilot: signed 'Was this right?' links (confirm page, then saved as a review) and live sending to pilot
addresses only while the mode is test. Synthetic data only."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from api.main import create_app
from database.connection import session_scope
from database.models.sales import SalesCase
from sales import feedback, geo


def _secret(monkeypatch, url="https://hr.example.com"):
    monkeypatch.setattr(feedback, "_key", lambda: b"x" * 40)
    monkeypatch.setattr(feedback, "public_url", lambda: url)


def test_tokens_are_signed_and_expire(monkeypatch):
    _secret(monkeypatch)
    t = feedback.token("SL00001", date(2026, 11, 21), "hod1@example.com", now=1_000_000)
    assert feedback.read(t, now=1_000_000 + 3600) == ("SL00001", date(2026, 11, 21), "hod1@example.com")
    assert feedback.read(t, now=1_000_000 + 22 * 86400) is None                  # 3 weeks
    assert feedback.read(t[:-2] + ("AA" if t[-2:] != "AA" else "BB")) is None     # tampered
    assert feedback.links([{"code": "SL1", "name": "A", "signs": [{"label": "X"}]}], date(2026, 11, 21), "h")[0]["right"].startswith(
        "https://hr.example.com/feedback/sales/")
    monkeypatch.setattr(feedback, "public_url", lambda: None)                    # localhost / not set
    assert feedback.links([{"code": "SL1", "name": "A", "signs": [{"label": "X"}]}], date(2026, 11, 21), "h") == []   # not reachable


def test_link_shows_a_confirm_page_and_the_button_saves_a_review(monkeypatch, settings, engine, tmp_path):
    _secret(monkeypatch)
    t = feedback.token("SL00001", date(2026, 11, 21), "hod1@example.com")
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "no-dist")) as c:
        r = c.get(f"/feedback/sales/{t}/right")
        assert r.status_code == 200 and "Confirm" in r.text and "SL00001" in r.text
        with session_scope(engine) as s:
            assert s.query(SalesCase).count() == 0                                # opening the link saves nothing
        r = c.post(f"/feedback/sales/{t}/right")                                  # no API header needed: signed link
        assert r.status_code == 200 and "Saved" in r.text
        with session_scope(engine) as s:
            case = s.query(SalesCase).one()
            assert case.status == geo.ACTION and case.reviewed_by == "email:hod1@example.com"
            geo.review(s, "SL00001", date(2026, 11, 21), geo.OK, "checked", "hr.user", "GPS_ERROR")
        r = c.post(f"/feedback/sales/{t}/wrong")
        assert r.status_code == 400 and "HR has already reviewed" in r.text      # HR's review is never overwritten
        assert c.get("/feedback/sales/not-a-token/right").status_code == 404


def test_pilot_sends_live_only_to_the_pilot_addresses(monkeypatch, engine, tmp_path):
    from types import SimpleNamespace

    from database.models.sales import SalesMailItem
    from sales import mail
    from sales.config import SalesEmail, save_email
    sent = []
    monkeypatch.setattr(mail, "render", lambda s, i: ("<p>x</p>", "x", []))
    monkeypatch.setattr(mail, "send", lambda cfg, msg, out: sent.append(cfg.mode) or SimpleNamespace(
        status="SENT" if cfg.mode == "live" else "SAVED", outbox_file=None))
    with session_scope(engine) as s:
        save_email(s, SalesEmail(mode="test", pilot_live=["hod1@example.com"]), "tester")
        items = [SalesMailItem(upload_id=1, report_date=date(2026, 11, 21), recipient_key=k, recipient_name=k, role="HOD", to_addrs=k,
                               subject="s", content="{}", counts="{}", status=mail.PENDING, attempts=0)
                 for k in ("hod1@example.com", "hod2@example.com")]
        done = mail.send_items(s, items, "tester", tmp_path)
        assert sent == ["live", "test"] and [i.status for i in done] == ["SENT", "SAVED"]
        assert done[0].note.startswith("Pilot: really sent")
