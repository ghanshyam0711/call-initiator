from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.crew import CrewKickoffRequest
from app.services.postgres_service import build_screening_row, fetch_screening_kickoff_id, upsert_screening


class CrewKickoffError(RuntimeError):
    pass


logger = logging.getLogger("flow-manager-api")


async def kickoff_crew(request: CrewKickoffRequest) -> str:
    if not settings.crewai_base_url or not settings.crewai_api_token:
        raise CrewKickoffError("CrewAI configuration is incomplete")

    payload = {"inputs": request.inputs.model_dump()}
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(kickoff_url, headers=headers, json=payload)

    if response.status_code >= 400:
        raise CrewKickoffError(f"CrewAI kickoff failed: {response.status_code} {response.text}")

    data: dict[str, Any] = response.json()
    kickoff_id = data.get("kickoff_id")
    if not kickoff_id or not isinstance(kickoff_id, str):
        logger.error("CrewAI kickoff response missing kickoff_id. Response body: %s", data)
        raise CrewKickoffError("CrewAI response did not include kickoff_id")

    row = build_screening_row(inputs=request.inputs.model_dump(), kickoff_id=kickoff_id)
    logger.info(
        "Persisting kickoff row for screening_id=%s with kickoff_id=%s",
        request.inputs.screening_id,
        kickoff_id,
    )
    await upsert_screening(row)

    persisted_kickoff_id = await fetch_screening_kickoff_id(request.inputs.screening_id)
    if persisted_kickoff_id != kickoff_id:
        logger.error(
            "Kickoff persistence mismatch for screening_id=%s expected=%s persisted=%s",
            request.inputs.screening_id,
            kickoff_id,
            persisted_kickoff_id,
        )
    else:
        logger.info(
            "Kickoff persisted successfully for screening_id=%s kickoff_id=%s",
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
        "executionId": execution_id,
        "taskId": task_id,
        "humanFeedback": human_feedback,
        "isApprove": True,
    }

    headers = {
        "Authorization": f"Bearer {settings.crewai_api_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(resume_url, headers=headers, json=payload)

    if response.status_code >= 400:
        raise CrewKickoffError(f"CrewAI resume failed: {response.status_code} {response.text}")

    data: dict[str, Any] = response.json()
    resume_kickoff_id = data.get("kickoff_id")
    if not resume_kickoff_id or not isinstance(resume_kickoff_id, str):
        raise CrewKickoffError("CrewAI resume response did not include kickoff_id")

    return resume_kickoff_id
