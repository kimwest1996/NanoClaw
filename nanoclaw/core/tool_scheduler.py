from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, Sequence, Union

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool as create_tool
from langgraph.utils.runnable import RunnableCallable

from .approval import ApprovalCallback, ApprovalDecision, ApprovalRequest
from .logger import audit_logger, trace_ctx
from .tool_errors import ToolErrorCode, ToolExecutionError
from .tool_policy import PolicyAction, ToolPolicy, default_policy

ExecutionKind = Literal["read_only", "side_effect"]

READ_ONLY_TOOLS = {
    "get_current_time",
    "calculator",
    "get_system_model_info",
    "list_office_files",
    "read_office_file",
    "list_scheduled_tasks",
    "web_search",
}

RESOURCE_BY_TOOL = {
    "save_user_profile": "profile",
    "schedule_task": "tasks",
    "delete_scheduled_task": "tasks",
    "modify_scheduled_task": "tasks",
    "write_office_file": "office",
    "execute_office_shell": "office",
}

_RESOURCE_LOCKS: dict[str, threading.Lock] = {
    "profile": threading.Lock(),
    "tasks": threading.Lock(),
    "office": threading.Lock(),
    "custom": threading.Lock(),
}


@dataclass(frozen=True)
class ToolExecutionPolicy:
    kind: ExecutionKind
    resource: Optional[str] = None

    @property
    def is_read_only(self) -> bool:
        return self.kind == "read_only"


def _tool_metadata(tool_obj: Optional[BaseTool]) -> dict[str, Any]:
    metadata = getattr(tool_obj, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _stringify_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


class SafeToolNode(RunnableCallable):
    """Tool node with Claude Code-style scheduling.

    Consecutive read-only tool calls are executed in parallel. Side-effecting tool
    calls are executed serially and protected by a coarse resource lock.
    """

    def __init__(
        self,
        tools: Sequence[Union[BaseTool, Callable]],
        *,
        name: str = "tools",
        messages_key: str = "messages",
        policy: Optional[ToolPolicy] = None,
    ) -> None:
        super().__init__(self._func, self._afunc, name=name, trace=False)
        self.messages_key = messages_key
        self.policy = policy or default_policy()
        self.tools_by_name: dict[str, BaseTool] = {}
        for tool_obj in tools:
            if not isinstance(tool_obj, BaseTool):
                tool_obj = create_tool(tool_obj)
            self.tools_by_name[tool_obj.name] = tool_obj

    def _func(
        self,
        input: Union[list[Any], dict[str, Any], Any],
        config: RunnableConfig,
        *,
        store: Any = None,
    ) -> Any:
        tool_calls, input_type = self._parse_input(input)
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "system_default")
        policies = [self.classify_tool_call(call) for call in tool_calls]
        self._log_batch(thread_id, tool_calls, policies)

        outputs: list[Optional[ToolMessage]] = [None] * len(tool_calls)
        index = 0
        while index < len(tool_calls):
            policy = policies[index]
            if policy.is_read_only:
                start = index
                while index < len(tool_calls) and policies[index].is_read_only:
                    index += 1
                self._run_read_block(tool_calls, start, index, config, outputs)
            else:
                outputs[index] = self._run_side_effect(tool_calls[index], policy, config)
                index += 1

        messages = [output for output in outputs if output is not None]
        if input_type == "list":
            return messages
        return {self.messages_key: messages}

    async def _afunc(
        self,
        input: Union[list[Any], dict[str, Any], Any],
        config: RunnableConfig,
        *,
        store: Any = None,
    ) -> Any:
        tool_calls, input_type = self._parse_input(input)
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "system_default")
        approval_callback: Optional[ApprovalCallback] = (
            (config or {}).get("configurable", {}).get("approval_callback")
        )
        policies = [self.classify_tool_call(call) for call in tool_calls]
        self._log_batch(thread_id, tool_calls, policies)

        outputs: list[Optional[ToolMessage]] = [None] * len(tool_calls)
        index = 0
        while index < len(tool_calls):
            exec_policy = policies[index]
            if exec_policy.is_read_only:
                start = index
                while index < len(tool_calls) and policies[index].is_read_only:
                    index += 1
                await self._arun_read_block(tool_calls, start, index, config, outputs)
            else:
                # Policy check + approval for side-effect tools
                blocked = await self._check_and_approve(
                    tool_calls[index], approval_callback, thread_id
                )
                if blocked is not None:
                    outputs[index] = blocked
                else:
                    outputs[index] = await self._arun_side_effect(
                        tool_calls[index], exec_policy, config
                    )
                index += 1

        messages = [output for output in outputs if output is not None]
        if input_type == "list":
            return messages
        return {self.messages_key: messages}

    async def _check_and_approve(
        self,
        call: dict[str, Any],
        approval_callback: Optional[ApprovalCallback],
        thread_id: str = "system_default",
    ) -> Optional[ToolMessage]:
        """Check tool policy and request approval if needed.

        Returns None if the tool should proceed, or a ToolMessage if blocked.
        """
        tool_name = str(call.get("name", ""))
        tool_call_id = str(call.get("id", ""))
        args = call.get("args") or {}

        result = self.policy.check(tool_name, args)

        audit_logger.log_event(
            thread_id=thread_id,
            event="tool_policy_check",
            tool=tool_name,
            action=result.action.value,
            risk_level=result.risk_level.value,
            reason=result.reason,
        )

        if result.action == PolicyAction.DENY:
            error = ToolExecutionError(
                error_code=ToolErrorCode.POLICY_DENIED,
                message=result.reason,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                retryable=False,
            )
            return ToolMessage(
                content=error.to_tool_message_content(),
                name=tool_name,
                tool_call_id=tool_call_id,
                status="error",
            )

        if result.action == PolicyAction.NEED_APPROVAL:
            if approval_callback is None:
                error = ToolExecutionError(
                    error_code=ToolErrorCode.APPROVAL_DENIED,
                    message=f"tool '{tool_name}' requires approval but no approval callback is configured",
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    retryable=False,
                )
                return ToolMessage(
                    content=error.to_tool_message_content(),
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    status="error",
                )

            request = ApprovalRequest(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                args=args,
                risk_level=result.risk_level,
                reason=result.reason,
            )
            response = await approval_callback(request)

            audit_logger.log_event(
                thread_id=thread_id,
                event="tool_approval_result",
                tool=tool_name,
                decision=response.decision.value,
                reason=response.reason,
            )

            if response.decision != ApprovalDecision.APPROVED:
                error = ToolExecutionError(
                    error_code=ToolErrorCode.APPROVAL_DENIED
                    if response.decision == ApprovalDecision.DENIED
                    else ToolErrorCode.APPROVAL_TIMEOUT,
                    message=response.reason,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    retryable=False,
                )
                return ToolMessage(
                    content=error.to_tool_message_content(),
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    status="error",
                )

        # ALLOW — proceed
        return None

    async def _arun_read_block(
        self,
        tool_calls: list[dict[str, Any]],
        start: int,
        end: int,
        config: RunnableConfig,
        outputs: list[Optional[ToolMessage]],
    ) -> None:
        block = tool_calls[start:end]
        results = await asyncio.gather(
            *(asyncio.to_thread(self._run_one, call, config) for call in block)
        )
        for offset, result in enumerate(results):
            outputs[start + offset] = result

    async def _arun_side_effect(
        self,
        call: dict[str, Any],
        policy: ToolExecutionPolicy,
        config: RunnableConfig,
    ) -> ToolMessage:
        resource = policy.resource or "custom"
        lock = _RESOURCE_LOCKS.setdefault(resource, threading.Lock())
        span_id = trace_ctx.new_span_id()
        t0 = time.monotonic()
        result = await asyncio.to_thread(self._run_one_with_retry, call, config, lock)
        duration = (time.monotonic() - t0) * 1000
        error_code = None
        if hasattr(result, 'status') and result.status == "error":
            error_code = "EXECUTION_ERROR"
        audit_logger.log_event(
            event="tool_scheduler",
            tool_name=str(call.get("name", "")),
            duration_ms=duration,
            span_id=span_id,
            status=getattr(result, 'status', 'success'),
            error_code=error_code,
        )
        return result

    def _run_one_with_retry(
        self,
        call: dict[str, Any],
        config: RunnableConfig,
        lock: threading.Lock,
        max_retries: int = 2,
    ) -> ToolMessage:
        """Execute a tool with retry on transient errors."""
        last_result = None
        for attempt in range(max_retries + 1):
            with lock:
                result = self._run_one(call, config)
            # Check if this was an error worth retrying
            if result.status == "error" and attempt < max_retries:
                if self._is_retryable_error(result.content):
                    time.sleep(0.5 * (2 ** attempt))  # exponential backoff
                    last_result = result
                    continue
            return result
        return last_result  # type: ignore[return-value]

    @staticmethod
    def _is_retryable_error(content: str) -> bool:
        """Check if an error message indicates a transient/retryable failure."""
        retryable_patterns = [
            "timeout",
            "timed out",
            "connection",
            "network",
            "temporary",
            "try again",
            "resource temporarily unavailable",
        ]
        content_lower = content.lower()
        return any(p in content_lower for p in retryable_patterns)

    def _parse_input(
        self, input: Union[list[Any], dict[str, Any], Any]
    ) -> tuple[list[dict[str, Any]], Literal["list", "dict", "tool_calls"]]:
        if isinstance(input, list):
            if input and isinstance(input[-1], dict) and input[-1].get("type") == "tool_call":
                return input, "tool_calls"
            messages = input
            input_type: Literal["list", "dict", "tool_calls"] = "list"
        elif isinstance(input, dict) and self.messages_key in input:
            messages = input.get(self.messages_key, [])
            input_type = "dict"
        else:
            messages = getattr(input, self.messages_key, [])
            input_type = "dict"

        latest_ai_message = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            None,
        )
        if latest_ai_message is None:
            raise ValueError("No AIMessage found in input")
        return list(latest_ai_message.tool_calls), input_type

    def classify_tool_call(self, call: dict[str, Any]) -> ToolExecutionPolicy:
        tool_name = str(call.get("name", ""))
        args = call.get("args") or {}
        tool_obj = self.tools_by_name.get(tool_name)
        metadata = _tool_metadata(tool_obj)

        execution = metadata.get("nanoclaw_execution")
        if execution == "read_only":
            return ToolExecutionPolicy("read_only")
        if execution == "side_effect":
            resource = str(metadata.get("nanoclaw_resource") or "custom")
            return ToolExecutionPolicy("side_effect", resource)

        if tool_name in READ_ONLY_TOOLS:
            return ToolExecutionPolicy("read_only")
        if tool_name in RESOURCE_BY_TOOL:
            return ToolExecutionPolicy("side_effect", RESOURCE_BY_TOOL[tool_name])

        # Dynamic skills all share the same two-phase schema. Help is a read-only
        # manual lookup; run delegates to shell and must be serialized as office IO.
        if "mode" in args:
            mode = str(args.get("mode", "")).lower()
            if mode == "help":
                return ToolExecutionPolicy("read_only")
            return ToolExecutionPolicy("side_effect", "office")

        return ToolExecutionPolicy("side_effect", "custom")

    def _run_read_block(
        self,
        tool_calls: list[dict[str, Any]],
        start: int,
        end: int,
        config: RunnableConfig,
        outputs: list[Optional[ToolMessage]],
    ) -> None:
        block = tool_calls[start:end]
        max_workers = (config or {}).get("max_concurrency") or len(block) or 1
        max_workers = max(1, min(int(max_workers), len(block) or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(lambda call: self._run_one(call, config), block))
        for offset, result in enumerate(results):
            outputs[start + offset] = result

    def _run_side_effect(
        self,
        call: dict[str, Any],
        policy: ToolExecutionPolicy,
        config: RunnableConfig,
    ) -> ToolMessage:
        resource = policy.resource or "custom"
        lock = _RESOURCE_LOCKS.setdefault(resource, threading.Lock())
        with lock:
            return self._run_one(call, config)

    def _run_one(self, call: dict[str, Any], config: RunnableConfig) -> ToolMessage:
        tool_name = str(call.get("name", ""))
        tool_call_id = str(call.get("id", ""))
        tool_obj = self.tools_by_name.get(tool_name)
        if tool_obj is None:
            available = ", ".join(sorted(self.tools_by_name.keys()))
            return ToolMessage(
                content=f"Unknown tool: {tool_name}. Available tools: {available}",
                name=tool_name,
                tool_call_id=tool_call_id,
                status="error",
            )

        try:
            call_args = {**call, "type": "tool_call"}
            response = tool_obj.invoke(call_args, config)
        except Exception as exc:
            return ToolMessage(
                content=f"Tool execution error: {exc}",
                name=tool_name,
                tool_call_id=tool_call_id,
                status="error",
            )

        if isinstance(response, ToolMessage):
            response.name = response.name or tool_name
            response.tool_call_id = response.tool_call_id or tool_call_id
            response.content = _stringify_content(response.content)
            return response

        return ToolMessage(
            content=_stringify_content(response),
            name=tool_name,
            tool_call_id=tool_call_id,
        )

    def _log_batch(
        self,
        thread_id: str,
        tool_calls: list[dict[str, Any]],
        policies: list[ToolExecutionPolicy],
    ) -> None:
        if not tool_calls:
            return
        read_only_count = sum(1 for policy in policies if policy.is_read_only)
        side_effect_count = len(policies) - read_only_count
        audit_logger.log_event(
            thread_id=thread_id,
            event="tool_batch",
            total=len(tool_calls),
            read_only_count=read_only_count,
            side_effect_count=side_effect_count,
            strategy="read_parallel_write_serial",
            tools=[
                {
                    "name": call.get("name"),
                    "kind": policy.kind,
                    "resource": policy.resource,
                }
                for call, policy in zip(tool_calls, policies)
            ],
        )
