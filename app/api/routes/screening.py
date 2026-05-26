import json
import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.core.api_events import START_SCREENING_CALL
from app.schemas.screening import StartScreeningCallRequest, StartScreeningCallResponse
from app.core.config import settings
from app.services.livekit_service import create_screening_call
from app.services.postgres_service import update_screening_call
from app.utils.db_log import log_db_info

router = APIRouter(tags=["screening"])
logger = logging.getLogger("flow-manager-api")


def build_metadata(request: StartScreeningCallRequest) -> str:
    return json.dumps(
        {
            "screening_id": request.screening_id,
            "candidate_mobile_no": request.candidate_mobile_no,
            "candidate_name": request.candidate_name,
            "interview_language": request.interview_language,
            "questions": request.questions,
        }
    )


def build_room_name(screening_id: str) -> str:
    return f"screening-{screening_id}-{uuid.uuid4().hex[:10]}"


@router.post("/start-screening-call", response_model=StartScreeningCallResponse)
async def start_screening_call(request: StartScreeningCallRequest) -> StartScreeningCallResponse:
    if not settings.livekit_sip_trunk_id:
        raise HTTPException(status_code=503, detail="LIVEKIT_SIP_TRUNK_ID is not configured")

    metadata = build_metadata(request)
    room_name = build_room_name(request.screening_id)
    log_db_info(
        START_SCREENING_CALL,
        "start_screening_call",
        "request received",
        screening_id=request.screening_id,
        room_name=room_name,
    )

    try:
        dispatch_id = await create_screening_call(
            request=request,
            room_name=room_name,
            metadata=metadata,
        )
        await update_screening_call(
            event=START_SCREENING_CALL,
            screening_id=request.screening_id,
            call_id=dispatch_id,
        )
    except Exception as exc:
        logger.exception(
            "Failed to start screening call for screening_id=%s candidate_mobile_no=%s",
            request.screening_id,
            request.candidate_mobile_no,
        )
        raise HTTPException(status_code=500, detail=f"LiveKit error: {exc}") from exc

    return StartScreeningCallResponse(
        success=True,
        room_name=room_name,
        screening_id=request.screening_id,
        candidate_mobile_no=request.candidate_mobile_no,
        message=f"Call initiated for {request.candidate_name}.",
        dispatch_id=dispatch_id,
    )
