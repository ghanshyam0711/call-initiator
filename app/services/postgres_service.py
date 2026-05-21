from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg

from app.core.config import settings


class DatabaseError(RuntimeError):
    pass


def _normalize_row_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def build_screening_row(*, inputs: dict[str, Any], kickoff_id: str) -> dict[str, Any]:
    return {
        "screening_id": inputs["screening_id"],
        "kickoff_id": kickoff_id,
        "execution_id": None,
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


async def _execute(statement: str, *args: Any) -> None:
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not configured")

    try:
        connection = await asyncpg.connect(settings.database_url)
        try:
            await connection.execute(statement, *args)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc


async def upsert_screening(row: dict[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "screening_id")
    statement = (
        f"INSERT INTO public.screenings ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (screening_id) DO UPDATE SET {assignments}"
    )
    values = [_normalize_row_value(row[column]) for column in columns]
    await _execute(statement, *values)


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
    await _execute(statement, screening_id, call_id, call_provider, call_status, call_message, updated_at)


async def update_screening_webhook_feedback(
    *,
    kickoff_id: str,
    execution_id: str,
    task_id: str,
    task_output: str,
) -> None:
    statement = (
        "UPDATE public.screenings "
        "SET execution_id = $2, webhook_kickoff_id = $3, resume_task_id = $4, call_message = $5, updated_at = $6 "
        "WHERE kickoff_id = $1 OR execution_id = $2 OR webhook_kickoff_id = $3"
    )
    received_at = datetime.now(timezone.utc)
    await _execute(statement, kickoff_id, execution_id, kickoff_id, task_id, task_output, received_at)


async def fetch_screening_resume_context(screening_id: str) -> dict[str, Any] | None:
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not configured")

    statement = (
        "SELECT screening_id, kickoff_id, execution_id, webhook_kickoff_id, resume_task_id, transcript "
        "FROM public.screenings WHERE screening_id = $1 LIMIT 1"
    )

    try:
        connection = await asyncpg.connect(settings.database_url)
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc

    return dict(row) if row else None


async def fetch_screening_kickoff_id(screening_id: str) -> str | None:
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not configured")

    statement = "SELECT kickoff_id FROM public.screenings WHERE screening_id = $1 LIMIT 1"

    try:
        connection = await asyncpg.connect(settings.database_url)
        try:
            row = await connection.fetchrow(statement, screening_id)
        finally:
            await connection.close()
    except Exception as exc:
        raise DatabaseError(str(exc)) from exc

    if not row:
        return None
    return row.get("kickoff_id")


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
    await _execute(statement, screening_id, transcript, candidate_name, candidate_mobile_no, interview_language, updated_at)
