"""NanoClaw 系统诊断工具。

检查环境/提供商/工作空间/MCP/技能/日志/数据库七项健康状态，
输出结构化报告供用户排查问题。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class CheckStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    suggestion: str = ""


class Doctor:
    """系统诊断器，运行一组健康检查并汇总报告。"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = self._detect_project_root()
        self.project_root = project_root

    @staticmethod
    def _detect_project_root() -> str:
        """向上查找 project root（存在 setup.py 的目录）。"""
        cwd = os.getcwd()
        for parent in [cwd] + _parent_dirs(cwd):
            if os.path.isfile(os.path.join(parent, "setup.py")):
                return parent
        return cwd

    def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        results.append(self.check_env())
        if results[-1].status == CheckStatus.PASS:
            results.append(self.check_provider())
        else:
            results.append(CheckResult("provider", CheckStatus.SKIP, "跳过（依赖环境检查通过）"))
        results.append(self.check_workspace())
        results.append(self.check_mcp())
        results.append(self.check_skills())
        results.append(self.check_logs())
        results.append(self.check_db())
        return results

    # ── 环境检查 ──────────────────────────────────────────

    def check_env(self) -> CheckResult:
        start = time.monotonic()
        dotenv_path = os.path.join(self.project_root, ".env")

        if not os.path.isfile(dotenv_path):
            return _result("env", CheckStatus.FAIL,
                           ".env 文件不存在", duration=_elapsed(start),
                           suggestion="执行 nanoclaw config 完成初始配置")

        from dotenv import load_dotenv
        load_dotenv(dotenv_path)

        provider = os.getenv("DEFAULT_PROVIDER")
        model = os.getenv("DEFAULT_MODEL")

        if not provider or not model:
            return _result("env", CheckStatus.FAIL,
                           "DEFAULT_PROVIDER 或 DEFAULT_MODEL 未配置", duration=_elapsed(start),
                           suggestion="执行 nanoclaw config 重新配置")

        api_key = self._resolve_api_key(provider)
        issues: list[str] = []
        if not api_key and provider != "ollama":
            issues.append(f"{provider} 未找到 API Key")

        for k in ("OPENAI_API_BASE", "DEEPSEEK_API_BASE", "MIMO_API_BASE"):
            if os.getenv(k):
                issues.append(f"已设代理: {k}={os.getenv(k)}")

        return _result("env", CheckStatus.PASS if not issues else CheckStatus.WARN,
                       f"Provider: {provider} / {model}" + (f" | {'; '.join(issues)}" if issues else ""),
                       duration=_elapsed(start),
                       details={"provider": provider or "", "model": model or "",
                                "api_key_configured": bool(api_key)})

    @staticmethod
    def _resolve_api_key(provider: str) -> Optional[str]:
        key_map = {
            "ollama": None,
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "xiaomi": "MIMO_API_KEY",
        }
        env_key = key_map.get(provider, "OPENAI_API_KEY")
        return os.getenv(env_key) if env_key else None

    # ── 提供商连通性检查 ──────────────────────────────────

    def check_provider(self) -> CheckResult:
        start = time.monotonic()
        from dotenv import load_dotenv
        load_dotenv(os.path.join(self.project_root, ".env"))

        provider = os.getenv("DEFAULT_PROVIDER", "")
        model = os.getenv("DEFAULT_MODEL", "")

        try:
            from nanoclaw.core.provider import get_provider
            from langchain_core.messages import HumanMessage
            llm = get_provider(provider_name=provider, model_name=model)
            t0 = time.monotonic()
            resp = llm.invoke([HumanMessage(content="回复一个字：'好'。")])
            elapsed = (time.monotonic() - t0) * 1000
            content = resp.content.strip() if resp.content else ""
            return _result("provider", CheckStatus.PASS,
                           f"API 连通成功 ({elapsed:.0f}ms): {content[:50]}",
                           duration=_elapsed(start),
                           details={"provider": provider, "model": model,
                                    "latency_ms": round(elapsed, 1)})
        except Exception as e:
            return _result("provider", CheckStatus.FAIL,
                           f"API 连接失败: {e}", duration=_elapsed(start),
                           suggestion="检查网络连接 / API Key 是否有效 / 模型名是否正确")

    # ── 工作空间检查 ──────────────────────────────────────

    def check_workspace(self) -> CheckResult:
        start = time.monotonic()
        from nanoclaw.core.config import WORKSPACE_DIR, MEMORY_DIR, OFFICE_DIR, \
            PERSONAS_DIR, SCRIPTS_DIR, SKILLS_DIR, TASKS_FILE, DB_PATH

        required_dirs = {
            "workspace": WORKSPACE_DIR,
            "memory": MEMORY_DIR,
            "office": OFFICE_DIR,
            "personas": PERSONAS_DIR,
            "scripts": SCRIPTS_DIR,
            "skills": SKILLS_DIR,
        }
        missing = []
        details: dict[str, Any] = {}
        for name, path in required_dirs.items():
            ok = os.path.isdir(path)
            if not ok:
                missing.append(name)
            details[name] = {"path": path, "exists": ok}

        # 检查 tasks.json
        tasks_path = TASKS_FILE
        details["tasks"] = {"path": tasks_path, "exists": os.path.isfile(tasks_path)}

        if missing:
            return _result("workspace", CheckStatus.WARN,
                           f"缺少 {len(missing)} 个工作目录: {', '.join(missing)}",
                           duration=_elapsed(start), details=details,
                           suggestion="运行 nanoclaw run 会自动创建缺失目录")
        return _result("workspace", CheckStatus.PASS,
                       f"工作空间就绪: {WORKSPACE_DIR}",
                       duration=_elapsed(start), details=details)

    # ── MCP 检查 ──────────────────────────────────────────

    def check_mcp(self) -> CheckResult:
        start = time.monotonic()
        from nanoclaw.core.config import WORKSPACE_DIR
        config_path = os.path.join(WORKSPACE_DIR, "mcp_servers.json")

        if not os.path.isfile(config_path):
            return _result("mcp", CheckStatus.SKIP,
                           "未配置 MCP Server（mcp_servers.json 不存在）",
                           duration=_elapsed(start))

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return _result("mcp", CheckStatus.FAIL,
                           f"配置文件解析失败: {e}", duration=_elapsed(start))

        servers = raw.get("mcpServers", raw.get("servers", {}))
        if not servers:
            return _result("mcp", CheckStatus.SKIP,
                           "mcp_servers.json 为空（无 Server 定义）",
                           duration=_elapsed(start))

        details: dict[str, Any] = {}
        issues: list[str] = []
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            valid = bool(cfg.get("command")) if transport == "stdio" else bool(cfg.get("url"))
            details[name] = {"transport": transport, "valid": valid}
            if not valid:
                issues.append(f"{name}: 配置不完整")

        status = CheckStatus.PASS if not issues else CheckStatus.WARN
        return _result("mcp", status,
                       f"已配置 {len(servers)} 个 Server" +
                       (f" | 问题: {'; '.join(issues)}" if issues else ""),
                       duration=_elapsed(start), details=details,
                       suggestion="使用 /mcp 命令查看运行时连接状态" if not issues else "")

    # ── 技能检查 ──────────────────────────────────────────

    def check_skills(self) -> CheckResult:
        start = time.monotonic()
        from nanoclaw.core.config import SKILLS_DIR

        if not os.path.isdir(SKILLS_DIR):
            return _result("skills", CheckStatus.SKIP,
                           "技能目录不存在", duration=_elapsed(start))

        items = os.listdir(SKILLS_DIR)
        skill_files = [f for f in items if f.endswith((".py", ".json", ".yaml", ".yml"))]
        return _result("skills", CheckStatus.PASS if skill_files else CheckStatus.SKIP,
                       f"技能目录: {len(skill_files)} 个技能文件" if skill_files else "技能目录为空",
                       duration=_elapsed(start),
                       details={"path": SKILLS_DIR, "total": len(items),
                                "skills": skill_files[:20]})

    # ── 日志检查 ──────────────────────────────────────────

    def check_logs(self) -> CheckResult:
        start = time.monotonic()
        log_dir = os.path.join(self.project_root, "logs")

        if not os.path.isdir(log_dir):
            return _result("logs", CheckStatus.SKIP,
                           "日志目录不存在（首次运行后自动创建）",
                           duration=_elapsed(start))

        files = [f for f in os.listdir(log_dir) if f.endswith(".jsonl")]
        total_size = sum(os.path.getsize(os.path.join(log_dir, f)) for f in files)
        total_size_mb = total_size / (1024 * 1024)

        details = {"path": log_dir, "file_count": len(files), "total_size_mb": round(total_size_mb, 2)}

        recent: list[dict] = []
        for f in sorted(files, key=lambda x: os.path.getmtime(os.path.join(log_dir, x)), reverse=True)[:5]:
            mtime = datetime.fromtimestamp(os.path.getmtime(os.path.join(log_dir, f)), tz=timezone.utc)
            recent.append({"file": f, "size_kb": round(os.path.getsize(os.path.join(log_dir, f)) / 1024, 1),
                           "mtime": mtime.strftime("%Y-%m-%dT%H:%M:%SZ")})
        details["recent"] = recent

        message = f"{len(files)} 个日志文件, {total_size_mb:.2f}MB"
        return _result("logs", CheckStatus.PASS if files else CheckStatus.SKIP,
                       message, duration=_elapsed(start), details=details)

    # ── 数据库检查 ────────────────────────────────────────

    def check_db(self) -> CheckResult:
        start = time.monotonic()
        from nanoclaw.core.config import DB_PATH

        if not os.path.isfile(DB_PATH):
            return _result("db", CheckStatus.SKIP,
                           "数据库文件不存在（首次运行后自动创建）",
                           duration=_elapsed(start))

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            conn.close()
            size_kb = os.path.getsize(DB_PATH) / 1024
            return _result("db", CheckStatus.PASS,
                           f"SQLite 就绪: {table_count} 个表, {size_kb:.1f}KB",
                           duration=_elapsed(start),
                           details={"path": DB_PATH, "size_kb": round(size_kb, 1),
                                    "table_count": table_count})
        except Exception as e:
            return _result("db", CheckStatus.FAIL,
                           f"数据库访问失败: {e}", duration=_elapsed(start),
                           suggestion="尝试删除 workspace/state.sqlite3 后重新运行")


def _parent_dirs(path: str) -> list[str]:
    parents = []
    while True:
        parent = os.path.dirname(path)
        if parent == path:
            break
        parents.append(parent)
        path = parent
    return parents


def _elapsed(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _result(name: str, status: CheckStatus, message: str, *,
            duration: float = 0.0, details: Optional[dict] = None,
            suggestion: str = "") -> CheckResult:
    return CheckResult(name=name, status=status, message=message,
                       details=details or {}, duration_ms=round(duration, 1),
                       suggestion=suggestion)
