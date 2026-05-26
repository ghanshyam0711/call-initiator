from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

import asyncpg

from app.core.config import settings
from app.utils.db_log import log_db_error, log_db_info, log_db_warning, log_missing_ids, log_screening_row


class DatabaseError(RuntimeError):
    pass


logger = logging.getLogger("flow-manager-api")

# On kickoff re-upsert, only touch these columns so webhook/call/resume state is never wiped.
_KICKOFF_CONFLICT_COLUMNS = frozenset(
    {
        "kickoff_id",
        "execution_id",
        "status",
        "hitl_status",
        "candidate_mobile_no",
        "candidate_name",
        "candidate_email",
        "candidate_phone_from_resume",
        "current_title",
        "total_experience_years",
        "highest_education",
        "skills",
        "languages",
        "resume_summary",
        "job_description",
        "interview_language",
        "experience_level",
        "updated_at",
    }
)

_ID_COLUMNS = frozenset({"kickoff_id", "execution_id", "webhook_kickoff_id"})


def _normalize_row_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _coalesce_id_assignment(column: str) -> str:
    return f"{column} = COALESCE(NULLIF(EXCLUDED.{column}, ''), screenings.{column})"


def build_screening_row(
    *,
    inputs: dict[str, Any],
    kickoff_id: str,
    execution_id: str | None = None,
) -> dict[str, Any]:
    return {
        "screening_id": inputs["screening_id"],
        "kickoff_id": kickoff_id,
        "execution_id": execution_id,
        "status": "crew_kickoff_created",
        "hitl_status": "pending",
        "resume_task_id": None,
        "webhook_kickoff_id": None,
        "candidate_mobile_no": inputs["candidate_mobile_no"],
        "candidate_name": inputs["candidate_name"],
        "candidate_email": inputs["candidate_email"],
        "candidate_phone_from_resume": None,
        "current_title": inputs["current_role"],
        "total_experience_years": inputs["years_of_experience"],
        "highest_education": None,
        "skills": None,
        "languages": None,
        "resume_summary": inputs["resume"],
        "job_description": inputs["job_description"],
        "interview_language": None,
        "experience_level": None,
        "questions": None,
        "call_id": None,
        "call_provider": None,
        "call_status": None,
        "call_message": None,
        "transcript": None,
        "overall_score": None,
        "technical_score": None,
        "communication_score": None,
        "problem_solving_score": None,
        "recommendation": None,
        "evaluation_summary": None,
        "strengths": None,
        "concerns": None,
        "human_feedback_received_at": None,
        "updated_at": datetime.now(timezone.utc),
    }


async def _connect() -> asyncpg.Connection:
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not configured")
    return await asyncpg.connect(settings.database_url)


async def _execute(event: str, operation: str, statement: str, *args: Any) -> str:
    log_db_info(event, operation, "executing SQL", statement=statement.strip().split("\n")[0])
    try:
        connection = await _connect()
        try:
            return await connection.execute(statement, *args)
        finally:
            await connection.close()
    except Exception as exc:
        log_db_error(event, operation, "database execute failed", error=str(exc))
        raise DatabaseError(str(exc)) from exc


def _rows_affected(status: str) -> int:
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def upsert_screening(*, event: str, row: dict[str, Any]) -> None:
    operation = "upsert_screening"
    screening_id = str(row.get("screening_id") or "")
    columns = list(row.keys())
    placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
    update_columns = [column for column in columns if column != "screening_id" and column in _KICKOFF_CONFLICT_COLUMNS]
    assignments = ", ".join(
        _coalesce_id_assignment(column) if column in _ID_COLUMNS else f"{column} = EXCLUDED.{column}"
        for column in update_columns
    )
    statement = (
        f"INSERT INTO public.screenings ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (screening_id) DO UPDATE SET {assignments}"
    )
    values = [_normalize_row_value(row[column]) for column in columns]

    if not row.get("kickoff_id"):
        log_db_error(event, operation, "kickoff_id is missing in upsert payload", screening_id=screening_id)

    log_db_info(
        event,
        operation,
        "upserting screening row",
        screening_id=screening_id,
        kickoff_id=row.get("kickoff_id"),
        execution_id=row.get("execution_id"),
        conflict_columns=",".join(sorted(update_columns)),
    )
    log_db_info(
        event,
        operation,
        "upsert payload",
        screening_id=screening_id,
        payload=json.dumps({column: row[column] for column in columns}, default=str),
    )

    status = await _execute(event, operation, statement, *values)
    log_db_info(event, operation, "upsert completed", screening_id=screening_id, db_status=status)

    after = await fetch_screening_lookup_context(
        event=event,
        lookup_id=None,
        screening_id=screening_id,
    )
    log_missing_ids(event, operation, after, "kickoff_id", screening_id=screening_id)


async def update_screening_call(
    *,
    event: str,
    screening_id: str,
    call_id: str,
    call_provider: str = "livekit",
    call_status: str = "initiated",
    call_message: str = "Call initiated successfully",
) -> None:
    operation = "update_screening_call"
    statement = (
        "UPDATE public.screenings "
        "SET call_id = $2, call_provider = $3, call_status = $4, call_message = $5, updated_at = $6 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    log_db_info(
        event,
        operation,
        "updating call fields",
        screening_id=screening_id,
        call_id=call_id,
        call_provider=call_provider,
        call_status=call_status,
    )
    status = await _execute(
        event,
        operation,
        statement,
        screening_id,
        call_id,
        call_provider,
        call_status,
        call_message,
        updated_at,
    )
    rows = _rows_affected(status)
    log_db_info(event, operation, "call update finished", screening_id=screening_id, rows_affected=rows, db_status=status)
    if rows == 0:
        log_db_warning(event, operation, "no screening row updated", screening_id=screening_id)


_SCREENING_LOOKUP_COLUMNS = (
    "screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, status, call_id"
)


async def _fetch_screening_row(event: str, operation: str, statement: str, *args: Any) -> dict[str, Any] | None:
    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, *args)
        finally:
            await connection.close()
    except Exception as exc:
        log_db_error(event, operation, "lookup query failed", error=str(exc), statement=statement[:120])
        raise DatabaseError(str(exc)) from exc
    return dict(row) if row else None


async def _log_lookup_diagnostics(event: str, operation: str, lookup_id: str | None) -> None:
    if not lookup_id:
        return
    exact_matches = await _fetch_screening_row(
        event,
        operation,
        f"SELECT {_SCREENING_LOOKUP_COLUMNS} FROM public.screenings "
        "WHERE kickoff_id::text = $1::text OR execution_id::text = $1::text OR webhook_kickoff_id::text = $1::text "
        "LIMIT 5",
        lookup_id,
    )
    recent_rows = await _fetch_screening_row(
        event,
        operation,
        f"SELECT {_SCREENING_LOOKUP_COLUMNS} FROM public.screenings "
        "WHERE status = 'crew_kickoff_created' AND call_id IS NOT NULL "
        "AND updated_at > NOW() - INTERVAL '2 hours' "
        "ORDER BY updated_at DESC LIMIT 3",
    )
    log_db_warning(
        event,
        operation,
        "lookup diagnostics",
        lookup_id=lookup_id,
        exact_match_found=bool(exact_matches),
        exact_match_screening_id=exact_matches.get("screening_id") if exact_matches else None,
        exact_match_kickoff_id=exact_matches.get("kickoff_id") if exact_matches else None,
        recent_fallback_screening_id=recent_rows.get("screening_id") if recent_rows else None,
        recent_fallback_kickoff_id=recent_rows.get("kickoff_id") if recent_rows else None,
        recent_fallback_call_id=recent_rows.get("call_id") if recent_rows else None,
    )


async def fetch_screening_lookup_context(
    *,
    event: str,
    lookup_id: str | None,
    screening_id: str | None,
) -> dict[str, Any] | None:
    operation = "fetch_screening_lookup_context"
    if screening_id:
        lookup_label = f"screening_id={screening_id}"
        log_db_info(event, operation, "loading screening row", match=lookup_label)
        result = await _fetch_screening_row(
            event,
            operation,
            f"SELECT {_SCREENING_LOOKUP_COLUMNS} FROM public.screenings WHERE screening_id = $1::text LIMIT 1",
            screening_id,
        )
    elif lookup_id:
        lookup_label = f"lookup_id={lookup_id}"
        log_db_info(event, operation, "loading screening row", match=lookup_label)
        result = await _fetch_screening_row(
            event,
            operation,
            f"SELECT {_SCREENING_LOOKUP_COLUMNS} FROM public.screenings "
            "WHERE kickoff_id::text = $1::text OR execution_id::text = $1::text OR webhook_kickoff_id::text = $1::text "
            "LIMIT 1",
            lookup_id,
        )
    else:
        log_db_warning(event, operation, "lookup skipped — no screening_id or lookup_id provided")
        return None

    if result is None:
        log_db_warning(event, operation, "no screening row matched lookup", match=lookup_label)
    else:
        log_screening_row(event, operation, "screening row loaded", result)
    return result


async def resolve_screening_for_webhook(
    *,
    event: str,
    lookup_id: str,
    screening_id: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve screening_id for webhook updates using multiple lookup strategies."""
    operation = "resolve_screening_for_webhook"

    if screening_id:
        row = await fetch_screening_lookup_context(
            event=event,
            lookup_id=None,
            screening_id=screening_id,
        )
        if row:
            log_db_info(event, operation, "resolved by screening_id from payload", screening_id=screening_id)
            return screening_id, row

    row = await fetch_screening_lookup_context(
        event=event,
        lookup_id=lookup_id,
        screening_id=None,
    )
    if row:
        resolved = str(row["screening_id"])
        log_db_info(event, operation, "resolved by kickoff_id/execution_id", screening_id=resolved, lookup_id=lookup_id)
        return resolved, row

    fallback = await _fetch_screening_row(
        event,
        operation,
        f"SELECT {_SCREENING_LOOKUP_COLUMNS} FROM public.screenings "
        "WHERE status = 'crew_kickoff_created' AND call_id IS NOT NULL "
        "AND updated_at > NOW() - INTERVAL '2 hours' "
        "ORDER BY updated_at DESC LIMIT 1",
    )
    if fallback:
        resolved = str(fallback["screening_id"])
        log_db_warning(
            event,
            operation,
            "resolved by recent active screening fallback — verify screening_id is correct",
            screening_id=resolved,
            lookup_id=lookup_id,
            fallback_kickoff_id=fallback.get("kickoff_id"),
            fallback_call_id=fallback.get("call_id"),
        )
        return resolved, fallback

    await _log_lookup_diagnostics(event, operation, lookup_id)
    log_db_error(
        event,
        operation,
        "could not resolve screening row for webhook",
        lookup_id=lookup_id,
        screening_id=screening_id,
    )
    return None, None


def _coalesce_id_sql(column: str, parameter_index: int) -> str:
    return f"{column} = COALESCE(NULLIF(${parameter_index}, ''), {column})"


async def update_screening_webhook_feedback(
    *,
    event: str,
    lookup_id: str,
    screening_id: str | None,
    kickoff_id: str | None,
    execution_id: str | None,
    task_id: str,
    task_output: str,
) -> int:
    operation = "update_screening_webhook_feedback"

    if not kickoff_id and not execution_id:
        log_db_error(
            event,
            operation,
            "kickoff_id and execution_id are both missing in webhook update request",
            lookup_id=lookup_id,
            screening_id=screening_id,
            task_id=task_id,
        )

    resolved_screening_id, before = await resolve_screening_for_webhook(
        event=event,
        lookup_id=lookup_id,
        screening_id=screening_id,
    )
    log_screening_row(event, operation, "row state before webhook update", before, screening_id=resolved_screening_id)

    if not resolved_screening_id:
        return 0

    statement = (
        "UPDATE public.screenings "
        f"SET {_coalesce_id_sql('kickoff_id', 2)}, "
        f"{_coalesce_id_sql('execution_id', 3)}, "
        f"{_coalesce_id_sql('webhook_kickoff_id', 2)}, "
        "resume_task_id = $4, call_message = $5, updated_at = $6 "
        "WHERE screening_id = $1::text"
    )
    args: tuple[Any, ...] = (
        resolved_screening_id,
        kickoff_id,
        execution_id,
        task_id,
        task_output,
        datetime.now(timezone.utc),
    )
    match_label = f"screening_id={resolved_screening_id}"

    log_db_info(
        event,
        operation,
        "applying webhook update",
        match=match_label,
        kickoff_id=kickoff_id,
        execution_id=execution_id,
        task_id=task_id,
    )
    status = await _execute(event, operation, statement, *args)
    rows = _rows_affected(status)

    after = await fetch_screening_lookup_context(
        event=event,
        lookup_id=None,
        screening_id=resolved_screening_id,
    )
    log_screening_row(event, operation, "row state after webhook update", after, screening_id=resolved_screening_id)

    if rows == 0:
        await _log_lookup_diagnostics(event, operation, lookup_id)
        log_db_error(
            event,
            operation,
            "no rows updated for resolved screening_id",
            match=match_label,
            lookup_id=lookup_id,
            kickoff_id=kickoff_id,
            execution_id=execution_id,
            screening_id=resolved_screening_id,
        )
    else:
        log_missing_ids(event, operation, after, "kickoff_id", "execution_id", screening_id=screening_id)
        log_db_info(event, operation, "webhook update succeeded", rows_affected=rows, db_status=status)

    return rows


async def fetch_screening_resume_context(*, event: str, screening_id: str) -> dict[str, Any] | None:
    operation = "fetch_screening_resume_context"
    statement = (
        "SELECT screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, transcript "
        "FROM public.screenings WHERE screening_id = $1 LIMIT 1"
    )

    log_db_info(event, operation, "loading resume context", screening_id=screening_id)
    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        log_db_error(event, operation, "resume context query failed", screening_id=screening_id, error=str(exc))
        raise DatabaseError(str(exc)) from exc

    result = dict(row) if row else None
    if result is None:
        log_db_warning(event, operation, "screening not found for transcript resume", screening_id=screening_id)
    else:
        log_screening_row(event, operation, "resume context loaded", result, screening_id=screening_id)
        if not result.get("resume_task_id"):
            log_db_error(
                event,
                operation,
                "resume_task_id is missing — webhook may not have run yet",
                screening_id=screening_id,
                kickoff_id=result.get("kickoff_id"),
                execution_id=result.get("execution_id"),
            )
        log_missing_ids(
            event,
            operation,
            result,
            "kickoff_id",
            "execution_id",
            screening_id=screening_id,
        )
    return result


async def fetch_screening_kickoff_id(*, event: str, screening_id: str) -> str | None:
    operation = "fetch_screening_kickoff_id"
    statement = "SELECT kickoff_id FROM public.screenings WHERE screening_id = $1 LIMIT 1"

    log_db_info(event, operation, "verifying persisted kickoff_id", screening_id=screening_id)
    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        log_db_error(event, operation, "kickoff_id verify query failed", screening_id=screening_id, error=str(exc))
        raise DatabaseError(str(exc)) from exc

    if not row:
        log_db_warning(event, operation, "screening not found during kickoff verify", screening_id=screening_id)
        return None

    kickoff_id = row.get("kickoff_id")
    if not kickoff_id:
        log_db_error(event, operation, "kickoff_id is missing after kickoff upsert", screening_id=screening_id)
    else:
        log_db_info(event, operation, "kickoff_id verified", screening_id=screening_id, kickoff_id=kickoff_id)
    return kickoff_id


async def update_screening_transcript(
    *,
    event: str,
    screening_id: str,
    transcript: str,
    candidate_name: str,
    candidate_mobile_no: str,
    interview_language: str,
) -> None:
    operation = "update_screening_transcript"
    statement = (
        "UPDATE public.screenings "
        "SET transcript = $2, candidate_name = $3, candidate_mobile_no = $4, interview_language = $5, updated_at = $6 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    log_db_info(
        event,
        operation,
        "saving transcript",
        screening_id=screening_id,
        transcript_chars=len(transcript),
        interview_language=interview_language,
    )
    status = await _execute(
        event,
        operation,
        statement,
        screening_id,
        transcript,
        candidate_name,
        candidate_mobile_no,
        interview_language,
        updated_at,
    )
    rows = _rows_affected(status)
    log_db_info(event, operation, "transcript saved", screening_id=screening_id, rows_affected=rows, db_status=status)


async def update_screening_resume_kickoff(
    *,
    event: str,
    screening_id: str,
    resume_kickoff_id: str,
    execution_id: str | None = None,
) -> None:
    operation = "update_screening_resume_kickoff"
    statement = (
        "UPDATE public.screenings "
        "SET webhook_kickoff_id = COALESCE(NULLIF($2, ''), webhook_kickoff_id), "
        "execution_id = COALESCE(NULLIF($3, ''), execution_id), "
        "updated_at = $4 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    log_db_info(
        event,
        operation,
        "persisting resume kickoff",
        screening_id=screening_id,
        resume_kickoff_id=resume_kickoff_id,
        execution_id=execution_id,
    )
    status = await _execute(
        event,
        operation,
        statement,
        screening_id,
        resume_kickoff_id,
        execution_id,
        updated_at,
    )
    rows = _rows_affected(status)
    log_db_info(
        event,
        operation,
        "resume kickoff persisted",
        screening_id=screening_id,
        rows_affected=rows,
        resume_kickoff_id=resume_kickoff_id,
    )

    after = await fetch_screening_lookup_context(event=event, lookup_id=None, screening_id=screening_id)
    log_missing_ids(event, operation, after, "kickoff_id", "execution_id", screening_id=screening_id)
