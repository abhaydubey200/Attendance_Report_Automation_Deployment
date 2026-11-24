"""Who gets which Field Sales email, from the staff list (HR) - one email per address per day.

Levels (Settings -> levels): immediate manager, ASM/RSM, zonal head, HOD. A person appears in the email of every level
above them that has an email address, so a vacant manager position simply means their people show in the next filled
level's report. The Director gets the whole company; HR gets the company plus the data problems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from database.models.sales import SalesEmployee
from sales.config import SalesEmail, valid_email

DIRECTOR, HR = "DIRECTOR", "HR"
LEVELS = {"manager": "Team head", "asm": "ASM / RSM", "zonal": "Zonal head", "hod": "HOD"}   # manager = HR file's Sub split ID
RANK = {"manager": 0, "asm": 1, "zonal": 2, "hod": 3}


@dataclass
class Recipient:
    key: str
    name: str
    role: str
    to: list[str]
    codes: set[str] = field(default_factory=set)        # everyone in this person's scope (HOD: the whole department)
    view: str = "team"             # team | company | hr
    detail: set[str] = field(default_factory=set)       # people whose Sub split ID is this address (shown one by one)
    status: str = "PENDING"
    note: str | None = None


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", s.lower()) if len(t) >= 3]


def belongs(name: str, email: str) -> bool:
    """Does this name plausibly own this address? 'SHAKIL AHMED' ~ shakeel@, 'ASIF ALI ANSARI' ~ asifansari@,
    but 'ARUN MISHRA' is not avdhesh@ (HR's file lists the reporting manager, whose team head may be someone else)."""
    local = email.split("@")[0]
    return any(e.startswith(n[:4]) or n in e for n in _tokens(name) for e in _tokens(local))


def title(name: str | None) -> str:
    """'ASIF ALI ANSARI' -> 'Asif Ali Ansari'; spaces and non-breaking spaces tidied (brief: title-case names)."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in str(name or "").replace("\xa0", " ").split())


def same_person(a: str | None, b: str | None) -> bool:
    """'Revanasiddappa' ~ 'Revanasiddappa Patil', 'Sanjay Kumar Singh' ~ 'Sanjay Singh': same first name, one name inside the other."""
    x, y = title(a).lower().split(), title(b).lower().split()
    return bool(x and y) and x[0] == y[0] and (set(x) <= set(y) or set(y) <= set(x))


def managers(staff: dict[str, SalesEmployee]) -> set[str]:
    """Codes of the managers (the build brief's 'Role = Manager'): people who report straight to their HOD and lead a team of
    their own, or who are listed inside their own team."""
    heads = {title(e.manager_name) for e in staff.values() if e.manager_name}
    out = set()
    for c, e in staff.items():
        direct = (e.manager_email or "").strip().lower() == (e.hod_email or "").strip().lower() != ""
        if (direct and any(same_person(e.name, h) for h in heads)) or (e.manager_name and same_person(e.name, e.manager_name)):
            out.add(c)
    return out


def exceptions(codes_in_day: set[str], staff: dict[str, SalesEmployee]) -> list[dict]:
    """Records that cannot be routed safely - never guess a recipient (brief, rule 5). Each: code, name, issue, detail."""
    out = []
    hods: dict[str, set[str]] = {}
    for code in sorted(codes_in_day):
        m = staff.get(code)
        if m is None:
            out.append({"code": code, "name": "", "issue": "NOT_IN_MASTER", "detail": "Marked attendance in Bizom but is not on the staff list."})
            continue
        if not valid_email((m.manager_email or "").strip().lower()):
            out.append({"code": code, "name": title(m.name), "issue": "NO_SUB_SPLIT_ID", "detail": "No reporting email (Sub split ID) on the staff list."})
        elif title(m.name) == title(m.manager_name):
            out.append({"code": code, "name": title(m.name), "issue": "MANAGER_IN_OWN_TEAM",
                        "detail": f"Listed inside their own team ({m.manager_email}); confirm who they report to."})
        if m.manager_email:
            hods.setdefault(m.manager_email.strip().lower(), set()).add((m.hod_email or "").strip().lower())
    for email, hs in sorted(hods.items()):
        if len({h for h in hs if h}) > 1:
            out.append({"code": "", "name": email, "issue": "HOD_EMAIL_CONFLICT", "detail": f"People of {email} have different HODs: {', '.join(sorted(h for h in hs if h))}."})
    return out


def name_from_email(email: str) -> str:
    """'rajeev.saxena@...' -> 'Rajeev Saxena'."""
    return " ".join(t.capitalize() for t in re.split(r"[._\-]+", email.split("@")[0]) if t) or email


def display_name(name: str | None, email: str) -> str:
    return title(name) if name and belongs(name, email) else name_from_email(email)


def recipients(codes_in_day: set[str], staff: dict[str, SalesEmployee], cfg: SalesEmail, hr_always: bool = True) -> list[Recipient]:
    """hr_always=False (daily): the HR email is only made when exceptions() finds something to fix."""
    by_email: dict[str, Recipient] = {}
    best: dict[str, str] = {}
    for code in codes_in_day:
        m = staff.get(code)
        if m is None:
            continue
        for lvl in cfg.levels:
            email = (getattr(m, f"{lvl}_email") or "").strip().lower()
            if not valid_email(email):
                continue
            name = display_name(getattr(m, f"{lvl}_name"), email)
            r = by_email.get(email)
            if r is None:
                r = by_email[email] = Recipient(email, name, LEVELS[lvl], [email])
                best[email] = lvl
            elif RANK[lvl] > RANK[best[email]]:                   # same person at two levels: name them by the higher one
                r.role, r.name, best[email] = LEVELS[lvl], name, lvl
            r.codes.add(code)
            if lvl == "manager":
                r.detail.add(code)
    out = sorted(by_email.values(), key=lambda r: (-RANK[best[r.key]], -len(r.codes), r.name))
    for r in out:
        if not r.detail:                       # an HOD who is nobody's Sub split ID: their whole department in detail
            r.detail = set(r.codes)
    director = Recipient(DIRECTOR, cfg.director_name or "Director", "Director", list(cfg.director_emails), set(codes_in_day), "company")
    hr = Recipient(HR, "HR", "HR", list(cfg.hr_emails), set(codes_in_day), "hr")
    extra = [director] + ([hr] if hr_always or exceptions(codes_in_day, staff) else [])
    for r in extra:
        if not r.to:
            r.status, r.note = "HELD", f"{r.role} email not set (Field Sales -> Settings)."
        out.append(r)
    return out
