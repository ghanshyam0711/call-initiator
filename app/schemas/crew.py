from pydantic import BaseModel, ConfigDict, Field, field_validator


class CrewKickoffInputs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    screening_id: str
    resume: str
    job_description: str
    candidate_mobile_no: str
    candidate_name: str
    candidate_email: str
    current_role: str
    years_of_experience: float

    @field_validator(
        "screening_id",
        "resume",
        "job_description",
        "candidate_mobile_no",
        "candidate_name",
        "candidate_email",
        "current_role",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("years_of_experience")
    @classmethod
    def validate_years(cls, value: float) -> float:
        if value < 0:
            raise ValueError("years_of_experience cannot be negative")
        return value


class CrewKickoffRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    inputs: CrewKickoffInputs
    human_input_webhook_url: str | None = Field(default=None, alias="humanInputWebhookUrl")


class CrewKickoffResponse(BaseModel):
    kickoff_id: str
