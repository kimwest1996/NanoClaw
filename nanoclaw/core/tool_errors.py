"""Structured tool execution errors with error codes and retryability."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ToolErrorCode(Enum):
    UNKNOWN_TOOL = "unknown_tool"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    TRANSIENT_ERROR = "transient_error"


@dataclass
class ToolExecutionError(Exception):
    error_code: ToolErrorCode
    message: str
    tool_name: str = ""
    tool_call_id: str = ""
    retryable: bool = False
    cause: Optional[BaseException] = None

    def __str__(self) -> str:
        return f"[{self.error_code.value}] {self.message}"

    def to_tool_message_content(self) -> str:
        prefix = "Error"
        if self.error_code == ToolErrorCode.POLICY_DENIED:
            prefix = "Policy Denied"
        elif self.error_code == ToolErrorCode.APPROVAL_DENIED:
            prefix = "Approval Denied"
        elif self.error_code == ToolErrorCode.APPROVAL_TIMEOUT:
            prefix = "Approval Timeout"
        elif self.error_code == ToolErrorCode.PERMISSION_DENIED:
            prefix = "Permission Denied"
        elif self.error_code == ToolErrorCode.TIMEOUT:
            prefix = "Timeout"
        elif self.error_code == ToolErrorCode.TRANSIENT_ERROR:
            prefix = "Transient Error"
        return f"{prefix}: {self.message}"
