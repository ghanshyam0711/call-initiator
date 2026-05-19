# call-initiator

FastAPI service that starts outbound LiveKit screening calls. It creates a room, dispatches the configured voice agent, and returns dispatch metadata to the caller.

This project is extracted from the HireLoop voice screening stack. The LiveKit agent worker runs separately (for example in `voice_agent`).

## Requirements

- Python 3.10+
- LiveKit project credentials
- SIP trunk ID (validated at request time)
- A registered LiveKit agent named `Jamie-cbf` (or update `AGENT_NAME` in `api.py`)

## Environment variables

Copy `.env.example` to `.env` and fill in values:

| Variable | Description |
|----------|-------------|
| `LIVEKIT_URL` | LiveKit server URL |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |
| `LIVEKIT_SIP_TRUNK_ID` | SIP trunk for outbound calls |

## Local development

```bash
cd call-initiator
cp .env.example .env
uv sync
uv run uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## API

### `POST /start-screening-call`

Request body:

```json
{
  "screening_id": "screening-123",
  "candidate_mobile_no": "+15551234567",
  "candidate_name": "Jane Doe",
  "interview_language": "English",
  "questions": [
    "Tell me about your experience with Python.",
    "What APIs have you built recently?"
  ]
}
```

Example:

```bash
curl -X POST "http://localhost:8000/start-screening-call" \
  -H "Content-Type: application/json" \
  -d '{
    "screening_id": "screening-123",
    "candidate_mobile_no": "+15551234567",
    "candidate_name": "Jane Doe",
    "interview_language": "English",
    "questions": ["Tell me about your experience with Python."]
  }'
```

Response:

```json
{
  "success": true,
  "room_name": "screening-screening-123-abc123def4",
  "screening_id": "screening-123",
  "candidate_mobile_no": "+15551234567",
  "message": "Call initiated for Jane Doe.",
  "dispatch_id": "..."
}
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The API is exposed on port `8000` by default (`API_PORT` can override the host mapping).

## Notes

- SIP participant creation is currently commented out in `api.py`; enabling it requires a valid `LIVEKIT_SIP_TRUNK_ID` and trunk configuration in LiveKit.
- Transcript collection and evaluation are handled by the separate agent service, not this API.
