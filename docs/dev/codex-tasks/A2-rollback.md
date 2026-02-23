# 任务 A2：回滚系统

> **优先级**: P0（Architect 引擎依赖此模块）
> **预计工作量**: 1-2 天
> **类型**: Python 模块开发

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。系统的核心机制是 Architect（架构师智能体）可以修改规则文件来改进系统行为。每次修改前，**必须**先备份受影响的文件，以便在修改导致指标恶化时自动回滚。

回滚系统是系统安全网的关键一环——没有可靠的回滚，系统就不敢自主修改任何规则。

详细背景见 `docs/design/v3-2-system-design.md` 第 6.6 节（爆炸半径控制与回滚）

---

## 你要做什么

实现 `RollbackManager` 类，提供规则文件的备份、恢复、清理和自动回滚功能。

---

## 接口定义

```python
# extensions/evolution/rollback.py

from pathlib import Path


class RollbackManager:
    """
    管理规则文件的备份和回滚。

    备份存储结构：
    workspace/backups/{backup_id}/
      └── (保持原始目录结构的文件副本)

    备份元数据：
    workspace/backups/{backup_id}/metadata.json
      {"backup_id": "...", "proposal_id": "...", "timestamp": "...",
       "files": [...], "status": "active"|"rolled_back"}
    """

    def __init__(self, workspace_path: str, backup_dir: str = "backups"):
        """
        初始化。

        Args:
            workspace_path: workspace/ 目录的绝对路径
            backup_dir: 备份子目录名，默认 "backups"
        """

    def backup(self, file_paths: list[str], proposal_id: str) -> str:
        """
        修改前备份指定文件。

        Args:
            file_paths: 要备份的文件路径列表（相对于 workspace_path 或绝对路径）
            proposal_id: 关联的提案 ID（如 "prop_024"）

        Returns:
            backup_id，格式：{timestamp}_{proposal_id}
            例如："20260225_101530_prop_024"

        行为：
        - 在 workspace/backups/{backup_id}/ 下创建备份
        - 保持原始目录结构（如 rules/experience/task_strategies.md
          备份到 backups/{id}/rules/experience/task_strategies.md）
        - 写入 metadata.json 记录备份信息
        - 如果文件不存在，记录在 metadata 中但不报错（文件可能是新建的）

        Raises:
            无。文件操作失败记录日志，不抛异常。
        """

    def rollback(self, backup_id: str) -> dict:
        """
        回滚到指定备份。

        Args:
            backup_id: 之前 backup() 返回的 ID

        Returns:
            {"restored_files": ["file1.md", "file2.md"],
             "status": "success" | "failed",
             "error": "..." | None}

        行为：
        - 将备份中的文件复制回原始位置，覆盖当前版本
        - 更新 metadata.json 中的 status 为 "rolled_back"
        - 如果备份不存在或已被回滚，返回 failed
        """

    def list_backups(self, limit: int = 10) -> list[dict]:
        """
        列出最近的备份，按时间倒序。

        Args:
            limit: 最多返回条数

        Returns:
            [{"backup_id": "...", "proposal_id": "...", "timestamp": "...",
              "files": [...], "status": "active"|"rolled_back"}]
        """

    def cleanup(self, retention_days: int = 30):
        """
        清理过期备份。

        Args:
            retention_days: 保留天数，默认 30 天

        行为：
        - 删除超过 retention_days 的备份目录
        - 不删除 status 为 "active" 且在验证期内的备份
        - 记录删除日志
        """

    def auto_rollback_check(self, proposal_id: str,
                            current_metrics: dict,
                            baseline_metrics: dict,
                            threshold: float = 0.20) -> bool:
        """
        检查是否需要自动回滚。

        比较 current_metrics 和 baseline_metrics 中的 tasks.success_rate。
        如果下降超过 threshold（相对值），执行回滚。

        Args:
            proposal_id: 提案 ID，用于查找对应的 backup_id
            current_metrics: 当前指标，格式 {"tasks": {"success_rate": 0.60, ...}}
            baseline_metrics: 基线指标，格式同上
            threshold: 恶化阈值，默认 0.20（即 20%）

        Returns:
            True 如果触发了回滚，False 如果未触发

        行为：
        - 计算 (baseline - current) / baseline
        - 如果 > threshold，找到 proposal_id 对应的 backup 并执行 rollback()
        - 返回是否触发了回滚

        示例：
            baseline success_rate = 0.85
            current success_rate = 0.60
            下降 = (0.85 - 0.60) / 0.85 = 0.294 > 0.20 → 触发回滚
        """
```

---

## 输入/输出格式

### 备份元数据 (metadata.json)

```json
{
    "backup_id": "20260225_101530_prop_024",
    "proposal_id": "prop_024",
    "timestamp": "2026-02-25T10:15:30",
    "files": [
        "rules/experience/task_strategies.md",
        "rules/experience/interaction_patterns.md"
    ],
    "status": "active"
}
```

### 指标格式（auto_rollback_check 的输入）

```python
metrics = {
    "tasks": {
        "total": 12,
        "success": 9,
        "partial": 2,
        "failure": 1,
        "success_rate": 0.75
    },
    "tokens": {"total": 33200},
    "user_corrections": 2
}
```

---

## 技术约束

- Python 3.11+
- 只使用标准库（pathlib, json, shutil, datetime, logging）
- 不用外部数据库，纯文件操作
- 文件操作失败 → 记录日志 + 返回错误状态（不抛异常到调用方）
- 时间戳格式：ISO 8601（`2026-02-25T10:15:30`）
- backup_id 格式：`{YYYYMMDD}_{HHMMSS}_{proposal_id}`

---

## 测试要求

创建 `tests/test_rollback.py`，必须通过以下测试：

```python
import pytest
import json
import time
from pathlib import Path

# 导入路径：from extensions.evolution.rollback import RollbackManager


class TestBackup:
    def test_backup_creates_directory(self, tmp_path):
        """备份创建正确的目录结构。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容\n策略1")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")

        assert backup_id is not None
        backup_dir = workspace / "backups" / backup_id
        assert backup_dir.exists()
        assert (backup_dir / "rules/experience/task_strategies.md").read_text() == "# 原始内容\n策略1"
        assert (backup_dir / "metadata.json").exists()

    def test_backup_metadata(self, tmp_path):
        """metadata.json 格式正确。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("content")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")

        meta = json.loads((workspace / "backups" / backup_id / "metadata.json").read_text())
        assert meta["proposal_id"] == "prop_001"
        assert meta["status"] == "active"
        assert "rules/experience/task_strategies.md" in meta["files"]

    def test_backup_multiple_files(self, tmp_path):
        """多文件备份。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/task_strategies.md").write_text("策略")
        (workspace / "rules/experience/interaction_patterns.md").write_text("交互")

        backup_id = rm.backup([
            "rules/experience/task_strategies.md",
            "rules/experience/interaction_patterns.md"
        ], "prop_002")

        backup_dir = workspace / "backups" / backup_id
        assert (backup_dir / "rules/experience/task_strategies.md").read_text() == "策略"
        assert (backup_dir / "rules/experience/interaction_patterns.md").read_text() == "交互"

    def test_backup_nonexistent_file(self, tmp_path):
        """备份不存在的文件不报错。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        backup_id = rm.backup(["rules/experience/nonexistent.md"], "prop_003")
        assert backup_id is not None  # 不报错，正常返回


class TestRollback:
    def test_rollback_restores_file(self, tmp_path):
        """回滚正确恢复文件。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("# 修改后内容")

        result = rm.rollback(backup_id)
        assert result["status"] == "success"
        assert rule_file.read_text() == "# 原始内容"

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
        rule_file.write_text("原始")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("修改后")
        rm.rollback(backup_id)

        meta = json.loads((workspace / "backups" / backup_id / "metadata.json").read_text())
        assert meta["status"] == "rolled_back"

    def test_double_rollback_fails(self, tmp_path):
        """已回滚的备份不能再次回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("原始")

        backup_id = rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("修改后")
        rm.rollback(backup_id)

        result = rm.rollback(backup_id)
        assert result["status"] == "failed"


class TestListAndCleanup:
    def test_list_backups_ordered(self, tmp_path):
        """列出备份按时间倒序。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/test.md").write_text("test")

        id1 = rm.backup(["rules/experience/test.md"], "prop_001")
        time.sleep(0.01)  # 确保时间戳不同
        id2 = rm.backup(["rules/experience/test.md"], "prop_002")

        backups = rm.list_backups()
        assert len(backups) >= 2
        assert backups[0]["backup_id"] == id2  # 最新的在前

    def test_list_backups_limit(self, tmp_path):
        """limit 参数生效。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        (workspace / "rules/experience/test.md").write_text("test")
        for i in range(5):
            rm.backup(["rules/experience/test.md"], f"prop_{i:03d}")

        backups = rm.list_backups(limit=3)
        assert len(backups) == 3


class TestAutoRollback:
    def test_auto_rollback_triggers(self, tmp_path):
        """指标恶化超过阈值时触发自动回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("原始策略")
        rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("坏策略")

        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.60}}  # 下降 29%

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is True
        assert rule_file.read_text() == "原始策略"

    def test_auto_rollback_no_trigger(self, tmp_path):
        """指标轻微波动不触发回滚。"""
        workspace = _setup_workspace(tmp_path)
        rm = RollbackManager(str(workspace))

        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("策略")
        rm.backup(["rules/experience/task_strategies.md"], "prop_001")
        rule_file.write_text("微调后策略")

        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.80}}  # 下降 6%

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is False
        assert rule_file.read_text() == "微调后策略"  # 未回滚


def _setup_workspace(tmp_path):
    """创建标准 workspace 目录结构。"""
    workspace = tmp_path / "workspace"
    for d in ["rules/constitution", "rules/experience", "backups",
              "signals", "metrics/daily", "observations/light_logs"]:
        (workspace / d).mkdir(parents=True)
    return workspace
```

---

## 交付物

```
extensions/evolution/rollback.py
extensions/__init__.py           # 空文件
extensions/evolution/__init__.py # 空文件
tests/test_rollback.py
```

---

## 验收标准

- [ ] backup() 创建完整的目录结构副本，保持原始路径
- [ ] rollback() 能准确恢复文件到备份状态
- [ ] 已回滚的备份不能重复回滚
- [ ] metadata.json 正确记录备份信息和状态
- [ ] auto_rollback_check 正确比较指标并触发回滚
- [ ] cleanup 只删除超过 retention 天数的备份
- [ ] list_backups 按时间倒序，limit 参数生效
- [ ] 所有方法有错误处理（文件不存在、权限问题等）
- [ ] 以上测试全部通过
- [ ] 代码有合理的日志输出（使用 logging 模块）

---

## 参考文档

- 完整设计：`docs/design/v3-2-system-design.md` 第 6.6 节（爆炸半径控制与回滚）
- 审批边界：`docs/design/v3-2-system-design.md` 第 6.7 节
- 模块计划：`docs/dev/mvp-module-plan.md` A2 节
- 开发指南：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I6、I7）
