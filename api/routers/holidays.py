"""HR's yearly holiday list (PDF) - one list for both modules. Module 1 uses the Delhi / Head Office page; Module 2 uses
the page of each person's holiday state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db, require
from daily import holiday_list
from security.audit import record_activity
from security.permissions import Perm, Principal

router = APIRouter(prefix="/holidays", tags=["holidays"])
MAX = 10 * 1024 * 1024


def _summary(cal: dict, year: str) -> dict:
    regions = cal.get("regions", [])
    ho = next((r for r in regions if holiday_list.HEAD_OFFICE in r["states"] or "Delhi" in r["states"]), None)
    return {"year": int(year), "file": cal.get("file"), "uploaded_by": cal.get("uploaded_by"), "uploaded_at": cal.get("uploaded_at"),
            "regions": regions, "head_office": ho["holidays"] if ho else [],
            "open_issues": sum(1 for r in regions for h in r["holidays"] if h["issue"] and not h["fixed"])}


async def _read(file: UploadFile) -> dict:
    data = await file.read(MAX + 1)
    if len(data) > MAX:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The PDF is larger than 10 MB.")
    try:
        return holiday_list.read_pdf(data)
    except holiday_list.HolidayListError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("")
def holidays(_: Principal = Depends(require(Perm.VIEW_INSIGHTS)), db: Session = Depends(get_db)) -> dict:
    years = holiday_list.years(db)
    return {"years": [_summary(c, y) for y, c in sorted(years.items(), reverse=True)], "states": holiday_list.STATES}


@router.post("/preview")
async def preview(file: UploadFile = File(...), _: Principal = Depends(require(Perm.MANAGE_SETTINGS))) -> dict:
    """Read the PDF and show what was found and every problem - nothing is saved."""
    parsed = await _read(file)
    return {**parsed, "file": file.filename}


@router.post("/upload")
async def upload(file: UploadFile = File(...), principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)),
                 db: Session = Depends(get_db)) -> dict:
    """Save the year's list (replaces that year) and apply it to the Field Sales days of that year."""
    parsed = await _read(file)
    cal = holiday_list.save(db, parsed, file.filename or "holidays.pdf", principal.username)
    from sales import calendar
    applied = calendar.apply_year(db, parsed["year"], principal.username)
    record_activity(db, "HOLIDAY_LIST", "SUCCESS", username=principal.username,
                    detail={"year": parsed["year"], "regions": len(parsed["regions"]), "open_issues": parsed["open_issues"]})
    return {**_summary(cal, str(parsed["year"])), "field_sales": applied}


class FixIn(BaseModel):
    region: str
    old: str
    new: str | None = None          # None = remove the line
    name: str | None = None


@router.put("/{year}/fix")
def fix(year: int, body: FixIn, principal: Principal = Depends(require(Perm.MANAGE_SETTINGS)), db: Session = Depends(get_db)) -> dict:
    try:
        cal = holiday_list.fix(db, year, body.region, body.old, body.new, body.name, principal.username)
    except (holiday_list.HolidayListError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    from sales import calendar
    applied = calendar.apply_year(db, year, principal.username)
    return {**_summary(cal, str(year)), "field_sales": applied}
