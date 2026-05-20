from fastapi import APIRouter, HTTPException

from app.schemas.transcript import ScreeningTranscriptRequest, ScreeningTranscriptResponse
from app.services.crew_service import CrewKickoffError, resume_crew
from app.services.postgres_service import (
    DatabaseError,
    fetch_screening_resume_context,
    update_screening_transcript,
)

router = APIRouter(tags=["transcript"])


@router.post("/screenings/{screening_id}/transcript", response_model=ScreeningTranscriptResponse)
async def submit_transcript(screening_id: str, request: ScreeningTranscriptRequest) -> ScreeningTranscriptResponse:
    if screening_id != request.screening_id:
        raise HTTPException(status_code=400, detail="screening_id path and body must match")

    try:
        context = await fetch_screening_resume_context(screening_id)
        if not context:
            raise HTTPException(status_code=404, detail="Screening not found")

        execution_id = context.get("execution_id") or context.get("webhook_kickoff_id") or context.get("kickoff_id")
        task_id = context.get("resume_task_id")
        if not execution_id or not task_id:
            raise HTTPException(status_code=409, detail="Crew execution context is incomplete")

        await update_screening_transcript(
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
    except DatabaseError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    except CrewKickoffError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ScreeningTranscriptResponse(
        screening_id=request.screening_id,
        execution_id=str(execution_id),
        task_id=str(task_id),
        resume_kickoff_id=resume_kickoff_id,
        status="resume_submitted",
    )
