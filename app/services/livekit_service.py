import re
import uuid

from app.schemas.screening import StartScreeningCallRequest
from app.core.config import settings


def build_participant_identity(candidate_mobile_no: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", candidate_mobile_no).strip("_")
    return f"candidate_{sanitized or uuid.uuid4().hex[:8]}"


async def create_screening_call(*, request: StartScreeningCallRequest, room_name: str, metadata: str) -> str:
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        raise RuntimeError("LiveKit configuration is incomplete")

    try:
        from livekit import api as livekit_api
        from livekit.api import CreateAgentDispatchRequest, CreateSIPParticipantRequest
    except ImportError as exc:
        raise RuntimeError("livekit-api is not installed") from exc

    lk = livekit_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    try:
        await lk.room.create_room(
            livekit_api.CreateRoomRequest(
                name=room_name,
                metadata=metadata,
                empty_timeout=300,
                max_participants=5,
            )
        )

        dispatch = await lk.agent_dispatch.create_dispatch(
            CreateAgentDispatchRequest(
                agent_name=settings.agent_name,
                room=room_name,
                metadata=metadata,
            )
        )

        await lk.sip.create_sip_participant(
            CreateSIPParticipantRequest(
                sip_trunk_id=settings.livekit_sip_trunk_id,
                sip_call_to=request.candidate_mobile_no,
                room_name=room_name,
                participant_identity=build_participant_identity(request.candidate_mobile_no),
                participant_name=request.candidate_name,
                participant_metadata=metadata,
                play_ringtone=True,
                krisp_enabled=True,
            )
        )

        return dispatch.id
    finally:
        await lk.aclose()
