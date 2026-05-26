from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flow-manager-api")

_UNKNOWN_EVENT = "unknown"


def _prefix(event: str, operation: str) -> str:
    return f"[event={event}] [op={operation}]"


def log_db_info(event: str, operation: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("%s %s%s", _prefix(event, operation), message, f" | {suffix}" if suffix else "")


def log_db_warning(event: str, operation: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("%s %s%s", _prefix(event, operation), message, f" | {suffix}" if suffix else "")


def log_db_error(event: str, operation: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.error("%s %s%s", _prefix(event, operation), message, f" | {suffix}" if suffix else "")


def log_screening_row(
    event: str,
    operation: str,
    message: str,
    row: dict[str, Any] | None,
    *,
    screening_id: str | None = None,
) -> None:
    if row is None:
        log_db_warning(
            event,
            operation,
            message,
            screening_id=screening_id,
            kickoff_id=None,
            execution_id=None,
            webhook_kickoff_id=None,
            resume_task_id=None,
            status=None,
            call_id=None,
        )
        return
    log_db_info(
        event,
        operation,
        message,
        screening_id=row.get("screening_id") or screening_id,
        kickoff_id=row.get("kickoff_id"),
        execution_id=row.get("execution_id"),
        webhook_kickoff_id=row.get("webhook_kickoff_id"),
        resume_task_id=row.get("resume_task_id"),
        status=row.get("status"),
        call_id=row.get("call_id"),
    )


def log_missing_ids(
    event: str,
    operation: str,
    row: dict[str, Any] | None,
    *required_fields: str,
    screening_id: str | None = None,
) -> None:
    if row is None:
        log_db_error(
            event,
            operation,
            "screening row not found — cannot verify IDs",
            screening_id=screening_id,
            missing=",".join(required_fields),
        )
        return

    missing = [field for field in required_fields if not row.get(field)]
    if not missing:
        return

    log_db_error(
        event,
        operation,
        f"{', '.join(missing)} is missing",
        screening_id=row.get("screening_id") or screening_id,
        kickoff_id=row.get("kickoff_id"),
        execution_id=row.get("execution_id"),
        webhook_kickoff_id=row.get("webhook_kickoff_id"),
        resume_task_id=row.get("resume_task_id"),
    )
