"""Processing orchestration (PRD 10.5, 17.3, 19).

One run = one version of the results for a reporting date. A run is identified by its
inputs (upload hashes, rules, schemas, adjustments): repeating identical inputs returns
the existing run instead of creating duplicate official records; changed inputs create
a new version and the previous one stays recoverable (is_current = false).

Stages and states:
  CREATED -> UPLOADING (collect inputs) -> VALIDATING -> VALIDATED -> PROCESSING
  -> RECONCILING -> GENERATING_REPORTS -> [AI_PROCESSING -> AI_UNAVAILABLE] -> READY_FOR_REVIEW
  -> APPROVED (HR) -> DISTRIBUTING -> COMPLETED
A failure records FAILED with the stage; resume() restarts from the last safe stage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from contracts.processing import ProcessingState as P
from contracts.processing import validate_processing_transition
from core.config import Settings, load_attendance_rules, load_source_authority
from core.logging_setup import run_id_var
from core.timeutils import ensure_utc, now_utc
from database.connection import session_scope
from database.models.attendance import (AttendanceAdjustment, AttendanceException, AttendanceReconciliation,
                                        FactAttendanceDaily, ProcessingRun)
from database.models.audit import ProcessingLog
from database.models.hr import DimEmployee
from database.models.staging import DatasetSchema, UploadRegistry
from data_engine import exception_manager, kpi_calculator
from data_engine.attendance_processor import build_facts, current_upload_ids, gather
from data_engine.reconciliation import NEEDS_EXCEPTION, SEVERITY, reconcile

log = logging.getLogger("pipeline")

DAILY_DATASETS = ("HRMS_ATTENDANCE", "BIZOM_ATTENDANCE", "HRMS_LEAVE", "HRMS_PUNCH")
ACTIVE_STATES = {P.CREATED, P.UPLOADING, P.VALIDATING, P.VALIDATED, P.PROCESSING, P.RECONCILING,
                 P.GENERATING_REPORTS, P.AI_PROCESSING, P.DISTRIBUTING}
STALE_AFTER = timedelta(hours=1)


class PipelineError(Exception):
    pass


@dataclass
class RunResult:
    run_id: int
    run_ref: str
    state: str
    created: bool


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _input_signature(session: Session, settings: Settings, day: date) -> tuple[str, dict]:
    uploads = current_upload_ids(session, day)
    ids = sorted({i for v in uploads.values() for i in v})
    hashes = {u.upload_id: u.sha256 for u in session.scalars(select(UploadRegistry).where(UploadRegistry.upload_id.in_(ids)))} if ids else {}
    rules_text = (settings.config_dir / "attendance_rules.yaml").read_text(encoding="utf-8")
    authority_text = (settings.config_dir / "source_authority.yaml").read_text(encoding="utf-8")
    schemas = sorted((r.dataset_id, r.version) for r in session.scalars(select(DatasetSchema).where(DatasetSchema.status == "ACTIVE")))
    adjustments = sorted(a.id for a in session.scalars(select(AttendanceAdjustment).where(
        AttendanceAdjustment.attendance_date == day, AttendanceAdjustment.is_active.is_(True))))
    mappings = session.execute(select(func.count(), func.max(DimEmployee.updated_at)).select_from(DimEmployee)).one()
    from database.models.hr import EmployeeSourceMapping
    mapping_state = session.execute(select(func.count(), func.max(EmployeeSourceMapping.reviewed_at))
                                    .where(EmployeeSourceMapping.status == "VERIFIED")).one()
    inputs = {
        "reporting_date": day.isoformat(),
        "uploads": {str(k): v for k, v in sorted(hashes.items())},
        "uploads_by_dataset": {k: sorted(v) for k, v in sorted(uploads.items())},
        "rules_sha": _sha(rules_text), "authority_sha": _sha(authority_text),
        "schemas": schemas, "adjustments": adjustments,
        "employees": [mappings[0], str(mappings[1])], "verified_mappings": [mapping_state[0], str(mapping_state[1])],
    }
    return _sha(json.dumps(inputs, sort_keys=True, default=str)), inputs


class _Stage:
    """Context manager: advances the run state, times the stage, logs the outcome."""

    def __init__(self, engine: Engine, run_id: int, state: P) -> None:
        self.engine, self.run_id, self.state = engine, run_id, state
        self.count: int | None = None
        self.message: str | None = None

    def __enter__(self) -> "_Stage":
        self.t0 = time.perf_counter()
        with session_scope(self.engine) as s:
            run = s.get(ProcessingRun, self.run_id)
            run.state = validate_processing_transition(P(run.state), self.state).value
        log.info("stage started", extra={"stage": self.state.value})
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = int((time.perf_counter() - self.t0) * 1000)
        with session_scope(self.engine) as s:
            s.add(ProcessingLog(run_id=self.run_id, stage=self.state.value, outcome="FAILED" if exc else "OK",
                                duration_ms=ms, record_count=self.count,
                                message=(f"{type(exc).__name__}: {exc}" if exc else self.message or "")[:1000] or None))
        return False


def _transition(engine: Engine, run_id: int, target: P, **fields) -> None:
    with session_scope(engine) as s:
        run = s.get(ProcessingRun, run_id)
        run.state = validate_processing_transition(P(run.state), target).value
        for k, v in fields.items():
            setattr(run, k, v)


def _fail(engine: Engine, run_id: int, exc: Exception) -> None:
    with session_scope(engine) as s:
        run = s.get(ProcessingRun, run_id)
        stage = run.state
        try:
            run.state = validate_processing_transition(P(run.state), P.FAILED).value
        except Exception:
            run.state = P.FAILED.value
        run.error = f"{stage}: {type(exc).__name__}: {exc}"[:1000]
        run.finished_at = now_utc()
    log.exception("run failed", extra={"stage": stage})


def start_run(engine: Engine, settings: Settings, day: date, actor: str, *, generate_reports: bool = True) -> RunResult:
    rules = load_attendance_rules(settings.config_dir)
    with session_scope(engine) as s:
        key, inputs = _input_signature(s, settings, day)
        existing = s.scalar(select(ProcessingRun).where(ProcessingRun.reporting_date == day, ProcessingRun.input_key == key,
                                                        ProcessingRun.state.notin_([P.FAILED.value, P.CANCELLED.value]))
                            .order_by(ProcessingRun.run_id.desc()))
        if existing:
            return RunResult(existing.run_id, existing.run_ref, existing.state, created=False)
        busy = s.scalar(select(ProcessingRun).where(ProcessingRun.reporting_date == day,
                                                    ProcessingRun.state.in_([x.value for x in ACTIVE_STATES])))
        if busy and now_utc() - ensure_utc(busy.started_at) < STALE_AFTER:
            raise PipelineError(f"Run {busy.run_ref} for {day} is still in progress.")
        version = (s.scalar(select(func.max(ProcessingRun.version_no)).where(ProcessingRun.reporting_date == day)) or 0) + 1
        run = ProcessingRun(run_ref=f"RUN-{day:%Y%m%d}-v{version}", reporting_date=day, version_no=version,
                            input_key=key, inputs=json.dumps(inputs, default=str), rule_version=rules.rule_version,
                            rules_approved=rules.is_approved, state=P.CREATED.value, started_by=actor)
        s.add(run)
        s.flush()
        run_id, run_ref = run.run_id, run.run_ref
    _execute(engine, settings, run_id, from_stage=P.UPLOADING, generate_reports=generate_reports)
    with session_scope(engine) as s:
        return RunResult(run_id, run_ref, s.get(ProcessingRun, run_id).state, created=True)


def resume_run(engine: Engine, settings: Settings, run_id: int, actor: str) -> RunResult:
    """Restart a FAILED run from the last safe stage (PRD 19.3)."""
    with session_scope(engine) as s:
        run = s.get(ProcessingRun, run_id)
        if run is None or run.state != P.FAILED.value:
            raise PipelineError("Only a failed run can be resumed.")
        has_facts = s.scalar(select(func.count()).select_from(FactAttendanceDaily).where(FactAttendanceDaily.run_id == run_id))
        failed_stage = (run.error or "").split(":")[0]
        restart = P.GENERATING_REPORTS if (has_facts and failed_stage in (P.GENERATING_REPORTS.value, P.AI_PROCESSING.value)) else P.PROCESSING
        run.error = None
        s.add(ProcessingLog(run_id=run_id, stage="RESUME", outcome="OK", message=f"resumed by {actor} from {restart.value}"))
        ref = run.run_ref
    _execute(engine, settings, run_id, from_stage=restart)
    with session_scope(engine) as s:
        return RunResult(run_id, ref, s.get(ProcessingRun, run_id).state, created=False)


def _execute(engine: Engine, settings: Settings, run_id: int, from_stage: P, generate_reports: bool = True) -> None:
    token = run_id_var.set(str(run_id))
    try:
        _execute_stages(engine, settings, run_id, from_stage, generate_reports)
    except Exception as exc:  # noqa: BLE001 -- any failure is recorded, never swallowed silently
        _fail(engine, run_id, exc)
    finally:
        run_id_var.reset(token)


def _execute_stages(engine: Engine, settings: Settings, run_id: int, from_stage: P, generate_reports: bool) -> None:
    rules = load_attendance_rules(settings.config_dir)
    authority = load_source_authority(settings.config_dir)
    official = rules.is_approved and authority.approval_status == "APPROVED"
    with session_scope(engine) as s:
        day = s.get(ProcessingRun, run_id).reporting_date
    stats: dict = {}

    if from_stage is P.UPLOADING:
        with _Stage(engine, run_id, P.UPLOADING) as st, session_scope(engine) as s:
            uploads = current_upload_ids(s, day)
            st.count = sum(len(v) for k, v in uploads.items() if k != "HRMS_LEAVE_ALL")
            if not s.scalar(select(func.count()).select_from(DimEmployee)):
                raise PipelineError("No employee master has been uploaded.")
        with _Stage(engine, run_id, P.VALIDATING) as st:
            missing = [d for d in DAILY_DATASETS if not uploads.get(d)]
            stats["missing_datasets"] = missing
            st.message = f"missing daily datasets: {', '.join(missing)}" if missing else "all daily datasets present"
        _transition(engine, run_id, P.VALIDATED)

    if from_stage in (P.UPLOADING, P.PROCESSING):
        if from_stage is P.PROCESSING:
            _transition(engine, run_id, P.PROCESSING)
            with session_scope(engine) as s:     # discard partial results of the failed attempt
                for model in (AttendanceReconciliation, FactAttendanceDaily):
                    s.execute(delete(model).where(model.run_id == run_id))
                s.execute(delete(AttendanceException).where(AttendanceException.run_id == run_id))
        with (_Stage(engine, run_id, P.PROCESSING) if from_stage is P.UPLOADING else _NoTransition(engine, run_id, P.PROCESSING)) as st, \
                session_scope(engine) as s:
            uploads = current_upload_ids(s, day)
            inputs = gather(s, day, uploads, rules)
            facts = build_facts(inputs, rules, authority, official)
            s.add_all([FactAttendanceDaily(run_id=run_id, **f) for f in facts])
            st.count = len(facts)
            active = sum(1 for e in inputs.employees if not (e.exit_date and e.exit_date < day))
            stats["kpis"] = kpi_calculator.summarize([f["final_status"] for f in facts], rules, active)
            by_dept: dict[str, list[str]] = {}
            for f in facts:
                by_dept.setdefault(f["department_code"] or "UNASSIGNED", []).append(f["final_status"])
            stats["departments"] = {k: kpi_calculator.summarize(v, rules) for k, v in sorted(by_dept.items())}
        with _Stage(engine, run_id, P.RECONCILING) as st, session_scope(engine) as s:
            recon = reconcile(inputs, rules)
            adjusted = {(a.employee_key) for a in s.scalars(select(AttendanceAdjustment).where(
                AttendanceAdjustment.attendance_date == day, AttendanceAdjustment.is_active.is_(True)))}
            exceptions = 0
            for r in recon:
                s.add(AttendanceReconciliation(run_id=run_id, employee_key=r.employee_key, source_employee_id=r.source_employee_id,
                                               attendance_date=day, category=r.category, bizom_value=r.bizom_value,
                                               hrms_value=r.hrms_value, detail=r.detail[:300]))
                if r.category in {c.value for c in NEEDS_EXCEPTION} and r.employee_key not in adjusted:
                    exception_manager.create(s, run_id=run_id, employee_key=r.employee_key, source_employee_id=r.source_employee_id,
                                             department_code=r.department_code, attendance_date=day, category=r.category,
                                             severity=SEVERITY[next(c for c in NEEDS_EXCEPTION if c.value == r.category)],
                                             source_values=r.source_values())
                    exceptions += 1
            st.count = len(recon)
            counts: dict[str, int] = {}
            for r in recon:
                counts[r.category] = counts.get(r.category, 0) + 1
            matched = counts.get("MATCHED", 0)
            compared = matched + counts.get("STATUS_CONFLICT", 0)
            stats["reconciliation"] = {"counts": counts, "exceptions": exceptions,
                                       "reconciliation_rate": round(100 * matched / compared, 2) if compared else None}
        with session_scope(engine) as s:
            s.get(ProcessingRun, run_id).stats = json.dumps(stats, default=str)
        _transition(engine, run_id, P.GENERATING_REPORTS)
    else:
        _transition(engine, run_id, P.GENERATING_REPORTS)

    # ---- reports (Phase 8)
    t0 = time.perf_counter()
    report_count = 0
    if generate_reports:
        from reporting.report_manager import generate_for_run
        with session_scope(engine) as s:
            report_count = len(generate_for_run(s, settings, run_id, actor="system:pipeline"))
    with session_scope(engine) as s:
        s.add(ProcessingLog(run_id=run_id, stage=P.GENERATING_REPORTS.value, outcome="OK",
                            duration_ms=int((time.perf_counter() - t0) * 1000), record_count=report_count))

    # ---- optional AI (Phase 11): never fails the run
    if settings.features.ai_enabled:
        _transition(engine, run_id, P.AI_PROCESSING)
        from ai_engine.summary_generator import generate_run_summary
        ok = False
        try:
            with session_scope(engine) as s:
                ok = generate_run_summary(s, settings, run_id)
        except Exception:  # noqa: BLE001
            log.exception("AI summary failed")
        if ok:
            _transition(engine, run_id, P.READY_FOR_REVIEW, ai_status="GENERATED")
        else:
            _transition(engine, run_id, P.AI_UNAVAILABLE, ai_status="UNAVAILABLE")
            _transition(engine, run_id, P.READY_FOR_REVIEW)
    else:
        _transition(engine, run_id, P.READY_FOR_REVIEW, ai_status="DISABLED")

    # ---- make this the current version for the date
    with session_scope(engine) as s:
        run = s.get(ProcessingRun, run_id)
        older = [r.run_id for r in s.scalars(select(ProcessingRun).where(
            ProcessingRun.reporting_date == run.reporting_date, ProcessingRun.run_id != run_id))]
        for r in s.scalars(select(ProcessingRun).where(ProcessingRun.run_id.in_(older))):
            r.is_current = False
        exception_manager.supersede_open(s, older)
        run.is_current, run.finished_at = True, now_utc()


class _NoTransition(_Stage):
    """Stage logger for a state already entered (resume path)."""

    def __enter__(self) -> "_Stage":
        self.t0 = time.perf_counter()
        return self


def approve_run(engine: Engine, run_id: int, actor: str) -> str:
    with session_scope(engine) as s:
        run = s.get(ProcessingRun, run_id)
        if run is None:
            raise PipelineError("Run not found.")
        run.state = validate_processing_transition(P(run.state), P.APPROVED).value
        run.approved_by, run.approved_at = actor, now_utc()
        s.add(ProcessingLog(run_id=run_id, stage="APPROVAL", outcome="OK", message=f"approved by {actor}"))
        return run.state
