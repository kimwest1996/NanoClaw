from fastapi import APIRouter, Request

from nanoclaw.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        provider=request.app.state.provider,
        model=request.app.state.model,
    )
