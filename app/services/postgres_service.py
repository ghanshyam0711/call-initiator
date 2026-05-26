from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

import asyncpg

from app.core.config import settings


class DatabaseError(RuntimeError):
    pass


logger = logging.getLogger("flow-manager-api")

_UPSERT_PRESERVE_IF_NULL = frozenset({"execution_id", "transcript", "resume_task_id", "webhook_kickoff_id"})


def _normalize_row_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _log_screening_snapshot(step: str, row: dict[str, Any] | None, *, screening_id: str | None = None) -> None:
    if row is None:
        logger.warning(
            "[flow=%s] screening row not found screening_id=%s",
            step,
            screening_id,
        )
        return
    logger.info(
        "[flow=%s] screening_id=%s kickoff_id=%s execution_id=%s webhook_kickoff_id=%s "
        "resume_task_id=%s status=%s call_id=%s",
        step,
        row.get("screening_id"),
        row.get("kickoff_id"),
        row.get("execution_id"),
        row.get("webhook_kickoff_id"),
        row.get("resume_task_id"),
        row.get("status"),
        row.get("call_id"),
    )


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


async def _execute(statement: str, *args: Any) -> str:
    try:
        connection = await _connect()
        try:
            return await connection.execute(statement, *args)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc


def _rows_affected(status: str) -> int:
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def upsert_screening(row: dict[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
    update_columns = [column for column in columns if column != "screening_id"]
    assignments = ", ".join(
        (
            f"{column} = COALESCE(EXCLUDED.{column}, screenings.{column})"
            if column in _UPSERT_PRESERVE_IF_NULL
            else f"{column} = EXCLUDED.{column}"
        )
        for column in update_columns
    )
    statement = (
        f"INSERT INTO public.screenings ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (screening_id) DO UPDATE SET {assignments}"
    )
    values = [_normalize_row_value(row[column]) for column in columns]
    logger.info("[flow=kickoff.upsert] executing query screening_id=%s", row.get("screening_id"))
    logger.info(
        "[flow=kickoff.upsert] payload=%s",
        json.dumps({column: row[column] for column in columns}, default=str),
    )
    status = await _execute(statement, *values)
    logger.info(
        "[flow=kickoff.upsert] completed screening_id=%s db_status=%s",
        row.get("screening_id"),
        status,
    )


async def update_screening_call(
    *,
    screening_id: str,
    call_id: str,
    call_provider: str = "livekit",
    call_status: str = "initiated",
    call_message: str = "Call initiated successfully",
) -> None:
    statement = (
        "UPDATE public.screenings "
        "SET call_id = $2, call_provider = $3, call_status = $4, call_message = $5, updated_at = $6 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    status = await _execute(statement, screening_id, call_id, call_provider, call_status, call_message, updated_at)
    rows = _rows_affected(status)
    logger.info(
        "[flow=call.update] screening_id=%s call_id=%s rows_affected=%s db_status=%s",
        screening_id,
        call_id,
        rows,
        status,
    )
    if rows == 0:
        logger.warning("[flow=call.update] no screening row updated for screening_id=%s", screening_id)


async def fetch_screening_lookup_context(
    *,
    lookup_id: str | None,
    screening_id: str | None,
) -> dict[str, Any] | None:
    if screening_id:
        statement = (
            "SELECT screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, "
            "status, call_id "
            "FROM public.screenings WHERE screening_id = $1 LIMIT 1"
        )
        args: tuple[Any, ...] = (screening_id,)
        lookup_label = f"screening_id={screening_id}"
    elif lookup_id:
        statement = (
            "SELECT screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, "
            "status, call_id "
            "FROM public.screenings "
            "WHERE kickoff_id = $1 OR execution_id = $1 OR webhook_kickoff_id = $1 "
            "LIMIT 1"
        )
        args = (lookup_id,)
        lookup_label = f"lookup_id={lookup_id}"
    else:
        return None

    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, *args)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc

    result = dict(row) if row else None
    if result is None:
        logger.warning("[flow=db.lookup] no row matched %s", lookup_label)
    else:
        _log_screening_snapshot("db.lookup", result)
    return result


async def update_screening_webhook_feedback(
    *,
    lookup_id: str,
    screening_id: str | None,
    kickoff_id: str | None,
    execution_id: str | None,
    task_id: str,
    task_output: str,
) -> int:
    before = await fetch_screening_lookup_context(lookup_id=lookup_id, screening_id=screening_id)
    _log_screening_snapshot("webhook.before_update", before, screening_id=screening_id)

    if screening_id:
        statement = (
            "UPDATE public.screenings "
            "SET kickoff_id = COALESCE($2, kickoff_id), execution_id = COALESCE($3, execution_id), "
            "webhook_kickoff_id = COALESCE($2, webhook_kickoff_id), resume_task_id = $4, "
            "call_message = $5, updated_at = $6 "
            "WHERE screening_id = $1"
        )
        args: tuple[Any, ...] = (screening_id, kickoff_id, execution_id, task_id, task_output, datetime.now(timezone.utc))
        match_label = f"screening_id={screening_id}"
    else:
        statement = (
            "UPDATE public.screenings "
            "SET kickoff_id = COALESCE($2, kickoff_id), execution_id = COALESCE($3, execution_id), "
            "webhook_kickoff_id = COALESCE($2, webhook_kickoff_id), resume_task_id = $4, "
            "call_message = $5, updated_at = $6 "
            "WHERE kickoff_id = $1 OR execution_id = $1 OR webhook_kickoff_id = $1"
        )
        args = (lookup_id, kickoff_id, execution_id, task_id, task_output, datetime.now(timezone.utc))
        match_label = f"lookup_id={lookup_id}"

    logger.info(
        "[flow=webhook.update] match=%s kickoff_id=%s execution_id=%s task_id=%s",
        match_label,
        kickoff_id,
        execution_id,
        task_id,
    )
    status = await _execute(statement, *args)
    rows = _rows_affected(status)

    after = await fetch_screening_lookup_context(
        lookup_id=lookup_id,
        screening_id=screening_id or (str(before["screening_id"]) if before else None),
    )
    _log_screening_snapshot("webhook.after_update", after, screening_id=screening_id)

    if rows == 0:
        logger.error(
            "[flow=webhook.update] no rows updated match=%s lookup_id=%s kickoff_id=%s execution_id=%s "
            "screening_id=%s — likely kickoff_id/execution_id mismatch (Crew sends execution_id, "
            "DB row may only have kickoff_id from /kickoff)",
            match_label,
            lookup_id,
            kickoff_id,
            execution_id,
            screening_id,
        )
    else:
        logger.info("[flow=webhook.update] success rows_affected=%s db_status=%s", rows, status)

    return rows


async def fetch_screening_resume_context(screening_id: str) -> dict[str, Any] | None:
    statement = (
        "SELECT screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, transcript "
        "FROM public.screenings WHERE screening_id = $1 LIMIT 1"
    )

    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc

    result = dict(row) if row else None
    _log_screening_snapshot("transcript.load_context", result, screening_id=screening_id)
    return result


async def fetch_screening_kickoff_id(screening_id: str) -> str | None:
    statement = "SELECT kickoff_id FROM public.screenings WHERE screening_id = $1 LIMIT 1"

    try:
        connection = await _connect()
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc

    if not row:
        logger.warning("[flow=kickoff.verify] screening not found screening_id=%s", screening_id)
        return None
    kickoff_id = row.get("kickoff_id")
    logger.info(
        "[flow=kickoff.verify] screening_id=%s persisted_kickoff_id=%s",
        screening_id,
        kickoff_id,
    )
    return kickoff_id


async def update_screening_transcript(
    *,
    screening_id: str,
    transcript: str,
    candidate_name: str,
    candidate_mobile_no: str,
    interview_language: str,
) -> None:
    statement = (
        "UPDATE public.screenings "
        "SET transcript = $2, candidate_name = $3, candidate_mobile_no = $4, interview_language = $5, updated_at = $6 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    status = await _execute(
        statement,
        screening_id,
        transcript,
        candidate_name,
        candidate_mobile_no,
        interview_language,
        updated_at,
    )
    rows = _rows_affected(status)
    logger.info(
        "[flow=transcript.save] screening_id=%s rows_affected=%s db_status=%s",
        screening_id,
        rows,
        status,
    )


async def update_screening_resume_kickoff(
    *,
    screening_id: str,
    resume_kickoff_id: str,
    execution_id: str | None = None,
) -> None:
    statement = (
        "UPDATE public.screenings "
        "SET webhook_kickoff_id = $2, execution_id = COALESCE($3, execution_id), updated_at = $4 "
        "WHERE screening_id = $1"
    )
    updated_at = datetime.now(timezone.utc)
    status = await _execute(statement, screening_id, resume_kickoff_id, execution_id, updated_at)
    rows = _rows_affected(status)
    logger.info(
        "[flow=resume.persist] screening_id=%s resume_kickoff_id=%s execution_id=%s rows_affected=%s",
        screening_id,
        resume_kickoff_id,
        execution_id,
        rows,
    )
