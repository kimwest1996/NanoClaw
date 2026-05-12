"""
Tests for memory module: ProfileManager + SessionMemoryStore.
"""

import os
import json
import tempfile
import unittest


class TestProfileManager(unittest.TestCase):
    """Tests for ProfileManager (long-term profile storage)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from nanoclaw.core.memory import ProfileManager
        self.mgr = ProfileManager(self.tmpdir)

    def test_read_empty(self):
        result = self.mgr.read()
        self.assertEqual(result, "暂无记录")

    def test_read_section_empty(self):
        result = self.mgr.read("个人基本信息")
        self.assertEqual(result, "暂无记录")

    def test_save_and_read_full(self):
        content = "# 个人基本信息\n- 姓名：张三"
        self.mgr.save(content)
        result = self.mgr.read()
        self.assertIn("张三", result)
        self.assertIn("个人基本信息", result)

    def test_save_and_read_section(self):
        content = "# 个人基本信息\n- 姓名：张三\n\n# 沟通偏好\n- 语言：中文"
        self.mgr.save(content)
        result = self.mgr.read("沟通偏好")
        self.assertIn("语言：中文", result)
        self.assertNotIn("张三", result)

    def test_update_section_adds_new(self):
        content = "# 个人基本信息\n- 姓名：张三"
        self.mgr.save(content)
        self.mgr.update_section("沟通偏好", "- 语言：中文")
        result = self.mgr.read("沟通偏好")
        self.assertIn("语言：中文", result)
        self.assertIn("沟通偏好", result)
        # original section unchanged
        base = self.mgr.read("个人基本信息")
        self.assertIn("张三", base)

    def test_update_section_overwrites(self):
        content = "# 个人基本信息\n- 姓名：张三\n\n# 沟通偏好\n- 语言：中文"
        self.mgr.save(content)
        self.mgr.update_section("沟通偏好", "- 语言：英文")
        result = self.mgr.read("沟通偏好")
        self.assertIn("英文", result)
        self.assertNotIn("中文", result)

    def test_merge_with_headers_keeps_other_sections(self):
        existing = "# 个人基本信息\n- 姓名：张三\n\n# 沟通偏好\n- 语言：中文"
        self.mgr.save(existing)
        incoming = "# 沟通偏好\n- 语言：英文"
        self.mgr.save(incoming)
        result = self.mgr.read()
        self.assertIn("个人基本信息", result)
        self.assertIn("张三", result)
        self.assertIn("英文", result)

    def test_merge_without_headers_full_overwrite(self):
        existing = "# 个人基本信息\n- 姓名：张三"
        self.mgr.save(existing)
        incoming = "纯文本内容"
        self.mgr.save(incoming)
        # 直接读文件验证覆写
        profile_path = os.path.join(self.tmpdir, "user_profile.md")
        with open(profile_path, encoding="utf-8") as f:
            result = f.read().strip()
        self.assertEqual(result, "纯文本内容")

    def test_read_unknown_section(self):
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        result = self.mgr.read("不存在的章节")
        self.assertIn("未找到章节", result)

    def test_save_empty_content(self):
        self.mgr.save("")
        result = self.mgr.read()
        self.assertEqual(result, "暂无记录")


class TestSessionMemoryStore(unittest.TestCase):
    """Tests for SessionMemoryStore (mid-term session summaries)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from nanoclaw.core.memory import SessionMemoryStore
        self.store = SessionMemoryStore(self.tmpdir, max_files=5, inject_limit=3)

    def _count_files(self):
        return len([f for f in os.listdir(self.tmpdir) if f.endswith(".json")])

    def test_store_and_get_recent(self):
        path = self.store.store_session("thread_1", "用户询问了天气", turn_count=5, tool_count=2)
        self.assertTrue(os.path.exists(path))
        sessions = self.store.get_recent_sessions("thread_1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["summary"], "用户询问了天气")
        self.assertEqual(sessions[0]["turn_count"], 5)

    def test_get_recent_other_thread(self):
        self.store.store_session("thread_1", "天气话题", turn_count=1)
        self.store.store_session("thread_2", "其他话题", turn_count=1)
        sessions = self.store.get_recent_sessions("thread_1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["summary"], "天气话题")

    def test_get_all_recent(self):
        self.store.store_session("t1", "s1", turn_count=1)
        self.store.store_session("t2", "s2", turn_count=1)
        sessions = self.store.get_all_recent(limit=2)
        self.assertEqual(len(sessions), 2)
        summaries = {s["summary"] for s in sessions}
        self.assertEqual(summaries, {"s1", "s2"})

    def test_prune_old(self):
        for i in range(6):
            self.store.store_session("t1", f"summary_{i}", turn_count=i)
        self.assertLessEqual(self._count_files(), 5)

    def test_empty_store(self):
        sessions = self.store.get_recent_sessions("nonexistent")
        self.assertEqual(sessions, [])
        all_sessions = self.store.get_all_recent()
        self.assertEqual(all_sessions, [])

    def test_corrupted_file_skipped(self):
        bad_file = os.path.join(self.tmpdir, "t1_corrupt.json")
        with open(bad_file, "w") as f:
            f.write("not json")
        good_path = self.store.store_session("t1", "good", turn_count=1)
        sessions = self.store.get_recent_sessions("t1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["summary"], "good")

    def test_inject_limit(self):
        for i in range(10):
            self.store.store_session("t1", f"s{i}", turn_count=i)
        sessions = self.store.get_recent_sessions("t1")
        self.assertLessEqual(len(sessions), 3)  # inject_limit from setUp


if __name__ == "__main__":
    unittest.main()
