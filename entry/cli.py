import os
import sys
from pathlib import Path

import typer
import questionary
import logging
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from dotenv import set_key, load_dotenv, unset_key

# ── Dev-mode bootstrap: make nanoclaw importable without pip install ──
# Remove once `pip install -e .` is the standard approach.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from nanoclaw.core.provider import get_provider
from nanoclaw.core.config import ensure_workspace
from langchain_core.messages import HumanMessage

ENTRY_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ENTRY_DIR)

app = typer.Typer(help="NanoClaw - 极客专属的赛博智能终端")
console = Console()

cyber_style = questionary.Style([
    ('qmark', 'fg:#8d52ff bold'),       
    ('question', 'fg:#00ffff bold'),    
    ('answer', 'fg:#8d52ff bold'),      
    ('pointer', 'fg:#00ffff bold'),     
    ('highlighted', 'fg:#00ffff bold'), 
    ('selected', 'fg:#00ffff'),
    ('instruction', 'fg:#808080 dim'),  
])

ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

@app.command("config")
def config_wizard():
    console.clear()
    console.print(Panel(
        "👾 Welcome to [bold #8d52ff]NanoClaw[/bold #8d52ff]...\n\n☁️[dim] 请完成模型配置，我们将把密钥安全固化在本地。[/dim]", 
        title="[bold white]✦  NanoClaw Config[/bold white]", 
        border_style="#8d52ff"
    ))
    provider_raw = questionary.select(
        "选择你的模型提供商 (Provider):",
        choices=[
            "openai",
            "anthropic",
            "aliyun (openai compatible)",
            "tencent (openai compatible)",
            "z.ai (openai compatible)",
            "deepseek",
            "xiaomi",
            "other (openai compatible)",
            "ollama",
        ],
        style=cyber_style,
        instruction="(按上下键选择，回车确认)"
    ).ask()

    if not provider_raw:
        console.print("[dim #8d52ff]✦   录入中断，NanoClaw 配置已取消。[/dim #8d52ff]")
        return

    provider = provider_raw.split(" ")[0].strip()
    is_openai_compatible = "openai" in provider_raw.lower()

    model_name = questionary.text(
        "输入指定的模型型号 (如 gpt-4o-mini, qwen-max, glm-4 等):",
        style=cyber_style
    ).ask()

    if model_name is None:
        console.print("[dim #8d52ff]✦   录入中断，NanoClaw 配置已取消。[/dim #8d52ff]")
        return

    api_key = ""
    env_key = ""
    if provider != "ollama":
        if is_openai_compatible:
            env_key = "OPENAI_API_KEY"
        elif provider == "anthropic":
            env_key = "ANTHROPIC_API_KEY"
        elif provider == "deepseek":
            env_key = "DEEPSEEK_API_KEY"
        elif provider == "xiaomi":
            env_key = "MIMO_API_KEY"

        api_key = questionary.password(
            f"输入你的 {env_key} (对应 {provider_raw}):",
            style=cyber_style
        ).ask()

        if api_key is None:
            console.print("[dim #8d52ff]✦   录入中断，NanoClaw 配置已取消。[/dim #8d52ff]")
            return

    base_url = ""
    if provider in ["openai", "anthropic", "deepseek", "xiaomi"]:
        base_url = questionary.text(
            f"输入 {provider} 代理 Base URL (直连请直接回车跳过):",
            style=cyber_style
        ).ask()
    elif provider == "ollama":
        base_url = questionary.text(
            "输入 Ollama Base URL (默认 http://localhost:11434，直接回车跳过):",
            style=cyber_style
        ).ask()
    else:
        base_url = questionary.text(
            "输入兼容 Base URL (不填直接回车将使用官方默认地址):",
            style=cyber_style
        ).ask()

    if base_url is None:
        console.print("[dim #8d52ff]✦   录入中断，NanoClaw 配置已取消。[/dim #8d52ff]")
        return

    console.print("\n[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")

    with Status(f"[bold #8d52ff]正在连接 {provider.upper()} 引擎并发送探测包...[/bold #8d52ff]", spinner="dots", spinner_style="#00ffff"):
        try:
            if env_key and api_key:
                os.environ[env_key] = api_key
            if base_url:
                if is_openai_compatible:
                    os.environ["OPENAI_API_BASE"] = base_url
                elif provider == "deepseek":
                    os.environ["DEEPSEEK_API_BASE"] = base_url
                elif provider == "xiaomi":
                    os.environ["MIMO_API_BASE"] = base_url
                else:
                    os.environ[f"{provider.upper()}_BASE_URL"] = base_url

            llm = get_provider(provider_name=provider, model_name=model_name)
            response = llm.invoke([HumanMessage(content="回复我'收到'。")])

            console.print(" [bold #00ffff][ 配置成功!][/bold #00ffff]")
            
        except Exception as e:

            console.print(f" [bold #8d52ff][ 配置失败!][/bold #8d52ff]  无法连接到模型，请检查 Key、Base URL、模型型号 或 网络！\n[dim]错误信息: {str(e)}[/dim]")
            return


    if not os.path.exists(ENV_PATH):
        open(ENV_PATH, 'w').close()

    logging.getLogger("dotenv.main").setLevel(logging.ERROR)

    unset_key(ENV_PATH, "OPENAI_API_BASE")
    unset_key(ENV_PATH, "ANTHROPIC_BASE_URL")
    unset_key(ENV_PATH, "DEEPSEEK_API_BASE")
    unset_key(ENV_PATH, "MIMO_API_BASE")
    unset_key(ENV_PATH, "XIAOMI_API_BASE")
    unset_key(ENV_PATH, "OLLAMA_BASE_URL")

    if env_key and api_key:
        set_key(ENV_PATH, env_key, api_key)
        
    if base_url:
        if is_openai_compatible:
            set_key(ENV_PATH, "OPENAI_API_BASE", base_url)
        elif provider == "deepseek":
            set_key(ENV_PATH, "DEEPSEEK_API_BASE", base_url)
        elif provider == "xiaomi":
            set_key(ENV_PATH, "MIMO_API_BASE", base_url)
        else:
            set_key(ENV_PATH, f"{provider.upper()}_BASE_URL", base_url)
    
    set_key(ENV_PATH, "DEFAULT_PROVIDER", provider)
    set_key(ENV_PATH, "DEFAULT_MODEL", model_name)

    console.print(Panel(
        f"配置已保存至 [#8d52ff]{ENV_PATH}[/#8d52ff]\n"
        f"当前默认提供商: [#8d52ff]{provider}[/#8d52ff] | 模型: [#8d52ff]{model_name}[/#8d52ff]\n\n"
        f"👉 输入 [bold #00ffff]nanoclaw run[/bold #00ffff] 即可启动系统！",
        border_style="#00ffff"
    ))

def _show_boot_error():
    console.print(Panel(
        "[bold #00ffff]NanoClaw未完成配置![/bold #00ffff]\n\n"
        "[#8d52ff]检测到 API Key、模型或Baseurl。请重新执行以下命令完成配置：[/#8d52ff]\n"
        "[bold #00ffff]nanoclaw config[/bold #00ffff]",
        title="[bold #8d52ff]⚠️ Boot Sequence Failed[/bold #8d52ff]",
        border_style="#8d52ff"
    ))


@app.command("run")
def run_agent(
    mode: str = typer.Option("full", "--mode", help="Tool pool mode: safe / no_shell / full"),
):
    load_dotenv(ENV_PATH)
    provider = os.getenv("DEFAULT_PROVIDER")
    model = os.getenv("DEFAULT_MODEL")
    if not provider or not model:
        _show_boot_error()
        raise typer.Exit()
    if provider != "ollama":
        if provider in ["openai", "aliyun", "z.ai", "tencent", "other"]: 
            if not os.getenv("OPENAI_API_KEY"):
                _show_boot_error()
                raise typer.Exit()

        elif provider == "deepseek":
            if not os.getenv("DEEPSEEK_API_KEY"):
                _show_boot_error()
                raise typer.Exit()

        elif provider == "xiaomi":
            if not (os.getenv("MIMO_API_KEY") or os.getenv("XIAOMI_API_KEY")):
                _show_boot_error()
                raise typer.Exit()

        elif provider == "anthropic":
            if not os.getenv("ANTHROPIC_API_KEY"):
                _show_boot_error()
                raise typer.Exit()
        
    from nanoclaw.core.tool_policy import ToolPoolMode
    import entry.main as nanoclaw_main
    try:
        pool_mode = ToolPoolMode(mode.lower().strip())
    except ValueError:
        typer.echo(f"Unknown mode: {mode}. Use: safe / no_shell / full")
        raise typer.Exit(1)
    ensure_workspace()
    nanoclaw_main.main(mode=pool_mode)

@app.command("serve")
def serve_api(
    host: str = typer.Option("127.0.0.1", "--host", help="API 监听地址"),
    port: int = typer.Option(8000, "--port", help="API 监听端口"),
    reload: bool = typer.Option(False, "--reload", help="启用开发热重载"),
):
    load_dotenv(ENV_PATH, override=True)
    provider = os.getenv("DEFAULT_PROVIDER")
    model = os.getenv("DEFAULT_MODEL")
    if not provider or not model:
        _show_boot_error()
        raise typer.Exit()

    import uvicorn

    ensure_workspace()
    uvicorn.run(
        "nanoclaw.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )

@app.command("monitor")
def run_monitor():    
        
    try:
        import entry.monitor as nanoclaw_monitor
        nanoclaw_monitor.main()
    except ImportError as e:
        console.print(f"[bold red]启动失败：找不到监视器模块！[/bold red]\n[dim]请确保 monitor.py 和 cli.py 在同一目录下。\n报错信息: {e}[/dim]")

@app.command("doctor")
def doctor():
    """运行系统诊断，检查环境/提供商/工作空间等健康状态"""
    load_dotenv(ENV_PATH)
    ensure_workspace()

    from nanoclaw.core.doctor import Doctor, CheckStatus
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console.print(Panel(
        "[bold #8d52ff]✦  NanoClaw 系统诊断[/bold #8d52ff]",
        border_style="#8d52ff"
    ))

    doc = Doctor()
    results = doc.run_all()

    table = Table(box=None, padding=(0, 2))
    table.add_column("项目", style="#8d52ff bold", width=14)
    table.add_column("状态", width=8)
    table.add_column("信息", style="#a0a0a0", no_wrap=False)
    table.add_column("耗时", style="#585858", width=8, justify="right")

    status_map = {
        CheckStatus.PASS: ("[bold green]✓ PASS[/bold green]", "green"),
        CheckStatus.WARN: ("[bold yellow]⚠ WARN[/bold yellow]", "yellow"),
        CheckStatus.FAIL: ("[bold red]✗ FAIL[/bold red]", "red"),
        CheckStatus.SKIP: ("[dim]– SKIP[/dim]", "dim"),
    }

    has_fail = False
    for r in results:
        label, color = status_map.get(r.status, ("???", "white"))
        table.add_row(r.name, label, r.message[:80], f"{r.duration_ms:.0f}ms")
        if r.status == CheckStatus.FAIL:
            has_fail = True

    console.print()
    console.print(table)
    console.print()

    # 显示建议和详情
    suggestions = [r for r in results if r.suggestion]
    if suggestions:
        console.print("[bold #ffa500]📋 建议[/bold #ffa500]")
        for r in suggestions:
            console.print(f"  [{status_map[r.status][1]}]{r.name}[/]: {r.suggestion}")
        console.print()

    # 显示详细诊断数据
    if any(r.details for r in results):
        console.print("[bold #585858]📊 详细信息[/bold #585858]")
        for r in results:
            if r.details:
                import json as _json
                console.print(f"  [{status_map[r.status][1]}]{r.name}[/]: "
                              f"{_json.dumps(r.details, ensure_ascii=False, indent=2)}")
        console.print()

    if has_fail:
        console.print("[bold red]❌ 诊断未通过，请根据建议修复后重试[/bold red]")
    else:
        console.print("[bold green]✅ 系统一切正常[/bold green]")


def main():
    app()

if __name__ == "__main__":
    main()
