from pydantic import BaseModel, field_validator


class StartScreeningCallRequest(BaseModel):
    screening_id: str
    candidate_mobile_no: str
    candidate_name: str
    interview_language: str
    questions: list[str]

    @field_validator("screening_id", "candidate_mobile_no", "candidate_name", "interview_language")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, questions: list[str]) -> list[str]:
        cleaned_questions = [question.strip() for question in questions if question.strip()]
        if not cleaned_questions:
            raise ValueError("questions must contain at least one non-empty question")
        return cleaned_questions


class StartScreeningCallResponse(BaseModel):
    success: bool
    room_name: str
    screening_id: str
    candidate_mobile_no: str
    message: str
    dispatch_id: str

