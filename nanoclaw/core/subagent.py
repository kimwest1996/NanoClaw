"""Subagent orchestration: async background execution with concurrency control."""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .provider import get_provider


@dataclass
class SubagentTask:
    id: str
    description: str
    status: str = "PENDING"       # PENDING | RUNNING | SUCCESS | FAILED
    created_at: float = 0.0
    timeout: float = 120.0
    result: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "timeout": self.timeout,
            "result": self.result,
            "error": self.error,
        }


SUBAGENT_SYSTEM_PROMPT = """你是一个后台分析子代理，专注于完成被分配的特定任务。

规则：
1. 你可以使用只读工具（读文件、搜代码、查网页、计算器）来获取需要的信息
2. 不要提问，直接执行
3. 完成后直接输出最终结果，不要加额外解释
4. 如果不需要工具，直接输出结果即可"""


class SubagentManager:
    """Manages async subagent execution with concurrency and timeout protection."""

    def __init__(self, provider: str, model: str, loop: asyncio.AbstractEventLoop):
        self._provider = provider
        self._model = model
        self._loop = loop
        self._tasks: dict[str, SubagentTask] = {}
        self._futures: dict[str, concurrent.futures.Future] = {}
        self._semaphore = asyncio.Semaphore(5)

    # ── public API ────────────────────────────────────────────────

    def spawn(self, description: str, timeout: float = 120.0) -> str:
        """Create a subagent task and schedule it on the event loop.

        Called from a thread-pool (SafeToolNode), so we use
        run_coroutine_threadsafe to dispatch onto the main loop.
        """
        task_id = uuid.uuid4().hex[:12]
        task = SubagentTask(
            id=task_id,
            description=description,
            status="PENDING",
            created_at=time.monotonic(),
            timeout=timeout,
        )
        self._tasks[task_id] = task
        fut = asyncio.run_coroutine_threadsafe(self._run_subagent(task_id), self._loop)
        self._futures[task_id] = fut
        return task_id

    def collect_finished(self) -> list[SubagentTask]:
        """Return and remove all SUCCESS/FAILED tasks."""
        finished: list[SubagentTask] = []
        for tid, task in list(self._tasks.items()):
            if task.status in ("SUCCESS", "FAILED"):
                finished.append(task)
                del self._tasks[tid]
                self._futures.pop(tid, None)
        return finished

    def get_pending(self) -> list[SubagentTask]:
        """Return all PENDING/RUNNING tasks."""
        return [t for t in self._tasks.values() if t.status in ("PENDING", "RUNNING")]

    def cancel_all(self) -> None:
        """Cancel all running subagents (cleanup on shutdown)."""
        for tid, task in list(self._tasks.items()):
            if task.status == "RUNNING":
                task.status = "FAILED"
                task.error = "cancelled (shutdown)"
            fut = self._futures.pop(tid, None)
            if fut is not None and not fut.done():
                fut.cancel()

    def update_provider(self, provider: str, model: str) -> None:
        """Update the provider/model used by new subagents."""
        self._provider = provider
        self._model = model

    # ── internal ──────────────────────────────────────────────────

    async def _run_subagent(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return

        async with self._semaphore:
            task.status = "RUNNING"
            try:
                result = await asyncio.wait_for(
                    self._run_react(task),
                    timeout=task.timeout,
                )
                task.result = result
                task.status = "SUCCESS"
            except asyncio.TimeoutError:
                task.error = f"timeout after {task.timeout:.0f}s"
                task.status = "FAILED"
            except Exception as exc:
                task.error = str(exc)
                task.status = "FAILED"

    async def _run_react(self, task: SubagentTask) -> str:
        """Mini ReAct loop: LLM + read-only tools, max 8 steps."""
        llm = get_provider(self._provider, self._model)
        subagent_tools = _build_subagent_tools()
        llm_with_tools = llm.bind_tools(subagent_tools)
        tool_map = {t.name: t for t in subagent_tools}

        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        messages = [
            SystemMessage(content=SUBAGENT_SYSTEM_PROMPT),
            HumanMessage(content=task.description),
        ]

        for step in range(8):
            response = await llm_with_tools.ainvoke(messages)
            if not response.tool_calls:
                return response.content or ""

            messages.append(response)
            for tc in response.tool_calls:
                tool = tool_map.get(tc["name"])
                if tool is None:
                    msg = f"unknown tool: {tc['name']}"
                    messages.append(ToolMessage(content=msg, tool_call_id=tc["id"], name=tc["name"]))
                    continue
                try:
                    tool_result = await asyncio.to_thread(tool.invoke, tc["args"])
                except Exception as exc:
                    tool_result = f"error: {exc}"
                messages.append(
                    ToolMessage(content=str(tool_result), tool_call_id=tc["id"], name=tc["name"])
                )

        return "（已达到最大分析步数）"


def _build_subagent_tools():
    """Build the read-only tool set available to subagents."""
    from langchain_core.tools import tool as create_tool
    from .tools.sandbox_tools import list_office_files, read_office_file
    from .tools.web_search import web_search

    @create_tool
    def get_current_time_sub() -> str:
        """获取当前系统时间"""
        from datetime import datetime
        return f"当前时间是: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    @create_tool
    def calculator_sub(expression: str) -> str:
        """执行数学计算"""
        try:
            result = eval(expression, {"__builtins__": {}}, {})
            return f"计算结果: {result}"
        except Exception as e:
            return f"计算错误: {e}"

    return [
        get_current_time_sub,
        calculator_sub,
        list_office_files,
        read_office_file,
        web_search,
    ]


# ── module-level singleton ───────────────────────────────────────

_manager: Optional[SubagentManager] = None


def configure_subagent_manager(
    provider: str, model: str, loop: asyncio.AbstractEventLoop
) -> SubagentManager:
    global _manager
    _manager = SubagentManager(provider, model, loop)
    return _manager


def get_subagent_manager() -> SubagentManager:
    assert _manager is not None, "SubagentManager not configured"
    return _manager
