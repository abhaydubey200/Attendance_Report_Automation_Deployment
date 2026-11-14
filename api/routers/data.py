"""Data management API: dataset registry and schemas, uploads, upload history, data quality."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings, require
from core.config import Settings
from database.models.staging import UploadRegistry, ValidationIssue
from ingestion.dataset_registry import load_dataset_registry
from ingestion.schema_definition import DATASET_KIND, TARGET_FIELDS, VALUE_MAP_TARGETS, SchemaDefinition
from ingestion.schema_service import SchemaError, get_active_schema, list_versions, save_schema
from ingestion.upload_manager import UploadError, confirm_upload, exceptions_csv, inspect_upload, pending_exceptions_csv
from reporting import analytics
from security.authorization import has_permission
from security.permissions import Perm, Principal

router = APIRouter(tags=["data"])


@router.get("/datasets")
def datasets(_: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW)), settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for d in load_dataset_registry(settings.config_dir).datasets:
        active = get_active_schema(db, d.dataset_id)
        out.append({"dataset_id": d.dataset_id, "dataset_name": d.dataset_name, "source_system": d.source_system.value,
                    "frequency": d.frequency, "active": d.active, "kind": DATASET_KIND[d.dataset_id],
                    "schema_version": active.version if active else None,
                    "schema_status": "DEFINED" if active else "PENDING_DISCOVERY",
                    "schema": active.definition.model_dump() if active else None,
                    "schema_notes": active.notes if active else None, "schema_by": active.created_by if active else None})
    return out


@router.get("/datasets/fields")
def fields(_: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW))) -> dict:
    return {"kinds": {k: [{"field": f, "type": t, "required": r} for f, (t, r) in v.items()] for k, v in TARGET_FIELDS.items()},
            "dataset_kind": DATASET_KIND, "value_maps": {k: sorted(v) for k, v in VALUE_MAP_TARGETS.items()}}


@router.get("/datasets/{dataset_id}/schemas")
def schema_versions(dataset_id: str, _: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"version": v.version, "status": v.status, "definition": json.loads(v.definition), "notes": v.notes,
             "created_by": v.created_by, "created_at": v.created_at.isoformat()} for v in list_versions(db, dataset_id)]


class SchemaIn(BaseModel):
    definition: dict
    notes: str | None = None


@router.post("/datasets/{dataset_id}/schemas")
def define_schema(dataset_id: str, body: SchemaIn, principal: Principal = Depends(require(Perm.DATA_REGISTRY_MANAGE)),
                  db: Session = Depends(get_db)) -> dict:
    if dataset_id not in DATASET_KIND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown dataset")
    try:
        definition = SchemaDefinition.model_validate(body.definition)
        saved = save_schema(db, dataset_id, definition, principal.username, body.notes)
    except (ValidationError, SchemaError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc).splitlines()[0][:500]) from None
    return {"dataset_id": dataset_id, "version": saved.version}


@router.post("/uploads/inspect")
async def inspect(request: Request, file: UploadFile = File(...), dataset_id: str = Form(...), source_system: str = Form(...),
                  reporting_date: date = Form(...), sheet: str | None = Form(None), header_row: int = Form(1),
                  principal: Principal = Depends(require(Perm.DATA_UPLOAD)), settings: Settings = Depends(get_settings),
                  db: Session = Depends(get_db)) -> dict:
    limit = settings.uploads.max_file_size_mb * 1024 * 1024
    data = await file.read(limit + 1)
    try:
        return inspect_upload(db, settings, load_dataset_registry(settings.config_dir), filename=file.filename or "upload",
                              data=data, dataset_id=dataset_id, source_system=source_system, reporting_date=reporting_date,
                              sheet=sheet or None, header_row=header_row, actor=principal.username)
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


class ConfirmIn(BaseModel):
    acknowledge_review: bool = False
    supersede: bool = False
    reprocess: bool = False


@router.post("/uploads/{token}/confirm")
def confirm(token: str, body: ConfirmIn, principal: Principal = Depends(require(Perm.DATA_UPLOAD)),
            settings: Settings = Depends(get_settings), db: Session = Depends(get_db)) -> dict:
    try:
        up = confirm_upload(db, settings, load_dataset_registry(settings.config_dir), token=token, actor=principal.username,
                            acknowledge_review=body.acknowledge_review, supersede=body.supersede, reprocess=body.reprocess,
                            can_reprocess=has_permission(principal, Perm.DATA_REGISTRY_MANAGE))
    except UploadError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _upload_row(up)


@router.get("/uploads/pending/{token}/exceptions.csv", response_class=PlainTextResponse)
def pending_exceptions(token: str, _: Principal = Depends(require(Perm.DATA_UPLOAD)), settings: Settings = Depends(get_settings),
                       db: Session = Depends(get_db)) -> PlainTextResponse:
    try:
        text = pending_exceptions_csv(settings, db, load_dataset_registry(settings.config_dir), token)
    except UploadError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return PlainTextResponse(text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="exceptions.csv"'})


def _upload_row(u: UploadRegistry) -> dict:
    return {"upload_id": u.upload_id, "dataset_id": u.dataset_id, "source_system": u.source_system,
            "reporting_date": u.reporting_date.isoformat(), "original_filename": u.original_filename, "sha256": u.sha256,
            "size_bytes": u.size_bytes, "file_type": u.file_type, "sheet_name": u.sheet_name, "schema_version": u.schema_version,
            "status": u.status, "validation_status": u.validation_status, "total_rows": u.total_rows, "valid_rows": u.valid_rows,
            "invalid_rows": u.invalid_rows, "duplicate_rows": u.duplicate_rows, "warning_count": u.warning_count,
            "standardized_rows": u.standardized_rows, "is_current": u.is_current, "reprocess_of": u.reprocess_of,
            "superseded_by": u.superseded_by, "uploaded_by": u.uploaded_by, "uploaded_at": u.uploaded_at.isoformat()}


@router.get("/uploads")
def history(dataset_id: str | None = None, start: date | None = None, end: date | None = None,
            _: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    q = select(UploadRegistry).order_by(UploadRegistry.upload_id.desc()).limit(500)
    if dataset_id:
        q = q.where(UploadRegistry.dataset_id == dataset_id)
    if start:
        q = q.where(UploadRegistry.reporting_date >= start)
    if end:
        q = q.where(UploadRegistry.reporting_date <= end)
    return [_upload_row(u) for u in db.scalars(q)]


@router.get("/uploads/{upload_id}")
def upload_detail(upload_id: int, _: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW)), db: Session = Depends(get_db)) -> dict:
    u = db.get(UploadRegistry, upload_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    issues = [{"row_number": i.row_number, "column_name": i.column_name, "code": i.code, "severity": i.severity, "message": i.message}
              for i in db.scalars(select(ValidationIssue).where(ValidationIssue.upload_id == upload_id).limit(500))]
    return {**_upload_row(u), "issues": issues}


@router.get("/uploads/{upload_id}/exceptions.csv", response_class=PlainTextResponse)
def upload_exceptions(upload_id: int, _: Principal = Depends(require(Perm.DATA_REGISTRY_VIEW)), db: Session = Depends(get_db)):
    if db.get(UploadRegistry, upload_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    return PlainTextResponse(exceptions_csv(db, upload_id), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="upload_{upload_id}_exceptions.csv"'})


@router.get("/data-quality")
def data_quality(start: date = Query(...), end: date = Query(...), _: Principal = Depends(require(Perm.DATA_QUALITY_VIEW)),
                 db: Session = Depends(get_db)) -> dict:
    try:
        return analytics.data_quality(db, start, end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
