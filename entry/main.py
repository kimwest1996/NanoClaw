import os
import sys
import time
import asyncio
import random
import shlex
from typing import Optional
import questionary
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from dotenv import set_key

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.styles import Style
from prompt_toolkit.application import get_app

from nanoclaw.core.agent import create_agent_app
from nanoclaw.core.approval import cli_approval_callback
from nanoclaw.core.config import DB_PATH
from nanoclaw.core.tool_policy import ToolPoolMode
from nanoclaw.core.bus import task_queue
from nanoclaw.core.heartbeat import pacemaker_loop
from nanoclaw.core.mcp_manager import MCPManager

KNOWN_PROVIDERS = {"openai", "anthropic", "aliyun", "dashscope", "tencent", "z.ai", "deepseek", "xiaomi", "ollama", "other"}
MODEL_CATALOG = {
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "xiaomi": ["mimo-v2-flash", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2.5", "mimo-v2.5-pro"],
}

def api_key_env_for_provider(provider: str) -> Optional[str]:
    if provider == "ollama":
        return None
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "deepseek":
        return "DEEPSEEK_API_KEY"
    if provider == "xiaomi":
        return "MIMO_API_KEY"
    return "OPENAI_API_KEY"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def type_line(text: str, delay: float = 0.008):
    for ch in text:
        print(ch, end='', flush=True)
        time.sleep(delay)
    print()

def print_banner():
    clear_screen()

    CYAN = '\033[38;5;51m'
    PURPLE = '\033[38;5;141m'
    SILVER = '\033[38;5;250m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    WHITE = '\033[37m'

    logo = f"""{CYAN}{BOLD}
███╗   ██╗ █████╗ ███╗   ██╗ ██████╗
████╗  ██║██╔══██╗████╗  ██║██╔═══██╗
██╔██╗ ██║███████║██╔██╗ ██║██║   ██║
██║╚██╗██║██╔══██║██║╚██╗██║██║   ██║
██║ ╚████║██║  ██║██║ ╚████║╚██████╔╝
╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝

 ██████╗██╗      █████╗ ██╗    ██╗
██╔════╝██║     ██╔══██╗██║    ██║
██║     ██║     ███████║██║ █╗ ██║
██║     ██║     ██╔══██║██║███╗██║
╚██████╗███████╗██║  ██║╚███╔███╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
{RESET}"""

    sub_title = f"{WHITE}{BOLD} 👾 Welcome to the {PURPLE}{BOLD}NanoClaw{RESET}{WHITE}{BOLD} !  {RESET}"

    quotes = [
        "It works on my machine.",
        "It compiles! Ship it.",
        "Git commit, push, pray.",
        "There's no place like 127.0.0.1.",
        "sudo make me a sandwich.",
        "Works fine in dev.",
        "May the source be with you.",
        "Ctrl+C, Ctrl+V, Deploy.",
        "Hello, World."
    ]
    quote = random.choice(quotes)
    meta = f" {SILVER}✦{RESET} {CYAN}{quote}{RESET}"

    tip = (
        f"{PURPLE} ✦ {RESET}"
        f"{SILVER}{PURPLE}{BOLD}NanoClaw{RESET} 已完成启动。输入命令开始，输入 {PURPLE}/exit{RESET}{SILVER} 退出。{RESET}\n"
    )

    print(logo)
    print(sub_title)
    print() 
    time.sleep(0.12)
    print(meta)
    print() 
    type_line(tip, delay=0.004)


def cprint(text="", end="\n"):
    print_formatted_text(ANSI(str(text)), end=end)


def parse_model_command(user_input: str, current_provider: str) -> tuple:
    try:
        parts = shlex.split(user_input)
    except ValueError as exc:
        return current_provider, "", False, f"命令解析失败：{exc}"
    save = False
    filtered_parts = []
    for part in parts:
        if part == "--save":
            save = True
        else:
            filtered_parts.append(part)
    parts = filtered_parts

    if len(parts) == 1:
        return current_provider, "", save, "interactive"

    if len(parts) == 2 and parts[1] in ["help", "-h", "--help"]:
        return current_provider, "", save, "help"

    if len(parts) == 2:
        return current_provider, parts[1], save, None

    provider = parts[1].lower()
    model = parts[2]
    if provider not in KNOWN_PROVIDERS:
        return current_provider, "", save, f"未知 provider：{provider}"
    return provider, model, save, None


async def async_main(mode: Optional[ToolPoolMode] = None):
    print_banner()
    
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(env_path)
    
    current_provider = os.getenv("DEFAULT_PROVIDER", "aliyun")
    current_model = os.getenv("DEFAULT_MODEL", "glm-5")

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
        # 启动 MCP
        mcp_manager = MCPManager()
        mcp_tools = await mcp_manager.start()
        if mcp_tools:
            cprint(f"  \033[38;5;51m✦ MCP: 已加载 {len(mcp_tools)} 个外部工具\033[0m")

        current_mode = mode or ToolPoolMode.FULL
        app = create_agent_app(provider_name=current_provider, model_name=current_model, checkpointer=memory, mode=current_mode, mcp_tools=mcp_tools)
        config = {"configurable": {"thread_id": "local_geek_master"}}

        def reload_runtime_env():
            load_dotenv(env_path, override=True)

        def print_model_help():
            cprint("  \033[38;5;141m/model 用法\033[0m")
            cprint("    /model                              打开交互式模型选择器")
            cprint("    /model help                         查看当前模型和命令帮助")
            cprint("    /model <model>                      切换当前 provider 下的模型")
            cprint("    /model <provider> <model>           切换 provider 和模型")
            cprint("    /model <provider> <model> --save    切换并写回 .env")
            cprint("    示例：/model deepseek deepseek-v4-flash")
            cprint("    示例：/model xiaomi mimo-v2-flash --save")

        def apply_model_switch(provider: str, model: str, save: bool) -> bool:
            nonlocal app, current_provider, current_model

            try:
                new_app = create_agent_app(provider_name=provider, model_name=model, checkpointer=memory, mode=current_mode)
            except Exception as exc:
                cprint(f"  \033[31m[ 模型切换失败：{exc} ]\033[0m")
                return False

            app = new_app
            current_provider = provider
            current_model = model
            os.environ["DEFAULT_PROVIDER"] = provider
            os.environ["DEFAULT_MODEL"] = model

            if save:
                set_key(env_path, "DEFAULT_PROVIDER", provider)
                set_key(env_path, "DEFAULT_MODEL", model)

            suffix = "，已写回 .env" if save else "，仅当前会话生效"
            cprint(f"  \033[38;5;51m✦ 已切换模型：{provider} / {model}{suffix}\033[0m")
            return True

        async def ensure_provider_key(provider: str, save: bool) -> bool:
            env_key = api_key_env_for_provider(provider)
            if env_key is None or os.getenv(env_key):
                return True

            cprint(f"  \033[38;5;214m当前缺少 {env_key}，需要先录入该 provider 的 API Key。\033[0m")
            api_key = await questionary.password(f"输入 {env_key}:").ask_async()
            if not api_key:
                cprint("  \033[38;5;242m已取消模型切换。\033[0m")
                return False

            os.environ[env_key] = api_key
            if save:
                set_key(env_path, env_key, api_key)
            return True

        async def open_model_picker() -> bool:
            provider_choices = [
                questionary.Choice(title=f"{provider} (current)", value=provider)
                if provider == current_provider else provider
                for provider in ["deepseek", "xiaomi", "openai", "anthropic", "aliyun", "dashscope", "tencent", "z.ai", "ollama", "other"]
            ]
            provider = await questionary.select(
                "选择 Provider:",
                choices=provider_choices,
                default=current_provider if current_provider in KNOWN_PROVIDERS else "deepseek",
            ).ask_async()
            if not provider:
                cprint("  \033[38;5;242m已取消模型切换。\033[0m")
                return True

            known_models = MODEL_CATALOG.get(provider, [])
            if known_models:
                model_choices = [
                    questionary.Choice(title=f"{model} (current)", value=model)
                    if provider == current_provider and model == current_model else model
                    for model in known_models
                ]
                model_choices.append(questionary.Choice(title="手动输入其他模型名", value="__custom__"))
                model = await questionary.select(
                    "选择模型:",
                    choices=model_choices,
                    default=current_model if current_model in known_models else known_models[0],
                ).ask_async()
                if model == "__custom__":
                    model = await questionary.text("输入模型名:", default=current_model if provider == current_provider else "").ask_async()
            else:
                model = await questionary.text("输入模型名:", default=current_model if provider == current_provider else "").ask_async()

            if not model:
                cprint("  \033[38;5;242m已取消模型切换。\033[0m")
                return True

            save = await questionary.confirm("是否写回 .env，作为下次启动默认模型？", default=False).ask_async()
            if save is None:
                cprint("  \033[38;5;242m已取消模型切换。\033[0m")
                return True

            if not await ensure_provider_key(provider, bool(save)):
                return True

            confirmed = await questionary.confirm(f"确认切换到 {provider} / {model}？", default=True).ask_async()
            if not confirmed:
                cprint("  \033[38;5;242m已取消模型切换。\033[0m")
                return True

            apply_model_switch(provider, model, bool(save))
            return True

        async def switch_model_command(user_input: str) -> bool:
            reload_runtime_env()
            provider, model, save, error = parse_model_command(user_input, current_provider)
            if error == "interactive":
                return await open_model_picker()
            if error == "help":
                cprint(f"  \033[38;5;51m当前模型：{current_provider} / {current_model}\033[0m")
                print_model_help()
                return True
            if error:
                cprint(f"  \033[31m[ /model 错误：{error} ]\033[0m")
                print_model_help()
                return True
            if not model:
                cprint("  \033[31m[ /model 错误：缺少模型名 ]\033[0m")
                print_model_help()
                return True

            env_key = api_key_env_for_provider(provider)
            if env_key and not os.getenv(env_key):
                cprint(f"  \033[31m[ 模型切换失败：缺少 {env_key}。请先在 .env 中配置，或直接输入 /model 使用交互式选择器录入。]\033[0m")
                return True

            apply_model_switch(provider, model, save)
            return True

        class SpinnerState:
            action_words = [
                "Thinking...",              
                "Working...",               
                "Beep boop...",             
                "Eating bugs...",           
                "Charging battery...",      
                "Brewing coffee...",        
                "Blinking lights...",       
                "Polishing pixels...",      
                "Scanning matrix...",       
                "Warming up circuits...",   
                "Syncing data...",          
                "Pinging server..."         
            ]
            current_words = [] 
            is_spinning = False
            start_time = 0
            frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
            is_tool_calling = False 
            tool_msg = ""           

        spinner = SpinnerState()


        def get_bottom_toolbar():
            if not spinner.is_spinning:
                return ANSI("") 
            
            elapsed = time.time() - spinner.start_time
            if spinner.is_tool_calling:
                display_msg = spinner.tool_msg
            else:
                idx_word = int(elapsed) % len(spinner.current_words)
                display_msg = f"👾 {spinner.current_words[idx_word]}"

            idx_frame = int(elapsed * 12) % len(spinner.frames)
            frame = spinner.frames[idx_frame]
            

            return ANSI(f"  \033[38;5;51m{frame}\033[0m \033[38;5;250m{display_msg}\033[0m \033[38;5;141m[{elapsed:.1f}s]\033[0m")

        prompt_message = ANSI("  \033[38;5;51m❯\033[0m ")
        placeholder_text = ANSI("\033[3m\033[38;5;242minput...\033[0m")

        async def agent_worker():
            nonlocal app, current_mode
            while True:
                user_input = await task_queue.get()
                if user_input.lower() in ["/exit", "/quit"]:
                    task_queue.task_done()
                    break
                first_token = user_input.split(maxsplit=1)[0].lower()
                if first_token == "/model":
                    await switch_model_command(user_input)
                    cprint()
                    task_queue.task_done()
                    continue

                if first_token == "/mode":
                    parts = user_input.split(maxsplit=1)
                    if len(parts) < 2 or parts[1].strip().lower() not in ("safe", "no_shell", "full"):
                        cprint("  \033[38;5;141m/mode 用法\033[0m")
                        cprint("    /mode safe       只加载只读工具（演示/教学）")
                        cprint("    /mode no_shell   除 shell 外全部加载（日常使用）")
                        cprint("    /mode full       全部工具（开发调试）")
                        cprint(f"  当前模式：\033[1m{current_mode.value}\033[0m")
                    else:
                        new_mode = ToolPoolMode(parts[1].strip().lower())
                        current_mode = new_mode
                        app = create_agent_app(
                            provider_name=current_provider,
                            model_name=current_model,
                            checkpointer=memory,
                            mode=current_mode,
                            mcp_tools=mcp_tools,
                        )
                        cprint(f"  \033[32m✓ 工具模式已切换为：{current_mode.value}\033[0m")
                    cprint()
                    task_queue.task_done()
                    continue

                if first_token == "/mcp":
                    cprint(f"  \033[38;5;141m{mcp_manager.status()}\033[0m")
                    if mcp_tools:
                        cprint("  \033[38;5;141mMCP 工具列表:\033[0m")
                        for t in mcp_tools:
                            cprint(f"    - {t.name}")
                    cprint()
                    task_queue.task_done()
                    continue
                
                spinner.current_words = spinner.action_words.copy()
                random.shuffle(spinner.current_words)
                
                spinner.start_time = time.time()
                spinner.is_spinning = True
                spinner.is_tool_calling = False
                
                inputs = {"messages": [HumanMessage(content=user_input)]}
                run_config = {
                    **config,
                    "configurable": {
                        **config.get("configurable", {}),
                        "approval_callback": cli_approval_callback,
                    },
                }
                try:
                    async for event in app.astream(inputs, config=run_config, stream_mode="updates"):
                        for node_name, node_data in event.items():
                            if node_name == "agent":
                                last_msg = node_data["messages"][-1]
                                
                                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                    for tc in last_msg.tool_calls:
                                        spinner.is_tool_calling = True
                                        spinner.tool_msg = f"唤醒内置工具 : {tc['name']}..."
                                        cprint(f"  ●\033[38;5;51m Tool Call: \033[0m{tc['name']}")
                                        cprint('')
                                        
                                elif last_msg.content:
                                    spinner.is_spinning = False
                                    
                                    lines = last_msg.content.strip().split('\n')
                                    if lines:
                                        formatted_out = f"  \033[38;5;141m❯\033[0m \033[38;5;250m{lines[0]}"
                                        for line in lines[1:]:
                                            formatted_out += f"\n    {line}"
                                        formatted_out += "\033[0m" 
                                        cprint(formatted_out)
                                    
                            elif node_name != "agent": 
                                spinner.is_tool_calling = False 
                                
                except Exception as e:
                    spinner.is_spinning = False
                    cprint(f"  \033[31m[ ⚠️ 引擎异常 : {e} ]\033[0m")

                spinner.is_spinning = False
                cprint() # 空出舒适的行距
                task_queue.task_done()

        async def user_input_loop():
            custom_style = Style.from_dict({
                'bottom-toolbar': 'bg:default fg:default noreverse',
            })
            
            session = PromptSession(
                bottom_toolbar=get_bottom_toolbar,
                style=custom_style,
                erase_when_done=True,
                reserve_space_for_menu=0  
            )
            
            async def redraw_timer():
                while True:
                    if spinner.is_spinning:
                        try:
                            get_app().invalidate()
                        except Exception:
                            pass
                    await asyncio.sleep(0.08)
                    
            redraw_task = asyncio.create_task(redraw_timer())
            
            while True:
                try:
                    user_input = await session.prompt_async(prompt_message, placeholder=placeholder_text)

                    user_input = user_input.strip()
                    if not user_input:
                        continue
                    

                    padded_bubble = f"  ❯ {user_input}    "
                    cprint(f"\033[48;2;38;38;38m\033[38;5;255m{padded_bubble}\033[0m\n")

                    first_token = user_input.split(maxsplit=1)[0].lower()
                    if first_token == "/model":
                        await switch_model_command(user_input)
                        cprint()
                        continue
                    
                    await task_queue.put(user_input)
                    if user_input.lower() in ["/exit", "/quit"]:
                        cprint("  \033[38;5;141m✦ 记忆已固化，NanoClaw 进入休眠。\033[0m")
                        break
                        
                except (KeyboardInterrupt, EOFError):
                    cprint("\n  \033[38;5;141m✦ 强制中断，NanoClaw 进入休眠。\033[0m")
                    await task_queue.put("/exit")
                    break

            redraw_task.cancel() 

        with patch_stdout():
            worker = asyncio.create_task(agent_worker())
            heartbeat_worker = asyncio.create_task(pacemaker_loop(check_interval=10))
            try:
                await user_input_loop()
                await task_queue.join()
            finally:
                worker.cancel()
                heartbeat_worker.cancel()
                await mcp_manager.stop()

def main(mode: Optional[ToolPoolMode] = None):
    asyncio.run(async_main(mode=mode))

if __name__ == "__main__":
    main()
