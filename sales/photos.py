"""Selfie checks for Field Sales ("needs checking", never "fraud").

Each attendance selfie is downloaded from Bizom's image server, looked at IN MEMORY and thrown away: only a fingerprint
(exact SHA-256 and a 64-bit perceptual hash), its size, face count, brightness / sharpness and any date the camera wrote into
it are kept, for keep_months. Only Bizom's own S3 image hosts are ever contacted (HTTPS, no redirects, size-capped).

Signs: the same or a nearly identical selfie on another day (or of another person), a date in the photo that does not match
the attendance, a photo not taken with the app's camera (full camera photo with its own date: likely picked from the
gallery), no face found, too dark / blurry to judge.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from core.timeutils import now_utc
from database.connection import session_scope
from database.models.sales import SalesDayUpload, SalesEmployee, SalesEmployeeDay, SalesPhoto, SalesPhotoPair
from sales.config import SalesRules, get_rules

PHOTO: dict[str, tuple[str, str, str]] = {
    "PHOTO_OTHER_PERSON": ("Same selfie as another person", "high", "This selfie is the same as, or nearly identical to, another person's selfie."),
    "PHOTO_REUSED": ("Selfie reused from another day", "high", "This selfie is the same as, or nearly identical to, one from another day."),
    "PHOTO_TIME_MISMATCH": ("Photo date does not match", "high", "The date / time written into the photo by the camera is not the attendance date / time."),
    "PHOTO_NOT_LIVE": ("Not taken with the app camera", "medium",
                       "A full camera photo with its own date inside, unlike the app's live selfies - it was probably picked from the gallery."),
    "PHOTO_NO_FACE": ("No face found", "medium", "No face could be found in a clear selfie."),
    "PHOTO_POOR": ("Too dark or blurry", "low", "The selfie is too dark or too blurry to check who it is."),
}
LEVEL = {"high": 0, "medium": 1, "low": 2}
NEW, DONE, FAILED, SKIPPED = "NEW", "DONE", "FAILED", "SKIPPED"
MAX_BYTES = 15 * 1024 * 1024
_BUCKET_HOST = re.compile(r"^(outletimages|bizompictures)\.s3[.-]ap-southeast-1\.amazonaws\.com$")
_PATH_HOSTS = {"s3.ap-southeast-1.amazonaws.com", "s3-ap-southeast-1.amazonaws.com"}


def allowed(url: str) -> bool:
    """Only Bizom's own image buckets, over HTTPS."""
    u = urlparse(url)
    if u.scheme != "https" or u.username or u.password or (u.port not in (None, 443)):
        return False
    host = (u.hostname or "").lower()
    return bool(_BUCKET_HOST.match(host)) or (host in _PATH_HOSTS and re.match(r"^/(outletimages|bizompictures)/", u.path) is not None)


# ---------------------------------------------------------------- registering selfies to check
def register(session: Session, items: list[tuple[str, str, date, str | None]]) -> int:
    """items: (url, code, day, attendance time). Existing links are kept as they are."""
    items = [i for i in items if i[0]]
    if not items:
        return 0
    have = set()
    urls = [i[0] for i in items]
    for k in range(0, len(urls), 500):
        have |= set(session.scalars(select(SalesPhoto.url).where(SalesPhoto.url.in_(urls[k:k + 500]))))
    n = 0
    for url, code, day, t in items:
        if url in have:
            continue
        have.add(url)
        session.add(SalesPhoto(url=url[:600], kind="SELFIE", code=code, day=day, att_time=t,
                               status=NEW if allowed(url) else SKIPPED, error=None if allowed(url) else "Not a Bizom image link.", tries=0))
        n += 1
    session.flush()
    return n


def register_day(session: Session, upload: SalesDayUpload) -> int:
    rows = session.execute(select(SalesEmployeeDay.photo_url, SalesEmployeeDay.code, SalesEmployeeDay.attendance_time)
                           .where(SalesEmployeeDay.upload_id == upload.upload_id, SalesEmployeeDay.photo_url.is_not(None)))
    return register(session, [(u, c, upload.report_date, t) for u, c, t in rows])


# ---------------------------------------------------------------- looking at one photo (in memory)
_DCT = None


def _dct_matrix():
    global _DCT
    if _DCT is None:
        import numpy as np
        n = 32
        k = np.arange(n).reshape(-1, 1)
        _DCT = np.cos(np.pi * (2 * np.arange(n) + 1) * k / (2 * n))
    return _DCT


def phash(gray) -> str:
    """64-bit perceptual hash (DCT of a 32x32 grey image, 8x8 low frequencies vs their median)."""
    import numpy as np
    from PIL import Image
    a = np.asarray(gray.resize((32, 32), Image.LANCZOS), dtype=np.float64)
    c = _dct_matrix()
    low = (c @ a @ c.T)[:8, :8].flatten()
    bits = low > np.median(low[1:])
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


_LOCAL = threading.local()


def _detectors():
    """One pair of face detectors per thread: OpenCV's cascade classifier must not be shared between threads."""
    if getattr(_LOCAL, "faces", None) is None:
        import cv2
        _LOCAL.faces = (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"),
                        cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml"))
    return _LOCAL.faces


YUNET = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"


def _yunet():
    """One YuNet face detector per thread (OpenCV's model zoo, MIT). None when the model file is missing."""
    if getattr(_LOCAL, "yunet", None) is None and YUNET.is_file():
        import cv2
        _LOCAL.yunet = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 50)
    return getattr(_LOCAL, "yunet", None)


def count_faces(gray, rgb=None) -> int:
    """Faces in the selfie. YuNet (a neural-network face finder) when available, else OpenCV's older cascades."""
    import cv2
    import numpy as np
    w = 480
    det = _yunet()
    if det is not None:
        src = rgb if rgb is not None else gray.convert("RGB")
        img = src.resize((w, max(1, int(src.height * w / src.width)))) if src.width > w else src
        bgr = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        det.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, faces = det.detect(bgr)
        return 0 if faces is None else len(faces)
    g = gray.resize((w, max(1, int(gray.height * w / gray.width)))) if gray.width > w else gray
    a = np.asarray(g)
    front, profile = _detectors()
    n = len(front.detectMultiScale(a, 1.1, 5, minSize=(40, 40)))
    if n == 0:
        n = len(profile.detectMultiScale(a, 1.1, 5, minSize=(40, 40))) or len(profile.detectMultiScale(cv2.flip(a, 1), 1.1, 5, minSize=(40, 40)))
    return n


def analyse(data: bytes) -> dict:
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    im.load()
    exif = im.getexif()
    raw_time = exif.get(36867) or exif.get_ifd(0x8769).get(36867) or exif.get(306)      # DateTimeOriginal / DateTime
    when = None
    if raw_time:
        try:
            when = datetime.strptime(str(raw_time).strip()[:19], "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = None
    im = ImageOps.exif_transpose(im)
    gray = im.convert("L")
    small = np.asarray(gray.resize((min(640, gray.width), max(1, int(gray.height * min(640, gray.width) / gray.width)))))
    return {"sha256": hashlib.sha256(data).hexdigest(), "phash": phash(gray), "width": im.width, "height": im.height,
            "size_kb": round(len(data) / 1024), "faces": count_faces(gray, im.convert("RGB")), "brightness": round(float(small.mean()), 1),
            "sharpness": round(float(cv2.Laplacian(small, cv2.CV_64F).var()), 1), "exif_time": when}


def _download(client, url: str) -> bytes:
    if not allowed(url):
        raise ValueError("Not a Bizom image link.")
    with client.stream("GET", url) as r:
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        if not r.headers.get("content-type", "").startswith("image/"):
            raise ValueError(f"Not an image ({r.headers.get('content-type', '?').split(';')[0]})")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("Larger than 15 MB.")
        return bytes(buf)


def fetch(engine, limit: int | None = None, client=None, workers: int = 6) -> dict:
    """Download, look at and fingerprint up to `limit` selfies that are new (or failed fewer than 3 times). Never stores a photo."""
    import httpx
    with session_scope(engine) as s:
        rules = get_rules(s)
        if not rules.photo_downloads:
            return {"fetched": 0, "note": "Photo downloads are switched off in Settings."}
        todo = list(s.execute(select(SalesPhoto.id, SalesPhoto.url).where(
            or_(SalesPhoto.status == NEW, (SalesPhoto.status == FAILED) & (SalesPhoto.tries < 3))).order_by(SalesPhoto.day.desc(), SalesPhoto.id)
            .limit(limit or rules.photo_batch)))
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "HR-Portal-photo-check/1.0"})
    stats: Counter = Counter()

    def work(item):
        pid, url = item
        try:
            return pid, analyse(_download(client, url)), None
        except Exception as exc:                                   # a bad photo never stops the run
            return pid, None, f"{type(exc).__name__}: {exc}"[:200]
    try:
        for k in range(0, len(todo), 200):
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(work, todo[k:k + 200]))
            with session_scope(engine) as s:
                for pid, res, err in results:
                    p = s.get(SalesPhoto, pid)
                    p.tries += 1
                    p.fetched_at = now_utc()
                    if res:
                        for key, val in res.items():
                            setattr(p, key, val)
                        p.status, p.error = DONE, None
                        stats["done"] += 1
                    else:
                        unfixable = err and ("Not an image" in err or "cannot identify" in err or "HTTP 403" in err or "HTTP 404" in err)
                        p.status, p.error = (SKIPPED if unfixable else FAILED), err
                        stats["skipped" if unfixable else "failed"] += 1
    finally:
        if own:
            client.close()
    res = check_and_confirm(engine, client if not own else None)
    return {"fetched": len(todo), **dict(stats), **res}


def check_and_confirm(engine, client=None) -> dict:
    """Fingerprint check -> confirm new look-alike pairs by image details -> final check -> risk scores."""
    with session_scope(engine) as s:
        res = check(s)
    confirmed = confirm_pairs(engine, res.pop("_waiting"), client)
    with session_scope(engine) as s:
        res = check(s)
        res.pop("_waiting", None)
        from sales import ml
        ml.rescore(s)                                     # risk scores include the selfie signs
    return {**res, "pairs_confirmed_now": confirmed}


def recount(engine, client=None, workers: int = 6) -> dict:
    """Look again (new face finder) at the selfies flagged 'no face' or 'too dark / blurry'. Photos are still not stored."""
    import httpx
    with session_scope(engine) as s:
        todo = list(s.execute(select(SalesPhoto.id, SalesPhoto.url).where(SalesPhoto.status == DONE, or_(
            SalesPhoto.flags.like("%PHOTO_NO_FACE%"), SalesPhoto.flags.like("%PHOTO_POOR%")))))
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "HR-Portal-photo-check/1.0"})
    changed = 0

    def work(item):
        pid, url = item
        try:
            return pid, analyse(_download(client, url))
        except Exception:
            return pid, None
    try:
        for k in range(0, len(todo), 200):
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(work, todo[k:k + 200]))
            with session_scope(engine) as s:
                for pid, res in results:
                    if res:
                        p = s.get(SalesPhoto, pid)
                        changed += (p.faces or 0) != (res["faces"] or 0)
                        p.faces, p.brightness, p.sharpness = res["faces"], res["brightness"], res["sharpness"]
    finally:
        if own:
            client.close()
    res = check_and_confirm(engine)
    return {"looked_again": len(todo), "face_count_changed": changed, **res}


# ---------------------------------------------------------------- the checks (all fingerprints at once)
def _near_pairs(photos: list[SalesPhoto], max_bits: int) -> dict[int, set[int]]:
    """Photos whose perceptual hashes differ in at most max_bits bits (multi-index hashing: with 8 chunks of 8 bits, two hashes
    within 7 bits always share one identical chunk)."""
    hashes = {p.id: int(p.phash, 16) for p in photos if p.phash}
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for pid, h in hashes.items():
        for i in range(8):
            buckets[(i, (h >> (8 * i)) & 0xFF)].append(pid)
    near: dict[int, set[int]] = defaultdict(set)
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        for a_i, a in enumerate(ids):
            ha = hashes[a]
            for b in ids[a_i + 1:]:
                if (ha ^ hashes[b]).bit_count() <= max_bits:
                    near[a].add(b)
                    near[b].add(a)
    return near


def check(session: Session, rules: SalesRules | None = None) -> dict:
    rules = rules or get_rules(session)
    photos = list(session.scalars(select(SalesPhoto).where(SalesPhoto.status == DONE)))
    by_id = {p.id: p for p in photos}
    names = {e.code: e.name for e in session.scalars(select(SalesEmployee))}
    near = _near_pairs(photos, min(7, max(rules.photo_same_bits, rules.photo_reuse_bits)))
    pairs = {(a, b): n for a, b, n in session.execute(select(SalesPhotoPair.a_id, SalesPhotoPair.b_id, SalesPhotoPair.points))}
    hashes = {p.id: int(p.phash, 16) for p in photos if p.phash}
    bits = lambda a, b: (hashes[a] ^ hashes[b]).bit_count() if a in hashes and b in hashes else 64  # noqa: E731
    for grp in _groups(photos, "sha256").values():
        for a in grp:
            near[a] |= set(grp) - {a}
    # a picture shared by many different people is a placeholder (e.g. Bizom's "no image" picture), not a reused selfie
    placeholder = {pid for pid, others in near.items() if len({by_id[o].code for o in others} | {by_id[pid].code}) >= 6}
    dims = Counter((p.width, p.height) for p in photos)
    common = {d for d, n in dims.items() if n >= max(5, 0.05 * len(photos))}
    # What is normal for each person: some phones always send full camera photos, and for some people's angle / light the face
    # finder always fails - those are not signs. Flag only what is unusual for the person (needs 5+ selfies to know).
    mine: dict[str, list[SalesPhoto]] = defaultdict(list)
    for p in photos:
        mine[p.code].append(p)
    camera_share = {c: sum(1 for x in v if x.exif_time or (x.width, x.height) not in common) / len(v) for c, v in mine.items()}
    face_share = {c: sum(1 for x in v if x.faces) / len(v) for c, v in mine.items()}
    known = {c for c, v in mine.items() if len(v) >= 5}
    stats: Counter = Counter()
    for p in photos:
        f: dict[str, str] = {}
        others = [by_id[o] for o in near.get(p.id, ()) if o not in placeholder and _confirmed(p, by_id[o], pairs, rules)] \
            if p.id not in placeholder else []
        other_people = sorted({o for o in others if o.code != p.code and (o.sha256 == p.sha256 or bits(o.id, p.id) <= rules.photo_same_bits)},
                              key=lambda o: (o.day, o.code))
        other_days = sorted({o for o in others if o.code == p.code and o.day != p.day
                             and (o.sha256 == p.sha256 or bits(o.id, p.id) <= rules.photo_reuse_bits)}, key=lambda o: o.day)
        matches = []
        if other_people:
            o = other_people[0]
            f["PHOTO_OTHER_PERSON"] = (f"Same as {names.get(o.code, o.code)}'s selfie on {o.day:%d-%b} ({_proof(p, o, pairs)})"
                                       + (f" (and {len(other_people) - 1} more)" if len(other_people) > 1 else "") + ".")
            matches += other_people[:3]
        if other_days:
            f["PHOTO_REUSED"] = f"Same as the selfie on {', '.join(f'{o.day:%d-%b}' for o in other_days[:3])}" + \
                                (f" and {len(other_days) - 3} more days" if len(other_days) > 3 else "") + f" ({_proof(p, other_days[0], pairs)})."
            matches += other_days[:3]
        if p.exif_time:
            taken = datetime.strptime(p.exif_time, "%Y-%m-%d %H:%M:%S")
            off_day = taken.date() != p.day
            off_time = False
            if not off_day and p.att_time:
                att = datetime.combine(p.day, datetime.strptime(p.att_time, "%H:%M").time())
                off_time = abs((taken - att).total_seconds()) > rules.photo_time_hours * 3600
            if off_day or off_time:
                f["PHOTO_TIME_MISMATCH"] = f"Photo taken {taken:%d-%b %I:%M %p}; attendance {p.day:%d-%b}" + \
                                           (f" {p.att_time}" if p.att_time else "") + "."
            if (p.width, p.height) not in common and (p.code not in known or camera_share[p.code] <= 0.5):
                f["PHOTO_NOT_LIVE"] = (f"Full camera photo ({p.width}x{p.height}, dated {taken:%d-%b %I:%M %p}) instead of the app's live selfie"
                                       + (f"; usually {100 - round(100 * camera_share[p.code])}% of this person's selfies are live." if p.code in known else "."))
        elif common and (p.width, p.height) not in common and p.size_kb and p.size_kb > 400 and (p.code not in known or camera_share[p.code] <= 0.5):
            f["PHOTO_NOT_LIVE"] = f"{p.width}x{p.height}, {p.size_kb} KB - not the app's usual live-selfie format."
        poor = (p.brightness is not None and p.brightness < rules.photo_dark) or (p.sharpness is not None and p.sharpness < rules.photo_blurry)
        if poor:
            f["PHOTO_POOR"] = ("Too dark" if p.brightness is not None and p.brightness < rules.photo_dark else "Too blurry") + " to check."
        elif p.faces == 0 and (p.code not in known or face_share[p.code] >= 0.8):
            f["PHOTO_NO_FACE"] = "No face found in the selfie" +                                  (f"; a face is found in {round(100 * face_share[p.code])}% of this person's selfies." if p.code in known else ".")
        order = sorted(f, key=lambda x: (LEVEL[PHOTO[x][1]], x))
        p.flags = ",".join(order) or None
        p.evidence = json.dumps({**{x: f[x] for x in order}, "_matches": [m.id for m in matches]}) if order else None
        stats.update(order)
    session.flush()
    waiting = [(a, b) for a, bs in near.items() for b in bs if a < b and (a, b) not in pairs
               and by_id[a].sha256 != by_id[b].sha256 and a not in placeholder and b not in placeholder]
    return {"checked": len(photos), "flagged": sum(1 for p in photos if p.flags), "signs": dict(stats), "placeholders": len(placeholder),
            "pairs_to_confirm": len(waiting), "_waiting": waiting}


def _key(a: SalesPhoto, b: SalesPhoto) -> tuple[int, int]:
    return (a.id, b.id) if a.id < b.id else (b.id, a.id)


def _confirmed(p: SalesPhoto, o: SalesPhoto, pairs: dict, rules: SalesRules) -> bool:
    if p.sha256 and p.sha256 == o.sha256:
        return True
    n = pairs.get(_key(p, o))
    return n is not None and n >= rules.photo_confirm_points


def _proof(p: SalesPhoto, o: SalesPhoto, pairs: dict) -> str:
    if p.sha256 and p.sha256 == o.sha256:
        return "identical file"
    return f"confirmed: {pairs.get(_key(p, o))} matching image details"


def match_points(a, b) -> int:
    """How many image details (ORB keypoints) line up between two photos after a RANSAC perspective fit."""
    import cv2
    import numpy as np
    orb = cv2.ORB_create(1500)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None:
        return 0
    good = [m for m, n in (x for x in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2) if len(x) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return 0
    _, mask = cv2.findHomography(np.float32([ka[m.queryIdx].pt for m in good]), np.float32([kb[m.trainIdx].pt for m in good]), cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0


def _grey(data: bytes):
    import numpy as np
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
    im.thumbnail((800, 800))
    return np.asarray(im)


def confirm_pairs(engine, waiting: list[tuple[int, int]], client=None) -> int:
    """Download each look-alike pair again (in memory) and store how many image details line up."""
    import httpx
    if not waiting:
        return 0
    with session_scope(engine) as s:
        urls = dict(s.execute(select(SalesPhoto.id, SalesPhoto.url).where(SalesPhoto.id.in_({i for p in waiting for i in p}))).all())
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "HR-Portal-photo-check/1.0"})
    cache: dict[int, object] = {}
    out = []
    try:
        for a, b in waiting:
            try:
                for i in (a, b):
                    if i not in cache:
                        cache[i] = _grey(_download(client, urls[i]))
                out.append((a, b, match_points(cache[a], cache[b])))
            except Exception:
                out.append((a, b, None))
    finally:
        if own:
            client.close()
    with session_scope(engine) as s:
        for a, b, n in out:
            s.add(SalesPhotoPair(a_id=a, b_id=b, points=n))
    return len(out)


def _groups(photos: list[SalesPhoto], attr: str) -> dict[str, list[int]]:
    g: dict[str, list[int]] = defaultdict(list)
    for p in photos:
        v = getattr(p, attr)
        if v:
            g[v].append(p.id)
    return {k: v for k, v in g.items() if len(v) > 1}


def purge(session: Session, before: date) -> int:
    return session.execute(delete(SalesPhoto).where(SalesPhoto.day < before)).rowcount


# ---------------------------------------------------------------- reading
def labels(p: SalesPhoto) -> list[dict]:
    ev = json.loads(p.evidence or "{}")
    return [{"code": k, "label": PHOTO[k][0], "level": PHOTO[k][1], "why": PHOTO[k][2], "evidence": ev.get(k, ""), "kind": "photo"}
            for k in (p.flags or "").split(",") if k in PHOTO]


def photo_dict(p: SalesPhoto, session: Session | None = None, names: dict | None = None) -> dict:
    out = {"id": p.id, "url": p.url, "code": p.code, "name": (names or {}).get(p.code, p.code), "date": p.day.isoformat(),
           "att_time": p.att_time, "status": p.status, "error": p.error, "faces": p.faces, "width": p.width, "height": p.height,
           "size_kb": p.size_kb, "exif_time": p.exif_time, "signs": labels(p), "matches": []}
    if session is not None and p.evidence:
        ids = json.loads(p.evidence).get("_matches", [])
        for m in session.scalars(select(SalesPhoto).where(SalesPhoto.id.in_(ids))) if ids else []:
            out["matches"].append({"id": m.id, "url": m.url, "code": m.code, "name": (names or {}).get(m.code, m.code), "date": m.day.isoformat()})
    return out


def for_day(session: Session, code: str, day: date) -> list[dict]:
    names = {e.code: e.name for e in session.scalars(select(SalesEmployee))}
    return [photo_dict(p, session, names) for p in session.scalars(select(SalesPhoto).where(SalesPhoto.code == code, SalesPhoto.day == day))]


def overview(session: Session, start: date, end: date, visible: set[str] | None, sign: str = "") -> dict:
    status = dict(session.execute(select(SalesPhoto.status, func.count()).group_by(SalesPhoto.status)).all())
    rows = [p for p in session.scalars(select(SalesPhoto).where(SalesPhoto.day >= start, SalesPhoto.day <= end))
            if visible is None or p.code in visible]
    flagged = [p for p in rows if p.flags]
    c: Counter = Counter(k for p in flagged for k in p.flags.split(","))
    shown = [p for p in flagged if not sign or sign in p.flags.split(",")]
    shown.sort(key=lambda p: (min(LEVEL[PHOTO[k][1]] for k in p.flags.split(",")), p.day, p.code))
    names = {e.code: e.name for e in session.scalars(select(SalesEmployee))}
    return {"from": start.isoformat(), "to": end.isoformat(), "photos": len(rows), "checked": sum(1 for p in rows if p.status == DONE),
            "flagged": len(flagged), "people": len({p.code for p in flagged}),
            "queue": {"waiting": status.get(NEW, 0), "done": status.get(DONE, 0), "failed": status.get(FAILED, 0), "skipped": status.get(SKIPPED, 0)},
            "signs": [{"code": k, "label": PHOTO[k][0], "level": PHOTO[k][1], "why": PHOTO[k][2], "n": n}
                      for k, n in sorted(c.items(), key=lambda kv: (LEVEL[PHOTO[kv[0]][1]], -kv[1]))],
            "items": [photo_dict(p, session, names) for p in shown[:600]], "shown": len(shown)}


def flagged_days(session: Session, start: date, end: date) -> dict[tuple[str, date], list[SalesPhoto]]:
    out: dict[tuple[str, date], list[SalesPhoto]] = defaultdict(list)
    for p in session.scalars(select(SalesPhoto).where(SalesPhoto.day >= start, SalesPhoto.day <= end, SalesPhoto.flags.is_not(None))):
        out[(p.code, p.day)].append(p)
    return out
