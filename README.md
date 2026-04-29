<div align="center">

# NanoClaw

**A transparent, controllable agent runtime for real engineering tasks**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-blue.svg)](https://langchain-ai.github.io/langgraph/)
[![LangChain](https://img.shields.io/badge/LangChain-1.x-blue.svg)](https://python.langchain.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-Passing-brightgreen.svg)](tests/)
[![GitHub](https://img.shields.io/badge/GitHub-@kimwest1996-black.svg?logo=github)](https://github.com/kimwest1996)

[Quick Start](#quick-start) · [Why NanoClaw](#why-nanoclaw) · [Architecture](#architecture) · [Evaluation](#evaluation) · [Docs](#docs)

</div>

---

## Why NanoClaw

NanoClaw is an agent runtime for people who care about what happens **after** the model decides to do something.

Most agent demos stop at "the model can call tools". Real engineering work starts after that:

- What can the tool touch?
- How do you audit the decision?
- How do you recover from bad executions?
- How do you keep long-running tasks from turning into opaque messes?
- How do you evaluate changes beyond a single happy-path demo?

NanoClaw is built around those questions.

## Positioning

NanoClaw is **inspired by OpenClaw**, but it is not intended to be a brand clone or a line-by-line fork in spirit.

The direction is different in a few important ways:

- **Smaller core, clearer control plane**  
  Start with a single-agent runtime and make safety, observability, and evaluation first-class before scaling complexity.

- **Tool execution as a software engineering problem**  
  File I/O, shell execution, scheduling, memory, and skill loading are treated as bounded runtime concerns, not just prompt decorations.

- **Evaluation built into the project story**  
  NanoClaw is moving toward measurable agent quality with repeatable evaluation suites, not just interactive demos.

- **Designed to evolve**  
  The current CLI runtime is the baseline. FastAPI service mode, multimodal workflows, richer MCP lifecycle management, and stronger skill governance are planned as deliberate extensions.

If OpenClaw is a major source of inspiration, NanoClaw is the attempt to turn that inspiration into a more compact, inspectable, and extensible engineering base.

## What It Does Today

NanoClaw currently provides:

- **LangGraph agent loop** with `ToolNode`-based tool execution
- **dual-layer memory**
  - long-term user profile in Markdown
  - short-term conversational summary in SQLite-backed state
- **two-phase skill execution**
  - `help` before `run`
  - dynamic skills loaded from `workspace/office/skills`
- **sandboxed engineering tools**
  - file read/write inside a restricted workspace
  - shell execution with path and command guardrails
- **heartbeat-driven task scheduling**
  - one-off and recurring tasks
  - persistent task queue
- **structured audit logging**
  - `llm_input`
  - `tool_call`
  - `tool_result`
  - `ai_message`
  - `system_action`
- **terminal monitor UI**
  - follow agent activity in real time

This means NanoClaw is already more than a chat shell. It is a runnable agent harness with memory, tools, tasks, logs, and tests.

## Core Design Principles

### 1. Transparent over magical

The model is allowed to decide, but the system must still expose what happened.

### 2. Bounded autonomy

Tool use is powerful only when boundaries are explicit. Workspace restrictions, shell limits, and staged skill execution are part of the runtime, not optional extras.

### 3. Single-agent first

Before adding multi-agent orchestration, NanoClaw focuses on making one agent reliable, inspectable, and testable.

### 4. Evaluation matters

A good agent is not just "it worked once in the terminal". NanoClaw is evolving toward repeatable evals and measurable regression detection.

## Architecture

At a high level, the runtime looks like this:

1. User input enters the LangGraph state machine
2. Memory context is trimmed and summarized when needed
3. The model decides whether to answer directly or call tools
4. Builtin tools and dynamic skills execute inside controlled boundaries
5. Results are written back into the state
6. Audit logs record the reasoning-visible side effects
7. Heartbeat workers trigger scheduled tasks independently

### Main subsystems

| Subsystem | Purpose |
|------|------|
| `nanoclaw/core/agent.py` | LangGraph agent loop and orchestration |
| `nanoclaw/core/context.py` | context trimming and state handling |
| `nanoclaw/core/provider.py` | model/provider abstraction |
| `nanoclaw/core/skill_loader.py` | dynamic skill discovery and two-phase invocation |
| `nanoclaw/core/tools/builtins.py` | builtin tools for time, tasks, profile, and system info |
| `nanoclaw/core/tools/sandbox_tools.py` | restricted file and shell execution |
| `nanoclaw/core/heartbeat.py` | recurring task trigger loop |
| `nanoclaw/core/logger.py` | JSONL audit event writer |
| `entry/main.py` | interactive runtime entrypoint |
| `entry/monitor.py` | live terminal monitor |

## Quick Start

### Install

```bash
git clone https://github.com/kimwest1996/NanoClaw.git
cd NanoClaw
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Configure

```bash
nanoclaw config
```

Or create `.env` manually:

```bash
cp .env.example .env
```

Typical configuration:

```bash
DEFAULT_PROVIDER=aliyun
DEFAULT_MODEL=glm-5
OPENAI_API_KEY=sk-your-api-key
OPENAI_API_BASE=https://coding.dashscope.aliyuncs.com/v1
```

### Run

```bash
nanoclaw run
```

### Monitor

In another terminal:

```bash
nanoclaw monitor
```

## Example Capabilities

NanoClaw is currently strongest on execution-oriented tasks such as:

- asking the current time
- simple and multi-step calculations
- writing, reading, and listing files under `workspace/office`
- running bounded shell commands
- creating and modifying scheduled tasks
- updating long-term user preferences
- executing skill workflows through staged `help -> run`

Example prompts:

```text
现在几点了？
帮我算一下 25 * 48
看看 office 里有什么文件
读取 readme.txt
每天早上 8 点提醒我喝水
帮我检查一下 weather skill 的说明
```

## Evaluation

NanoClaw includes an evaluation direction, not just a demo direction.

The repository already contains an `evals/` workspace and baseline evaluation notes. The intended workflow is:

```bash
python evals/run_eval.py --suite core
python evals/run_eval.py --suite agent --provider aliyun --model glm-5
```

The point of this layer is to compare:

- success rate
- required tool usage coverage
- forbidden tool violations
- invalid tool call rate
- average tool call depth
- category-level success

That is a deliberate project choice: NanoClaw should eventually be something you can tune with evidence, not vibes.

## What Comes Next

NanoClaw's planned improvement direction is centered on software-engineering depth rather than feature inflation.

Priority themes:

- **human-in-the-loop approvals** for risky actions
- **centralized tool permission policy**
- **better runtime reliability**
  - retries
  - task states
  - failure recovery
- **stronger observability**
  - richer trace fields
  - better monitor surface
- **MCP lifecycle management**
- **FastAPI service mode**
- **multimodal input support**
- **stronger skill registry / versioning / governance**

This roadmap matters because the project is meant to become more than a CLI demo. The long-term target is a controllable, serviceable agent runtime.

## Docs

- [Improvement Directions](docs/improvement-directions.md)
- [Evaluation Baseline](docs/evaluation-baseline.md)

## Tests

Run the full suite:

```bash
python3 -m pytest tests/ -v
```

Or with the repository's current local workflow:

```bash
UV_CACHE_DIR=/tmp/uv-cache-align-20260429 uv run --with-requirements requirements.txt --with pytest pytest -q
```

The current baseline passes the full suite, which is important: NanoClaw is being treated as an evolving engineering runtime, not a throwaway prototype.

## Repository Shape

```text
NanoClaw/
├── nanoclaw/
│   ├── core/
│   └── ...
├── entry/
├── tests/
├── docs/
├── evals/
├── workspace/
└── README.md
```

## Credits

NanoClaw is developed independently, but openly acknowledges inspiration from:

- [OpenClaw](https://github.com/openclaw/openclaw)
- the broader ecosystem around controllable coding/terminal agents

The project goal is not to mimic branding. The goal is to absorb good ideas, harden the runtime, and extend it in a direction that is more evaluation-driven and engineering-focused.

## License

MIT License
