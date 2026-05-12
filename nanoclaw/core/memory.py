"""
Memory management module for NanoClaw — MemoryOS-inspired three-tier system.

Tiers:
  Short-term: LangGraph messages[] (in AgentState)
  Mid-term:   Session summaries (persisted as JSON files in SESSIONS_DIR)
  Long-term:  User profile (Markdown file, section-structured)

External dependencies: none. All storage is file-based.
"""

import os
import re
import json
import glob
from datetime import datetime
from typing import Optional


# ── Profile Manager ──────────────────────────────────────────

PROFILE_SECTIONS = [
    "个人基本信息",
    "沟通偏好",
    "专业领域",
    "行为习惯",
    "其他信息",
]


def _parse_sections(content: str) -> dict[str, list[str]]:
    """Parse user_profile.md into {section_name: [lines]}."""
    sections: dict[str, list[str]] = {}
    current_key = "__preamble__"
    current_lines: list[str] = []

    for line in content.split("\n"):
        m = re.match(r'^#+\s+(.+)$', line)
        if m:
            if current_lines:
                sections[current_key] = current_lines
            current_key = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_key] = current_lines

    return sections


def _format_sections(sections: dict[str, list[str]]) -> str:
    """Format section dict back to Markdown, skipping empty sections."""
    parts = []
    for key, lines in sections.items():
        stripped = [l for l in lines if l.strip()]
        if not stripped:
            continue
        parts.extend(stripped)
    return "\n".join(parts)


def _merge_content(existing: str, incoming: str) -> str:
    """
    Merge incoming content into existing by section.

    - incoming has Markdown headings → section-level merge
    - incoming has no headings      → full overwrite (legacy)
    """
    has_headers = bool(re.search(r'^#+\s+\S', incoming, re.MULTILINE))
    if not has_headers:
        return incoming

    existing_sections = _parse_sections(existing)
    incoming_sections = _parse_sections(incoming)

    for key, lines in incoming_sections.items():
        existing_sections[key] = lines

    return _format_sections(existing_sections)


class ProfileManager:
    """Manage the long-term user profile stored as a Markdown file."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.profile_path = os.path.join(memory_dir, "user_profile.md")

    def read(self, section: str = "") -> str:
        """Read full profile or a specific section."""
        if not os.path.exists(self.profile_path):
            return "暂无记录"

        with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()

        if not content:
            return "暂无记录"

        if not section:
            sections = _parse_sections(content)
            index_lines = [s for s in sections if s != "__preamble__"]
            index = "\n".join(f"- {s}" for s in index_lines) if index_lines else "暂无结构化章节"
            return f"当前档案包含以下章节：\n{index}\n\n---\n\n{content}"

        sections = _parse_sections(content)
        for sname, slines in sections.items():
            if section in sname:
                return "\n".join(slines)

        return f"未找到章节「{section}」，可用章节：{', '.join(PROFILE_SECTIONS)}"

    def save(self, new_content: str) -> str:
        """Save content with section-aware merging."""
        os.makedirs(self.memory_dir, exist_ok=True)

        existing = ""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()

        merged = _merge_content(existing, new_content)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(merged)

        return "记忆档案已成功覆写更新。新的人设画像已生效。"

    def update_section(self, section: str, content: str) -> str:
        """Update a single profile section, leaving others intact."""
        os.makedirs(self.memory_dir, exist_ok=True)

        existing = ""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()

        sections = _parse_sections(existing)

        matched_key = next((s for s in PROFILE_SECTIONS if s == section), None)
        if not matched_key:
            matched_key = next((s for s in PROFILE_SECTIONS if section in s or s in section), section)

        lines = [f"# {matched_key}"] + [l.rstrip() for l in content.strip().split("\n") if l.rstrip()]
        sections[matched_key] = lines

        merged = _format_sections(sections)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(merged)

        return f"章节「{matched_key}」已成功更新。"


# ── Session Memory Store ─────────────────────────────────────


class SessionMemoryStore:
    """Persist and retrieve mid-term session summaries."""

    def __init__(self, sessions_dir: str, max_files: int = 100, inject_limit: int = 5):
        self.sessions_dir = sessions_dir
        self.max_files = max_files
        self.inject_limit = inject_limit

    def store_session(
        self,
        thread_id: str,
        summary: str,
        turn_count: int = 0,
        tool_count: int = 0,
    ) -> str:
        """Store a session summary as a JSON file. Returns the file path."""
        os.makedirs(self.sessions_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{thread_id}_{timestamp}.json"
        filepath = os.path.join(self.sessions_dir, filename)

        data = {
            "thread_id": thread_id,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "turn_count": turn_count,
            "tool_count": tool_count,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self._prune_old()
        return filepath

    def get_recent_sessions(self, thread_id: str, limit: Optional[int] = None) -> list[dict]:
        """Get the most recent N session summaries for a thread."""
        limit = limit if limit is not None else self.inject_limit
        pattern = os.path.join(self.sessions_dir, f"{thread_id}_*.json")
        files = sorted(glob.glob(pattern), reverse=True)
        return self._load_files(files[:limit])

    def get_all_recent(self, limit: Optional[int] = None) -> list[dict]:
        """Get recent sessions across all threads."""
        limit = limit if limit is not None else self.inject_limit
        pattern = os.path.join(self.sessions_dir, "*.json")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        return self._load_files(files[:limit])

    def _load_files(self, paths: list[str]) -> list[dict]:
        """Load and decode a list of JSON session files."""
        results = []
        for fp in paths:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
        return results

    def _prune_old(self) -> int:
        """Delete oldest session files beyond max_files. Returns count removed."""
        pattern = os.path.join(self.sessions_dir, "*.json")
        files = sorted(glob.glob(pattern), key=os.path.getmtime)

        to_remove = len(files) - self.max_files
        if to_remove <= 0:
            return 0

        for fp in files[:to_remove]:
            try:
                os.remove(fp)
            except OSError:
                continue
        return to_remove
