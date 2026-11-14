"""Upload and processing-run lifecycles with validated transitions (PRD 5.6 / 19.2).

Transition tables are PROVISIONAL and will be refined when orchestration is built.
"""

from __future__ import annotations

from enum import StrEnum

from core.exceptions import InvalidStateTransition


class UploadState(StrEnum):
    FILE_SELECTED = "FILE_SELECTED"
    FILE_INSPECTION = "FILE_INSPECTION"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    CONTENT_VALIDATION = "CONTENT_VALIDATION"
    PREVIEW = "PREVIEW"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    RAW_FILE_ARCHIVE = "RAW_FILE_ARCHIVE"
    UPLOAD_REGISTERED = "UPLOAD_REGISTERED"
    READY_FOR_PROCESSING = "READY_FOR_PROCESSING"
    REJECTED = "REJECTED"


_UPLOAD_SEQUENCE = [
    UploadState.FILE_SELECTED,
    UploadState.FILE_INSPECTION,
    UploadState.SCHEMA_VALIDATION,
    UploadState.CONTENT_VALIDATION,
    UploadState.PREVIEW,
    UploadState.USER_CONFIRMATION,
    UploadState.RAW_FILE_ARCHIVE,
    UploadState.UPLOAD_REGISTERED,
    UploadState.READY_FOR_PROCESSING,
]

UPLOAD_TRANSITIONS: dict[UploadState, frozenset[UploadState]] = {
    current: frozenset({nxt, UploadState.REJECTED}) for current, nxt in zip(_UPLOAD_SEQUENCE, _UPLOAD_SEQUENCE[1:])
}
UPLOAD_TRANSITIONS[UploadState.READY_FOR_PROCESSING] = frozenset()
UPLOAD_TRANSITIONS[UploadState.REJECTED] = frozenset()


class ProcessingState(StrEnum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PROCESSING = "PROCESSING"
    RECONCILING = "RECONCILING"
    GENERATING_REPORTS = "GENERATING_REPORTS"
    AI_PROCESSING = "AI_PROCESSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    DISTRIBUTING = "DISTRIBUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    CANCELLED = "CANCELLED"


_P = ProcessingState
PROCESSING_TRANSITIONS: dict[ProcessingState, frozenset[ProcessingState]] = {
    _P.CREATED: frozenset({_P.UPLOADING, _P.FAILED, _P.CANCELLED}),
    _P.UPLOADING: frozenset({_P.VALIDATING, _P.FAILED, _P.CANCELLED}),
    _P.VALIDATING: frozenset({_P.VALIDATED, _P.PENDING_REVIEW, _P.FAILED, _P.CANCELLED}),
    _P.VALIDATED: frozenset({_P.PROCESSING, _P.CANCELLED}),
    _P.PROCESSING: frozenset({_P.RECONCILING, _P.FAILED, _P.CANCELLED}),
    _P.RECONCILING: frozenset({_P.GENERATING_REPORTS, _P.PENDING_REVIEW, _P.FAILED, _P.CANCELLED}),
    _P.PENDING_REVIEW: frozenset({_P.VALIDATED, _P.GENERATING_REPORTS, _P.FAILED, _P.CANCELLED}),
    _P.GENERATING_REPORTS: frozenset({_P.AI_PROCESSING, _P.READY_FOR_REVIEW, _P.PARTIAL_SUCCESS, _P.FAILED}),
    # AI failure never fails the run (PRD 14.5).
    _P.AI_PROCESSING: frozenset({_P.READY_FOR_REVIEW, _P.AI_UNAVAILABLE}),
    _P.AI_UNAVAILABLE: frozenset({_P.READY_FOR_REVIEW}),
    _P.PARTIAL_SUCCESS: frozenset({_P.GENERATING_REPORTS, _P.READY_FOR_REVIEW, _P.CANCELLED}),
    _P.READY_FOR_REVIEW: frozenset({_P.APPROVED, _P.CANCELLED}),
    _P.APPROVED: frozenset({_P.DISTRIBUTING, _P.COMPLETED}),
    _P.DISTRIBUTING: frozenset({_P.COMPLETED, _P.DELIVERY_FAILED}),
    # Email failure keeps reports available; distribution can be retried (PRD 19.3).
    _P.DELIVERY_FAILED: frozenset({_P.DISTRIBUTING, _P.CANCELLED}),
    # Resume from the last safe stage rather than repeating upstream work (PRD 19.3).
    _P.FAILED: frozenset({_P.PROCESSING, _P.GENERATING_REPORTS, _P.CANCELLED}),
    _P.COMPLETED: frozenset(),
    _P.CANCELLED: frozenset(),
}

TERMINAL_PROCESSING_STATES = frozenset(s for s, nxt in PROCESSING_TRANSITIONS.items() if not nxt)


def validate_upload_transition(current: UploadState, target: UploadState) -> UploadState:
    if target not in UPLOAD_TRANSITIONS[current]:
        raise InvalidStateTransition(f"upload: {current} -> {target} is not allowed")
    return target


def validate_processing_transition(current: ProcessingState, target: ProcessingState) -> ProcessingState:
    if target not in PROCESSING_TRANSITIONS[current]:
        raise InvalidStateTransition(f"processing: {current} -> {target} is not allowed")
    return target
