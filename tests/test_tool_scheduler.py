import threading
import time

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from nanoclaw.core.tool_scheduler import SafeToolNode


class EmptyArgs(BaseModel):
    pass


class ModeArgs(BaseModel):
    mode: str = Field(description="help or run")


def _call(name, call_id, args=None):
    return {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}


def _invoke(node, calls):
    ai = AIMessage(content="", tool_calls=calls)
    return node.invoke({"messages": [ai]}, {"configurable": {"thread_id": "test"}})["messages"]


def test_read_only_tools_run_concurrently_and_preserve_order():
    def make_tool(name):
        def run():
            time.sleep(0.2)
            return name
        return StructuredTool.from_function(func=run, name=name, description=f"{name} tool", args_schema=EmptyArgs)

    node = SafeToolNode([make_tool("get_current_time"), make_tool("calculator")])
    started = time.perf_counter()
    messages = _invoke(node, [_call("get_current_time", "1"), _call("calculator", "2")])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.35
    assert [m.tool_call_id for m in messages] == ["1", "2"]
    assert [m.content for m in messages] == ["get_current_time", "calculator"]


def test_side_effect_tools_run_serially_in_order():
    events = []
    lock = threading.Lock()

    def make_tool(name):
        def run(value: str = ""):
            with lock:
                events.append(f"{name}:start")
            time.sleep(0.05)
            with lock:
                events.append(f"{name}:end")
            return name
        return StructuredTool.from_function(func=run, name=name, description=f"{name} tool")

    node = SafeToolNode([make_tool("save_user_profile"), make_tool("write_office_file")])
    messages = _invoke(node, [_call("save_user_profile", "1"), _call("write_office_file", "2")])

    assert [m.tool_call_id for m in messages] == ["1", "2"]
    assert events == [
        "save_user_profile:start",
        "save_user_profile:end",
        "write_office_file:start",
        "write_office_file:end",
    ]


def test_mixed_batch_uses_read_barrier_before_and_after_write():
    events = []
    lock = threading.Lock()

    def record(event):
        with lock:
            events.append(event)

    def read_a():
        record("read_a:start")
        time.sleep(0.05)
        record("read_a:end")
        return "a"

    def read_b():
        record("read_b:start")
        time.sleep(0.05)
        record("read_b:end")
        return "b"

    def write():
        record("write:start")
        time.sleep(0.02)
        record("write:end")
        return "w"

    def read_c():
        record("read_c:start")
        record("read_c:end")
        return "c"

    tools = [
        StructuredTool.from_function(func=read_a, name="get_current_time", description="read a", args_schema=EmptyArgs),
        StructuredTool.from_function(func=read_b, name="calculator", description="read b", args_schema=EmptyArgs),
        StructuredTool.from_function(func=write, name="write_office_file", description="write", args_schema=EmptyArgs),
        StructuredTool.from_function(func=read_c, name="list_scheduled_tasks", description="read c", args_schema=EmptyArgs),
    ]
    node = SafeToolNode(tools)
    messages = _invoke(node, [
        _call("get_current_time", "1"),
        _call("calculator", "2"),
        _call("write_office_file", "3"),
        _call("list_scheduled_tasks", "4"),
    ])

    assert [m.tool_call_id for m in messages] == ["1", "2", "3", "4"]
    assert events.index("write:start") > events.index("read_a:end")
    assert events.index("write:start") > events.index("read_b:end")
    assert events.index("read_c:start") > events.index("write:end")


def test_dynamic_skill_help_is_read_only_and_run_is_office_side_effect():
    def skill(mode: str):
        return mode

    dynamic = StructuredTool.from_function(func=skill, name="demo_skill", description="dynamic", args_schema=ModeArgs)
    node = SafeToolNode([dynamic])

    help_policy = node.classify_tool_call(_call("demo_skill", "1", {"mode": "help"}))
    run_policy = node.classify_tool_call(_call("demo_skill", "2", {"mode": "run"}))

    assert help_policy.kind == "read_only"
    assert run_policy.kind == "side_effect"
    assert run_policy.resource == "office"


def test_unknown_tool_returns_error_message():
    node = SafeToolNode([])
    messages = _invoke(node, [_call("missing_tool", "1")])

    assert len(messages) == 1
    assert messages[0].status == "error"
    assert messages[0].tool_call_id == "1"
    assert "Unknown tool" in messages[0].content


def test_custom_tool_defaults_serial_but_metadata_can_mark_read_only():
    def custom_a():
        return "a"

    def custom_b():
        return "b"

    serial_tool = StructuredTool.from_function(func=custom_a, name="custom_a", description="custom", args_schema=EmptyArgs)
    read_tool = StructuredTool.from_function(func=custom_b, name="custom_b", description="custom", args_schema=EmptyArgs)
    read_tool.metadata = {"nanoclaw_execution": "read_only"}
    node = SafeToolNode([serial_tool, read_tool])

    assert node.classify_tool_call(_call("custom_a", "1")).kind == "side_effect"
    assert node.classify_tool_call(_call("custom_b", "2")).kind == "read_only"


def test_tool_exception_is_wrapped_as_error_message():
    @tool
    def broken_tool() -> str:
        """Broken test tool."""
        raise RuntimeError("boom")

    node = SafeToolNode([broken_tool])
    messages = _invoke(node, [_call("broken_tool", "1")])

    assert len(messages) == 1
    assert messages[0].status == "error"
    assert "boom" in messages[0].content
