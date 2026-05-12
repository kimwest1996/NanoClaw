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
import math
import shutil
from datetime import datetime
from typing import Optional

from .config import HEAT_DECAY_DAYS, HEAT_ARCHIVE_THRESHOLD, HISTORY_MAX_VERSIONS


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


_KV_PATTERN = re.compile(r'^-\s+(.+?)\s*[:：]\s*(.+)$')


def _parse_key_values(lines: list[str]) -> dict[str, str]:
    """Parse key-value lines (``- key: value``) from section content."""
    kvs: dict[str, str] = {}
    for line in lines:
        m = _KV_PATTERN.match(line.strip())
        if m:
            kvs[m.group(1).strip()] = m.group(2).strip()
    return kvs


class ProfileManager:
    """Manage the long-term user profile stored as a Markdown file."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.profile_path = os.path.join(memory_dir, "user_profile.md")
        self.archive_dir = os.path.join(memory_dir, "archive")
        self.history_dir = os.path.join(memory_dir, "history")
        self.heat_scores_path = os.path.join(memory_dir, "heat_scores.json")

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

    # ── Version snapshot ────────────────────────────────────────

    def _snapshot_before_write(self):
        """Copy current profile to history/ before modification. Prune to max."""
        if not os.path.exists(self.profile_path):
            return
        os.makedirs(self.history_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = os.path.join(self.history_dir, f"{ts}_user_profile.md")
        shutil.copy2(self.profile_path, dest)

        files = sorted(glob.glob(os.path.join(self.history_dir, "*_user_profile.md")))
        while len(files) > HISTORY_MAX_VERSIONS:
            os.remove(files.pop(0))

    # ── Heat scoring ─────────────────────────────────────────────

    def _load_heat_scores(self) -> dict:
        """Load heat scores from JSON file."""
        if not os.path.exists(self.heat_scores_path):
            return {}
        try:
            with open(self.heat_scores_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_heat_scores(self, scores: dict):
        """Persist heat scores to JSON file."""
        os.makedirs(self.memory_dir, exist_ok=True)
        with open(self.heat_scores_path, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)

    def _update_heat_score(self, section: str):
        """Increment update count and recalc score for a section."""
        scores = self._load_heat_scores()
        now = datetime.now()
        entry = scores.get(section, {"count": 0, "last_updated": now.isoformat()})
        entry["count"] = entry.get("count", 0) + 1
        entry["last_updated"] = now.isoformat()
        entry["score"] = self._calc_score(entry["count"], entry["last_updated"])
        scores[section] = entry
        self._save_heat_scores(scores)

    @staticmethod
    def _calc_score(count: int, last_updated_iso: str) -> float:
        """Score = count × exp(-days_since_update / HEAT_DECAY_DAYS)."""
        try:
            last = datetime.fromisoformat(last_updated_iso)
            days = (datetime.now() - last).total_seconds() / 86400.0
        except (ValueError, TypeError):
            days = 0.0
        return round(count * math.exp(-days / HEAT_DECAY_DAYS), 4)

    def _decay_scores(self):
        """Recompute all scores based on current time."""
        scores = self._load_heat_scores()
        for section, entry in scores.items():
            entry["score"] = self._calc_score(entry["count"], entry["last_updated"])
        self._save_heat_scores(scores)

    # ── Cold archive ─────────────────────────────────────────────

    def get_cold_sections(self) -> list[str]:
        """Return section names whose heat score is below archive threshold."""
        scores = self._load_heat_scores()
        return [s for s, e in scores.items() if e.get("score", 1.0) < HEAT_ARCHIVE_THRESHOLD]

    def archive_cold_sections(self) -> int:
        """Move cold section content to archive/, replace with ref line. Returns count."""
        cold = self.get_cold_sections()
        if not cold:
            return 0

        if not os.path.exists(self.profile_path):
            return 0

        with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        sections = _parse_sections(content)
        archived = 0
        os.makedirs(self.archive_dir, exist_ok=True)

        for section_name in cold:
            if section_name not in sections:
                continue
            lines = sections[section_name]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = os.path.join(self.archive_dir, f"{section_name}_{ts}.md")
            with open(archive_path, "w", encoding="utf-8") as af:
                af.write("\n".join(lines))
            # Replace with a reference line
            sections[section_name] = [f"# {section_name}", f"<!-- archived: {archive_path} -->"]
            archived += 1

        merged = _format_sections(sections)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(merged)

        return archived

    # ── History & rollback ───────────────────────────────────────

    def list_history_versions(self) -> list[dict]:
        """List available history snapshots with metadata."""
        pattern = os.path.join(self.history_dir, "*_user_profile.md")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        results = []
        SUFFIX = "_user_profile.md"
        for fp in files:
            fname = os.path.basename(fp)
            if not fname.endswith(SUFFIX):
                continue
            version_id = fname[:-len(SUFFIX)]  # strip suffix → full timestamp
            results.append({
                "version_id": version_id,
                "filename": fname,
                "size": os.path.getsize(fp),
                "mtime": datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(),
            })
        return results

    def rollback(self, version_id: str) -> str:
        """Restore profile from a specific history snapshot."""
        pattern = os.path.join(self.history_dir, f"{version_id}_user_profile.md")
        matches = glob.glob(pattern)
        if not matches:
            return f"未找到版本 {version_id}。可用版本：{len(self.list_history_versions())} 个"
        src = matches[0]
        shutil.copy2(src, self.profile_path)
        return f"已从版本 {version_id} 恢复。当前档案已被该历史快照覆盖。"

    # ── Save with integration ───────────────────────────────────

    def save(self, new_content: str) -> str:
        """Save content with section-aware merging + snapshot + heat."""
        os.makedirs(self.memory_dir, exist_ok=True)

        existing = ""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()

        self._snapshot_before_write()
        merged = _merge_content(existing, new_content)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(merged)

        # Update heat scores for sections in incoming content
        has_headers = bool(re.search(r'^#+\s+\S', new_content, re.MULTILINE))
        if has_headers:
            incoming_sections = _parse_sections(new_content)
            for key in incoming_sections:
                if key != "__preamble__":
                    self._update_heat_score(key)

        return "记忆档案已成功覆写更新。新的人设画像已生效。"

    def update_section(self, section: str, content: str) -> str:
        """Update a single profile section with snapshot + heat + conflict detection."""
        os.makedirs(self.memory_dir, exist_ok=True)

        existing = ""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()

        old_sections = _parse_sections(existing)
        sections = _parse_sections(existing)

        matched_key = next((s for s in PROFILE_SECTIONS if s == section), None)
        if not matched_key:
            matched_key = next((s for s in PROFILE_SECTIONS if section in s or s in section), section)

        # Conflict detection: archive old conflicting key-value pairs
        old_lines = sections.get(matched_key, [])
        old_kvs = _parse_key_values(old_lines)
        new_lines = content.strip().split("\n")
        new_kvs = _parse_key_values(new_lines)
        for key, old_val in old_kvs.items():
            new_val = new_kvs.get(key)
            if new_val is not None and new_val != old_val:
                self._archive_conflict(matched_key, key, old_val, new_val)

        self._snapshot_before_write()

        formatted_lines = [f"# {matched_key}"] + [l.rstrip() for l in new_lines if l.rstrip()]
        sections[matched_key] = formatted_lines

        merged = _format_sections(sections)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(merged)

        self._update_heat_score(matched_key)

        return f"章节「{matched_key}」已成功更新。"

    def _archive_conflict(self, section: str, key: str, old_val: str, new_val: str):
        """Archive a conflicting key-value pair."""
        os.makedirs(self.archive_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        conflict_path = os.path.join(self.archive_dir, f"conflict_{section}_{key}_{ts}.md")
        with open(conflict_path, "w", encoding="utf-8") as f:
            f.write(f"# Conflict: {section} > {key}\n\n")
            f.write(f"**New value** (kept): {new_val}\n\n")
            f.write(f"**Old value** (archived): {old_val}\n\n")
            f.write(f"Archived at: {datetime.now().isoformat()}\n")


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
