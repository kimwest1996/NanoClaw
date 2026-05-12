"""Centralized tool permission policy layer.

Provides risk classification, deny-lists, and approval thresholds for tool
execution. This is a pure data/logic layer with no dependencies on SafeToolNode
or the approval mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ToolRiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Ordering for threshold comparison
_RISK_ORDER = {
    ToolRiskLevel.SAFE: 0,
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
    ToolRiskLevel.CRITICAL: 4,
}


class PolicyAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEED_APPROVAL = "need_approval"


@dataclass(frozen=True)
class PolicyResult:
    action: PolicyAction
    risk_level: ToolRiskLevel
    reason: str


@dataclass
class ToolPolicyEntry:
    risk_level: ToolRiskLevel
    needs_approval: bool = False


@dataclass
class ToolPolicy:
    tool_entries: dict[str, ToolPolicyEntry] = field(default_factory=dict)
    prefix_entries: dict[str, ToolPolicyEntry] = field(default_factory=dict)
    denied_tools: set[str] = field(default_factory=set)
    denied_prefixes: set[str] = field(default_factory=set)
    approval_threshold: ToolRiskLevel = ToolRiskLevel.HIGH

    def check(self, tool_name: str, args: Optional[dict] = None) -> PolicyResult:
        """Check whether a tool call is allowed, denied, or needs approval.

        Args:
            tool_name: Name of the tool being called.
            args: Tool arguments (reserved for future argument-level policies).

        Returns:
            PolicyResult with the action, risk level, and reason.
        """
        # 1. Explicit deny by name
        if tool_name in self.denied_tools:
            return PolicyResult(
                action=PolicyAction.DENY,
                risk_level=ToolRiskLevel.CRITICAL,
                reason=f"tool '{tool_name}' is explicitly denied",
            )

        # 2. Explicit deny by prefix
        for prefix in self.denied_prefixes:
            if tool_name.startswith(prefix):
                return PolicyResult(
                    action=PolicyAction.DENY,
                    risk_level=ToolRiskLevel.CRITICAL,
                    reason=f"tool '{tool_name}' denied by prefix '{prefix}'",
                )

        # 3. Look up entry by exact name, then by prefix
        entry = self.tool_entries.get(tool_name)
        if entry is None:
            for prefix, prefix_entry in self.prefix_entries.items():
                if tool_name.startswith(prefix):
                    entry = prefix_entry
                    break

        # 4. Unknown tools default to NEED_APPROVAL at HIGH risk
        if entry is None:
            return PolicyResult(
                action=PolicyAction.NEED_APPROVAL,
                risk_level=ToolRiskLevel.HIGH,
                reason=f"unknown tool '{tool_name}' requires approval (deny-by-default)",
            )

        # 5. Explicit approval flag on entry
        if entry.needs_approval:
            return PolicyResult(
                action=PolicyAction.NEED_APPROVAL,
                risk_level=entry.risk_level,
                reason=f"tool '{tool_name}' requires approval by policy entry",
            )

        # 6. Risk level >= approval threshold
        if _RISK_ORDER[entry.risk_level] >= _RISK_ORDER[self.approval_threshold]:
            return PolicyResult(
                action=PolicyAction.NEED_APPROVAL,
                risk_level=entry.risk_level,
                reason=f"tool '{tool_name}' risk level {entry.risk_level.value} meets approval threshold {self.approval_threshold.value}",
            )

        # 7. Allow
        return PolicyResult(
            action=PolicyAction.ALLOW,
            risk_level=entry.risk_level,
            reason=f"tool '{tool_name}' allowed at risk level {entry.risk_level.value}",
        )


class ToolPoolMode(Enum):
    """Runtime mode controlling which tools are available."""
    SAFE = "safe"
    NO_SHELL = "no_shell"
    FULL = "full"


# Read-only tool names — safe for all modes
_READ_ONLY_TOOL_NAMES = {
    "get_current_time",
    "calculator",
    "get_system_model_info",
    "list_office_files",
    "read_office_file",
    "list_scheduled_tasks",
    "web_search",
    "read_user_profile",
    "list_profile_versions",
}

# Shell tool — excluded in no_shell mode
_SHELL_TOOL_NAME = "execute_office_shell"


def get_tools_for_mode(mode: ToolPoolMode, all_tools: list) -> list:
    """Filter tool list based on runtime mode.

    Args:
        mode: The desired tool pool mode.
        all_tools: Full list of available tools.

    Returns:
        Filtered tool list for the given mode.
    """
    if mode == ToolPoolMode.FULL:
        return all_tools

    if mode == ToolPoolMode.SAFE:
        return [t for t in all_tools if t.name in _READ_ONLY_TOOL_NAMES]

    if mode == ToolPoolMode.NO_SHELL:
        return [t for t in all_tools if t.name != _SHELL_TOOL_NAME]

    return all_tools


def default_policy() -> ToolPolicy:
    """Create the default policy with all 13 built-in tools mapped."""
    tool_entries = {
        # SAFE — pure read, no side effects
        "get_current_time": ToolPolicyEntry(ToolRiskLevel.SAFE),
        "calculator": ToolPolicyEntry(ToolRiskLevel.SAFE),
        "get_system_model_info": ToolPolicyEntry(ToolRiskLevel.SAFE),
        # LOW — read-only sandbox or external
        "list_office_files": ToolPolicyEntry(ToolRiskLevel.LOW),
        "read_office_file": ToolPolicyEntry(ToolRiskLevel.LOW),
        "list_scheduled_tasks": ToolPolicyEntry(ToolRiskLevel.LOW),
        "web_search": ToolPolicyEntry(ToolRiskLevel.LOW),
        # LOW — read-only memory
        "read_user_profile": ToolPolicyEntry(ToolRiskLevel.LOW),
        "list_profile_versions": ToolPolicyEntry(ToolRiskLevel.LOW),
        # MEDIUM — side effects within sandbox
        "save_user_profile": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "update_user_profile": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "rollback_user_profile": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "write_office_file": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "schedule_task": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "modify_scheduled_task": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        "delete_scheduled_task": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        # MEDIUM — spawns background subagents
        "spawn_subagent": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
        # HIGH — shell execution, requires approval
        "execute_office_shell": ToolPolicyEntry(ToolRiskLevel.HIGH, needs_approval=True),
    }
    prefix_entries = {
        # MCP tools — external, moderate risk
        "mcp_": ToolPolicyEntry(ToolRiskLevel.MEDIUM),
    }
    return ToolPolicy(
        tool_entries=tool_entries,
        prefix_entries=prefix_entries,
        approval_threshold=ToolRiskLevel.HIGH,
    )
