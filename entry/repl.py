"""REPL two-coroutine event loop.

Architecture
------------
- ``Repl`` owns the ``app`` variable — no other code writes to it.
- ``_user_input_loop`` handles ``/model``, ``/mode``, ``/mcp`` instantly.
- ``_agent_worker`` is the sole rebuilder of ``app``, controlled by the
  ``pending_rebuild`` flag.
- Regular user messages travel through ``asyncio.Queue`` (producer-consumer).
"""

import asyncio
import random
from typing import Optional

from langchain_core.messages import HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import ANSI

from nanoclaw.core.agent import create_agent_app
from nanoclaw.core.approval import cli_approval_callback
from nanoclaw.core.subagent import get_subagent_manager
from nanoclaw.core.bus import task_queue
from nanoclaw.core.heartbeat import pacemaker_loop
from nanoclaw.core.tool_policy import ToolPoolMode

from entry.ui import SpinnerState, cprint, get_bottom_toolbar
from entry.model_switcher import handle_model_command


PROMPT_STYLE = Style.from_dict({"bottom-toolbar": "bg:default fg:default noreverse"})


class Repl:
    """Two-coroutine REPL that owns the agent app lifecycle."""

    def __init__(
        self,
        app,
        memory,
        mcp_manager,
        mcp_tools,
        provider: str,
        model: str,
        mode: ToolPoolMode,
        config: dict,
    ):
        self.app = app
        self.memory = memory
        self.mcp_manager = mcp_manager
        self.mcp_tools = mcp_tools
        self.current_provider = provider
        self.current_model = model
        self.current_mode = mode
        self.config = config
        self.spinner = SpinnerState()
        self.pending_rebuild = False

    # ── agent_worker: processes user messages ──────────────────────

    async def _agent_worker(self):
        while True:
            user_input = await task_queue.get()

            if user_input.lower() in ("/exit", "/quit"):
                task_queue.task_done()
                break

            # Rebuild app if a model/mode switch was signalled.
            if self.pending_rebuild:
                try:
                    self.app = create_agent_app(
                        provider_name=self.current_provider,
                        model_name=self.current_model,
                        checkpointer=self.memory,
                        mode=self.current_mode,
                        mcp_tools=self.mcp_tools,
                    )
                except Exception as exc:
                    cprint(f"  \033[31m[ agent 重建失败：{exc} ]\033[0m")
                self.pending_rebuild = False

            self.spinner.current_words = self.spinner.action_words.copy()
            random.shuffle(self.spinner.current_words)
            self.spinner.start_time = asyncio.get_event_loop().time()
            self.spinner.is_spinning = True
            self.spinner.is_tool_calling = False

            inputs = {"messages": [HumanMessage(content=user_input)]}
            run_config = {
                **self.config,
                "configurable": {
                    **self.config.get("configurable", {}),
                    "approval_callback": cli_approval_callback,
                },
            }

            try:
                async for event in self.app.astream(
                    inputs, config=run_config, stream_mode="updates"
                ):
                    for node_name, node_data in event.items():
                        if node_name == "agent":
                            last_msg = node_data["messages"][-1]

                            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                for tc in last_msg.tool_calls:
                                    self.spinner.is_tool_calling = True
                                    self.spinner.tool_msg = (
                                        f"唤醒内置工具 : {tc['name']}..."
                                    )
                                    cprint(f"  ●\033[38;5;51m Tool Call: \033[0m{tc['name']}")
                                    cprint("")

                            elif last_msg.content:
                                self.spinner.is_spinning = False
                                lines = last_msg.content.strip().split("\n")
                                if lines:
                                    out = f"  \033[38;5;141m❯\033[0m \033[38;5;250m{lines[0]}"
                                    for line in lines[1:]:
                                        out += f"\n    {line}"
                                    out += "\033[0m"
                                    cprint(out)

                        elif node_name != "agent":
                            self.spinner.is_tool_calling = False

            except Exception as e:
                self.spinner.is_spinning = False
                cprint(f"  \033[31m[ ⚠️ 引擎异常 : {e} ]\033[0m")

            self.spinner.is_spinning = False
            cprint()
            task_queue.task_done()

    # ── user_input_loop: reads keyboard ────────────────────────────

    async def _user_input_loop(self):
        session = PromptSession(
            bottom_toolbar=lambda: get_bottom_toolbar(self.spinner),
            style=PROMPT_STYLE,
            erase_when_done=True,
            reserve_space_for_menu=0,
        )

        prompt_message = ANSI("  \033[38;5;51m❯\033[0m ")
        placeholder_text = ANSI("\033[3m\033[38;5;242minput...\033[0m")

        async def _redraw_timer():
            while True:
                if self.spinner.is_spinning:
                    try:
                        get_app().invalidate()
                    except Exception:
                        pass
                await asyncio.sleep(0.08)

        redraw_task = asyncio.create_task(_redraw_timer())

        while True:
            try:
                user_input = await session.prompt_async(
                    prompt_message, placeholder=placeholder_text
                )
                user_input = user_input.strip()
                if not user_input:
                    continue

                padded = f"  ❯ {user_input}    "
                cprint(f"\033[48;2;38;38;38m\033[38;5;255m{padded}\033[0m\n")

                first_token = user_input.split(maxsplit=1)[0].lower()

                # ── /model ──────────────────────────────────────────
                if first_token == "/model":
                    new_provider, new_model, msgs = await handle_model_command(
                        user_input,
                        self.current_provider,
                        self.current_model,
                    )
                    for msg in msgs:
                        cprint(msg)
                    if new_provider is not None:
                        self.current_provider = new_provider
                        self.current_model = new_model
                        get_subagent_manager().update_provider(new_provider, new_model)
                        self.pending_rebuild = True
                    cprint()
                    continue

                # ── /mode ───────────────────────────────────────────
                if first_token == "/mode":
                    parts = user_input.split(maxsplit=1)
                    if len(parts) < 2 or parts[1].strip().lower() not in (
                        "safe",
                        "no_shell",
                        "full",
                    ):
                        cprint("  \033[38;5;141m/mode 用法\033[0m")
                        cprint("    /mode safe       只加载只读工具（演示/教学）")
                        cprint("    /mode no_shell   除 shell 外全部加载（日常使用）")
                        cprint("    /mode full       全部工具（开发调试）")
                        cprint(f"  当前模式：\033[1m{self.current_mode.value}\033[0m")
                    else:
                        new_mode = ToolPoolMode(parts[1].strip().lower())
                        if new_mode != self.current_mode:
                            self.current_mode = new_mode
                            self.pending_rebuild = True
                            cprint(
                                f"  \033[32m✓ 工具模式已记录，下一轮生效：{self.current_mode.value}\033[0m"
                            )
                        else:
                            cprint(f"  当前已经是 {self.current_mode.value} 模式")
                    cprint()
                    continue

                # ── /mcp — instant, no rebuild needed ──────────────
                if first_token == "/mcp":
                    cprint(f"  \033[38;5;141m{self.mcp_manager.status()}\033[0m")
                    if self.mcp_tools:
                        cprint("  \033[38;5;141mMCP 工具列表:\033[0m")
                        for t in self.mcp_tools:
                            cprint(f"    - {t.name}")
                    cprint()
                    continue

                # ── normal message ─────────────────────────────────
                await task_queue.put(user_input)

                if user_input.lower() in ("/exit", "/quit"):
                    cprint("  \033[38;5;141m✦ 记忆已固化，NanoClaw 进入休眠。\033[0m")
                    break

            except (KeyboardInterrupt, EOFError):
                cprint("\n  \033[38;5;141m✦ 强制中断，NanoClaw 进入休眠。\033[0m")
                await task_queue.put("/exit")
                break

        redraw_task.cancel()

    # ── run: launch both coroutines ────────────────────────────────

    async def run(self):
        with patch_stdout():
            worker = asyncio.create_task(self._agent_worker())
            heartbeat = asyncio.create_task(pacemaker_loop(check_interval=10))
            try:
                await self._user_input_loop()
                await task_queue.join()
            finally:
                try:
                    get_subagent_manager().cancel_all()
                except Exception:
                    pass
                worker.cancel()
                heartbeat.cancel()
                await self.mcp_manager.stop()