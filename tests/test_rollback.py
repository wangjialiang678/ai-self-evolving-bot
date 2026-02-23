import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from extensions.evolution.rollback import RollbackManager


class TestBackup:
    def test_backup_creates_directory(self, tmp_path):
        """备份创建正确的目录结构。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容\n策略1", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")

        assert backup_id is not None
        assert backup_id.startswith("backup_")
        backup_dir = workspace / "backups" / backup_id
        assert backup_dir.exists()
        assert (backup_dir / "rules/experience/task_strategies.md").read_text(encoding="utf-8") == "# 原始内容\n策略1"
        assert (backup_dir / "metadata.json").exists()

    def test_backup_metadata(self, tmp_path):
        """metadata.json 格式正确。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("content", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")

        meta = json.loads((workspace / "backups" / backup_id / "metadata.json").read_text(encoding="utf-8"))
        assert meta["proposal_id"] == "prop_001"
        assert meta["status"] == "active"
        assert "rules/experience/task_strategies.md" in meta["files"]

    def test_backup_multiple_files(self, tmp_path):
        """多文件备份。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/task_strategies.md").write_text("策略", encoding="utf-8")
        (workspace / "rules/experience/interaction_patterns.md").write_text("交互", encoding="utf-8")

        backup_id = rm.backup([
            "rules/experience/task_strategies.md",
            "rules/experience/interaction_patterns.md",
        ], "prop_002")

        backup_dir = workspace / "backups" / backup_id
        assert (backup_dir / "rules/experience/task_strategies.md").read_text(encoding="utf-8") == "策略"
        assert (backup_dir / "rules/experience/interaction_patterns.md").read_text(encoding="utf-8") == "交互"

    def test_backup_nonexistent_file(self, tmp_path):
        """备份不存在的文件不报错。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        backup_id = rm.backup(["rules/experience/nonexistent.md"], "prop_003")
        assert backup_id is not None

        meta = json.loads((workspace / "backups" / backup_id / "metadata.json").read_text(encoding="utf-8"))
        assert "rules/experience/nonexistent.md" in meta["files"]
        assert "rules/experience/nonexistent.md" in meta["missing_files"]

    def test_backup_id_has_prefix(self, tmp_path):
        """backup_id 使用 backup_ 前缀。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))
        (workspace / "rules/experience/task_strategies.md").write_text("x", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        assert backup_id.startswith("backup_")

    def test_backup_raises_when_backup_dir_uncreatable(self, tmp_path):
        """备份目录无法创建时抛出异常。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        blocked = workspace / "blocked"
        blocked.write_text("not a dir", encoding="utf-8")
        rm.backups_root = blocked

        with pytest.raises(RuntimeError):
            rm.backup(["rules/experience/task_strategies.md"], "prop_fail")


class TestRollback:
    def test_rollback_restores_file(self, tmp_path):
        """回滚正确恢复文件。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("# 修改后内容", encoding="utf-8")

        result = rm.rollback(backup_id)
        assert result["status"] == "success"
        assert rule_file.read_text(encoding="utf-8") == "# 原始内容"

    def test_rollback_nonexistent_backup(self, tmp_path):
        """回滚不存在的备份返回错误。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        result = rm.rollback("nonexistent_backup_id")
        assert result["status"] == "failed"

    def test_rollback_updates_metadata(self, tmp_path):
        """回滚后 metadata 状态更新。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("原始", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("修改后", encoding="utf-8")
        rm.rollback(backup_id)

        meta = json.loads((workspace / "backups" / backup_id / "metadata.json").read_text(encoding="utf-8"))
        assert meta["status"] == "rolled_back"

    def test_double_rollback_fails(self, tmp_path):
        """已回滚的备份不能再次回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("原始", encoding="utf-8")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("修改后", encoding="utf-8")
        rm.rollback(backup_id)

        result = rm.rollback(backup_id)
        assert result["status"] == "failed"

    def test_rollback_deletes_new_file_if_missing_at_backup(self, tmp_path):
        """备份时不存在的文件，回滚时应删除后续新增版本。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        target = workspace / "rules/experience/new_file.md"
        backup_id = rm.backup(["rules/experience/new_file.md"], "prop_100")
        target.write_text("new", encoding="utf-8")

        result = rm.rollback(backup_id)
        assert result["status"] == "success"
        assert not target.exists()


class TestListAndCleanup:
    def test_list_backups_ordered(self, tmp_path):
        """列出备份按时间倒序。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/test.md").write_text("test", encoding="utf-8")

        id1 = rm.backup(["rules/experience/test.md"], "prop_001")
        time.sleep(0.01)
        id2 = rm.backup(["rules/experience/test.md"], "prop_002")

        backups = rm.list_backups()
        assert len(backups) >= 2
        assert backups[0]["backup_id"] == id2
        assert backups[1]["backup_id"] == id1

    def test_list_backups_limit(self, tmp_path):
        """limit 参数生效。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/test.md").write_text("test", encoding="utf-8")
        for i in range(5):
            rm.backup(["rules/experience/test.md"], f"prop_{i:03d}")

        backups = rm.list_backups(limit=3)
        assert len(backups) == 3

    def test_cleanup_deletes_old_backups_including_stale_active(self, tmp_path):
        """cleanup 清理超过保留期的备份（含 stale active）。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        file_path = workspace / "rules/experience/test.md"
        file_path.write_text("test", encoding="utf-8")
        old_id = rm.backup(["rules/experience/test.md"], "prop_old")
        active_id = rm.backup(["rules/experience/test.md"], "prop_active")

        old_meta_file = workspace / "backups" / old_id / "metadata.json"
        old_meta = json.loads(old_meta_file.read_text(encoding="utf-8"))
        old_meta["timestamp"] = (datetime.now() - timedelta(days=60)).replace(microsecond=0).isoformat()
        old_meta["status"] = "rolled_back"
        old_meta_file.write_text(json.dumps(old_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        active_meta_file = workspace / "backups" / active_id / "metadata.json"
        active_meta = json.loads(active_meta_file.read_text(encoding="utf-8"))
        active_meta["timestamp"] = (datetime.now() - timedelta(days=60)).replace(microsecond=0).isoformat()
        active_meta["status"] = "active"
        active_meta_file.write_text(json.dumps(active_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        rm.cleanup(retention_days=30)

        assert not (workspace / "backups" / old_id).exists()
        assert not (workspace / "backups" / active_id).exists()


class TestAutoRollback:
    def test_auto_rollback_triggers(self, tmp_path):
        """指标恶化超过阈值时触发自动回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("原始策略", encoding="utf-8")
        rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("坏策略", encoding="utf-8")

        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.60}}

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is True
        assert rule_file.read_text(encoding="utf-8") == "原始策略"

    def test_auto_rollback_no_trigger(self, tmp_path):
        """指标轻微波动不触发回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("策略", encoding="utf-8")
        rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("微调后策略", encoding="utf-8")

        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.80}}

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is False
        assert rule_file.read_text(encoding="utf-8") == "微调后策略"

    def test_auto_rollback_no_backup(self, tmp_path):
        """无对应备份时不触发回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.60}}

        triggered = rm.auto_rollback_check("prop_404", current, baseline, 0.20)
        assert triggered is False


def _setup_workspace(tmp_path):
    """创建标准 workspace 目录结构。"""
    workspace = tmp_path / "workspace"
    for d in [
        "rules/constitution",
        "rules/experience",
        "backups",
        "signals",
        "metrics/daily",
        "observations/light_logs",
    ]:
        (workspace / d).mkdir(parents=True)
    return workspace
