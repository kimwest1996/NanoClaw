"""JSONL 结构化事件日志器。

支持 trace context（session_id / span_id）、延迟测量、错误码埋点。
"""

from __future__ import annotations

import os
import json
import threading
import queue
import atexit
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class TraceContext:
    """线程安全的 trace context 持有者。

    session_id — 每次运行会话的唯一标识
    span_id    — 当前操作（如单次 tool call）的唯一标识
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._session_id: str = ""
        self._parent_span_id: str = ""

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        with self._lock:
            self._session_id = value

    @property
    def parent_span_id(self) -> str:
        return self._parent_span_id

    @parent_span_id.setter
    def parent_span_id(self, value: str) -> None:
        with self._lock:
            self._parent_span_id = value

    def new_span_id(self) -> str:
        """生成新的 span_id 并设置到 context。"""
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._parent_span_id = sid
        return sid

    def reset_session(self) -> str:
        """重置会话，返回新的 session_id。"""
        sid = uuid.uuid4().hex
        with self._lock:
            self._session_id = sid
            self._parent_span_id = ""
        return sid


# 全局 trace context 实例
trace_ctx = TraceContext()


class JSONLEventLogger:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, log_dir: str = "logs"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_logger(log_dir)
            return cls._instance

    def _init_logger(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_queue: queue.Queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._write_loop, daemon=True)
        self.worker_thread.start()
        atexit.register(self.shutdown)

    def _write_loop(self):
        while True:
            log_item = self.log_queue.get()
            if log_item is None:
                self.log_queue.task_done()
                break
            try:
                thread_id = log_item.get("thread_id") or log_item.get("session_id", "system")
                safe_id = "".join(c for c in thread_id if c.isalnum() or c in "-_") or "default"
                file_path = os.path.join(self.log_dir, f"{safe_id}.jsonl")
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_item, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[Logger Error] 异步写日志失败: {e}")
            finally:
                self.log_queue.task_done()

    def log_event(
        self,
        thread_id: str = "",
        event: str = "",
        *,
        duration_ms: Optional[float] = None,
        error_code: Optional[str] = None,
        **kwargs,
    ):
        """埋点记录事件。

        Args:
            thread_id: 原始 thread_id（兼容旧调用）。自动回退到 session_id。
            event:     事件名（如 tool_call, tool_result, ai_message）。
            duration_ms: 操作耗时（毫秒）。
            error_code:  错误码（如 TIMEOUT, POLICY_DENIED）。
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_item: dict[str, Any] = {
            "ts": now_utc,
            "event": event,
        }

        # trace context
        sid = trace_ctx.session_id
        log_item["session_id"] = sid or thread_id or "system"
        if trace_ctx.parent_span_id:
            log_item["span_id"] = trace_ctx.parent_span_id

        # 兼容旧字段
        if thread_id and not sid:
            log_item["thread_id"] = thread_id

        # 可选可观测字段
        if duration_ms is not None:
            log_item["duration_ms"] = round(duration_ms, 1)
        if error_code is not None:
            log_item["error_code"] = error_code

        log_item.update(kwargs)
        self.log_queue.put(log_item)

    def shutdown(self):
        self.log_queue.put(None)
        self.log_queue.join()


audit_logger = JSONLEventLogger()
