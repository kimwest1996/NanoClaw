import unittest
from unittest.mock import patch, mock_open
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanoclaw.core.tools.sandbox_tools import (
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell,
    _get_safe_path
)
from nanoclaw.core.config import OFFICE_DIR


class TestGetSafePath(unittest.TestCase):
    """Tests for _get_safe_path — workspace containment validation."""

    OFFICE_PATCH = "nanoclaw.core.tools.sandbox_tools.OFFICE_DIR"

    # ── accepted ────────────────────────────────────────────────────

    def test_normal_relative_path(self):
        """测试正常相对路径被接受"""
        result = _get_safe_path("subdir/file.txt")
        expected = os.path.abspath(os.path.join(OFFICE_DIR, "subdir/file.txt"))
        self.assertEqual(result, expected)

    def test_empty_relative_path(self):
        """测试空路径返回工位根目录"""
        result = _get_safe_path("")
        self.assertEqual(result, os.path.abspath(OFFICE_DIR))

    # ── rejected ────────────────────────────────────────────────────

    def test_traversal_rejected(self):
        """测试 '../../etc/passwd' 被拒绝"""
        with self.assertRaises(PermissionError):
            _get_safe_path("../../etc/passwd")

    @patch("nanoclaw.core.tools.sandbox_tools.OFFICE_DIR", "/tmp/test_office")
    def test_prefix_bypass_rejected(self):
        """测试 office_evil 前缀绕过被拒绝"""
        with self.assertRaises(PermissionError):
            _get_safe_path("../test_office_evil/steal.sh")

    @patch("nanoclaw.core.tools.sandbox_tools.OFFICE_DIR", "/tmp/test_office")
    def test_unix_absolute_path_rejected(self):
        """测试 Unix 绝对路径 /etc/passwd 被拒绝"""
        with self.assertRaises(PermissionError):
            _get_safe_path("/etc/passwd")

    @patch("nanoclaw.core.tools.sandbox_tools.OFFICE_DIR", "/tmp/test_office")
    def test_deep_traversal_rejected(self):
        """测试深层遍历 ../../../../etc 被拒绝"""
        with self.assertRaises(PermissionError):
            _get_safe_path("../../../../../../etc/passwd")


class TestExecuteOfficeShell(unittest.TestCase):
    """Tests for execute_office_shell denial patterns.

    These tests verify that the regex-based denylist catches common path
    traversal and escape patterns. The shell tool is described as
    "restricted workspace command execution" — not a production sandbox.
    """

    def test_safe_command_passes_denylist(self):
        """测试普通命令通过拒绝列表检查"""
        with patch("nanoclaw.core.tools.sandbox_tools.subprocess.run") as mock_run:
            mock_result = mock_run.return_value
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""

            result = execute_office_shell.invoke({"command": "ls -la"})

            # 命令应该通过拒绝列表检查并执行
            mock_run.assert_called_once_with(
                "ls -la", shell=True, cwd=OFFICE_DIR,
                capture_output=True, encoding='utf-8',
                errors='replace', timeout=60,
            )

    def test_shell_path_traversal_blocked(self):
        """测试 shell 中 '../' 路径遍历被拦截"""
        commands = [
            "cd ../",
            "ls ../../etc",
            "cat ../config.json",
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                result = execute_office_shell.invoke({"command": cmd})
                self.assertIn("❌ 权限拒绝", result)

    def test_shell_unix_absolute_path_blocked(self):
        """测试 shell 中 Unix 绝对路径被拦截"""
        commands = [
            "cat /etc/passwd",
            "ls /root",
            "</etc/passwd cat",
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                result = execute_office_shell.invoke({"command": cmd})
                self.assertIn("❌ 权限拒绝", result)

    def test_shell_home_dir_blocked(self):
        """测试 shell 中 '~' 主目录被拦截"""
        commands = [
            "ls ~",
            "cat ~/.ssh/id_rsa",
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                result = execute_office_shell.invoke({"command": cmd})
                self.assertIn("❌ 权限拒绝", result)

    def test_shell_windows_path_blocked(self):
        """测试 shell 中 Windows 盘符路径被拦截"""
        commands = [
            "dir \\",
            "type C:\\windows\\system32\\config\\sam",
            "dir D:",
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                result = execute_office_shell.invoke({"command": cmd})
                self.assertIn("❌ 权限拒绝", result)

    @patch("nanoclaw.core.tools.sandbox_tools.subprocess.run")
    def test_shell_python_c_bypass_is_not_blocked(self, mock_run):
        """已知限制：python -c 绕过不被当前黑名单拦截（需要 Option B 解决）"""
        mock_result = mock_run.return_value
        mock_result.returncode = 0
        mock_result.stdout = "hello"
        mock_result.stderr = ""

        # python -c 不匹配任何 deny pattern，应该通过
        result = execute_office_shell.invoke({"command": "python -c \"print('hello')\""})
        self.assertNotIn("❌ 权限拒绝", result)
        mock_run.assert_called_once()

    @patch("nanoclaw.core.tools.sandbox_tools.subprocess.run")
    def test_shell_node_e_bypass_is_not_blocked(self, mock_run):
        """已知限制：node -e 绕过不被当前黑名单拦截（需要 Option B 解决）"""
        mock_result = mock_run.return_value
        mock_result.returncode = 0
        mock_result.stdout = "hi"
        mock_result.stderr = ""

        result = execute_office_shell.invoke({"command": "node -e \"console.log('hi')\""})
        self.assertNotIn("❌ 权限拒绝", result)
        mock_run.assert_called_once()

    @patch("nanoclaw.core.tools.sandbox_tools.subprocess.run")
    def test_shell_base64_bypass_is_not_blocked(self, mock_run):
        """已知限制：base64 编码命令绕过不被当前黑名单拦截（需要 Option B 解决）"""
        mock_result = mock_run.return_value
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        result = execute_office_shell.invoke(
            {"command": "echo L2V0Yw== | base64 -d | xargs ls"}
        )
        self.assertNotIn("❌ 权限拒绝", result)
        mock_run.assert_called_once()


class TestOfficeFileTools(unittest.TestCase):
    """Tests for list/read/write office file tools."""

    @patch('nanoclaw.core.tools.sandbox_tools.os.path.exists', return_value=True)
    @patch('nanoclaw.core.tools.sandbox_tools.os.listdir', return_value=['file1.txt', 'subdir'])
    @patch('nanoclaw.core.tools.sandbox_tools.os.path.isdir', side_effect=lambda x: x.endswith('subdir'))
    def test_list_office_files(self, mock_isdir, mock_listdir, mock_exists):
        """测试列出办公文件功能"""
        result = list_office_files.invoke({"sub_dir": ""})
        mock_exists.assert_called_once()
        mock_listdir.assert_called_once()
        self.assertIn("📄 file1.txt", result)
        self.assertIn("📁 subdir", result)

    @patch('nanoclaw.core.tools.sandbox_tools.os.path.exists', return_value=False)
    def test_list_office_files_nonexistent_dir(self, mock_exists):
        """测试列出不存在目录的文件"""
        result = list_office_files.invoke({"sub_dir": "nonexistent"})
        self.assertIn("目录不存在", result)

    @patch('nanoclaw.core.tools.sandbox_tools.os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data="file content")
    def test_read_office_file_success(self, mock_file, mock_exists):
        """测试成功读取办公文件"""
        result = read_office_file.invoke({"filepath": "test.txt"})
        self.assertEqual(result, "file content")
        mock_file.assert_called_once()

    @patch('nanoclaw.core.tools.sandbox_tools.os.path.exists', return_value=False)
    def test_read_office_file_nonexistent(self, mock_exists):
        """测试读取不存在的办公文件"""
        result = read_office_file.invoke({"filepath": "nonexistent.txt"})
        self.assertIn("文件不存在", result)

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    def test_write_office_file_success(self, mock_makedirs, mock_file):
        """测试成功写入办公文件"""
        result = write_office_file.invoke({"filepath": "test.txt", "content": "test content", "mode": "w"})
        self.assertIn("成功以 覆盖/新建 模式写入文件", result)
        mock_file.assert_called_once()
        mock_makedirs.assert_called_once()

    def test_write_office_file_invalid_mode(self):
        """测试写入办公文件 - 无效模式"""
        result = write_office_file.invoke({"filepath": "test.txt", "content": "test content", "mode": "x"})
        self.assertIn("❌ 错误：mode 参数必须是", result)

    @patch("nanoclaw.core.tools.sandbox_tools.subprocess.run")
    def test_execute_office_shell_safe_command(self, mock_run):
        """测试执行安全的 shell 命令（冒烟测试）"""
        mock_result = mock_run.return_value
        mock_result.returncode = 0
        mock_result.stdout = "command output"
        mock_result.stderr = ""

        result = execute_office_shell.invoke({"command": "ls"})
        self.assertIn("ls", result)
        self.assertIn("command output", result)


if __name__ == '__main__':
    unittest.main()
