import logging

from fastapi import APIRouter, HTTPException

from app.core.api_events import TRANSCRIPT_SUBMIT
from app.schemas.transcript import ScreeningTranscriptRequest, ScreeningTranscriptResponse
from app.services.crew_service import CrewKickoffError, resume_crew
from app.services.postgres_service import (
    DatabaseError,
    fetch_screening_resume_context,
    update_screening_resume_kickoff,
    update_screening_transcript,
)
from app.utils.db_log import log_db_error, log_db_info

router = APIRouter(tags=["transcript"])
logger = logging.getLogger("flow-manager-api")


@router.post("/screenings/{screening_id}/transcript", response_model=ScreeningTranscriptResponse)
async def submit_transcript(screening_id: str, request: ScreeningTranscriptRequest) -> ScreeningTranscriptResponse:
    if screening_id != request.screening_id:
        raise HTTPException(status_code=400, detail="screening_id path and body must match")

    log_db_info(
        TRANSCRIPT_SUBMIT,
        "submit_transcript",
        "request received",
        screening_id=screening_id,
        transcript_chars=len(request.transcript),
    )

    try:
        context = await fetch_screening_resume_context(event=TRANSCRIPT_SUBMIT, screening_id=screening_id)
        if not context:
            log_db_error(
                TRANSCRIPT_SUBMIT,
                "submit_transcript",
                "screening not found",
                screening_id=screening_id,
            )
            raise HTTPException(status_code=404, detail="Screening not found")

        stored_execution_id = context.get("execution_id")
        stored_kickoff_id = context.get("kickoff_id")
        stored_webhook_kickoff_id = context.get("webhook_kickoff_id")
        task_id = context.get("resume_task_id")

        execution_id = stored_execution_id or stored_webhook_kickoff_id or stored_kickoff_id
        logger.info(
            "[flow=transcript.resolve] screening_id=%s execution_id=%s (from execution_id=%s "
            "webhook_kickoff_id=%s kickoff_id=%s) resume_task_id=%s",
            screening_id,
            execution_id,
            stored_execution_id,
            stored_webhook_kickoff_id,
            stored_kickoff_id,
            task_id,
        )

        if not execution_id or not task_id:
            log_db_error(
                TRANSCRIPT_SUBMIT,
                "submit_transcript",
                "execution_id or resume_task_id is missing — webhook may not have linked IDs",
                screening_id=screening_id,
                execution_id=execution_id,
                resume_task_id=task_id,
            )
            raise HTTPException(status_code=409, detail="Crew execution context is incomplete")

        await update_screening_transcript(
            event=TRANSCRIPT_SUBMIT,
            screening_id=request.screening_id,
            transcript=request.transcript,
            candidate_name=request.candidate_name,
            candidate_mobile_no=request.candidate_mobile_no,
            interview_language=request.interview_language,
        )

        resume_kickoff_id = await resume_crew(
            execution_id=str(execution_id),
            task_id=str(task_id),
            human_feedback=request.transcript,
        )

        await update_screening_resume_kickoff(
            event=TRANSCRIPT_SUBMIT,
            screening_id=request.screening_id,
            resume_kickoff_id=resume_kickoff_id,
            execution_id=str(execution_id),
        )
    except DatabaseError as exc:
        logger.exception("[flow=transcript.error] database failure screening_id=%s", screening_id)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    except CrewKickoffError as exc:
        logger.error("[flow=transcript.error] crew resume failed screening_id=%s error=%s", screening_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "[flow=transcript.complete] screening_id=%s execution_id=%s task_id=%s resume_kickoff_id=%s",
        screening_id,
        execution_id,
        task_id,
        resume_kickoff_id,
    )
    return ScreeningTranscriptResponse(
        screening_id=request.screening_id,
        execution_id=str(execution_id),
        task_id=str(task_id),
        resume_kickoff_id=resume_kickoff_id,
        status="resume_submitted",
    )
