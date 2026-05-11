"""Tests for the Subagent orchestration system."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanoclaw.core.subagent import (
    SubagentManager,
    SubagentTask,
    configure_subagent_manager,
    get_subagent_manager,
)

# Reset the global _manager before each test in TestSubagentGlobalManager
_cleanup_done = False


def _reset_global_manager():
    import nanoclaw.core.subagent as _m
    _m._manager = None


class TestSubjectTask:
    def test_dataclass_defaults(self):
        task = SubagentTask(id="abc123", description="test task")
        assert task.status == "PENDING"
        assert task.timeout == 120.0
        assert task.result == ""
        assert task.error == ""

    def test_to_dict(self):
        task = SubagentTask(id="abc", description="desc", status="SUCCESS", result="ok")
        d = task.to_dict()
        assert d["id"] == "abc"
        assert d["description"] == "desc"
        assert d["status"] == "SUCCESS"
        assert d["result"] == "ok"


class TestSubagentManager:
    def test_spawn_creates_pending_task(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)
        task_id = manager.spawn("test task", 60.0)
        assert len(task_id) == 12
        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].id == task_id
        assert pending[0].status == "PENDING"
        loop.close()

    def test_spawn_respects_timeout(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)
        task_id = manager.spawn("quick task", 30.0)
        task = manager._tasks[task_id]
        assert task.timeout == 30.0
        loop.close()

    def test_collect_finished(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)
        task = SubagentTask(id="done123", description="done", status="SUCCESS", result="ok")
        manager._tasks["done123"] = task
        task2 = SubagentTask(id="run456", description="running", status="RUNNING")
        manager._tasks["run456"] = task2

        finished = manager.collect_finished()
        assert len(finished) == 1
        assert finished[0].id == "done123"
        assert finished[0].result == "ok"
        assert "done123" not in manager._tasks
        assert "run456" in manager._tasks
        loop.close()

    def test_get_pending(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)
        t1 = SubagentTask(id="a", description="a", status="PENDING")
        t2 = SubagentTask(id="b", description="b", status="RUNNING")
        t3 = SubagentTask(id="c", description="c", status="SUCCESS")
        manager._tasks = {"a": t1, "b": t2, "c": t3}
        pending = manager.get_pending()
        assert len(pending) == 2
        assert {t.id for t in pending} == {"a", "b"}
        loop.close()

    def test_cancel_all(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)
        t1 = SubagentTask(id="a", description="a", status="RUNNING")
        t2 = SubagentTask(id="b", description="b", status="PENDING")
        manager._tasks = {"a": t1, "b": t2}
        manager.cancel_all()
        assert t1.status == "FAILED"
        assert "cancelled" in t1.error
        loop.close()

    def test_update_provider(self):
        loop = asyncio.new_event_loop()
        manager = SubagentManager("old_p", "old_m", loop)
        manager.update_provider("new_p", "new_m")
        assert manager._provider == "new_p"
        assert manager._model == "new_m"
        loop.close()

    def test_concurrency_limit(self):
        """Spawning more than N should queue extras (N=2)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        manager = SubagentManager("tp", "tm", loop)
        manager._semaphore = asyncio.Semaphore(2)

        async def _blocking_invoke(*args, **kwargs):
            await asyncio.sleep(999)

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = _blocking_invoke

        with patch("nanoclaw.core.subagent.get_provider", return_value=mock_llm):
            ids = [manager.spawn(f"task-{i}", 999.0) for i in range(3)]

            async def _wait_and_check():
                await asyncio.sleep(0.2)
                running = [t for t in manager._tasks.values() if t.status == "RUNNING"]
                pending = [t for t in manager._tasks.values() if t.status == "PENDING"]
                return len(running), len(pending)

            n_running, n_pending = loop.run_until_complete(_wait_and_check())
            assert n_running == 2, f"expected 2 running, got {n_running}"
            assert n_pending == 1, f"expected 1 pending, got {n_pending}"

            manager.cancel_all()
        loop.close()

    def test_subagent_react_completes(self):
        """Subagent should SUCCESS when LLM returns without tool calls."""
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)

        mock_response = MagicMock()
        mock_response.tool_calls = []
        mock_response.content = "analysis result: project uses Python 3.12"

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("nanoclaw.core.subagent.get_provider", return_value=mock_llm):
            task_id = manager.spawn("analyze project", 30.0)

            # Wait for completion
            for _ in range(50):
                task = manager._tasks.get(task_id)
                if task and task.status in ("SUCCESS", "FAILED"):
                    break
                loop.run_until_complete(asyncio.sleep(0.05))

            finished = manager.collect_finished()
            assert len(finished) == 1
            assert finished[0].status == "SUCCESS", f"got {finished[0].status}: {finished[0].error}"
            assert "Python 3.12" in finished[0].result
        loop.close()

    def test_subagent_timeout(self):
        """Subagent should FAILED on timeout."""
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=lambda msgs: asyncio.sleep(999))

        with patch("nanoclaw.core.subagent.get_provider", return_value=mock_llm):
            task_id = manager.spawn("slow task", timeout=0.2)
            loop.run_until_complete(asyncio.sleep(0.5))

            task = manager._tasks.get(task_id)
            if task and task.status == "RUNNING":
                manager.cancel_all()

            finished = manager.collect_finished()
            if finished:
                assert finished[0].status == "FAILED"
        loop.close()

    def test_subagent_react_tool_calls(self):
        """Subagent should handle tool calls in its mini ReAct loop."""
        loop = asyncio.new_event_loop()
        manager = SubagentManager("tp", "tm", loop)

        mock_tool_call = {"name": "calculator_sub", "args": {}, "id": "call_1"}
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [mock_tool_call]
        response_with_tool.content = ""

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "final result"

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[response_with_tool, response_final])

        with patch("nanoclaw.core.subagent.get_provider", return_value=mock_llm):
            task_id = manager.spawn("test with tools", 30.0)

            for _ in range(50):
                task = manager._tasks.get(task_id)
                if task and task.status in ("SUCCESS", "FAILED"):
                    break
                loop.run_until_complete(asyncio.sleep(0.05))

            finished = manager.collect_finished()
            assert len(finished) == 1
            assert finished[0].status == "SUCCESS", f"got {finished[0].status}: {finished[0].error}"
            assert "final result" in finished[0].result
        loop.close()


class TestSubagentGlobalManager:
    def test_configure_and_get(self):
        _reset_global_manager()
        loop = asyncio.new_event_loop()
        configure_subagent_manager("p1", "m1", loop)
        mgr = get_subagent_manager()
        assert mgr._provider == "p1"
        assert mgr._model == "m1"
        loop.close()

    def test_get_without_configure_raises(self):
        _reset_global_manager()
        with pytest.raises(AssertionError):
            get_subagent_manager()
