"""
Tests for memory module: ProfileManager + SessionMemoryStore.
"""

import os
import json
import tempfile
import unittest
from datetime import datetime, timedelta


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

    # ── Phase 3: Snapshot ───────────────────────────────────────

    def test_snapshot_created_on_save(self):
        """验证 save 时自动创建快照"""
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        self.mgr.save("# 沟通偏好\n- 语言：中文")
        versions = self.mgr.list_history_versions()
        self.assertGreaterEqual(len(versions), 1)

    def test_snapshot_created_on_update_section(self):
        """验证 update_section 时自动创建快照"""
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        self.mgr.update_section("沟通偏好", "- 语言：中文")
        versions = self.mgr.list_history_versions()
        self.assertGreaterEqual(len(versions), 1)

    def test_snapshot_prune_max_10(self):
        """验证快照裁剪到最多 10 份"""
        for i in range(15):
            self.mgr.save(f"# 个人基本信息\n- 姓名：第{i}号")
        versions = self.mgr.list_history_versions()
        self.assertLessEqual(len(versions), 10)

    # ── Phase 3: Heat scoring ────────────────────────────────────

    def test_heat_score_increments_on_save(self):
        """验证 save 带标题时更新热度"""
        self.mgr.save("# 沟通偏好\n- 语言：中文")
        scores = self.mgr._load_heat_scores()
        self.assertIn("沟通偏好", scores)
        self.assertEqual(scores["沟通偏好"]["count"], 1)

    def test_heat_score_increments_on_update(self):
        """验证 update_section 增加热度计数"""
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        self.mgr.update_section("沟通偏好", "- 语言：中文")
        scores = self.mgr._load_heat_scores()
        self.assertEqual(scores["沟通偏好"]["count"], 1)

    def test_heat_score_decay(self):
        """验证热度随天数衰减"""
        scores = {"测试章节": {"count": 10, "last_updated": (datetime.now() - timedelta(days=60)).isoformat(), "score": 0.0}}
        self.mgr._save_heat_scores(scores)
        self.mgr._decay_scores()
        reloaded = self.mgr._load_heat_scores()
        # 60 days ~ exp(-2) ≈ 0.135, count=10 → score ≈ 1.35
        self.assertLess(reloaded["测试章节"]["score"], 10.0)
        self.assertGreater(reloaded["测试章节"]["score"], 0.0)

    # ── Phase 3: Cold archive ────────────────────────────────────

    def test_archive_cold_sections(self):
        """验证冷区章节被归档"""
        # 直接写 profile 文件，绕过 save() 的热度追踪
        os.makedirs(self.mgr.memory_dir, exist_ok=True)
        with open(self.mgr.profile_path, "w", encoding="utf-8") as f:
            f.write("# 个人基本信息\n- 姓名：张三\n\n# 冷区\n- 数据：旧数据")
        # 覆盖热度数据（冷区极低分）
        scores = {"冷区": {"count": 1, "last_updated": "2000-01-01T00:00:00", "score": 0.01}}
        self.mgr._save_heat_scores(scores)

        archived = self.mgr.archive_cold_sections()
        self.assertEqual(archived, 1)

        # 验证占位符
        result = self.mgr.read()
        self.assertIn("archived:", result)

    def test_no_cold_sections_returns_zero(self):
        """验证没有冷区时返回 0"""
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        archived = self.mgr.archive_cold_sections()
        self.assertEqual(archived, 0)

    # ── Phase 3: Rollback ────────────────────────────────────────

    def test_rollback_restores_content(self):
        """验证 rollback 恢复历史内容"""
        self.mgr.save("# 个人基本信息\n- 姓名：张三")
        self.mgr.save("# 个人基本信息\n- 姓名：李四")
        versions = self.mgr.list_history_versions()
        self.assertGreaterEqual(len(versions), 1)

        # Rollback to first version (oldest)
        oldest = versions[-1]
        result = self.mgr.rollback(oldest["version_id"])
        self.assertIn("已从版本", result)

        with open(self.mgr.profile_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("张三", content)

    def test_rollback_invalid_version(self):
        """验证回滚到不存在的版本"""
        result = self.mgr.rollback("nonexistent")
        self.assertIn("未找到版本", result)

    # ── Phase 3: Conflict detection ──────────────────────────────

    def test_conflict_archive_on_update(self):
        """验证 update_section 检测到冲突时归档旧值"""
        self.mgr.save("# 沟通偏好\n- 语言：中文\n- 风格：简洁")
        self.mgr.update_section("沟通偏好", "- 语言：英文\n- 风格：简洁")

        # 验证 archive 目录有冲突文件
        archive_files = os.listdir(self.mgr.archive_dir)
        conflict_files = [f for f in archive_files if f.startswith("conflict_")]
        self.assertGreaterEqual(len(conflict_files), 1)


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
