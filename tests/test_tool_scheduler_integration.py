"""Integration tests for SafeToolNode with tool policy and approval gateway."""

import asyncio
import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage

from nanoclaw.core.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    auto_approve_callback,
    auto_deny_callback,
)
from nanoclaw.core.tool_policy import ToolPolicy, ToolPolicyEntry, ToolRiskLevel, default_policy
from nanoclaw.core.tool_scheduler import SafeToolNode


def _make_tool(name: str, return_value: str = "ok"):
    """Create a simple mock tool."""
    def tool_fn(**kwargs):
        return return_value
    tool_fn.__name__ = name
    tool_fn.__doc__ = f"Mock tool: {name}"
    return tool_fn


def _make_input(tool_calls: list[dict]) -> dict:
    """Wrap tool_calls into a LangGraph-style input dict."""
    ai_msg = AIMessage(content="", tool_calls=tool_calls)
    return {"messages": [ai_msg]}


class TestPolicyIntegration(unittest.TestCase):
    """Test SafeToolNode with tool policy (no approval callback)."""

    def test_allowed_tool_executes_normally(self):
        tools = [_make_tool("get_current_time", "2026-05-07")]
        node = SafeToolNode(tools)
        input_data = _make_input([{"name": "get_current_time", "args": {}, "id": "c1"}])
        result = node._func(input_data, {})
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "2026-05-07")

    def test_policy_denied_tool_returns_error_async(self):
        """Policy checks are enforced in the async path (_afunc)."""
        policy = default_policy()
        policy.denied_tools.add("dangerous_tool")
        tools = [_make_tool("dangerous_tool")]
        node = SafeToolNode(tools, policy=policy)
        input_data = _make_input([{"name": "dangerous_tool", "args": {}, "id": "c1"}])
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(node._afunc(input_data, {}))
        loop.close()
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertIn("denied", messages[0].content.lower())
        self.assertEqual(messages[0].status, "error")

    def test_approval_required_without_callback_denies_async(self):
        """When execute_office_shell is called without an approval callback via async path, it should be denied."""
        tools = [_make_tool("execute_office_shell")]
        node = SafeToolNode(tools)
        input_data = _make_input([{"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c1"}])
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(node._afunc(input_data, {}))
        loop.close()
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].status, "error")

    def test_read_only_tools_bypass_policy(self):
        """Read-only tools should execute without policy checks in sync mode."""
        tools = [_make_tool("calculator", "42")]
        node = SafeToolNode(tools)
        input_data = _make_input([{"name": "calculator", "args": {"expression": "6*7"}, "id": "c1"}])
        result = node._func(input_data, {})
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "42")

    def test_unknown_tool_returns_error(self):
        tools = [_make_tool("calculator", "42")]
        node = SafeToolNode(tools)
        input_data = _make_input([{"name": "nonexistent_tool", "args": {}, "id": "c1"}])
        result = node._func(input_data, {})
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertIn("Unknown tool", messages[0].content)
        self.assertEqual(messages[0].status, "error")


class TestAsyncPolicyIntegration(unittest.TestCase):
    """Test SafeToolNode._afunc with policy and approval callbacks."""

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_async_allowed_tool_executes(self):
        tools = [_make_tool("get_current_time", "2026-05-07")]
        node = SafeToolNode(tools)
        input_data = _make_input([{"name": "get_current_time", "args": {}, "id": "c1"}])
        result = self._run_async(node._afunc(input_data, {}))
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "2026-05-07")

    def test_async_approval_required_with_auto_approve(self):
        tools = [_make_tool("execute_office_shell", "file.txt")]
        node = SafeToolNode(tools)
        input_data = _make_input([
            {"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c1"}
        ])
        config = {"configurable": {"approval_callback": auto_approve_callback}}
        result = self._run_async(node._afunc(input_data, config))
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "file.txt")

    def test_async_approval_required_with_auto_deny(self):
        tools = [_make_tool("execute_office_shell", "file.txt")]
        node = SafeToolNode(tools)
        input_data = _make_input([
            {"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c1"}
        ])
        config = {"configurable": {"approval_callback": auto_deny_callback}}
        result = self._run_async(node._afunc(input_data, config))
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertIn("denied", messages[0].content.lower())
        self.assertEqual(messages[0].status, "error")

    def test_async_no_callback_denies_approval_tools(self):
        tools = [_make_tool("execute_office_shell")]
        node = SafeToolNode(tools)
        input_data = _make_input([
            {"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c1"}
        ])
        result = self._run_async(node._afunc(input_data, {}))
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].status, "error")
        self.assertIn("no approval callback", messages[0].content.lower())

    def test_async_policy_denied_tool(self):
        policy = default_policy()
        policy.denied_tools.add("execute_office_shell")
        tools = [_make_tool("execute_office_shell")]
        node = SafeToolNode(tools, policy=policy)
        input_data = _make_input([
            {"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c1"}
        ])
        config = {"configurable": {"approval_callback": auto_approve_callback}}
        result = self._run_async(node._afunc(input_data, config))
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        self.assertIn("denied", messages[0].content.lower())

    def test_async_mixed_batch_approved_and_readonly(self):
        tools = [
            _make_tool("get_current_time", "now"),
            _make_tool("execute_office_shell", "done"),
        ]
        node = SafeToolNode(tools)
        input_data = _make_input([
            {"name": "get_current_time", "args": {}, "id": "c1"},
            {"name": "execute_office_shell", "args": {"command": "ls"}, "id": "c2"},
        ])
        config = {"configurable": {"approval_callback": auto_approve_callback}}
        result = self._run_async(node._afunc(input_data, config))
        messages = result["messages"]
        self.assertEqual(len(messages), 2)


class TestRetryLogic(unittest.TestCase):
    """Test _run_one_with_retry and _is_retryable_error."""

    def test_is_retryable_error_detects_timeout(self):
        self.assertTrue(SafeToolNode._is_retryable_error("Tool execution error: timed out after 60s"))
        self.assertTrue(SafeToolNode._is_retryable_error("Timeout: operation took too long"))
        self.assertTrue(SafeToolNode._is_retryable_error("Connection error"))
        self.assertTrue(SafeToolNode._is_retryable_error("Resource temporarily unavailable"))

    def test_is_retryable_error_rejects_permanent(self):
        self.assertFalse(SafeToolNode._is_retryable_error("Permission denied"))
        self.assertFalse(SafeToolNode._is_retryable_error("Unknown tool: foo"))
        self.assertFalse(SafeToolNode._is_retryable_error("Policy Denied: blocked"))

    def test_retry_on_transient_error(self):
        call_count = {"n": 0}
        original_run_one = SafeToolNode._run_one

        def flaky_run_one(self_node, call, config):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ToolMessage(
                    content="Timeout: timed out",
                    name="test_tool",
                    tool_call_id="c1",
                    status="error",
                )
            return ToolMessage(
                content="success",
                name="test_tool",
                tool_call_id="c1",
            )

        tools = [_make_tool("test_tool")]
        node = SafeToolNode(tools)
        import threading
        lock = threading.Lock()

        # Monkey-patch for this test
        node._run_one = lambda call, config: flaky_run_one(node, call, config)
        result = node._run_one_with_retry(
            {"name": "test_tool", "args": {}, "id": "c1"},
            {},
            lock,
            max_retries=2,
        )
        self.assertEqual(result.content, "success")
        self.assertEqual(call_count["n"], 2)

    def test_retry_exhaustion(self):
        call_count = {"n": 0}

        def always_fail(self_node, call, config):
            call_count["n"] += 1
            return ToolMessage(
                content="Timeout: timed out",
                name="test_tool",
                tool_call_id="c1",
                status="error",
            )

        tools = [_make_tool("test_tool")]
        node = SafeToolNode(tools)
        import threading
        lock = threading.Lock()

        node._run_one = lambda call, config: always_fail(node, call, config)
        result = node._run_one_with_retry(
            {"name": "test_tool", "args": {}, "id": "c1"},
            {},
            lock,
            max_retries=2,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(call_count["n"], 3)  # initial + 2 retries

    def test_non_retryable_error_skips_retry(self):
        call_count = {"n": 0}

        def perm_fail(self_node, call, config):
            call_count["n"] += 1
            return ToolMessage(
                content="Permission Denied: blocked",
                name="test_tool",
                tool_call_id="c1",
                status="error",
            )

        tools = [_make_tool("test_tool")]
        node = SafeToolNode(tools)
        import threading
        lock = threading.Lock()

        node._run_one = lambda call, config: perm_fail(node, call, config)
        result = node._run_one_with_retry(
            {"name": "test_tool", "args": {}, "id": "c1"},
            {},
            lock,
            max_retries=2,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(call_count["n"], 1)  # no retries for non-retryable


if __name__ == "__main__":
    unittest.main()
