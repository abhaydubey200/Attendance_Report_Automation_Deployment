"""MIS reports: list (authorised only), download, approve, regenerate (PRD 11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import current_principal, get_db, get_settings, require
from core.config import Settings
from database.models.attendance import ProcessingRun
from reporting.report_manager import ReportError, decide, generate_for_run, open_report, visible_reports
from security.permissions import Perm, Principal

router = APIRouter(tags=["reports"])

MIME = {"XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "HTML": "text/html; charset=utf-8"}


def _row(r, run: ProcessingRun | None) -> dict:
    return {"report_id": r.report_id, "run_id": r.run_id, "run_ref": run.run_ref if run else None,
            "reporting_date": run.reporting_date.isoformat() if run else None, "report_type": r.report_type,
            "department_code": r.department_code, "file_format": r.file_format, "report_version": r.report_version,
            "provisional": r.provisional, "status": r.status, "generated_by": r.generated_by,
            "generated_at": r.generated_at.isoformat()}


@router.get("/reports")
def reports(run_id: int | None = None, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> list[dict]:
    rows = visible_reports(db, principal, run_id)
    runs = {r.run_id: db.get(ProcessingRun, r.run_id) for r in rows}
    return [_row(r, runs[r.run_id]) for r in rows]


@router.get("/reports/{report_id}/download")
def download(report_id: int, inline: bool = False, principal: Principal = Depends(current_principal),
             settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> Response:
    try:
        report, content = open_report(db, settings, principal, report_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found") from None
    except ReportError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    name = report.file_path.replace("\\", "/").rsplit("/", 1)[-1]
    disposition = "inline" if (inline and report.file_format == "HTML") else "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{name}"'}
    if report.file_format == "HTML":   # rendered in a sandbox: no scripts, no same-origin access
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'"
    return Response(content, media_type=MIME[report.file_format], headers=headers)


class DecisionIn(BaseModel):
    decision: str
    comment: str | None = None


@router.post("/reports/{report_id}/decision")
def decision(report_id: int, body: DecisionIn, principal: Principal = Depends(require(Perm.REPORT_APPROVE)),
             db: Session = Depends(get_db)) -> dict:
    try:
        r = decide(db, report_id, principal, body.decision, body.comment)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found") from None
    except ReportError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"report_id": r.report_id, "status": r.status}


@router.post("/runs/{run_id}/reports")
def regenerate(run_id: int, principal: Principal = Depends(require(Perm.REPORT_GENERATE)),
               settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    try:
        created = generate_for_run(db, settings, run_id, principal.username)
    except ReportError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return {"generated": len(created)}
