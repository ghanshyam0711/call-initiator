# Flow Manager API

FastAPI service for screening-call orchestration with room for future crew endpoints and webhooks.

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `LIVEKIT_SIP_TRUNK_ID`
- `AGENT_NAME` optional, defaults to `Jamie-cbf`
- `CREWAI_BASE_URL`
- `CREWAI_API_TOKEN`
- `CREWAI_HUMAN_INPUT_WEBHOOK_URL` optional if the request does not supply one
- `CREWAI_HUMAN_INPUT_WEBHOOK_TOKEN` optional bearer token for webhook verification
- `DATABASE_URL`

## Crew kickoff

`POST /crew/kickoff` proxies to `CREWAI_BASE_URL/kickoff`, sends the documented `humanInputWebhook` object, and upserts the returned `kickoff_id` into `public.screenings`.

## Crew webhook

`POST /webhooks/crew/human-input` accepts the human-in-the-loop callback payload from CrewAI and updates the matching `public.screenings` row by `kickoff_id`, storing the raw `task_output` in `transcript`.

## Transcript handoff

`POST /screenings/{screening_id}/transcript` stores the transcript, reads the stored Crew execution context, calls `CREWAI_BASE_URL/resume`, and saves the returned `kickoff_id` as the resume kickoff id.
