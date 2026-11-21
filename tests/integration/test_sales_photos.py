"""Module 2 selfie checks with a fake image server (no network): only Bizom links fetched, fingerprints not photos, every sign,
placeholders ignored, retries, cases / day page / API. Synthetic images only."""

from __future__ import annotations

import io
from datetime import date

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from database.connection import session_scope
from database.models.sales import SalesPhoto
from sales import geo, photos

HOST = "https://outletimages.s3.ap-southeast-1.amazonaws.com/apis/"


def picture(seed: int, size=(750, 1000), shift: int = 0, dark: bool = False, exif_time: str | None = None, fmt="JPEG") -> bytes:
    rng = np.random.default_rng(seed)
    small = (rng.random((10, 8)) * 255).astype(np.uint8)
    im = Image.fromarray(small).resize(size, Image.BILINEAR).convert("RGB")
    grain = (rng.random((size[1], size[0], 1)) * 60 - 30).astype(int)          # fine detail: a sharp photo
    a = np.clip(np.asarray(im).astype(int) + grain + shift, 0, 255)
    if dark:
        a = a // 12
    im = Image.fromarray(a.astype(np.uint8))
    buf = io.BytesIO()
    if exif_time:
        ex = Image.Exif()
        ex[306] = exif_time
        im.save(buf, fmt, exif=ex, quality=90)
    else:
        im.save(buf, fmt, quality=90)
    return buf.getvalue()


SAME = picture(1)
IMAGES = {
    "a_day10.jpg": SAME, "a_day11.jpg": SAME,                                # same person, same bytes on two days
    "b_near.jpg": picture(1, shift=6),                                        # another person: nearly identical
    "c_clean.jpg": picture(3), "c2.jpg": picture(4), "c3.jpg": picture(5), "c4.jpg": picture(6), "c5.jpg": picture(7),
    "d_camera.jpg": picture(8, size=(2448, 3264), exif_time="2026:10:30 10:08:00"),
    "e_dark.jpg": picture(9, dark=True), "f_noface.jpg": picture(10),
    **{f"placeholder{i}.jpg": picture(42) for i in range(6)},
    "pdf.jpg": b"%PDF-1.4 not an image",
}
REQUESTED: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    REQUESTED.append(str(request.url))
    assert request.url.host.endswith("amazonaws.com")
    name = request.url.path.rsplit("/", 1)[-1]
    if name == "gone.jpg":
        return httpx.Response(404)
    if name == "busy.jpg":
        return httpx.Response(500)
    if name == "pdf.jpg":
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=IMAGES[name])
    return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=IMAGES[name])


@pytest.fixture
def checked(engine, monkeypatch):
    real = photos.count_faces
    faceless = [np.asarray(Image.open(io.BytesIO(IMAGES[n])).convert("L")).mean() for n in ("f_noface.jpg", "e_dark.jpg")]
    monkeypatch.setattr(photos, "count_faces", lambda g, *rest: 0 if any(abs(np.asarray(g).mean() - m) < 0.5 for m in faceless) else 1)
    D = lambda d: date(2026, 11, d)  # noqa: E731
    items = [(HOST + "a_day10.jpg", "SL00001", D(10), "09:00"), (HOST + "a_day11.jpg", "SL00001", D(11), "09:00"),
             (HOST + "b_near.jpg", "SL00002", D(12), "09:10"), (HOST + "c_clean.jpg", "SL00003", D(12), "09:00"),
             (HOST + "c2.jpg", "SL00003", D(13), "09:00"), (HOST + "c3.jpg", "SL00003", D(14), "09:00"),
             (HOST + "c4.jpg", "SL00005", D(13), "09:00"), (HOST + "c5.jpg", "SL00005", D(14), "09:00"),
             (HOST + "d_camera.jpg", "SL00004", D(12), "09:30"), (HOST + "e_dark.jpg", "SL00005", D(12), "09:00"),
             (HOST + "f_noface.jpg", "SL00006", D(12), "09:00"), (HOST + "pdf.jpg", "SL00006", D(13), "09:00"),
             (HOST + "gone.jpg", "SL00006", D(14), "09:00"), (HOST + "busy.jpg", "SL00006", D(15), "09:00"),
             ("https://evil.example.com/x.jpg", "SL00007", D(12), "09:00"), ("http://outletimages.s3.ap-southeast-1.amazonaws.com/a.jpg", "SL00007", D(13), None)]
    items += [(HOST + f"placeholder{i}.jpg", f"SL0010{i}", D(12), "09:00") for i in range(6)]
    with session_scope(engine) as s:
        assert photos.register(s, items) == len(items)
        assert photos.register(s, items[:3]) == 0                                     # already known
    REQUESTED.clear()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = photos.fetch(engine, client=client)
    monkeypatch.setattr(photos, "count_faces", real)
    return engine, res, client


def flags(s, url) -> set[str]:
    p = s.query(SalesPhoto).filter_by(url=url).one()
    return set((p.flags or "").split(",")) - {""}


def test_allowed_links():
    assert photos.allowed("https://outletimages.s3.ap-southeast-1.amazonaws.com/x/y.jpeg")
    assert photos.allowed("https://bizompictures.s3-ap-southeast-1.amazonaws.com/y.jpg")
    assert photos.allowed("https://s3.ap-southeast-1.amazonaws.com/outletimages/y.jpg")
    for bad in ("http://outletimages.s3.ap-southeast-1.amazonaws.com/x.jpg", "https://evil.example.com/x.jpg",
                "https://outletimages.s3.ap-southeast-1.amazonaws.com.evil.com/x.jpg", "https://s3.ap-southeast-1.amazonaws.com/other/x.jpg",
                "https://user:pw@outletimages.s3.ap-southeast-1.amazonaws.com/x.jpg", "file:///etc/passwd"):
        assert not photos.allowed(bad), bad


def test_every_sign_and_safety(checked):
    engine, res, _ = checked
    assert not any("evil" in u or u.startswith("http://") for u in REQUESTED)              # only Bizom over HTTPS
    assert res["done"] == 17 and res["skipped"] == 2 and res["failed"] == 1 and res["placeholders"] == 6
    with session_scope(engine) as s:
        assert flags(s, HOST + "a_day11.jpg") == {"PHOTO_REUSED", "PHOTO_OTHER_PERSON"} and flags(s, HOST + "a_day10.jpg") >= {"PHOTO_REUSED"}
        assert "PHOTO_OTHER_PERSON" in flags(s, HOST + "b_near.jpg")
        assert flags(s, HOST + "d_camera.jpg") == {"PHOTO_NOT_LIVE", "PHOTO_TIME_MISMATCH"}
        assert flags(s, HOST + "e_dark.jpg") == {"PHOTO_POOR"}
        assert flags(s, HOST + "f_noface.jpg") == {"PHOTO_NO_FACE"}
        assert flags(s, HOST + "c_clean.jpg") == set() and flags(s, HOST + "placeholder0.jpg") == set()
        p = s.query(SalesPhoto).filter_by(url=HOST + "d_camera.jpg").one()
        assert p.exif_time == "2026-10-30 10:08:00" and len(p.sha256) == 64 and len(p.phash) == 16
        assert s.query(SalesPhoto).filter_by(url="https://evil.example.com/x.jpg").one().status == photos.SKIPPED
        assert s.query(SalesPhoto).filter_by(url=HOST + "pdf.jpg").one().status == photos.SKIPPED
        busy = s.query(SalesPhoto).filter_by(url=HOST + "busy.jpg").one()
        assert busy.status == photos.FAILED and busy.tries == 1


def test_retry_cases_day_page_purge_and_api(checked, settings, tmp_path):
    engine, _, client = checked
    again = photos.fetch(engine, client=client)                                         # only the failed one is tried again
    assert again["fetched"] == 1
    with session_scope(engine) as s:
        cs = geo.cases(s, date(2026, 11, 1), date(2026, 11, 30), None, kind="photos")
        codes = {(c["code"], c["date"]) for c in cs}
        assert ("SL00001", "2026-11-11") in codes and ("SL00004", "2026-11-12") in codes and ("SL00003", "2026-11-12") not in codes
        m = geo.day_map(s, date(2026, 11, 11), "SL00001")                               # a day known only from its selfie
        assert m and {x["code"] for x in m["photos"][0]["signs"]} == {"PHOTO_REUSED", "PHOTO_OTHER_PERSON"}
        assert "2026-11-10" in {x["date"] for x in m["photos"][0]["matches"]}
        ov = photos.overview(s, date(2026, 11, 1), date(2026, 11, 30), None)
        assert ov["flagged"] >= 6 and ov["queue"]["failed"] == 1 and ov["signs"][0]["level"] == "high"
        assert photos.overview(s, date(2026, 11, 1), date(2026, 11, 30), {"SL00003"})["flagged"] == 0
    with TestClient(create_app(settings, engine, frontend_dist=tmp_path / "x")) as api:
        ov = api.get("/api/v1/sales/photos?start=2026-11-01&end=2026-11-30").json()
        assert ov["photos"] == 22 and any(i["matches"] for i in ov["items"])
    with session_scope(engine) as s:
        assert photos.purge(s, date(2026, 11, 12)) == 2


def test_image_detail_confirmation():
    same_a, same_b = photos._grey(picture(21)), photos._grey(picture(21, shift=8))          # re-saved copy
    other = photos._grey(picture(22))                                                         # a different photo
    assert photos.match_points(same_a, same_b) >= 70 > photos.match_points(same_a, other)
