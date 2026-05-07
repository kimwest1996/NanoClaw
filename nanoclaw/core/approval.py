"""Human-in-the-loop approval gateway for tool execution.

Provides approval callbacks for CLI, API, and testing scenarios. The approval
callback is injected via LangGraph's RunnableConfig["configurable"] and awaited
inside SafeToolNode._afunc().
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional

from nanoclaw.core.tool_policy import ToolRiskLevel


class ApprovalDecision(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    tool_call_id: str
    args: dict
    risk_level: ToolRiskLevel
    reason: str


@dataclass(frozen=True)
class ApprovalResponse:
    decision: ApprovalDecision
    reason: str


# Type alias for approval callbacks
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalResponse]]


async def auto_approve_callback(request: ApprovalRequest) -> ApprovalResponse:
    """Always approve. For testing and unattended mode."""
    return ApprovalResponse(
        decision=ApprovalDecision.APPROVED,
        reason="auto-approved",
    )


async def auto_deny_callback(request: ApprovalRequest) -> ApprovalResponse:
    """Always deny. For strict safety mode."""
    return ApprovalResponse(
        decision=ApprovalDecision.DENIED,
        reason="auto-denied by strict policy",
    )


async def cli_approval_callback(request: ApprovalRequest) -> ApprovalResponse:
    """Prompt the user in the terminal via questionary.

    Displays the tool name, risk level, and args preview, then asks for
    confirmation. Works with prompt_toolkit's patch_stdout context.
    """
    try:
        import questionary
    except ImportError:
        # Fallback: deny if questionary is not installed
        return ApprovalResponse(
            decision=ApprovalDecision.DENIED,
            reason="questionary not installed, cannot prompt for approval",
        )

    risk_label = request.risk_level.value.upper()
    args_preview = _format_args_preview(request.args)

    print(f"\n  \033[38;5;208m⚠ Approval Required\033[0m")
    print(f"  Tool: \033[1m{request.tool_name}\033[0m")
    print(f"  Risk: \033[38;5;208m{risk_label}\033[0m")
    if args_preview:
        print(f"  Args: {args_preview}")
    print()

    try:
        approved = await questionary.confirm(
            f"Allow '{request.tool_name}' to execute?",
            default=False,
        ).ask_async()
    except (EOFError, KeyboardInterrupt):
        approved = False

    if approved:
        return ApprovalResponse(
            decision=ApprovalDecision.APPROVED,
            reason="approved by user",
        )
    return ApprovalResponse(
        decision=ApprovalDecision.DENIED,
        reason="denied by user",
    )


def create_api_approval_callback() -> tuple[ApprovalCallback, dict[str, asyncio.Future]]:
    """Create an API-compatible approval callback with pending futures.

    Returns:
        A tuple of (callback, pending_dict). The callback creates an asyncio.Future
        keyed by tool_call_id and awaits it with a 120s timeout. The API router
        resolves futures by calling future.set_result().

    Usage:
        callback, pending = create_api_approval_callback()
        # In the agent loop, callback blocks until the future is resolved
        # In the API router: pending[tool_call_id].set_result(ApprovalResponse(...))
    """
    pending: dict[str, asyncio.Future] = {}

    async def api_approval_callback(request: ApprovalRequest) -> ApprovalResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalResponse] = loop.create_future()
        pending[request.tool_call_id] = future

        try:
            response = await asyncio.wait_for(future, timeout=120.0)
            return response
        except asyncio.TimeoutError:
            return ApprovalResponse(
                decision=ApprovalDecision.TIMED_OUT,
                reason="approval timed out after 120 seconds",
            )
        finally:
            pending.pop(request.tool_call_id, None)

    return api_approval_callback, pending


def _format_args_preview(args: dict, max_len: int = 120) -> str:
    """Format tool args into a short preview string."""
    if not args:
        return ""
    parts = []
    for key, value in args.items():
        val_str = str(value)
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        parts.append(f"{key}={val_str}")
    preview = ", ".join(parts)
    if len(preview) > max_len:
        preview = preview[:max_len - 3] + "..."
    return preview
