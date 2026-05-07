import json
import os
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage

from nanoclaw.core.logger import audit_logger


def is_valid_thread_id(thread_id: str) -> bool:
    return bool(thread_id) and all(c.isalnum() or c in "-_" for c in thread_id)


def clean_content(content: str) -> str:
    return content.strip()


def message_to_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def final_ai_content(messages: Iterable[BaseMessage]) -> str:
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage) or getattr(message, "type", None) == "ai":
            return message_to_text(message)
    return ""


def safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def read_thread_events(thread_id: str, limit: int) -> list[dict[str, Any]]:
    audit_logger.log_queue.join()
    safe_id = "".join(c for c in thread_id if c.isalnum() or c in "-_") or "default"
    file_path = os.path.join(audit_logger.log_dir, f"{safe_id}.jsonl")
    if not os.path.exists(file_path):
        return []

    events: list[dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("thread_id") == thread_id:
                events.append(event)
    return events[-limit:]

