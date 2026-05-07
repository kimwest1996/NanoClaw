import unittest

from nanoclaw.core.tool_policy import (
    PolicyAction,
    PolicyResult,
    ToolPolicy,
    ToolPolicyEntry,
    ToolRiskLevel,
    default_policy,
)


class TestToolRiskLevel(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(ToolRiskLevel.SAFE.value, "safe")
        self.assertEqual(ToolRiskLevel.LOW.value, "low")
        self.assertEqual(ToolRiskLevel.MEDIUM.value, "medium")
        self.assertEqual(ToolRiskLevel.HIGH.value, "high")
        self.assertEqual(ToolRiskLevel.CRITICAL.value, "critical")


class TestPolicyResult(unittest.TestCase):
    def test_frozen_dataclass(self):
        result = PolicyResult(
            action=PolicyAction.ALLOW,
            risk_level=ToolRiskLevel.SAFE,
            reason="test",
        )
        self.assertEqual(result.action, PolicyAction.ALLOW)
        self.assertEqual(result.risk_level, ToolRiskLevel.SAFE)
        self.assertEqual(result.reason, "test")


class TestDefaultPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = default_policy()

    def test_default_policy_maps_all_13_tools(self):
        all_tools = [
            "get_current_time", "calculator", "get_system_model_info",
            "list_office_files", "read_office_file", "list_scheduled_tasks", "web_search",
            "save_user_profile", "write_office_file", "schedule_task",
            "modify_scheduled_task", "delete_scheduled_task",
            "execute_office_shell",
        ]
        for tool_name in all_tools:
            self.assertIn(tool_name, self.policy.tool_entries, f"missing entry for {tool_name}")

    def test_safe_tools_return_allow(self):
        for name in ["get_current_time", "calculator", "get_system_model_info"]:
            result = self.policy.check(name)
            self.assertEqual(result.action, PolicyAction.ALLOW, f"{name} should be ALLOW")
            self.assertEqual(result.risk_level, ToolRiskLevel.SAFE)

    def test_low_risk_tools_return_allow(self):
        for name in ["list_office_files", "read_office_file", "list_scheduled_tasks", "web_search"]:
            result = self.policy.check(name)
            self.assertEqual(result.action, PolicyAction.ALLOW, f"{name} should be ALLOW")
            self.assertEqual(result.risk_level, ToolRiskLevel.LOW)

    def test_medium_risk_tools_return_allow(self):
        for name in ["save_user_profile", "write_office_file", "schedule_task",
                      "modify_scheduled_task", "delete_scheduled_task"]:
            result = self.policy.check(name)
            self.assertEqual(result.action, PolicyAction.ALLOW, f"{name} should be ALLOW")
            self.assertEqual(result.risk_level, ToolRiskLevel.MEDIUM)

    def test_execute_office_shell_returns_need_approval(self):
        result = self.policy.check("execute_office_shell")
        self.assertEqual(result.action, PolicyAction.NEED_APPROVAL)
        self.assertEqual(result.risk_level, ToolRiskLevel.HIGH)

    def test_unknown_tool_returns_need_approval_at_high_risk(self):
        result = self.policy.check("some_unknown_tool")
        self.assertEqual(result.action, PolicyAction.NEED_APPROVAL)
        self.assertEqual(result.risk_level, ToolRiskLevel.HIGH)
        self.assertIn("unknown tool", result.reason)

    def test_denied_tool_returns_deny(self):
        policy = default_policy()
        policy.denied_tools.add("dangerous_tool")
        result = policy.check("dangerous_tool")
        self.assertEqual(result.action, PolicyAction.DENY)
        self.assertEqual(result.risk_level, ToolRiskLevel.CRITICAL)

    def test_denied_prefix_returns_deny(self):
        policy = default_policy()
        policy.denied_prefixes.add("rm_")
        result = policy.check("rm_everything")
        self.assertEqual(result.action, PolicyAction.DENY)
        self.assertIn("prefix", result.reason)

    def test_custom_approval_threshold(self):
        policy = default_policy()
        policy.approval_threshold = ToolRiskLevel.MEDIUM
        # Medium tools should now need approval
        result = policy.check("write_office_file")
        self.assertEqual(result.action, PolicyAction.NEED_APPROVAL)
        self.assertEqual(result.risk_level, ToolRiskLevel.MEDIUM)
        # Safe tools should still be allowed
        result = policy.check("get_current_time")
        self.assertEqual(result.action, PolicyAction.ALLOW)

    def test_prefix_entries_work(self):
        policy = ToolPolicy(
            prefix_entries={"mcp_": ToolPolicyEntry(ToolRiskLevel.HIGH, needs_approval=True)},
            approval_threshold=ToolRiskLevel.HIGH,
        )
        result = policy.check("mcp_read_file")
        self.assertEqual(result.action, PolicyAction.NEED_APPROVAL)
        self.assertEqual(result.risk_level, ToolRiskLevel.HIGH)

    def test_exact_name_takes_priority_over_prefix(self):
        policy = ToolPolicy(
            tool_entries={"special_tool": ToolPolicyEntry(ToolRiskLevel.SAFE)},
            prefix_entries={"special_": ToolPolicyEntry(ToolRiskLevel.HIGH, needs_approval=True)},
            approval_threshold=ToolRiskLevel.HIGH,
        )
        result = policy.check("special_tool")
        self.assertEqual(result.action, PolicyAction.ALLOW)
        self.assertEqual(result.risk_level, ToolRiskLevel.SAFE)

    def test_args_parameter_accepted(self):
        result = self.policy.check("execute_office_shell", {"command": "ls"})
        self.assertEqual(result.action, PolicyAction.NEED_APPROVAL)


if __name__ == "__main__":
    unittest.main()
