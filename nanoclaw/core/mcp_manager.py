"""MCP Server connection manager.

Reads mcp_servers.json, connects to MCP servers via langchain-mcp-adapters,
and provides LangChain-compatible tools for the agent.
"""

import json
import os
from typing import Optional

from langchain_core.tools import BaseTool

from .config import WORKSPACE_DIR

MCP_CONFIG_FILE = os.path.join(WORKSPACE_DIR, "mcp_servers.json")


class MCPManager:
    """Manages MCP server connections and tool loading."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or MCP_CONFIG_FILE
        self._client = None
        self._tools: list[BaseTool] = []
        self._connected_servers: list[str] = []

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools

    @property
    def connected_servers(self) -> list[str]:
        return self._connected_servers

    async def start(self) -> list[BaseTool]:
        """Load config, connect to MCP servers, return LangChain tools."""
        config = self._load_config()
        if not config:
            return []

        from langchain_mcp_adapters.client import MultiServerMCPClient

        self._client = MultiServerMCPClient(
            connections=config,
            tool_name_prefix=True,
        )

        try:
            raw_tools = await self._client.get_tools()
            # Prefix all MCP tool names with "mcp_" for policy identification
            from langchain_core.tools import StructuredTool
            self._tools = []
            for t in raw_tools:
                prefixed = StructuredTool(
                    name=f"mcp_{t.name}",
                    description=t.description,
                    args_schema=t.args_schema,
                    coroutine=t.coroutine if hasattr(t, 'coroutine') else None,
                    func=t.func if hasattr(t, 'func') else None,
                    response_format=getattr(t, 'response_format', 'content'),
                    metadata=getattr(t, 'metadata', None),
                )
                self._tools.append(prefixed)
            self._connected_servers = list(config.keys())
        except Exception as e:
            print(f" \033[38;5;196m[MCP] 连接失败: {e}\033[0m")
            self._tools = []
            self._connected_servers = []

        return self._tools

    async def stop(self):
        """Clean up MCP connections."""
        self._tools = []
        self._connected_servers = []
        self._client = None

    def status(self) -> str:
        """Return a human-readable status string."""
        if not self._connected_servers:
            return "MCP: 未连接任何 Server"
        lines = [f"MCP: 已连接 {len(self._connected_servers)} 个 Server"]
        for name in self._connected_servers:
            server_tools = [t for t in self._tools if t.name.startswith(f"{name}_")]
            lines.append(f"  - {name}: {len(server_tools)} 个工具")
        return "\n".join(lines)

    def _load_config(self) -> dict:
        """Read mcp_servers.json, return MultiServerMCPClient connections format.

        Expected format:
        {
            "mcpServers": {
                "server_name": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
                    "transport": "stdio"
                },
                "another_server": {
                    "url": "http://localhost:3001",
                    "transport": "sse"
                }
            }
        }
        """
        if not os.path.exists(self.config_path):
            return {}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f" \033[38;5;196m[MCP] 配置文件读取失败: {e}\033[0m")
            return {}

        servers = raw.get("mcpServers", raw.get("servers", {}))
        if not servers:
            return {}

        connections = {}
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            if transport == "stdio":
                connections[name] = {
                    "command": cfg["command"],
                    "args": cfg.get("args", []),
                    "transport": "stdio",
                    "env": cfg.get("env"),
                }
            elif transport in ("sse", "http", "streamable_http", "streamable-http"):
                connections[name] = {
                    "url": cfg["url"],
                    "transport": transport,
                    "headers": cfg.get("headers"),
                }
            else:
                print(f" \033[38;5;214m[MCP] 未知 transport '{transport}'，跳过 {name}\033[0m")

        return connections
