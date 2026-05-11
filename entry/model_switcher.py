"""Model switching logic — pure validation + interactive picker.

Returns structured results (``(provider, model, messages)``) so the caller
decides how to display output.  This module never imports from ``entry.ui``
and never touches the agent ``app``.
"""

import os
import shlex
from typing import Optional

import questionary
from dotenv import set_key, load_dotenv

KNOWN_PROVIDERS = {
    "openai", "anthropic", "aliyun", "dashscope",
    "tencent", "z.ai", "deepseek", "xiaomi", "ollama", "other",
}

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


def parse_model_command(user_input: str, current_provider: str) -> tuple:
    """Parse a ``/model`` line.

    Returns ``(provider, model, save, error_hint)`` where *error_hint* is
    ``None`` on success or one of ``"interactive"``, ``"help"``, or an error
    message string.
    """
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
    if len(parts) == 2 and parts[1] in ("help", "-h", "--help"):
        return current_provider, "", save, "help"
    if len(parts) == 2:
        return current_provider, parts[1], save, None

    provider = parts[1].lower()
    model = parts[2]
    if provider not in KNOWN_PROVIDERS:
        return current_provider, "", save, f"未知 provider：{provider}"
    return provider, model, save, None


def _help_messages(current_provider: str, current_model: str) -> list[str]:
    return [
        f"  \033[38;5;51m当前模型：{current_provider} / {current_model}\033[0m",
        "  \033[38;5;141m/model 用法\033[0m",
        "    /model                              打开交互式模型选择器",
        "    /model help                         查看当前模型和命令帮助",
        "    /model <model>                      切换当前 provider 下的模型",
        "    /model <provider> <model>           切换 provider 和模型",
        "    /model <provider> <model> --save    切换并写回 .env",
        "    示例：/model deepseek deepseek-v4-flash",
        "    示例：/model xiaomi mimo-v2-flash --save",
    ]


async def _ensure_provider_key(provider: str, save: bool, env_path: str) -> tuple[bool, list[str]]:
    """Prompt user to enter an API key if missing.

    Returns ``(ok, messages)`` — *ok* is ``True`` when the key is available.
    """
    msgs: list[str] = []
    env_key = api_key_env_for_provider(provider)
    if env_key is None or os.getenv(env_key):
        return True, msgs

    msgs.append(f"  \033[38;5;214m当前缺少 {env_key}，需要先录入该 provider 的 API Key。\033[0m")
    api_key = await questionary.password(f"输入 {env_key}:").ask_async()
    if not api_key:
        msgs.append("  \033[38;5;242m已取消模型切换。\033[0m")
        return False, msgs

    os.environ[env_key] = api_key
    if save:
        set_key(env_path, env_key, api_key)
    return True, msgs


async def _open_model_picker(
    current_provider: str,
    current_model: str,
    env_path: str,
) -> tuple[Optional[str], Optional[str], list[str]]:
    """Interactive model picker.

    Returns ``(new_provider, new_model, messages)``.
    ``(None, None, messages)`` when cancelled.
    """
    msgs: list[str] = []

    provider_choices = [
        questionary.Choice(title=f"{p} (current)", value=p)
        if p == current_provider else p
        for p in [
            "deepseek", "xiaomi", "openai", "anthropic",
            "aliyun", "dashscope", "tencent", "z.ai", "ollama", "other",
        ]
    ]
    provider = await questionary.select(
        "选择 Provider:",
        choices=provider_choices,
        default=current_provider if current_provider in KNOWN_PROVIDERS else "deepseek",
    ).ask_async()
    if not provider:
        msgs.append("  \033[38;5;242m已取消模型切换。\033[0m")
        return None, None, msgs

    known_models = MODEL_CATALOG.get(provider, [])
    if known_models:
        model_choices = [
            questionary.Choice(title=f"{m} (current)", value=m)
            if provider == current_provider and m == current_model else m
            for m in known_models
        ]
        model_choices.append(questionary.Choice(title="手动输入其他模型名", value="__custom__"))
        model = await questionary.select(
            "选择模型:",
            choices=model_choices,
            default=current_model if current_model in known_models else known_models[0],
        ).ask_async()
        if model == "__custom__":
            model = await questionary.text(
                "输入模型名:", default=current_model if provider == current_provider else ""
            ).ask_async()
    else:
        model = await questionary.text(
            "输入模型名:", default=current_model if provider == current_provider else ""
        ).ask_async()

    if not model:
        msgs.append("  \033[38;5;242m已取消模型切换。\033[0m")
        return None, None, msgs

    save = await questionary.confirm(
        "是否写回 .env，作为下次启动默认模型？", default=False
    ).ask_async()
    if save is None:
        msgs.append("  \033[38;5;242m已取消模型切换。\033[0m")
        return None, None, msgs

    key_ok, key_msgs = await _ensure_provider_key(provider, bool(save), env_path)
    msgs.extend(key_msgs)
    if not key_ok:
        return None, None, msgs

    confirmed = await questionary.confirm(
        f"确认切换到 {provider} / {model}？", default=True
    ).ask_async()
    if not confirmed:
        msgs.append("  \033[38;5;242m已取消模型切换。\033[0m")
        return None, None, msgs

    msgs.extend(_apply_env_update(provider, model, bool(save), env_path))
    return provider, model, msgs


def _apply_env_update(provider: str, model: str, save: bool, env_path: str) -> list[str]:
    """Write provider/model to env vars and optionally to ``.env``.

    Returns messages to display.
    """
    os.environ["DEFAULT_PROVIDER"] = provider
    os.environ["DEFAULT_MODEL"] = model
    if save:
        set_key(env_path, "DEFAULT_PROVIDER", provider)
        set_key(env_path, "DEFAULT_MODEL", model)
    suffix = "，已写回 .env" if save else "，仅当前会话生效"
    return [f"  \033[38;5;51m✦ 已切换模型：{provider} / {model}{suffix}\033[0m"]


async def handle_model_command(
    user_input: str,
    current_provider: str,
    current_model: str,
) -> tuple[Optional[str], Optional[str], list[str]]:
    """Handle ``/model`` from the REPL.

    Returns ``(new_provider, new_model, messages)``.
    ``(None, None, messages)`` when nothing changed.
    """
    env_path = make_env_path()
    load_dotenv(env_path, override=True)

    provider, model, save, error = parse_model_command(user_input, current_provider)

    if error == "interactive":
        return await _open_model_picker(current_provider, current_model, env_path)

    if error == "help":
        return None, None, _help_messages(current_provider, current_model)

    if error:
        return None, None, [
            f"  \033[31m[ /model 错误：{error} ]\033[0m",
            *_help_messages(current_provider, current_model),
        ]

    if not model:
        return None, None, [
            "  \033[31m[ /model 错误：缺少模型名 ]\033[0m",
            *_help_messages(current_provider, current_model),
        ]

    env_key = api_key_env_for_provider(provider)
    if env_key and not os.getenv(env_key):
        return None, None, [
            f"  \033[31m[ 模型切换失败：缺少 {env_key}。"
            "请先在 .env 中配置，或直接输入 /model 使用交互式选择器录入。]\033[0m",
        ]

    return provider, model, _apply_env_update(provider, model, save, env_path)


def make_env_path() -> str:
    """Return the absolute path to the project's ``.env`` file."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(this_dir)
    return os.path.join(project_root, ".env")
