from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.api_events import CREW_KICKOFF
from app.core.config import settings
from app.schemas.crew import CrewKickoffRequest
from app.services.postgres_service import build_screening_row, fetch_screening_kickoff_id, upsert_screening
from app.utils.crew_contract import parse_crew_kickoff_response


class CrewKickoffError(RuntimeError):
    pass


logger = logging.getLogger("flow-manager-api")


async def kickoff_crew(request: CrewKickoffRequest) -> str:
    if not settings.crewai_base_url or not settings.crewai_api_token:
        raise CrewKickoffError("CrewAI configuration is incomplete")

    payload = {"inputs": request.inputs.model_dump()}
    logger.info(
        "[flow=kickoff.request] screening_id=%s payload=%s",
        request.inputs.screening_id,
        json.dumps(payload, default=str),
    )
    webhook_url = request.human_input_webhook_url or settings.crewai_human_input_webhook_url
    if not webhook_url:
        raise CrewKickoffError("humanInputWebhookUrl is required")
    human_input_webhook: dict[str, Any] = {"url": webhook_url}
    if settings.crewai_human_input_webhook_token:
        human_input_webhook["authentication"] = {
            "strategy": "bearer",
            "token": settings.crewai_human_input_webhook_token,
        }
    payload["humanInputWebhook"] = human_input_webhook

    headers = {
        "Authorization": f"Bearer {settings.crewai_api_token}",
        "Content-Type": "application/json",
    }

    kickoff_url = settings.crewai_base_url.rstrip("/") + "/kickoff"
    logger.info("[flow=kickoff.http] POST %s screening_id=%s", kickoff_url, request.inputs.screening_id)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(kickoff_url, headers=headers, json=payload)

    logger.info(
        "[flow=kickoff.http] status=%s screening_id=%s body=%s",
        response.status_code,
        request.inputs.screening_id,
        response.text,
    )
    if response.status_code >= 400:
        raise CrewKickoffError(f"CrewAI kickoff failed: {response.status_code} {response.text}")

    data: dict[str, Any] = response.json()
    parsed = parse_crew_kickoff_response(data)
    kickoff_id = parsed.kickoff_id
    if not kickoff_id:
        raise CrewKickoffError("CrewAI response did not include kickoff_id")

    row = build_screening_row(
        inputs=request.inputs.model_dump(),
        kickoff_id=kickoff_id,
        execution_id=parsed.execution_id,
    )
    logger.info(
        "[flow=kickoff.persist] screening_id=%s kickoff_id=%s execution_id=%s",
        request.inputs.screening_id,
        kickoff_id,
        parsed.execution_id,
    )
    await upsert_screening(event=CREW_KICKOFF, row=row)

    persisted_kickoff_id = await fetch_screening_kickoff_id(
        event=CREW_KICKOFF,
        screening_id=request.inputs.screening_id,
    )
    if persisted_kickoff_id != kickoff_id:
        logger.error(
            "[flow=kickoff.verify] mismatch screening_id=%s expected=%s persisted=%s",
            request.inputs.screening_id,
            kickoff_id,
            persisted_kickoff_id,
        )
    else:
        logger.info(
            "[flow=kickoff.verify] success screening_id=%s kickoff_id=%s",
            request.inputs.screening_id,
            persisted_kickoff_id,
        )
    return kickoff_id


def _resolve_resume_url() -> str:
    return settings.crewai_base_url.rstrip("/") + "/resume"


async def resume_crew(*, execution_id: str, task_id: str, human_feedback: str) -> str:
    if not settings.crewai_api_token:
        raise CrewKickoffError("CrewAI API token is not configured")

    resume_url = _resolve_resume_url()
    payload = {
        "execution_id": execution_id,
        "executionId": execution_id,
        "task_id": task_id,
        "taskId": task_id,
        "human_feedback": human_feedback,
        "humanFeedback": human_feedback,
        "is_approve": True,
        "isApprove": True,
    }

    headers = {
        "Authorization": f"Bearer {settings.crewai_api_token}",
        "Content-Type": "application/json",
    }

    logger.info(
        "[flow=resume.http] POST %s execution_id=%s task_id=%s feedback_chars=%s",
        resume_url,
        execution_id,
        task_id,
        len(human_feedback),
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(resume_url, headers=headers, json=payload)

    logger.info(
        "[flow=resume.http] status=%s execution_id=%s body=%s",
        response.status_code,
        execution_id,
        response.text,
    )
    if response.status_code >= 400:
        raise CrewKickoffError(f"CrewAI resume failed: {response.status_code} {response.text}")

    data: dict[str, Any] = response.json()
    parsed = parse_crew_kickoff_response(data)
    resume_kickoff_id = parsed.kickoff_id
    if not resume_kickoff_id:
        logger.error(
            "[flow=resume.parse] missing kickoff_id execution_id=%s response_keys=%s",
            execution_id,
            parsed.response_keys,
        )
        raise CrewKickoffError("CrewAI resume response did not include kickoff_id")

    logger.info(
        "[flow=resume.parse] execution_id=%s resume_kickoff_id=%s resume_execution_id=%s",
        execution_id,
        resume_kickoff_id,
        parsed.execution_id,
    )
    return resume_kickoff_id
