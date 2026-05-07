from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    provider: str
    model: str


class CreateSessionRequest(BaseModel):
    thread_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    thread_id: str


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class MessageResponse(BaseModel):
    thread_id: str
    content: str
    messages_count: int

