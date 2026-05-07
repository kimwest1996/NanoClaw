from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from nanoclaw.api.runtime import clean_content, final_ai_content, is_valid_thread_id, safe_json
from nanoclaw.api.schemas import MessageRequest, MessageResponse
from nanoclaw.core.approval import ApprovalDecision, ApprovalResponse

router = APIRouter()


def _config(thread_id: str, approval_callback=None) -> dict:
    configurable = {"thread_id": thread_id}
    if approval_callback is not None:
        configurable["approval_callback"] = approval_callback
    return {"configurable": configurable}


@router.post("/sessions/{thread_id}/messages", response_model=MessageResponse)
async def create_message(thread_id: str, message: MessageRequest, request: Request) -> MessageResponse:
    if not is_valid_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="invalid thread_id")
    content = clean_content(message.content)
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")

    try:
        result = await request.app.state.agent_app.ainvoke(
            {"messages": [HumanMessage(content=content)]},
            config=_config(thread_id, getattr(request.app.state, "approval_callback", None)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    messages = result.get("messages", [])
    return MessageResponse(
        thread_id=thread_id,
        content=final_ai_content(messages),
        messages_count=len(messages),
    )


@router.post("/sessions/{thread_id}/messages/stream")
async def stream_message(thread_id: str, message: MessageRequest, request: Request) -> StreamingResponse:
    if not is_valid_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="invalid thread_id")
    content = clean_content(message.content)
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")

    async def event_generator():
        try:
            async for event in request.app.state.agent_app.astream(
                {"messages": [HumanMessage(content=content)]},
                config=_config(thread_id, getattr(request.app.state, "approval_callback", None)),
                stream_mode="updates",
            ):
                for node_name, node_data in event.items():
                    yield f"event: {node_name}\n"
                    yield f"data: {safe_json(node_data)}\n\n"
            yield "event: done\n"
            yield f"data: {safe_json({'thread_id': thread_id})}\n\n"
        except Exception as exc:
            yield "event: error\n"
            yield f"data: {safe_json({'error_code': 'graph_stream_error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class ApprovalBody(BaseModel):
    decision: str  # "approved" or "denied"


@router.post("/sessions/{thread_id}/approvals/{tool_call_id}")
async def resolve_approval(
    thread_id: str,
    tool_call_id: str,
    body: ApprovalBody,
    request: Request,
) -> dict:
    """Resolve a pending approval request for a tool call."""
    pending = getattr(request.app.state, "pending_approvals", None)
    if pending is None:
        raise HTTPException(status_code=503, detail="approval system not initialized")

    future = pending.get(tool_call_id)
    if future is None:
        raise HTTPException(status_code=404, detail=f"no pending approval for tool_call_id '{tool_call_id}'")

    if future.done():
        raise HTTPException(status_code=409, detail="approval already resolved")

    decision = body.decision.lower().strip()
    if decision == "approved":
        future.set_result(ApprovalResponse(
            decision=ApprovalDecision.APPROVED,
            reason="approved via API",
        ))
    elif decision == "denied":
        future.set_result(ApprovalResponse(
            decision=ApprovalDecision.DENIED,
            reason="denied via API",
        ))
    else:
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'denied'")

    return {"tool_call_id": tool_call_id, "decision": decision}


@router.get("/sessions/{thread_id}/approvals")
async def list_pending_approvals(
    thread_id: str,
    request: Request,
) -> dict:
    """List pending approval requests."""
    pending = getattr(request.app.state, "pending_approvals", None)
    if pending is None:
        return {"pending": []}

    active = [
        {"tool_call_id": tid}
        for tid, future in pending.items()
        if not future.done()
    ]
    return {"pending": active}
