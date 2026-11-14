"""Report distribution (PRD 13.3-13.5).

REPORT_GENERATED -> REPORT_PREVIEW -> HR_APPROVAL -> RECIPIENT_VALIDATION -> EMAIL_DISTRIBUTION -> DELIVERY_AUDIT

Guards: only APPROVED reports of an APPROVED run; attachments re-verified against
their stored checksum; one delivery per (report, recipient); retries for transient
errors; every attempt logged. Real delivery additionally needs features.email_enabled
(production only) and recipients.yaml approved by HR; otherwise the outbox (test mode)
is used and nothing leaves the machine.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from contracts.processing import ProcessingState as P
from contracts.processing import validate_processing_transition
from core.config import Settings, load_recipients
from core.timeutils import now_utc
from database.models.attendance import ProcessingRun
from database.models.audit import EmailDeliveryLog
from database.models.reporting import ReportRegistry
from email_engine.email_client import Attachment, Message, TransportError, build_transport
from ingestion.checksum import sha256_bytes
from security.audit import record_activity

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class DistributionError(Exception):
    pass


@dataclass
class DistributionResult:
    mode: str
    sent: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    problems: list[str] = field(default_factory=list)


def recipients_for(report: ReportRegistry, recipients: dict) -> list[str]:
    if report.report_type == "HOD":
        return list((recipients.get("hod_reports") or {}).get(report.department_code or "", []))
    if report.report_type == "DIRECTORS":
        return list(recipients.get("directors_reports") or [])
    return list(recipients.get("hr_operational") or [])


def distribute(session: Session, settings: Settings, run_id: int, actor: str, sleep=time.sleep) -> DistributionResult:
    run = session.get(ProcessingRun, run_id)
    if run is None:
        raise DistributionError("Run not found.")
    if run.state not in (P.APPROVED.value, P.DELIVERY_FAILED.value):
        raise DistributionError("The run must be approved by HR before distribution.")
    live = settings.features.email_enabled and settings.email.transport != "outbox"
    recipients = load_recipients(settings.config_dir)
    if live and recipients.get("approval_status") != "APPROVED":
        raise DistributionError("Recipient lists are not approved by HR (config/recipients.yaml).")
    if live and not settings.email.sender:
        raise DistributionError("No sender address is configured (email.sender).")

    reports = list(session.scalars(select(ReportRegistry).where(
        ReportRegistry.run_id == run_id, ReportRegistry.file_format == "XLSX", ReportRegistry.status.in_(["APPROVED", "DISTRIBUTED"]))))
    if not reports:
        raise DistributionError("No approved XLSX reports to distribute for this run.")

    transport = build_transport(settings)
    result = DistributionResult(mode=transport.mode)
    run.state = validate_processing_transition(P(run.state), P.DISTRIBUTING).value
    session.flush()

    for report in reports:
        targets = recipients_for(report, recipients)
        if not live:   # test mode: redirect, never to real lists
            targets = list(settings.email.test_recipients) or ["outbox@test.invalid"]
        bad = [t for t in targets if not _EMAIL.match(t)]
        if bad:
            result.problems.append(f"report {report.report_id}: invalid addresses {bad}")
            targets = [t for t in targets if t not in bad]
        if not targets:
            result.problems.append(f"report {report.report_id}: no recipients configured")
            continue
        content = Path(report.file_path).read_bytes()
        if sha256_bytes(content) != report.sha256:
            result.problems.append(f"report {report.report_id}: attachment checksum mismatch; not sent")
            result.failed += len(targets)
            continue
        for to in targets:
            entry = session.scalar(select(EmailDeliveryLog).where(EmailDeliveryLog.report_id == report.report_id,
                                                                  EmailDeliveryLog.recipient == to))
            if entry and entry.status == "SENT":
                result.skipped_duplicates += 1
                continue
            entry = entry or EmailDeliveryLog(report_id=report.report_id, recipient=to, mode=transport.mode, status="PENDING", attempts=0)
            session.add(entry)
            label = f"{report.report_type}{' ' + report.department_code if report.department_code else ''}"
            message = Message(
                sender=settings.email.sender or "hr-mis@test.invalid", to=[to],
                subject=f"{'[TEST] ' if not live else ''}{'[PROVISIONAL] ' if report.provisional else ''}"
                        f"APIS Attendance MIS - {label} - {run.reporting_date:%d-%b-%Y}",
                body=(f"Attached: {label} attendance report for {run.reporting_date:%d-%b-%Y} "
                      f"(run {run.run_ref}, version {report.report_version}).\n\n"
                      + ("These figures are PROVISIONAL until HR approves the attendance rules.\n" if report.provisional else "")
                      + "This is an automated message from the APIS Intelligent HR & Attendance MIS."),
                attachments=[Attachment(Path(report.file_path).name, content)],
            )
            for attempt in range(1, settings.email.max_attempts + 1):
                entry.attempts = attempt
                try:
                    transport.send(message)
                    entry.status, entry.sent_at, entry.error = "SENT", now_utc(), None
                    result.sent += 1
                    break
                except TransportError as exc:
                    entry.status, entry.error = "FAILED", str(exc)[:500]
                    if not exc.transient or attempt == settings.email.max_attempts:
                        result.failed += 1
                        break
                    sleep(min(2 ** attempt, 30))
        if live and all(e.status == "SENT" for e in session.scalars(
                select(EmailDeliveryLog).where(EmailDeliveryLog.report_id == report.report_id))):
            report.status = "DISTRIBUTED"

    target = P.DELIVERY_FAILED if result.failed else P.COMPLETED
    run.state = validate_processing_transition(P(run.state), target).value
    record_activity(session, "REPORT_DISTRIBUTION", "FAILED" if result.failed else "SUCCESS", username=actor,
                    detail={"run_id": run_id, "mode": result.mode, "sent": result.sent, "failed": result.failed,
                            "duplicates_skipped": result.skipped_duplicates})
    session.flush()
    return result
