import asyncio
import json
import os
import tempfile
import unittest

from nanoclaw.core.mcp_manager import MCPManager


class TestMCPManagerConfig(unittest.TestCase):
    """Test MCPManager config parsing."""

    def test_missing_config_returns_empty(self):
        mgr = MCPManager(config_path="/nonexistent/path.json")
        result = mgr._load_config()
        self.assertEqual(result, {})

    def test_empty_mcp_servers_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"mcpServers": {}}, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertEqual(result, {})
        os.unlink(f.name)

    def test_stdio_connection_parsed(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "mcpServers": {
                    "test_fs": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                        "transport": "stdio"
                    }
                }
            }, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertIn("test_fs", result)
            self.assertEqual(result["test_fs"]["command"], "npx")
            self.assertEqual(result["test_fs"]["transport"], "stdio")
            self.assertIn("/tmp", result["test_fs"]["args"])
        os.unlink(f.name)

    def test_sse_connection_parsed(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "mcpServers": {
                    "test_sse": {
                        "url": "http://localhost:3001",
                        "transport": "sse"
                    }
                }
            }, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertIn("test_sse", result)
            self.assertEqual(result["test_sse"]["url"], "http://localhost:3001")
            self.assertEqual(result["test_sse"]["transport"], "sse")
        os.unlink(f.name)

    def test_unknown_transport_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "mcpServers": {
                    "bad_server": {
                        "transport": "magic"
                    }
                }
            }, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertNotIn("bad_server", result)
        os.unlink(f.name)

    def test_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertEqual(result, {})
        os.unlink(f.name)

    def test_servers_key_also_accepted(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "servers": {
                    "my_server": {
                        "command": "python",
                        "args": ["server.py"],
                        "transport": "stdio"
                    }
                }
            }, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            result = mgr._load_config()
            self.assertIn("my_server", result)
        os.unlink(f.name)


class TestMCPManagerStatus(unittest.TestCase):
    """Test MCPManager status reporting."""

    def test_status_no_connections(self):
        mgr = MCPManager()
        self.assertIn("未连接", mgr.status())

    def test_status_with_servers(self):
        mgr = MCPManager()
        mgr._connected_servers = ["fs", "github"]
        mgr._tools = [
            type("Tool", (), {"name": "mcp_fs_read_file"})(),
            type("Tool", (), {"name": "mcp_fs_write_file"})(),
            type("Tool", (), {"name": "mcp_github_create_issue"})(),
        ]
        status = mgr.status()
        self.assertIn("2 个 Server", status)
        self.assertIn("fs", status)
        self.assertIn("github", status)


class TestMCPManagerLifecycle(unittest.TestCase):
    """Test MCPManager start/stop lifecycle."""

    def test_start_with_empty_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"mcpServers": {}}, f)
            f.flush()
            mgr = MCPManager(config_path=f.name)
            loop = asyncio.new_event_loop()
            tools = loop.run_until_complete(mgr.start())
            loop.close()
            self.assertEqual(tools, [])
            self.assertEqual(mgr.connected_servers, [])
        os.unlink(f.name)

    def test_stop_clears_state(self):
        mgr = MCPManager()
        mgr._tools = [type("Tool", (), {"name": "fake"})()]
        mgr._connected_servers = ["fake"]
        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr.stop())
        loop.close()
        self.assertEqual(mgr.tools, [])
        self.assertEqual(mgr.connected_servers, [])


class TestMCPPolicyIntegration(unittest.TestCase):
    """Test that MCP tools are correctly identified by policy."""

    def test_mcp_prefix_matches_policy(self):
        from nanoclaw.core.tool_policy import default_policy, PolicyAction, ToolRiskLevel
        policy = default_policy()
        result = policy.check("mcp_fs_read_file")
        self.assertEqual(result.action, PolicyAction.ALLOW)
        self.assertEqual(result.risk_level, ToolRiskLevel.MEDIUM)

    def test_mcp_prefix_allows_without_approval(self):
        from nanoclaw.core.tool_policy import default_policy, PolicyAction
        policy = default_policy()
        result = policy.check("mcp_github_create_issue")
        self.assertEqual(result.action, PolicyAction.ALLOW)


if __name__ == "__main__":
    unittest.main()
