import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    livekit_url: str = os.getenv("LIVEKIT_URL", "")
    livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    livekit_sip_trunk_id: str = os.getenv("LIVEKIT_SIP_TRUNK_ID", "")
    agent_name: str = os.getenv("AGENT_NAME", "Jamie-cbf")
    crewai_base_url: str = os.getenv("CREWAI_BASE_URL", "")
    crewai_api_token: str = os.getenv("CREWAI_API_TOKEN", "")
    crewai_human_input_webhook_url: str = os.getenv("CREWAI_HUMAN_INPUT_WEBHOOK_URL", "")
    crewai_human_input_webhook_token: str = os.getenv("CREWAI_HUMAN_INPUT_WEBHOOK_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", ""))


settings = Settings()
