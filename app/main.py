import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import crew, health, screening, transcript, webhooks

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


@app.on_event("startup")
async def log_configuration() -> None:
    if not os.getenv("LIVEKIT_URL") or not os.getenv("LIVEKIT_API_KEY") or not os.getenv("LIVEKIT_API_SECRET"):
        logging.getLogger("flow-manager-api").warning("Missing LiveKit env vars - screening calls may fail.")
    if not os.getenv("CREWAI_BASE_URL") or not os.getenv("CREWAI_API_TOKEN"):
        logging.getLogger("flow-manager-api").warning("Missing CrewAI env vars - crew kickoff calls may fail.")
    if not os.getenv("DATABASE_URL"):
        logging.getLogger("flow-manager-api").warning("Missing DATABASE_URL - persistence will fail.")
