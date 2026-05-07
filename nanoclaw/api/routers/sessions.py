from uuid import uuid4

from fastapi import APIRouter, HTTPException

from nanoclaw.api.runtime import is_valid_thread_id
from nanoclaw.api.schemas import CreateSessionRequest, CreateSessionResponse

router = APIRouter()


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    thread_id = request.thread_id or str(uuid4())
    if not is_valid_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="thread_id may only contain letters, numbers, '-' and '_'")
    return CreateSessionResponse(thread_id=thread_id)
