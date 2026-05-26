import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import crew, health, screening, transcript, webhooks
from app.utils.db_log import log_db_info

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Flow Manager API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(screening.router)
app.include_router(transcript.router)
app.include_router(crew.router)
app.include_router(webhooks.router)


def _resolve_request_event(method: str, path: str) -> str:
    if path == "/crew/kickoff" and method == "POST":
        return "POST /crew/kickoff"
    if path == "/webhooks/crew/human-input" and method == "POST":
        return "POST /webhooks/crew/human-input"
    if path == "/start-screening-call" and method == "POST":
        return "POST /start-screening-call"
    if path.startswith("/screenings/") and path.endswith("/transcript") and method == "POST":
        return "POST /screenings/{screening_id}/transcript"
    return f"{method} {path}"


@app.middleware("http")
async def log_incoming_request_event(request: Request, call_next):
    event = _resolve_request_event(request.method, request.url.path)
    log_db_info(event, "http_request", "incoming request", client=request.client.host if request.client else None)
    response = await call_next(request)
    log_db_info(event, "http_request", "request completed", status_code=response.status_code)
    return response


@app.on_event("startup")
async def log_configuration() -> None:
    if not os.getenv("LIVEKIT_URL") or not os.getenv("LIVEKIT_API_KEY") or not os.getenv("LIVEKIT_API_SECRET"):
        logging.getLogger("flow-manager-api").warning("Missing LiveKit env vars - screening calls may fail.")
    if not os.getenv("CREWAI_BASE_URL") or not os.getenv("CREWAI_API_TOKEN"):
        logging.getLogger("flow-manager-api").warning("Missing CrewAI env vars - crew kickoff calls may fail.")
    if not os.getenv("DATABASE_URL"):
        logging.getLogger("flow-manager-api").warning("Missing DATABASE_URL - persistence will fail.")
