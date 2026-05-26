import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.services.postgres_service import DatabaseError, update_screening_webhook_feedback
from app.utils.crew_contract import parse_human_input_webhook

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
            logger.warning("[flow=webhook.auth] unauthorized webhook call")
            raise HTTPException(status_code=401, detail="Unauthorized webhook call")

    payload: dict[str, Any] = await request.json()
    logger.info(
        "[flow=webhook.received] raw_payload=%s",
        json.dumps(payload, default=str),
    )

    fields = parse_human_input_webhook(payload)
    lookup_id = fields.lookup_id
    task_id = fields.task_id
    task_output = fields.task_output

    if not lookup_id or not task_id or task_output is None:
        logger.error(
            "[flow=webhook.validate] rejected payload_keys=%s lookup_id=%s task_id=%s "
            "has_task_output=%s",
            fields.payload_keys,
            lookup_id,
            task_id,
            task_output is not None,
        )
        raise HTTPException(
            status_code=422,
            detail="Missing kickoff_id/execution_id, task_id, or task_output",
        )

    if isinstance(task_output, (dict, list)):
        task_output_text = json.dumps(task_output)
    else:
        task_output_text = str(task_output)

    try:
        rows_updated = await update_screening_webhook_feedback(
            lookup_id=str(lookup_id),
            screening_id=fields.screening_id,
            kickoff_id=fields.kickoff_id,
            execution_id=fields.execution_id,
            task_id=str(task_id),
            task_output=task_output_text,
        )
        if rows_updated == 0:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No screening row matched webhook identifiers. "
                    f"lookup_id={lookup_id} screening_id={fields.screening_id}"
                ),
            )
        logger.info(
            "[flow=webhook.complete] kickoff_id=%s execution_id=%s screening_id=%s task_id=%s rows=%s",
            fields.kickoff_id,
            fields.execution_id,
            fields.screening_id,
            task_id,
            rows_updated,
        )
    except DatabaseError as exc:
        logger.exception(
            "[flow=webhook.error] database failure kickoff_id=%s execution_id=%s task_id=%s",
            fields.kickoff_id,
            fields.execution_id,
            task_id,
        )
        raise HTTPException(status_code=500, detail=f"Database update failed: {exc}") from exc

    return {"status": "updated"}
