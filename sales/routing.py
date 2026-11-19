"""Who gets which Field Sales email, from the staff list (HR) - one email per address per day.

Levels (Settings -> levels): immediate manager, ASM/RSM, zonal head, HOD. A person appears in the email of every level
above them that has an email address, so a vacant manager position simply means their people show in the next filled
level's report. The Director gets the whole company; HR gets the company plus the data problems.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from database.models.sales import SalesEmployee
from sales.config import SalesEmail, valid_email

DIRECTOR, HR = "DIRECTOR", "HR"
LEVELS = {"manager": "Manager", "asm": "ASM / RSM", "zonal": "Zonal head", "hod": "HOD"}
RANK = {"manager": 0, "asm": 1, "zonal": 2, "hod": 3}


@dataclass
class Recipient:
    key: str
    name: str
    role: str
    to: list[str]
    codes: set[str] = field(default_factory=set)
    view: str = "team"             # team | company | hr
    status: str = "PENDING"
    note: str | None = None


def recipients(codes_in_day: set[str], staff: dict[str, SalesEmployee], cfg: SalesEmail) -> list[Recipient]:
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
            name = getattr(m, f"{lvl}_name") or email.split("@")[0]
            r = by_email.get(email)
            if r is None:
                r = by_email[email] = Recipient(email, name, LEVELS[lvl], [email])
                best[email] = lvl
            elif RANK[lvl] > RANK[best[email]]:                   # same person at two levels: name them by the higher one
                r.role, r.name, best[email] = LEVELS[lvl], name, lvl
            r.codes.add(code)
    out = sorted(by_email.values(), key=lambda r: (-RANK[best[r.key]], -len(r.codes), r.name))
    director = Recipient(DIRECTOR, cfg.director_name or "Director", "Director", list(cfg.director_emails), set(codes_in_day), "company")
    hr = Recipient(HR, "HR", "HR", list(cfg.hr_emails), set(codes_in_day), "hr")
    for r in (director, hr):
        if not r.to:
            r.status, r.note = "HELD", f"{r.role} email not set (Field Sales -> Settings)."
        out.append(r)
    return out
