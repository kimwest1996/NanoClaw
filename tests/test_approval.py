import asyncio
import unittest

from nanoclaw.core.approval import (
    ApprovalCallback,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    auto_approve_callback,
    auto_deny_callback,
    create_api_approval_callback,
    _format_args_preview,
)
from nanoclaw.core.tool_policy import ToolRiskLevel


def _make_request(tool_name: str = "execute_office_shell", tool_call_id: str = "call_1") -> ApprovalRequest:
    return ApprovalRequest(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args={"command": "ls -la"},
        risk_level=ToolRiskLevel.HIGH,
        reason="requires approval",
    )


class TestAutoApproveCallback(unittest.TestCase):
    def test_returns_approved(self):
        request = _make_request()
        result = asyncio.get_event_loop().run_until_complete(auto_approve_callback(request))
        self.assertEqual(result.decision, ApprovalDecision.APPROVED)
        self.assertIn("auto-approved", result.reason)


class TestAutoDenyCallback(unittest.TestCase):
    def test_returns_denied(self):
        request = _make_request()
        result = asyncio.get_event_loop().run_until_complete(auto_deny_callback(request))
        self.assertEqual(result.decision, ApprovalDecision.DENIED)
        self.assertIn("auto-denied", result.reason)


class TestCreateApiApprovalCallback(unittest.TestCase):
    def test_returns_callback_and_pending_dict(self):
        callback, pending = create_api_approval_callback()
        self.assertTrue(callable(callback))
        self.assertIsInstance(pending, dict)
        self.assertEqual(len(pending), 0)

    def test_callback_stores_pending_future(self):
        callback, pending = create_api_approval_callback()
        request = _make_request(tool_call_id="call_42")
        results = []

        async def resolve_later():
            await asyncio.sleep(0.05)
            while "call_42" not in pending:
                await asyncio.sleep(0.01)
            pending["call_42"].set_result(
                ApprovalResponse(decision=ApprovalDecision.APPROVED, reason="resolved")
            )

        async def run():
            resp = await callback(request)
            results.append(resp)

        async def main():
            await asyncio.gather(run(), resolve_later())

        asyncio.get_event_loop().run_until_complete(main())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].decision, ApprovalDecision.APPROVED)
        # Pending should be cleaned up
        self.assertEqual(len(pending), 0)

    def test_callback_timeout(self):
        callback, pending = create_api_approval_callback()
        request = _make_request(tool_call_id="call_timeout")

        async def run():
            # Never resolve the future — should time out
            return await callback(request)

        # Override timeout for test speed
        import nanoclaw.core.approval as mod

        original_wait_for = asyncio.wait_for

        async def fast_wait_for(fut, timeout=None):
            return await original_wait_for(fut, timeout=0.1)

        asyncio.wait_for = fast_wait_for
        try:
            result = asyncio.get_event_loop().run_until_complete(run())
        finally:
            asyncio.wait_for = original_wait_for

        self.assertEqual(result.decision, ApprovalDecision.TIMED_OUT)
        self.assertEqual(len(pending), 0)

    def test_callback_deny_resolution(self):
        callback, pending = create_api_approval_callback()
        request = _make_request(tool_call_id="call_deny")
        results = []

        async def resolve_deny():
            await asyncio.sleep(0.05)
            while "call_deny" not in pending:
                await asyncio.sleep(0.01)
            pending["call_deny"].set_result(
                ApprovalResponse(decision=ApprovalDecision.DENIED, reason="user denied")
            )

        async def run():
            resp = await callback(request)
            results.append(resp)

        async def main():
            await asyncio.gather(run(), resolve_deny())

        asyncio.get_event_loop().run_until_complete(main())
        self.assertEqual(results[0].decision, ApprovalDecision.DENIED)


class TestFormatArgsPreview(unittest.TestCase):
    def test_empty_args(self):
        self.assertEqual(_format_args_preview({}), "")

    def test_short_args(self):
        result = _format_args_preview({"command": "ls"})
        self.assertEqual(result, "command=ls")

    def test_long_value_truncated(self):
        long_val = "x" * 200
        result = _format_args_preview({"content": long_val})
        self.assertIn("...", result)
        self.assertLessEqual(len(result), 150)

    def test_multiple_args(self):
        result = _format_args_preview({"a": 1, "b": 2})
        self.assertIn("a=1", result)
        self.assertIn("b=2", result)


class TestApprovalRequest(unittest.TestCase):
    def test_frozen(self):
        request = _make_request()
        self.assertEqual(request.tool_name, "execute_office_shell")
        self.assertEqual(request.tool_call_id, "call_1")
        self.assertEqual(request.risk_level, ToolRiskLevel.HIGH)

    def test_cannot_modify(self):
        request = _make_request()
        with self.assertRaises(AttributeError):
            request.tool_name = "other"


class TestApprovalResponse(unittest.TestCase):
    def test_frozen(self):
        response = ApprovalResponse(decision=ApprovalDecision.APPROVED, reason="ok")
        self.assertEqual(response.decision, ApprovalDecision.APPROVED)
        with self.assertRaises(AttributeError):
            response.decision = ApprovalDecision.DENIED


if __name__ == "__main__":
    unittest.main()
