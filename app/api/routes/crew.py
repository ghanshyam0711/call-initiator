from fastapi import APIRouter, HTTPException

from app.core.api_events import CREW_KICKOFF
from app.schemas.crew import CrewKickoffRequest, CrewKickoffResponse
from app.services.crew_service import CrewKickoffError, kickoff_crew
from app.utils.db_log import log_db_info

router = APIRouter(prefix="/crew", tags=["crew"])


@router.get("/health")
async def crew_health() -> dict[str, str]:
    return {"status": "crew-router-ready"}


@router.post("/kickoff", response_model=CrewKickoffResponse)
async def kickoff(request: CrewKickoffRequest) -> CrewKickoffResponse:
    log_db_info(
        CREW_KICKOFF,
        "kickoff",
        "handler invoked",
        screening_id=request.inputs.screening_id,
    )
    try:
        kickoff_id = await kickoff_crew(request)
    except CrewKickoffError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CrewKickoffResponse(kickoff_id=kickoff_id)
