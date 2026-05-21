import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.services.postgres_service import DatabaseError, update_screening_webhook_feedback

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("flow-manager-api")


@router.get("/health")
async def webhooks_health() -> dict[str, str]:
    return {"status": "webhooks-router-ready"}


@router.post("/crew/human-input")
async def crew_human_input_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    expected_token = settings.crewai_human_input_webhook_token
    if expected_token:
        expected_authorization = f"Bearer {expected_token}"
        if authorization != expected_authorization:
            raise HTTPException(status_code=401, detail="Unauthorized webhook call")

    payload: dict[str, Any] = await request.json()
    logger.info(
        "Received /webhooks/crew/human-input payload: %s",
        json.dumps(payload, default=str),
    )
    kickoff_id = payload.get("kickoff_id") or payload.get("execution_id")
    execution_id = payload.get("execution_id") or kickoff_id
    task_id = payload.get("task_id")
    task_output = payload.get("task_output")

    if not kickoff_id or not task_id or task_output is None:
        raise HTTPException(status_code=422, detail="Missing kickoff_id, task_id, or task_output")

    if isinstance(task_output, (dict, list)):
        task_output_text = json.dumps(task_output)
    else:
        task_output_text = str(task_output)

    try:
        await update_screening_webhook_feedback(
            kickoff_id=str(kickoff_id),
            execution_id=str(execution_id),
            task_id=str(task_id),
            task_output=task_output_text,
        )
        logger.info(
            "Processed /webhooks/crew/human-input kickoff_id=%s execution_id=%s task_id=%s",
            kickoff_id,
            execution_id,
            task_id,
        )
    except DatabaseError as exc:
        logger.exception(
            "Failed /webhooks/crew/human-input kickoff_id=%s execution_id=%s task_id=%s",
            kickoff_id,
            execution_id,
            task_id,
        )
        raise HTTPException(status_code=500, detail=f"Database update failed: {exc}") from exc

    return {"status": "updated"}
