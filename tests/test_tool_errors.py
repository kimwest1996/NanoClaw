import unittest

from nanoclaw.core.tool_errors import ToolErrorCode, ToolExecutionError


class TestToolErrorCode(unittest.TestCase):
    def test_all_codes_exist(self):
        expected = [
            "unknown_tool", "execution_error", "timeout", "permission_denied",
            "policy_denied", "approval_denied", "approval_timeout", "transient_error",
        ]
        actual = [code.value for code in ToolErrorCode]
        self.assertEqual(sorted(actual), sorted(expected))


class TestToolExecutionError(unittest.TestCase):
    def test_fields(self):
        err = ToolExecutionError(
            error_code=ToolErrorCode.POLICY_DENIED,
            message="tool blocked by policy",
            tool_name="execute_office_shell",
            tool_call_id="call_123",
            retryable=False,
        )
        self.assertEqual(err.error_code, ToolErrorCode.POLICY_DENIED)
        self.assertEqual(err.message, "tool blocked by policy")
        self.assertEqual(err.tool_name, "execute_office_shell")
        self.assertEqual(err.tool_call_id, "call_123")
        self.assertFalse(err.retryable)

    def test_str(self):
        err = ToolExecutionError(
            error_code=ToolErrorCode.TIMEOUT,
            message="timed out after 60s",
        )
        self.assertIn("timeout", str(err))
        self.assertIn("timed out after 60s", str(err))

    def test_to_tool_message_content(self):
        cases = [
            (ToolErrorCode.POLICY_DENIED, "blocked", "Policy Denied"),
            (ToolErrorCode.APPROVAL_DENIED, "user said no", "Approval Denied"),
            (ToolErrorCode.APPROVAL_TIMEOUT, "no response", "Approval Timeout"),
            (ToolErrorCode.PERMISSION_DENIED, "no access", "Permission Denied"),
            (ToolErrorCode.TIMEOUT, "too slow", "Timeout"),
            (ToolErrorCode.TRANSIENT_ERROR, "try again", "Transient Error"),
            (ToolErrorCode.EXECUTION_ERROR, "broke", "Error"),
            (ToolErrorCode.UNKNOWN_TOOL, "who?", "Error"),
        ]
        for code, msg, expected_prefix in cases:
            err = ToolExecutionError(error_code=code, message=msg)
            content = err.to_tool_message_content()
            self.assertTrue(
                content.startswith(expected_prefix),
                f"{code.value}: expected prefix '{expected_prefix}', got '{content}'",
            )
            self.assertIn(msg, content)

    def test_cause_preserved(self):
        original = ValueError("bad value")
        err = ToolExecutionError(
            error_code=ToolErrorCode.EXECUTION_ERROR,
            message="wrapped",
            cause=original,
        )
        self.assertIs(err.cause, original)

    def test_is_exception(self):
        err = ToolExecutionError(
            error_code=ToolErrorCode.EXECUTION_ERROR,
            message="test",
        )
        self.assertIsInstance(err, Exception)


if __name__ == "__main__":
    unittest.main()
