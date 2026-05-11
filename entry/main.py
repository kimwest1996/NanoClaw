"""Thin entry-point: bootstrap the three runtime resources and hand off to Repl."""

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from nanoclaw.core.agent import create_agent_app
from nanoclaw.core.config import DB_PATH
from nanoclaw.core.mcp_manager import MCPManager
from nanoclaw.core.subagent import configure_subagent_manager
from nanoclaw.core.tool_policy import ToolPoolMode

from entry.repl import Repl
from entry.ui import cprint, print_banner


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


async def async_main(mode: Optional[ToolPoolMode] = None):
    print_banner()
    load_dotenv(ENV_PATH)

    current_provider = os.getenv("DEFAULT_PROVIDER", "aliyun")
    current_model = os.getenv("DEFAULT_MODEL", "glm-5")

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
        # ── MCP ────────────────────────────────────────────────────
        mcp_manager = MCPManager()
        mcp_tools = await mcp_manager.start()
        if mcp_tools:
            cprint(f"  \033[38;5;51m✦ MCP: 已加载 {len(mcp_tools)} 个外部工具\033[0m")

        # ── subagent manager ───────────────────────────────────────
        configure_subagent_manager(current_provider, current_model, asyncio.get_event_loop())

        # ── initial app ────────────────────────────────────────────
        current_mode = mode or ToolPoolMode.FULL
        app = create_agent_app(
            provider_name=current_provider,
            model_name=current_model,
            checkpointer=memory,
            mode=current_mode,
            mcp_tools=mcp_tools,
        )
        config = {"configurable": {"thread_id": "local_geek_master"}}

        repl = Repl(
            app=app,
            memory=memory,
            mcp_manager=mcp_manager,
            mcp_tools=mcp_tools,
            provider=current_provider,
            model=current_model,
            mode=current_mode,
            config=config,
        )
        await repl.run()


def main(mode: Optional[ToolPoolMode] = None):
    asyncio.run(async_main(mode=mode))


if __name__ == "__main__":
    main()
