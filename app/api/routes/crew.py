from fastapi import APIRouter, HTTPException

from app.schemas.crew import CrewKickoffRequest, CrewKickoffResponse
from app.services.crew_service import CrewKickoffError, kickoff_crew

router = APIRouter(prefix="/crew", tags=["crew"])


@router.get("/health")
async def crew_health() -> dict[str, str]:
    return {"status": "crew-router-ready"}


@router.post("/kickoff", response_model=CrewKickoffResponse)
async def kickoff(request: CrewKickoffRequest) -> CrewKickoffResponse:
    try:
        kickoff_id = await kickoff_crew(request)
    except CrewKickoffError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CrewKickoffResponse(kickoff_id=kickoff_id)
