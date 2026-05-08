"""Tests for the Doctor diagnostic module."""

import os
import sys
import json
import tempfile
from pathlib import Path

import pytest

from nanoclaw.core.doctor import (
    Doctor,
    CheckResult,
    CheckStatus,
)


class TestDoctorBasic:
    """Unit tests for individual health checks."""

    def test_env_pass(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = os.path.join(tmp, ".env")
            with open(env_path, "w") as f:
                f.write("DEFAULT_PROVIDER=test_provider\nDEFAULT_MODEL=test_model\nOPENAI_API_KEY=sk-test\n")
            monkeypatch.setenv("DEFAULT_PROVIDER", "test_provider")
            monkeypatch.setenv("DEFAULT_MODEL", "test_model")
            monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
            # 清除可能干扰的代理环境变量
            monkeypatch.delenv("OPENAI_API_BASE", raising=False)
            monkeypatch.delenv("DEEPSEEK_API_BASE", raising=False)
            monkeypatch.delenv("MIMO_API_BASE", raising=False)
            doc = Doctor(project_root=tmp)
            result = doc.check_env()
            assert result.status == CheckStatus.PASS

    def test_env_fail_no_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doctor(project_root=tmp)
            result = doc.check_env()
            assert result.status == CheckStatus.FAIL

    @pytest.mark.parametrize("provider,key_var", [
        ("openai", "OPENAI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("xiaomi", "MIMO_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ])
    def test_resolve_api_key(self, provider, key_var, monkeypatch):
        monkeypatch.setenv(key_var, "sk-test")
        key = Doctor._resolve_api_key(provider)
        assert key == "sk-test"

    def test_resolve_api_key_ollama(self):
        key = Doctor._resolve_api_key("ollama")
        assert key is None

    def test_workspace_pass(self):
        doc = Doctor(project_root=os.getcwd())
        result = doc.check_workspace()
        assert result.status in (CheckStatus.PASS, CheckStatus.WARN)

    def test_mcp_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doctor(project_root=tmp)
            result = doc.check_mcp()
            assert result.status == CheckStatus.SKIP

    def test_mcp_empty_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = os.path.join(tmp, "workspace")
            os.makedirs(workspace)
            cfg = os.path.join(workspace, "mcp_servers.json")
            with open(cfg, "w") as f:
                json.dump({"mcpServers": {}}, f)
            # Override WORKSPACE_DIR via import
            import nanoclaw.core.config as cfgmod
            original = cfgmod.WORKSPACE_DIR
            cfgmod.WORKSPACE_DIR = workspace
            try:
                doc = Doctor(project_root=tmp)
                result = doc.check_mcp()
                assert result.status == CheckStatus.SKIP
            finally:
                cfgmod.WORKSPACE_DIR = original

    def test_skills_empty(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            import nanoclaw.core.config as cfgmod
            original = cfgmod.SKILLS_DIR
            skills_dir = os.path.join(tmp, "skills")
            os.makedirs(skills_dir)
            cfgmod.SKILLS_DIR = skills_dir
            try:
                doc = Doctor(project_root=tmp)
                result = doc.check_skills()
                assert result.status == CheckStatus.SKIP
            finally:
                cfgmod.SKILLS_DIR = original

    def test_logs_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doctor(project_root=tmp)
            result = doc.check_logs()
            assert result.status == CheckStatus.SKIP

    def test_db_not_exist(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            fake_db = os.path.join(tmp, "no_such_db.sqlite3")
            monkeypatch.setattr("nanoclaw.core.config.DB_PATH", fake_db)
            doc = Doctor(project_root=tmp)
            result = doc.check_db()
            assert result.status == CheckStatus.SKIP

    def test_run_all_returns_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doctor(project_root=tmp)
            results = doc.run_all()
            assert len(results) >= 6
            names = [r.name for r in results]
            for expected in ("env", "workspace", "mcp", "skills", "logs", "db"):
                assert expected in names

    def test_check_result_dataclass(self):
        r = CheckResult(name="test", status=CheckStatus.PASS, message="ok",
                        details={"key": "val"}, duration_ms=12.3,
                        suggestion="do something")
        assert r.name == "test"
        assert r.status == CheckStatus.PASS
        assert r.message == "ok"
        assert r.details == {"key": "val"}
        assert r.duration_ms == 12.3
        assert r.suggestion == "do something"

