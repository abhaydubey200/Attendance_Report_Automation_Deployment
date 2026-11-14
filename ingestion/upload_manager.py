"""Two-step manual upload (PRD 5.4-5.8): inspect + validate + preview, then confirm.

Nothing enters processing until a user confirms a non-rejected file. The original
file is archived unchanged (read-only) and every standardized record links back to
its upload.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from contracts.base import SourceSystem
from contracts.processing import UploadState, validate_upload_transition
from core.config import Settings
from core.timeutils import now_utc
from database.models.staging import UploadRegistry, UploadRow, ValidationIssue
from data_engine import normalizer
from ingestion.adapters.base_adapter import adapter_for
from ingestion.checksum import sha256_bytes
from ingestion.dataset_registry import DatasetRegistry
from ingestion.file_inspector import inspect_file, safe_filename
from ingestion.file_reader import ReadError, Table, read_for_dataset
from ingestion.schema_definition import DATASET_KIND
from ingestion.schema_service import get_active_schema
from ingestion.validator import MAX_STORED_ISSUES, ValidationResult, ValidationStatus, validate_table
from security.audit import record_activity

PENDING_TTL = timedelta(hours=2)
PREVIEW_ROWS = 20


class UploadError(Exception):
    """A user-facing reason the upload cannot proceed."""


def _pending_dir(settings: Settings) -> Path:
    path = settings.storage.area("uploads") / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_pending(settings: Settings) -> int:
    removed = 0
    for entry in _pending_dir(settings).iterdir():
        meta = entry / "meta.json"
        try:
            created = datetime.fromisoformat(json.loads(meta.read_text())["created_at"])
        except (OSError, ValueError, KeyError):
            created = None
        if created is None or now_utc() - created > PENDING_TTL:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def _profile(table: Table) -> list[dict]:
    profile = []
    for col in table.columns:
        values = [r.get(col, "") for r in table.rows]
        non_blank = [v for v in values if v]
        samples = list(dict.fromkeys(non_blank))[:12]
        profile.append({"column": col, "blank": len(values) - len(non_blank), "distinct": len(set(non_blank)),
                        "samples": samples})
    return profile


def _validate(session: Session, registry: DatasetRegistry, dataset_id: str, table: Table, reporting_date: date):
    schema = get_active_schema(session, dataset_id)
    if schema is None:
        return None, None
    daily = registry.get(dataset_id).frequency == "DAILY"
    return schema, validate_table(table, dataset_id, schema.definition, reporting_date, daily)


def _check_dataset(registry: DatasetRegistry, dataset_id: str, source_system: str) -> None:
    try:
        ds = registry.get(dataset_id)
    except KeyError:
        raise UploadError(f"Unknown dataset '{dataset_id}'.") from None
    if not ds.active:
        raise UploadError(f"Dataset '{dataset_id}' is not active.")
    if ds.source_system.value != source_system:
        raise UploadError(f"Dataset '{dataset_id}' comes from {ds.source_system.value}, not {source_system}.")


def inspect_upload(
    session: Session, settings: Settings, registry: DatasetRegistry, *, filename: str, data: bytes,
    dataset_id: str, source_system: str, reporting_date: date, sheet: str | None, header_row: int, actor: str,
) -> dict:
    _check_dataset(registry, dataset_id, source_system)
    ext_allowed = tuple(settings.uploads.allowed_extensions)
    inspection = inspect_file(filename, data, ext_allowed, settings.uploads.max_file_size_mb * 1024 * 1024)
    if not inspection.ok:
        return {"accepted": False, "errors": inspection.errors}
    try:
        table = read_for_dataset(data, inspection.file_type, dataset_id, sheet, header_row)
    except ReadError as exc:
        return {"accepted": False, "errors": [str(exc)]}

    sha = sha256_bytes(data)
    duplicate = session.scalar(select(UploadRegistry).where(UploadRegistry.sha256 == sha).order_by(UploadRegistry.upload_id.desc()))
    current = session.scalar(select(UploadRegistry).where(
        UploadRegistry.dataset_id == dataset_id, UploadRegistry.reporting_date == reporting_date,
        UploadRegistry.is_current.is_(True)))
    schema, result = _validate(session, registry, dataset_id, table, reporting_date)

    cleanup_pending(settings)
    token = secrets.token_urlsafe(18)
    folder = _pending_dir(settings) / token
    folder.mkdir()
    (folder / "file.bin").write_bytes(data)
    (folder / "meta.json").write_text(json.dumps({
        "filename": safe_filename(filename), "dataset_id": dataset_id, "source_system": source_system,
        "reporting_date": reporting_date.isoformat(), "sheet": sheet or (table.sheets[0] if table.sheets else None),
        "header_row": header_row, "sha256": sha, "size": len(data), "file_type": inspection.file_type,
        "created_at": now_utc().isoformat(), "actor": actor,
    }))

    validation = None
    if result is not None:
        validation = {**result.summary(), "issues": [i.as_dict() for i in result.issues[:200]]}
    return {
        "accepted": True,
        "token": token,
        "file_type": inspection.file_type,
        "sha256": sha,
        "sheets": table.sheets,
        "sheet": sheet or (table.sheets[0] if table.sheets else None),
        "columns": table.columns,
        "row_count": len(table.rows),
        "preview": table.rows[:PREVIEW_ROWS],
        "profile": _profile(table),
        "schema_version": schema.version if schema else None,
        "schema_defined": schema is not None,
        "validation": validation,
        "duplicate_of": {"upload_id": duplicate.upload_id, "uploaded_at": duplicate.uploaded_at.isoformat(),
                         "dataset_id": duplicate.dataset_id} if duplicate else None,
        "current_upload": {"upload_id": current.upload_id, "original_filename": current.original_filename} if current else None,
        "can_confirm": bool(schema and result and result.status is not ValidationStatus.REJECTED),
    }


def _load_pending(settings: Settings, token: str) -> tuple[Path, dict, bytes]:
    if not token or not token.replace("-", "").replace("_", "").isalnum():
        raise UploadError("Invalid upload reference.")
    folder = _pending_dir(settings) / token
    try:
        meta = json.loads((folder / "meta.json").read_text())
        data = (folder / "file.bin").read_bytes()
    except OSError:
        raise UploadError("This upload preview has expired; upload the file again.") from None
    if now_utc() - datetime.fromisoformat(meta["created_at"]) > PENDING_TTL:
        shutil.rmtree(folder, ignore_errors=True)
        raise UploadError("This upload preview has expired; upload the file again.")
    return folder, meta, data


def _archive(settings: Settings, meta: dict, data: bytes, upload_id: int) -> Path:
    folder = settings.storage.area("raw") / meta["dataset_id"] / meta["reporting_date"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{upload_id:06d}_{meta['sha256'][:12]}_{meta['filename']}"
    target.write_bytes(data)
    os.chmod(target, stat.S_IREAD)       # immutable raw copy (PRD 5.8)
    return target


def confirm_upload(
    session: Session, settings: Settings, registry: DatasetRegistry, *, token: str, actor: str,
    acknowledge_review: bool = False, supersede: bool = False, reprocess: bool = False, can_reprocess: bool = False,
) -> UploadRegistry:
    folder, meta, data = _load_pending(settings, token)
    dataset_id, reporting_date = meta["dataset_id"], date.fromisoformat(meta["reporting_date"])
    _check_dataset(registry, dataset_id, meta["source_system"])

    state = UploadState.FILE_SELECTED
    state = validate_upload_transition(state, UploadState.FILE_INSPECTION)
    table = read_for_dataset(data, meta["file_type"], dataset_id, meta["sheet"], meta["header_row"])
    state = validate_upload_transition(state, UploadState.SCHEMA_VALIDATION)
    schema, result = _validate(session, registry, dataset_id, table, reporting_date)
    if schema is None:
        raise UploadError("This dataset has no approved column schema yet. Define it in the Dataset Registry first.")
    state = validate_upload_transition(state, UploadState.CONTENT_VALIDATION)
    assert result is not None
    if result.status is ValidationStatus.REJECTED:
        raise UploadError("The file failed validation and cannot be accepted. Download the exceptions and correct the file.")
    state = validate_upload_transition(state, UploadState.PREVIEW)
    if result.status is ValidationStatus.REQUIRES_REVIEW and not acknowledge_review:
        raise UploadError("The file has warnings or invalid rows. Review them and confirm again to accept the valid rows.")
    state = validate_upload_transition(state, UploadState.USER_CONFIRMATION)

    duplicate = session.scalar(select(UploadRegistry).where(UploadRegistry.sha256 == meta["sha256"])
                               .order_by(UploadRegistry.upload_id.desc()))
    if duplicate and not reprocess:
        raise UploadError(f"This exact file was already uploaded (upload #{duplicate.upload_id}). "
                          "Use controlled reprocessing if it must be processed again.")
    if duplicate and reprocess and not can_reprocess:
        raise UploadError("You are not authorised to reprocess an existing file.")
    current = session.scalar(select(UploadRegistry).where(
        UploadRegistry.dataset_id == dataset_id, UploadRegistry.reporting_date == reporting_date,
        UploadRegistry.is_current.is_(True)))
    if current and not (supersede or reprocess):
        raise UploadError(f"Upload #{current.upload_id} is already current for {dataset_id} on {reporting_date}. "
                          "Confirm that this file supersedes it.")

    upload = UploadRegistry(
        dataset_id=dataset_id, source_system=meta["source_system"], reporting_date=reporting_date,
        original_filename=meta["filename"], stored_path="", sha256=meta["sha256"], size_bytes=meta["size"],
        file_type=meta["file_type"], sheet_name=meta["sheet"], header_row=meta["header_row"],
        schema_version=schema.version, status=state.value, validation_status=result.status.value,
        total_rows=result.total_rows, valid_rows=result.valid_rows, invalid_rows=result.invalid_rows,
        duplicate_rows=result.duplicate_rows, warning_count=result.warning_count, is_current=True,
        reprocess_of=duplicate.upload_id if (duplicate and reprocess) else None, uploaded_by=actor,
    )
    session.add(upload)
    session.flush()
    if current:
        current.is_current, current.superseded_by = False, upload.upload_id

    _store_raw_rows(session, upload.upload_id, table, result)
    state = validate_upload_transition(state, UploadState.RAW_FILE_ARCHIVE)
    upload.stored_path = str(_archive(settings, meta, data, upload.upload_id))
    state = validate_upload_transition(state, UploadState.UPLOAD_REGISTERED)

    stats = standardize(session, upload, result)
    upload.standardized_rows = stats.get("records", stats.get("created", 0) + stats.get("updated", 0)
                                         + stats.get("departments", 0) + stats.get("holidays", 0)
                                         + stats.get("hierarchy_changes", 0))
    upload.status = validate_upload_transition(state, UploadState.READY_FOR_PROCESSING).value
    record_activity(session, "UPLOAD_CONFIRM", "SUCCESS", username=actor, detail={
        "upload_id": upload.upload_id, "dataset_id": dataset_id, "reporting_date": reporting_date.isoformat(),
        "valid_rows": result.valid_rows, "invalid_rows": result.invalid_rows, "superseded": current.upload_id if current else None,
        "reprocess_of": upload.reprocess_of, "standardized": stats,
    })
    session.flush()
    shutil.rmtree(folder, ignore_errors=True)
    return upload


def _store_raw_rows(session: Session, upload_id: int, table: Table, result: ValidationResult) -> None:
    for raw, number in zip(table.rows, table.row_numbers):
        if not any(v.strip() for v in raw.values()):
            continue
        session.add(UploadRow(upload_id=upload_id, row_number=number, data=json.dumps(raw, ensure_ascii=False),
                              is_valid=number not in result.invalid_row_numbers))
    for issue in result.issues[:MAX_STORED_ISSUES]:
        session.add(ValidationIssue(upload_id=upload_id, row_number=issue.row_number, column_name=issue.column_name,
                                    code=issue.code, severity=issue.severity.value, message=issue.message[:500]))
    session.flush()


def standardize(session: Session, upload: UploadRegistry, result: ValidationResult) -> dict:
    """Adapters -> contracts -> standardized tables (Phase 4)."""
    adapter = adapter_for(upload.dataset_id, SourceSystem(upload.source_system), upload.upload_id)
    output = adapter.run(result.typed_rows)
    for row_number, reason in output.rejected:
        session.add(ValidationIssue(upload_id=upload.upload_id, row_number=row_number, code="CONTRACT_REJECTED",
                                    severity="ERROR", message=reason[:500]))
    kind = DATASET_KIND[upload.dataset_id]
    if kind == "EMPLOYEE":
        stats = normalizer.save_employee_master(session, output.records, upload.reporting_date, upload.upload_id)
    elif kind == "DEPARTMENT":
        stats = normalizer.save_departments(session, output.records, upload.upload_id)
    elif kind == "HIERARCHY":
        stats = normalizer.save_hierarchy(session, output.records, upload.reporting_date, upload.upload_id)
    elif kind == "HOLIDAY":
        stats = normalizer.save_holidays(session, output.records, upload.upload_id)
    elif kind == "ATTENDANCE_SUMMARY":
        stats = normalizer.save_attendance_summary(session, output.records, upload.reporting_date, upload.upload_id)
    elif kind == "ATTENDANCE":
        names = {r.values["source_employee_id"]: r.values.get("source_employee_name") for r in result.typed_rows}
        stats = normalizer.save_attendance(session, output.records, names, upload.upload_id)
    elif kind == "LEAVE":
        stats = normalizer.save_leave(session, output.records, upload.upload_id)
    else:
        stats = normalizer.save_punches(session, output.records, upload.upload_id)
    stats["contract_rejected"] = len(output.rejected)
    return stats


def exceptions_csv(session: Session, upload_id: int) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row_number", "column", "severity", "code", "message"])
    for i in session.scalars(select(ValidationIssue).where(ValidationIssue.upload_id == upload_id)
                             .order_by(ValidationIssue.row_number, ValidationIssue.issue_id)):
        writer.writerow([i.row_number or "", i.column_name or "", i.severity, i.code, i.message])
    return buf.getvalue()


def pending_exceptions_csv(settings: Settings, session: Session, registry: DatasetRegistry, token: str) -> str:
    """Exceptions for a file that was inspected but not confirmed (e.g. rejected)."""
    import csv
    import io

    _, meta, data = _load_pending(settings, token)
    table = read_for_dataset(data, meta["file_type"], meta["dataset_id"], meta["sheet"], meta["header_row"])
    _, result = _validate(session, registry, meta["dataset_id"], table, date.fromisoformat(meta["reporting_date"]))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row_number", "column", "severity", "code", "message"])
    for i in (result.issues if result else []):
        writer.writerow([i.row_number or "", i.column_name or "", i.severity.value, i.code, i.message])
    return buf.getvalue()
