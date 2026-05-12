import os

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.dirname(CORE_DIR)
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

WORKSPACE_DIR = os.getenv("NANOCLAW_WORKSPACE", os.path.join(PROJECT_ROOT, "workspace"))


DB_PATH = os.path.join(WORKSPACE_DIR, "state.sqlite3")     # 状态机：潜意识与短期记忆
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")         # 显性记忆：Markdown 画像
PERSONAS_DIR = os.path.join(WORKSPACE_DIR, "personas")     # 人设区：系统 Prompt
SCRIPTS_DIR = os.path.join(WORKSPACE_DIR, "scripts")       # 脚本区：自动化武器库
OFFICE_DIR = os.path.join(WORKSPACE_DIR, "office")         # 沙盒工位 唯一被允许执行文件与shell操作的空间
SKILLS_DIR = os.path.join(OFFICE_DIR, "skills")            # 技能卡槽
TASKS_FILE = os.path.join(WORKSPACE_DIR, "tasks.json")

# Mid-term session memory
SESSIONS_DIR = os.path.join(MEMORY_DIR, "sessions")
SESSION_MAX_FILES = 100       # 最多保留的 session 文件数
SESSION_INJECT_LIMIT = 5      # 注入系统提示的最近 session 数

# Phase 3 — deterministic maintenance
ARCHIVE_DIR = os.path.join(MEMORY_DIR, "archive")     # 冷区归档
HISTORY_DIR = os.path.join(MEMORY_DIR, "history")     # 版本快照
HEAT_SCORES_FILE = os.path.join(MEMORY_DIR, "heat_scores.json")

HEAT_DECAY_DAYS = 30           # 热度衰减半衰期（天）
HEAT_ARCHIVE_THRESHOLD = 0.1   # 低于此值归档
HISTORY_MAX_VERSIONS = 10      # 最多保留的快照数

_workspace_initialized = False


def ensure_workspace() -> None:
    """Create workspace directories if they don't exist. Idempotent."""
    global _workspace_initialized
    if _workspace_initialized:
        return
    for d in [WORKSPACE_DIR, MEMORY_DIR, PERSONAS_DIR, SCRIPTS_DIR, OFFICE_DIR, SKILLS_DIR, SESSIONS_DIR, ARCHIVE_DIR, HISTORY_DIR]:
        os.makedirs(d, exist_ok=True)
    _workspace_initialized = True