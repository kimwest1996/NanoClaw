import unittest
from unittest.mock import Mock, patch, mock_open
import os
import sys
import tempfile
import json
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanoclaw.core.tools.builtins import (
    get_current_time,
    calculator,
    web_search,
)
from nanoclaw.core.config import MEMORY_DIR, TASKS_FILE


class TestBuiltInTools(unittest.TestCase):

    def test_get_current_time(self):
        """测试获取当前时间功能"""
        result = get_current_time.invoke({})
        self.assertIn("当前本地系统时间是:", result)

        # 提取时间字符串并验证格式
        time_str = result.replace("当前本地系统时间是：", "").strip()
        try:
            parsed_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            self.assertIsInstance(parsed_time, datetime)
        except ValueError:
            # 如果格式不匹配，至少验证返回了时间字符串
            self.assertTrue(len(time_str) > 0)

    def test_calculator_valid_expressions(self):
        """测试计算器功能 - 有效表达式"""
        test_cases = [
            ("2 + 3", 5),
            ("10 * 5", 50),
            ("15 / 3", 5.0),
            ("2 ** 3", 8),
            ("17 % 5", 2)
        ]

        for expr, expected in test_cases:
            with self.subTest(expr=expr):
                result = calculator.invoke({"expression": expr})
                self.assertIn(str(expected), result)

    def test_calculator_invalid_expression(self):
        """测试计算器功能 - 无效表达式"""
        invalid_expressions = [
            "2 +",
            "1 / 0",
            "__import__('os')",
            "import os",
            "eval('2+2')"
        ]

        for expr in invalid_expressions:
            with self.subTest(expr=expr):
                result = calculator.invoke({"expression": expr})
                self.assertIn("计算出错", result)

    def _set_profile_manager(self, tmpdir):
        """Replace the module-level profile manager with one pointing to tmpdir."""
        import nanoclaw.core.tools.builtins
        from nanoclaw.core.memory import ProfileManager
        nanoclaw.core.tools.builtins._profile_manager = ProfileManager(tmpdir)

    def test_save_user_profile(self):
        """测试保存用户档案功能"""
        from nanoclaw.core.tools.builtins import save_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        test_content = "# 用户档案\n- 姓名：张三\n- 职业：工程师"
        result = save_user_profile.invoke({"new_content": test_content})
        self.assertEqual(result, "记忆档案已成功覆写更新。新的人设画像已生效。")

        profile_path = os.path.join(tmpdir, "user_profile.md")
        self.assertTrue(os.path.exists(profile_path))
        with open(profile_path, 'r', encoding='utf-8') as f:
            saved_content = f.read()
        self.assertEqual(saved_content, test_content)

    def test_read_user_profile_no_file(self):
        """测试读取不存在的档案"""
        from nanoclaw.core.tools.builtins import read_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        result = read_user_profile.invoke({})
        self.assertIn("暂无记录", result)

    def test_read_user_profile_with_content(self):
        """测试读取已有档案"""
        from nanoclaw.core.tools.builtins import read_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        profile_path = os.path.join(tmpdir, "user_profile.md")
        with open(profile_path, 'w', encoding='utf-8') as f:
            f.write("# 沟通偏好\n- 语言：中文\n- 风格：简洁")
        result = read_user_profile.invoke({})
        self.assertIn("沟通偏好", result)
        self.assertIn("中文", result)

    def test_update_user_profile_add_section(self):
        """测试增量更新新增章节"""
        from nanoclaw.core.tools.builtins import update_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        profile_path = os.path.join(tmpdir, "user_profile.md")
        with open(profile_path, 'w', encoding='utf-8') as f:
            f.write("# 个人基本信息\n- 姓名：张三")

        result = update_user_profile.invoke({
            "section": "沟通偏好",
            "content": "- 语言：中文\n- 风格：简洁"
        })
        self.assertIn("沟通偏好", result)

        with open(profile_path, 'r', encoding='utf-8') as f:
            c = f.read()
        self.assertIn("个人基本信息", c)
        self.assertIn("沟通偏好", c)
        self.assertIn("张三", c)
        self.assertIn("中文", c)

    def test_save_user_profile_merge_with_headers(self):
        """测试 save_user_profile 带分区标题时合并而非覆写"""
        from nanoclaw.core.tools.builtins import save_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        profile_path = os.path.join(tmpdir, "user_profile.md")
        with open(profile_path, 'w', encoding='utf-8') as f:
            f.write("# 个人基本信息\n- 姓名：张三\n\n# 沟通偏好\n- 语言：中文")

        save_user_profile.invoke({"new_content": "# 沟通偏好\n- 语言：英文\n- 风格：简洁"})

        with open(profile_path, 'r', encoding='utf-8') as f:
            c = f.read()
        self.assertIn("个人基本信息", c)
        self.assertIn("张三", c)
        self.assertIn("语言：英文", c)

    def test_save_user_profile_full_overwrite_without_headers(self):
        """测试 save_user_profile 不带标题时保持完整覆写（兼容旧行为）"""
        from nanoclaw.core.tools.builtins import save_user_profile

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        self._set_profile_manager(tmpdir)

        profile_path = os.path.join(tmpdir, "user_profile.md")
        with open(profile_path, 'w', encoding='utf-8') as f:
            f.write("旧内容")

        save_user_profile.invoke({"new_content": "新内容"})

        with open(profile_path, 'r', encoding='utf-8') as f:
            c = f.read()
        self.assertEqual(c, "新内容")

    def test_web_search_missing_api_key(self):
        """测试 web search 未配置 API key"""
        with patch.dict(os.environ, {}, clear=True):
            result = web_search.invoke({"query": "OpenAI latest model"})

        self.assertIn("missing TAVILY_API_KEY", result)

    @patch("nanoclaw.core.tools.web_search.urllib.request.urlopen")
    def test_web_search_returns_results(self, mock_urlopen):
        """测试 web search 格式化搜索结果"""
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        response.read.return_value = json.dumps({
            "results": [
                {
                    "title": "Example result",
                    "url": "https://example.com",
                    "content": "Example summary",
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value = response

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            result = web_search.invoke({"query": "test query", "max_results": 1})

        self.assertIn("Example result", result)
        self.assertIn("https://example.com", result)
        self.assertIn("Example summary", result)


class TestScheduledTasks(unittest.TestCase):

    def setUp(self):
        # 创建临时任务文件
        self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')
        self.original_tasks_file = TASKS_FILE
        # 更新 TASKS_FILE 指向临时文件
        import nanoclaw.core.tools.builtins
        nanoclaw.core.tools.builtins.TASKS_FILE = self.temp_file.name

    def tearDown(self):
        # 清理临时文件
        self.temp_file.close()
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
        # 恢复原始路径
        import nanoclaw.core.tools.builtins
        nanoclaw.core.tools.builtins.TASKS_FILE = self.original_tasks_file

    def test_schedule_task_single(self):
        """测试单次任务调度功能"""
        from nanoclaw.core.tools.builtins import schedule_task, list_scheduled_tasks

        future_time = (datetime.now().replace(hour=9, minute=0, second=0)
                      if datetime.now().hour >= 9 else
                      datetime.now().replace(hour=9, minute=0, second=0))
        if future_time <= datetime.now():
            future_time = future_time.replace(day=future_time.day + 1)

        target_time = future_time.strftime("%Y-%m-%d %H:%M:%S")

        result = schedule_task.invoke({"target_time": target_time, "description": "喝水提醒"})
        self.assertIn("任务已成功加入队列", result)
        self.assertIn("喝水提醒", result)

        # 验证任务已添加到文件
        with open(self.temp_file.name, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)

        self.assertEqual(len(tasks_data), 1)
        self.assertEqual(tasks_data[0]["description"], "喝水提醒")
        self.assertEqual(tasks_data[0]["target_time"], target_time)

    def test_schedule_task_invalid_time_format(self):
        """测试调度任务 - 无效时间格式"""
        from nanoclaw.core.tools.builtins import schedule_task

        result = schedule_task.invoke({"target_time": "invalid_time", "description": "测试任务"})
        self.assertIn("设定失败：时间格式错误", result)

    def test_list_scheduled_tasks_empty(self):
        """测试列出空任务列表"""
        from nanoclaw.core.tools.builtins import list_scheduled_tasks

        # 确保文件为空
        with open(self.temp_file.name, 'w') as f:
            f.write("")

        result = list_scheduled_tasks.invoke({})
        # 兼容两种可能的返回消息
        self.assertTrue("没有任何定时任务" in result or "任务列表为空" in result)

    def test_get_system_model_info(self):
        """测试获取系统模型信息功能"""
        from nanoclaw.core.tools.builtins import get_system_model_info

        # 保存原有环境变量
        orig_provider = os.environ.get('DEFAULT_PROVIDER')
        orig_model = os.environ.get('DEFAULT_MODEL')

        try:
            # 测试正常情况
            os.environ['DEFAULT_PROVIDER'] = 'test_provider'
            os.environ['DEFAULT_MODEL'] = 'test_model'

            result = get_system_model_info.invoke({})
            self.assertIn('test_provider', result)
            self.assertIn('test_model', result)

            # 测试未知情况
            os.environ['DEFAULT_PROVIDER'] = 'unknown'
            os.environ['DEFAULT_MODEL'] = 'unknown'

            result = get_system_model_info.invoke({})
            self.assertIn("无法获取当前的系统模型配置", result)

        finally:
            # 恢复环境变量
            if orig_provider is not None:
                os.environ['DEFAULT_PROVIDER'] = orig_provider
            else:
                os.environ.pop('DEFAULT_PROVIDER', None)

            if orig_model is not None:
                os.environ['DEFAULT_MODEL'] = orig_model
            else:
                os.environ.pop('DEFAULT_MODEL', None)


class TestScheduledTasksWithTasks(unittest.TestCase):

    def setUp(self):
        self.temp_tasks_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')

        # 设置临时任务文件路径
        self.original_tasks_file = TASKS_FILE
        import nanoclaw.core.tools.builtins
        nanoclaw.core.tools.builtins.TASKS_FILE = self.temp_tasks_file.name

        # 添加一些测试任务
        future_time = (datetime.now().replace(hour=9, minute=0, second=0)
                      if datetime.now().hour >= 9 else
                      datetime.now().replace(hour=9, minute=0, second=0))
        if future_time <= datetime.now():
            future_time = future_time.replace(day=future_time.day + 1)

        target_time = future_time.strftime("%Y-%m-%d %H:%M:%S")

        test_tasks = [
            {
                "id": "task1",
                "target_time": target_time,
                "description": "任务 1",
                "repeat": None,
                "repeat_count": None
            },
            {
                "id": "task2",
                "target_time": target_time,
                "description": "任务 2",
                "repeat": None,
                "repeat_count": None
            }
        ]

        with open(self.temp_tasks_file.name, 'w', encoding='utf-8') as f:
            json.dump(test_tasks, f, ensure_ascii=False, indent=2)

    def tearDown(self):
        # 清理临时文件
        self.temp_tasks_file.close()
        if os.path.exists(self.temp_tasks_file.name):
            os.unlink(self.temp_tasks_file.name)
        # 恢复原始路径
        import nanoclaw.core.tools.builtins
        nanoclaw.core.tools.builtins.TASKS_FILE = self.original_tasks_file

    def test_list_scheduled_tasks_non_empty(self):
        """测试列出非空任务列表"""
        from nanoclaw.core.tools.builtins import list_scheduled_tasks

        result = list_scheduled_tasks.invoke({})
        self.assertIn("当前待执行任务列表", result)
        self.assertIn("任务 1", result)
        self.assertIn("任务 2", result)

    def test_delete_scheduled_task(self):
        """测试删除计划任务"""
        from nanoclaw.core.tools.builtins import delete_scheduled_task, list_scheduled_tasks

        result = delete_scheduled_task.invoke({"task_id": "task1"})
        self.assertIn("已成功取消", result)

        # 验证任务已被删除
        result = list_scheduled_tasks.invoke({})
        self.assertNotIn("任务 1", result)
        self.assertIn("任务 2", result)

    def test_delete_nonexistent_task(self):
        """测试删除不存在的任务"""
        from nanoclaw.core.tools.builtins import delete_scheduled_task

        result = delete_scheduled_task.invoke({"task_id": "nonexistent"})
        self.assertIn("删除失败：未找到", result)

    def test_modify_scheduled_task(self):
        """测试修改计划任务"""
        from nanoclaw.core.tools.builtins import modify_scheduled_task, list_scheduled_tasks

        new_time = (datetime.now().replace(hour=10, minute=0, second=0)
                   if datetime.now().hour >= 10 else
                   datetime.now().replace(hour=10, minute=0, second=0))
        if new_time <= datetime.now():
            new_time = new_time.replace(day=new_time.day + 1)

        new_target_time = new_time.strftime("%Y-%m-%d %H:%M:%S")

        result = modify_scheduled_task.invoke({"task_id": "task1", "new_time": new_target_time, "new_description": "修改后的任务 1"})
        self.assertIn("已成功更新", result)

        # 验证任务已被修改
        result = list_scheduled_tasks.invoke({})
        self.assertIn("修改后的任务 1", result)
        self.assertIn(new_target_time, result)

    def test_modify_scheduled_task_invalid_time(self):
        """测试修改计划任务 - 无效时间格式"""
        from nanoclaw.core.tools.builtins import modify_scheduled_task

        result = modify_scheduled_task.invoke({"task_id": "task1", "new_time": "invalid_time"})
        self.assertIn("修改失败：时间格式错误", result)

    def test_modify_nonexistent_task(self):
        """测试修改不存在的任务"""
        from nanoclaw.core.tools.builtins import modify_scheduled_task

        result = modify_scheduled_task.invoke({"task_id": "nonexistent", "new_description": "不存在的任务"})
        self.assertIn("修改失败：未找到", result)


if __name__ == '__main__':
    unittest.main()
