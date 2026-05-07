from fastapi import APIRouter, HTTPException, Query

from nanoclaw.api.runtime import is_valid_thread_id, read_thread_events

router = APIRouter()


@router.get("/sessions/{thread_id}/events")
async def get_events(thread_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    if not is_valid_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="invalid thread_id")
    return {"thread_id": thread_id, "events": read_thread_events(thread_id, limit)}
