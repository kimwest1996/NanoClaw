import unittest
import os
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanoclaw.core.context import AgentState
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver


class TestAgent(unittest.TestCase):

    def test_agent_state_initialization(self):
        """测试 AgentState 的初始化"""
        from nanoclaw.core.context import AgentState

        initial_state = AgentState(
            messages=[],
            summary=""
        )

        self.assertEqual(initial_state["messages"], [])
        self.assertEqual(initial_state["summary"], "")

    def test_reasoning_replay_serializer_keeps_reasoning_content(self):
        from nanoclaw.core.agent import _serialize_for_reasoning_replay

        ai_message = AIMessage(
            content="tool call pending",
            tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": "call-1"}],
            additional_kwargs={"reasoning_content": "I should calculate this first."},
        )

        payload = _serialize_for_reasoning_replay(ai_message)

        self.assertEqual(payload["role"], "assistant")
        self.assertEqual(payload["content"], "tool call pending")
        self.assertEqual(payload["reasoning_content"], "I should calculate this first.")
        self.assertEqual(payload["tool_calls"][0]["name"], "calculator")

    @patch('nanoclaw.core.provider.get_provider')
    @patch('nanoclaw.core.skill_loader.load_dynamic_skills')
    @patch('nanoclaw.core.tools.builtins.BUILTIN_TOOLS', [])
    def test_deepseek_agent_replays_reasoning_messages(self, mock_load_skills, mock_get_provider):
        from nanoclaw.core.agent import create_agent_app

        mock_llm_with_tools = Mock()
        mock_llm_with_tools.invoke.return_value = AIMessage(
            content="answer",
            additional_kwargs={"reasoning_content": "reasoning trace"},
        )

        mock_provider = Mock()
        mock_provider.bind_tools.return_value = mock_llm_with_tools
        mock_provider.invoke.return_value = AIMessage(content="summary")
        mock_get_provider.return_value = mock_provider
        mock_load_skills.return_value = []

        app = create_agent_app(
            provider_name="deepseek",
            model_name="deepseek-v4-flash",
            checkpointer=MemorySaver(),
        )

        app.invoke(
            {"messages": [HumanMessage(content="hello")], "summary": ""},
            {"configurable": {"thread_id": "test-thread"}},
        )

        llm_input = mock_llm_with_tools.invoke.call_args.args[0]
        self.assertIsInstance(llm_input[0], dict)
        self.assertEqual(llm_input[0]["role"], "system")
        self.assertEqual(llm_input[1]["role"], "user")
        self.assertEqual(llm_input[1]["content"], "hello")

    @patch('nanoclaw.core.provider.get_provider')
    @patch('nanoclaw.core.skill_loader.load_dynamic_skills')
    @patch('nanoclaw.core.tools.builtins.BUILTIN_TOOLS', [])
    def test_create_agent_app_basic(self, mock_load_skills, mock_get_provider):
        """测试创建基础代理应用（带 Mock）"""
        from nanoclaw.core.agent import create_agent_app

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock 动态技能加载
        mock_load_skills.return_value = []

        try:
            app = create_agent_app(provider_name="openai", model_name="gpt-4o-mini")
            self.assertIsNotNone(app)
        except Exception as e:
            # 即使出现其他错误也记录
            print(f"Unexpected error: {e}")
            raise

    @patch('nanoclaw.core.provider.get_provider')
    @patch('nanoclaw.core.skill_loader.load_dynamic_skills')
    @patch('nanoclaw.core.tools.builtins.BUILTIN_TOOLS', [])
    def test_create_agent_app_with_custom_tools(self, mock_load_skills, mock_get_provider):
        """测试创建带有自定义工具的代理应用（带 Mock）"""
        from nanoclaw.core.agent import create_agent_app
        from langchain_core.tools import tool

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock 动态技能加载
        mock_load_skills.return_value = []

        # 创建一个真正的 mock 工具（使用@tool 装饰器）
        @tool
        def mock_tool(test_param: str) -> str:
            """A mock tool for testing"""
            return f"mock result: {test_param}"

        try:
            app = create_agent_app(
                provider_name="openai",
                model_name="gpt-4o-mini",
                tools=[mock_tool]
            )
            self.assertIsNotNone(app)
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

    @patch('nanoclaw.core.provider.get_provider')
    @patch('nanoclaw.core.skill_loader.load_dynamic_skills')
    @patch('nanoclaw.core.tools.builtins.BUILTIN_TOOLS', [])
    def test_create_agent_app_with_checkpointer(self, mock_load_skills, mock_get_provider):
        """测试创建带有检查点的代理应用（带 Mock）"""
        from nanoclaw.core.agent import create_agent_app

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock 动态技能加载
        mock_load_skills.return_value = []

        memory_saver = MemorySaver()
        try:
            app = create_agent_app(
                provider_name="openai",
                model_name="gpt-4o-mini",
                checkpointer=memory_saver
            )
            self.assertIsNotNone(app)
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise


if __name__ == '__main__':
    unittest.main()
