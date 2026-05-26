from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("flow-manager-api")

_NESTED_PAYLOAD_KEYS = ("data", "body", "payload", "meta", "inputs", "callback_info", "callbackInfo")


@dataclass(frozen=True)
class HumanInputWebhookFields:
    kickoff_id: str | None
    execution_id: str | None
    screening_id: str | None
    task_id: str | None
    task_output: Any
    lookup_id: str | None
    payload_keys: tuple[str, ...]
    nested_sources: tuple[str, ...]


@dataclass(frozen=True)
class CrewKickoffResponseFields:
    kickoff_id: str | None
    execution_id: str | None
    response_keys: tuple[str, ...]


def _coerce_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _iter_payload_sources(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sources: list[tuple[str, dict[str, Any]]] = [("root", payload)]
    for key in _NESTED_PAYLOAD_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            sources.append((key, nested))
    return sources


def extract_field(payload: dict[str, Any], *field_names: str) -> tuple[str | None, str | None]:
    """Return (value, source) from payload using snake_case and camelCase aliases."""
    aliases: list[str] = []
    for name in field_names:
        aliases.append(name)
        if "_" in name:
            parts = name.split("_")
            camel = parts[0] + "".join(part.capitalize() for part in parts[1:])
            aliases.append(camel)
        else:
            snake = "".join(f"_{char.lower()}" if char.isupper() else char for char in name).lstrip("_")
            if snake not in aliases:
                aliases.append(snake)

    for source_name, source_payload in _iter_payload_sources(payload):
        for alias in aliases:
            if alias in source_payload:
                value = _coerce_id(source_payload.get(alias))
                if value is not None:
                    return value, f"{source_name}.{alias}"
    return None, None


def parse_human_input_webhook(payload: dict[str, Any]) -> HumanInputWebhookFields:
    kickoff_id, kickoff_source = extract_field(payload, "kickoff_id")
    execution_id, execution_source = extract_field(payload, "execution_id")
    screening_id, screening_source = extract_field(payload, "screening_id")
    task_id, task_source = extract_field(payload, "task_id")
    lookup_id = execution_id or kickoff_id

    task_output: Any = None
    task_output_source: str | None = None
    for source_name, source_payload in _iter_payload_sources(payload):
        for alias in ("task_output", "taskOutput", "output"):
            if alias in source_payload:
                task_output = source_payload.get(alias)
                task_output_source = f"{source_name}.{alias}"
                break
        if task_output_source:
            break

    nested_sources = tuple(
        source_name
        for source_name, _ in _iter_payload_sources(payload)
        if source_name != "root"
    )

    logger.info(
        "[flow=webhook.parse] payload_keys=%s nested_sources=%s "
        "kickoff_id=%s kickoff_source=%s execution_id=%s execution_source=%s "
        "screening_id=%s screening_source=%s task_id=%s task_source=%s "
        "task_output_source=%s lookup_id=%s",
        tuple(payload.keys()),
        nested_sources,
        kickoff_id,
        kickoff_source,
        execution_id,
        execution_source,
        screening_id,
        screening_source,
        task_id,
        task_source,
        task_output_source,
        lookup_id,
    )

    if kickoff_id is None and execution_id is None:
        logger.warning(
            "[flow=webhook.parse] missing kickoff_id and execution_id; raw payload=%s",
            json.dumps(payload, default=str),
        )

    return HumanInputWebhookFields(
        kickoff_id=kickoff_id,
        execution_id=execution_id,
        screening_id=screening_id,
        task_id=task_id,
        task_output=task_output,
        lookup_id=lookup_id,
        payload_keys=tuple(payload.keys()),
        nested_sources=nested_sources,
    )


def parse_crew_kickoff_response(data: dict[str, Any]) -> CrewKickoffResponseFields:
    kickoff_id, kickoff_source = extract_field(data, "kickoff_id")
    execution_id, execution_source = extract_field(data, "execution_id")

    logger.info(
        "[flow=kickoff.parse] response_keys=%s kickoff_id=%s kickoff_source=%s "
        "execution_id=%s execution_source=%s",
        tuple(data.keys()),
        kickoff_id,
        kickoff_source,
        execution_id,
        execution_source,
    )

    if kickoff_id is None:
        logger.error(
            "[flow=kickoff.parse] missing kickoff_id in CrewAI response body=%s",
            json.dumps(data, default=str),
        )

    return CrewKickoffResponseFields(
        kickoff_id=kickoff_id,
        execution_id=execution_id,
        response_keys=tuple(data.keys()),
    )
