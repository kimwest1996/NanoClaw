from datetime import datetime
from .base import nanoclaw_tool, NanoClawBaseTool
import os
import json
import uuid
import threading
from ..config import MEMORY_DIR, TASKS_FILE
from .sandbox_tools import (
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell
)
from .web_search import web_search
from ..memory import ProfileManager


tasks_lock = threading.Lock()

_profile_manager = None


def _get_profile_manager():
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager(MEMORY_DIR)
    return _profile_manager


@nanoclaw_tool
def get_system_model_info() -> str:
    """
    获取当前 NanoClaw 正在运行的底层大模型（LLM）型号和提供商信息。
    当用户询问“你是基于什么模型”、“你的底层大模型是什么”、“你是GPT还是GLM”、“现在用的什么模型”等身份问题时，调用此工具。
    """
    provider = os.getenv("DEFAULT_PROVIDER", "unknown")
    model = os.getenv("DEFAULT_MODEL", "unknown")
    
    if provider == "unknown" or model == "unknown":
        return "无法获取当前的系统模型配置，可能是环境变量未正确加载。"
        
    return f"当前使用的模型提供商(Provider)是: {provider}，具体型号(Model)是: {model}。"


@nanoclaw_tool
def save_user_profile(new_content: str) -> str:
    """
    更新用户的全局显性记忆档案。
    当你发现用户的偏好发生改变，或者有新的重要事实需要记录时：
    1.请先调用 read_user_profile 获取当前的完整档案。
    2.在你的上下文中，将新信息融入档案，并删去冲突或过时的旧信息。
    3.将修改后的一整篇完整 Markdown 文本作为 new_content 参数传入此工具。
    注意：此操作将完全覆盖旧文件！请确保传入的是完整的最新档案。
    """
    return _get_profile_manager().save(new_content)


@nanoclaw_tool
def read_user_profile(section: str = "") -> str:
    """
    读取用户的长期记忆档案。

    在调用 save_user_profile 或 update_user_profile 工具更新记忆之前，
    建议先调用此工具获取当前已有记录，避免重复记录或冲突。

    Args:
        section: 可选，指定要读取的章节名称。留空则返回完整档案。
    """
    return _get_profile_manager().read(section)


@nanoclaw_tool
def update_user_profile(section: str, content: str) -> str:
    """
    增量更新用户长期记忆档案中的特定章节，不影响其他章节。

    当你发现用户的偏好发生改变，且只需要更新某个特定方面时，
    使用此工具替代 save_user_profile（后者会处理整个档案）。

    Args:
        section: 章节名称
        content: 该章节的新内容（Markdown 格式，不要包含章节标题）。
                 例如: "- 语言：中文\\n- 风格：简洁直接"
    """
    return _get_profile_manager().update_section(section, content)



@nanoclaw_tool
def get_current_time() -> str:
    """
    获取当前的系统时间和日期。
    当用户询问“现在几点”、“今天星期几”、“今天几号”等与当前时间相关的问题时，调用此工具。
    """
    now = datetime.now()
    return f"当前本地系统时间是: {now.strftime('%Y-%m-%d %H:%M:%S')}"


@nanoclaw_tool
def calculator(expression: str) -> str:
    """
    一个简单的数学计算器。
    用于计算基础的数学表达式，例如: '3 * 5' 或 '100 / 4'。
    注意：参数 expression 必须是一个合法的 Python 数学表达式字符串。
    支持: +, -, *, /, //, %, **
    """
    from nanoclaw.core.safe_eval import safe_eval

    try:
        result = safe_eval(expression)
        return f"表达式 '{expression}' 的计算结果是: {result}"
    except Exception as e:
        return f"计算出错，请检查表达式格式。错误信息: {str(e)}"


@nanoclaw_tool
def schedule_task(target_time: str, description: str, repeat: str = None, repeat_count: int = None) -> str:
    """
    为一个未来的任务设定闹钟或提醒。
    参数 target_time 必须是严格的格式："YYYY-MM-DD HH:MM:SS"（请先调用 get_current_time 获取当前时间，并在其基础上推算）。
    参数 description 是需要执行的动作或要说的话。
    
    【高级循环功能】：
    - repeat (可选): 设置重复频率。可选值为 "hourly", "daily", "weekly"。如果不重复请留空。
    - repeat_count (可选): 结合 repeat 使用，表示一共需要触发几次。
    
    【案例教学】：
    1. 用户说："以后每天8点提醒我喝牛奶" -> repeat="daily", repeat_count=None (无限循环)
    2. 用户说："接下来的3天，每天提醒我吃药" -> repeat="daily", repeat_count=3 (有限循环)
    3. 用户说："明早8点叫我起床" -> repeat=None, repeat_count=None (单次任务)

    【时间歧义严格确认协议 (AM/PM Ambiguity CRITICAL)】：
    当用户说出的时间存在 12 小时制的模糊性时（例如：只说了“7点”，没明确说早上还是晚上）：
    1. 你必须向用户提问确认是上午还是下午。
    2. 【死命令】：在用户明确回复“上午”或“下午”（或改为24小时制）之前，本工具处于【绝对锁定状态】！
    3. 就算用户发省略号（如“。。”）、发脾气、或者说无关内容，你也【绝对禁止】为了讨好用户而自行猜测时间！
    4. 严禁出现“抱歉多问了”、“默认早上”这种妥协行为。
    5. 如果用户不明确回答，你必须坚定地回复：“抱歉，没有明确上下午，我无权为您设置闹钟。请明确告知时间段。”并立即中止工具调用。
    """
    try:
        datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "设定失败：时间格式错误，必须严格遵循 'YYYY-MM-DD HH:MM:SS' 格式。"

    with tasks_lock:
        tasks = []
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        tasks = json.loads(content)
            except Exception as e:
                return f"设定失败：读取任务队列异常 {str(e)}"

        new_task = {
            "id": str(uuid.uuid4())[:8],
            "target_time": target_time,
            "description": description,
            "repeat": repeat,
            "repeat_count": repeat_count
        }
        tasks.append(new_task)

        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"设定失败：写入任务队列异常 {str(e)}"

    msg = f" 任务已成功加入队列。首发时间：{target_time} | 任务：{description}"
    if repeat:
        msg += f" | 循环模式：{repeat} (共 {repeat_count if repeat_count else '无限'} 次)"
    return msg


@nanoclaw_tool
def list_scheduled_tasks() -> str:
    """
    查看当前所有待处理的定时任务列表。
    当用户询问“我都有哪些任务”、“查一下闹钟”、“刚才定了什么”时调用此工具。
    """
    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "当前没有任何定时任务。"
        
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return "任务列表为空。"
                tasks = json.loads(content)
            
            if not tasks:
                return "当前没有任何定时任务。"
            
            tasks.sort(key=lambda x: x['target_time'])
            
            res = " 当前待执行任务列表：\n"
            for t in tasks:
                res += f"- [ID: {t['id']}] 时间: {t['target_time']} | 任务: {t['description']}\n"
            return res
        except Exception as e:
            return f"查询失败：{str(e)}"
    

@nanoclaw_tool
def delete_scheduled_task(task_id: str) -> str:
    """
    根据任务 ID 取消或删除一个定时任务。
    
    【强制性风险控制协议 (CRITICAL)】：
    删除操作具有不可逆性。
    1. 只要匹配到符合描述的任务数量 > 1。
    2. 无论用户语气多么确定，只要他没提供具体的任务 ID。
    
    【你必须执行的动作】：
    【禁止】在单次回复中针对同一个模糊描述发起多个删除工具调用。
    你必须先列出所有匹配的任务（1. 2. 3.），并询问用户：
    “发现了多个符合条件的提醒（列出列表），为了安全起见，请问是要全部删除，还是只删除其中几个？”
    必须要用户明确给出编号或者说确定全部删除，才能调用此工具！！
    严禁自作主张执行批量删除。
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "删除失败：任务列表文件不存在。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            new_tasks = [t for t in tasks if t['id'] != task_id]
            
            if len(new_tasks) == len(tasks):
                return f"删除失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(new_tasks, f, ensure_ascii=False, indent=2)
            
            return f" 任务 [ID: {task_id}] 已成功取消。"
        except Exception as e:
            return f"操作异常：{str(e)}"
    

@nanoclaw_tool
def modify_scheduled_task(task_id: str, new_time: str = None, new_description: str = None) -> str:
    """
    修改现有定时任务的时间或内容。
    
    【强制性风险控制协议 (CRITICAL)】：
    1. 只要用户通过“模糊描述”（如：那个5天的任务、洗澡的任务）来要求修改，而没有直接提供 ID。
    2. 无论用户的话语看起来是单数还是复数（如：“把5天的任务全改了”）。
    3. 只要系统中匹配到的任务数量 > 1。
    
    【你必须执行的动作】：
    禁止直接调用本工具！你必须向用户展示匹配到的所有任务列表，并强制询问：
    “我发现有 [N] 个任务符合描述（列出列表），请问你是要【全部修改】，还是修改其中【某几个】？（请告诉我编号或确认全部）”
    
    必须在用户回复“全部”或者指定了具体编号后，你才能继续操作！修改任务并非小事,这是为了安全！！
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "修改失败：任务列表为空。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            found = False
            for t in tasks:
                if t['id'] == task_id:
                    if new_time:
                        datetime.strptime(new_time, "%Y-%m-%d %H:%M:%S")
                        t['target_time'] = new_time
                    if new_description:
                        t['description'] = new_description
                    found = True
                    break
            
            if not found:
                return f"修改失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
                
            return f" 任务 [ID: {task_id}] 已成功更新。"
        except ValueError:
            return "修改失败：时间格式错误。"
        except Exception as e:
            return f"操作异常：{str(e)}"


@nanoclaw_tool
def spawn_subagent(description: str, timeout: int = 120) -> str:
    """在后台启动一个子代理来独立执行任务。子代理可以使用只读工具（读文件、搜代码、查网页）来分析。

    使用场景：
    - 需要同时调研多个方向
    - 长时间分析（如审阅整个项目结构）
    - 可以并行执行的独立子任务

    子代理会在后台异步执行（最多 5 个并发），结果在后续回合自动收集。

    Args:
        description: 子代理的任务描述，越清晰越好
        timeout: 最大执行时间（秒），默认 120，最大 600
    """
    from ..subagent import get_subagent_manager
    mgr = get_subagent_manager()
    safe_timeout = min(float(timeout), 600.0)
    task_id = mgr.spawn(description, safe_timeout)
    return (
        f"✅ 子代理已启动\n"
        f"  ID: {task_id[:8]}\n"
        f"  任务: {description}\n"
        f"  超时: {timeout}s\n"
        f"  状态: PENDING（排队中，最多同时运行 5 个）"
    )


BUILTIN_TOOLS = [
    get_current_time,
    calculator,
    save_user_profile,
    read_user_profile,
    update_user_profile,
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell,
    get_system_model_info,
    schedule_task,
    list_scheduled_tasks,
    delete_scheduled_task,
    modify_scheduled_task,
    web_search,
    spawn_subagent,
]
