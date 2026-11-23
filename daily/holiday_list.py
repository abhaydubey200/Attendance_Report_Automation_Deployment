"""HR's yearly holiday list (PDF), shared by both modules.

HR issues one PDF a year with one page per region ("UP/MP/.../Delhi/HO", "Plant/Uttrakhand", "Maharashtra/Goa", ...).
Each page has a table: Sr No, Month, Date, Day, Festivals. The app reads every page, checks every line and keeps the list:

* Module 1 (Head Office) uses the Delhi / HO page only - everyone sits in the Delhi Head Office.
* Module 2 (Field Sales) uses the page of each person's holiday state.

Checks (nothing is guessed): the date must be that year and fall on the weekday written next to it, the month column must
match, and a date may appear once per region. A year typo is corrected only when the weekday proves it (e.g. "11-Aug-25
Tuesday" on the 2026 list = 11-Aug-2026, a Tuesday); a date that does not match its weekday is kept as written and flagged
for HR to confirm or correct before it is relied on.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

KEY = "holiday_calendar"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
HEAD_OFFICE = "Head Office"
PLANT = "Plant"

# names written in HR's list -> one spelling (the Field Sales "holiday state" uses the same names)
STATE_ALIASES = {
    "up": "Uttar Pradesh", "uttar pradesh": "Uttar Pradesh", "mp": "Madhya Pradesh", "madhya pradesh": "Madhya Pradesh",
    "chhattisgarh": "Chhattisgarh", "chattisgarh": "Chhattisgarh", "himachal": "Himachal Pradesh", "himachal pradesh": "Himachal Pradesh",
    "punjab": "Punjab", "haryana": "Haryana", "j&k": "Jammu and Kashmir", "jammu and kashmir": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir", "orissa": "Odisha", "odisha": "Odisha", "delhi": "Delhi", "new delhi": "Delhi",
    "ho": HEAD_OFFICE, "head office": HEAD_OFFICE, "plant": PLANT, "uttrakhand": "Uttarakhand", "uttarakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand", "maharashtra": "Maharashtra", "goa": "Goa", "tamil nadu": "Tamil Nadu", "tamilnadu": "Tamil Nadu",
    "andhra pradesh": "Andhra Pradesh", "telangana": "Telangana", "karnataka": "Karnataka", "kerala": "Kerala",
    "jharkhand": "Jharkhand", "bihar": "Bihar", "west bengal": "West Bengal", "assam": "Assam", "gujrat": "Gujarat",
    "gujarat": "Gujarat", "rajasthan": "Rajasthan", "chandigarh": "Chandigarh", "puducherry": "Puducherry", "pondicherry": "Puducherry",
    # not on HR's 2026 pages - can still be chosen as a person's state (then only HR's own decisions apply to them)
    "meghalaya": "Meghalaya", "tripura": "Tripura", "manipur": "Manipur", "nagaland": "Nagaland", "mizoram": "Mizoram",
    "arunachal pradesh": "Arunachal Pradesh", "sikkim": "Sikkim",
}
STATES = sorted({v for v in STATE_ALIASES.values() if v not in (HEAD_OFFICE, PLANT)})

_ROW = re.compile(r"^\s*(\d+)\s+(" + "|".join(MONTHS) + r")\s+(\d{1,2}-[A-Za-z]{3}-\d{2,4})\s+(" + "|".join(DAYS) + r")\s+(.+?)\s*$")


class HolidayListError(ValueError):
    """Shown to the user as-is."""


def region_states(region: str) -> list[str]:
    """'UP/MP/Chhattisgarh/.../J&K/Orissa/Delhi/HO' -> ['Uttar Pradesh', ..., 'Delhi', 'Head Office']. Unknown names are kept."""
    text = region.replace("J&K", "J_K").replace("j&k", "J_K")
    parts = re.split(r"[/,&]| and ", text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p.replace("J_K", "J&K")).strip()
        if p:
            name = STATE_ALIASES.get(p.lower(), p)
            if name not in out:
                out.append(name)
    return out


def _date(text: str) -> date:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise HolidayListError(f"Unreadable date '{text}'.")


def parse_pages(pages: list[str]) -> dict:
    """Text of each PDF page -> {year, regions: [{name, states, holidays: [{date, name, day, issue, fixed}]}], issues}."""
    regions, years = [], set()
    for n, text in enumerate(pages, start=1):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        head = next((i for i, ln in enumerate(lines) if re.match(r"HOLIDAY LIST\s+\d{4}", ln, re.I)), None)
        if head is None:
            continue
        year = int(re.search(r"(\d{4})", lines[head]).group(1))
        years.add(year)
        end = next((i for i in range(head + 1, len(lines)) if lines[i].lower().startswith("holidays list for")), None)
        name = " ".join(lines[head + 1:end]).strip() if end else ""
        if not name:
            raise HolidayListError(f"Page {n}: the region (e.g. 'Maharashtra/Goa') could not be read.")
        hols, seen = [], {}
        for ln in lines[(end or head) + 1:]:
            m = _ROW.match(ln)
            if not m:
                continue
            _, month, dtext, day, fest = m.groups()
            d = _date(dtext)
            issue, fixed = None, False
            if d.year != year:
                alt = date(year, d.month, d.day)
                if DAYS[alt.weekday()] == day:
                    issue, fixed = f"Written as {dtext}; {alt:%d-%b-%Y} is a {day} as written - read as {alt:%d-%b-%Y}.", True
                    d = alt
                else:
                    issue = f"Written as {dtext}, not in {year} - check with HR."
            if not fixed and issue is None and DAYS[d.weekday()] != day:
                issue = f"{d:%d-%b-%Y} is a {DAYS[d.weekday()]}, the list says {day} - confirm the date with HR."
            if issue is None and MONTHS[d.month - 1] != month:
                issue = f"Month column says {month}, the date is in {MONTHS[d.month - 1]} - confirm with HR."
            if d in seen:
                issue = (issue + " " if issue else "") + f"Same date as '{seen[d]}' - listed twice."
            seen[d] = fest
            hols.append({"date": d.isoformat(), "name": re.sub(r"\s+", " ", fest), "day": day, "issue": issue, "fixed": fixed})
        if not hols:
            raise HolidayListError(f"Page {n} ({name}): no holiday rows found (expected Sr No, Month, Date, Day, Festivals).")
        regions.append({"name": name, "states": region_states(name), "page": n, "holidays": sorted(hols, key=lambda h: h["date"])})
    if not regions:
        raise HolidayListError("No holiday list found - expected pages titled 'HOLIDAY LIST <year>' with a Date / Day / Festivals table.")
    if len(years) != 1:
        raise HolidayListError(f"The PDF mixes several years: {sorted(years)}.")
    issues = [{"region": r["name"], **h} for r in regions for h in r["holidays"] if h["issue"]]
    return {"year": years.pop(), "regions": regions, "issues": issues,
            "open_issues": sum(1 for i in issues if not i["fixed"])}


def read_pdf(data: bytes) -> dict:
    if not data.startswith(b"%PDF"):
        raise HolidayListError("This is not a PDF file.")
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise HolidayListError("The PDF is password-protected.")
        pages = [p.extract_text() or "" for p in reader.pages[:60]]
    except HolidayListError:
        raise
    except Exception as exc:                                   # malformed PDF: never crash the screen
        raise HolidayListError(f"The PDF could not be read ({type(exc).__name__}).") from None
    return parse_pages(pages)


# ---------------------------------------------------------------- stored calendar (app_setting)
def _all(session: Session) -> dict:
    from daily.settings_store import _get
    return _get(session, KEY) or {}


def save(session: Session, parsed: dict, filename: str, actor: str) -> dict:
    from core.timeutils import now_utc
    from daily.settings_store import _put as set_value
    data = _all(session)
    data[str(parsed["year"])] = {"file": filename[:200], "uploaded_by": actor, "uploaded_at": now_utc().isoformat(),
                                 "regions": parsed["regions"]}
    set_value(session, KEY, data, actor)
    return data[str(parsed["year"])]


def years(session: Session) -> dict:
    return _all(session)


def fix(session: Session, year: int, region: str, old: str, new: str | None, name: str | None, actor: str) -> dict:
    """HR corrects one line: a new date (the issue is cleared, noting who confirmed it) or removes it (new=None)."""
    from daily.settings_store import _put as set_value
    data = _all(session)
    cal = data.get(str(year))
    r = next((x for x in (cal or {}).get("regions", []) if x["name"] == region), None)
    h = next((x for x in (r or {}).get("holidays", []) if x["date"] == old), None)
    if h is None:
        raise HolidayListError("That holiday is not in the saved list.")
    if new is None:
        r["holidays"].remove(h)
    else:
        d = date.fromisoformat(new)
        if d.year != year:
            raise HolidayListError(f"The date must be in {year}.")
        h["date"], h["day"], h["fixed"] = d.isoformat(), DAYS[d.weekday()], True
        h["issue"] = f"Confirmed by {actor} as {d:%d-%b-%Y} ({DAYS[d.weekday()]})."
        if name:
            h["name"] = name.strip()[:80]
        r["holidays"].sort(key=lambda x: x["date"])
    set_value(session, KEY, data, actor)
    return cal


def region_for(cal: dict, state: str) -> dict | None:
    return next((r for r in cal.get("regions", []) if state in r["states"]), None)


def holidays_on(session: Session, day: date, state: str) -> str | None:
    """The holiday name on `day` for a state ('Delhi', 'Karnataka', HEAD_OFFICE ...) from the saved list, else None.
    A line still waiting for HR's confirmation (date / weekday mismatch) is not used."""
    cal = _all(session).get(str(day.year))
    r = region_for(cal or {}, state)
    if not r:
        return None
    h = next((x for x in r["holidays"] if x["date"] == day.isoformat()), None)
    return h["name"] if h and (not h["issue"] or h["fixed"]) else None


def company_holiday(session: Session, day: date) -> str | None:
    """A date that is a (confirmed) holiday on every page of HR's list for that year, e.g. Independence Day."""
    cal = _all(session).get(str(day.year))
    regions = (cal or {}).get("regions", [])
    names = []
    for r in regions:
        h = next((x for x in r["holidays"] if x["date"] == day.isoformat() and (not x["issue"] or x["fixed"])), None)
        if h is None:
            return None
        names.append(h["name"])
    return min(names, key=len) if names else None


def head_office_holiday(session: Session, day: date) -> str | None:
    """Module 1: the Delhi / Head Office page only (everyone sits in the Delhi Head Office)."""
    return holidays_on(session, day, HEAD_OFFICE) or holidays_on(session, day, "Delhi")
