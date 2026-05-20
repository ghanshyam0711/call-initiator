from pydantic import BaseModel, field_validator


class ScreeningTranscriptRequest(BaseModel):
    screening_id: str
    candidate_name: str
    candidate_mobile_no: str
    interview_language: str
    transcript: str

    @field_validator("screening_id", "candidate_name", "candidate_mobile_no", "interview_language", "transcript")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value

class ScreeningTranscriptResponse(BaseModel):
    screening_id: str
    execution_id: str
    task_id: str
    resume_kickoff_id: str
    status: str
