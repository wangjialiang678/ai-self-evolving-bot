# 任务 A3：指标追踪系统

> **优先级**: P0（回滚系统和 Observer 依赖指标数据）
> **预计工作量**: 1-2 天
> **类型**: Python 模块开发

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。系统需要持续追踪自身的运行指标（任务成功率、token 消耗、信号检测数等），用于：

1. **Observer** 读取指标判断系统健康度
2. **Architect** 用基线指标对比修改效果
3. **回滚系统** 根据指标变化决定是否自动回滚
4. **日报** 向用户展示系统运行状况

指标系统是纯数据收集和统计模块，不做任何决策。

详细背景见 `docs/design/v3-2-system-design.md` 第 12.2 节

---

## 你要做什么

实现 `MetricsTracker` 类，提供事件记录、日统计、趋势分析和异常检测功能。

---

## 接口定义

```python
# extensions/evolution/metrics.py

from pathlib import Path
from datetime import date


class MetricsTracker:
    """
    追踪系统运行指标。

    数据存储：
    - workspace/metrics/events.jsonl — 实时事件流（JSONL 追加写入）
    - workspace/metrics/daily/{date}.yaml — 每日汇总
    """

    def __init__(self, metrics_dir: str):
        """
        Args:
            metrics_dir: workspace/metrics/ 目录路径
        """

    def record_task(self, task_id: str, outcome: str, tokens: int,
                    model: str, duration_ms: int,
                    user_corrections: int = 0,
                    error_type: str | None = None):
        """
        记录一次任务结果。

        Args:
            task_id: 任务 ID，如 "task_042"
            outcome: "SUCCESS" | "PARTIAL" | "FAILURE"
            tokens: 消耗的 token 数
            model: 使用的模型，如 "opus" | "gemini-flash"
            duration_ms: 耗时毫秒
            user_corrections: 用户纠正次数，默认 0
            error_type: "ERROR" | "PREFERENCE" | None

        行为：
        - 写入一条 event 到 events.jsonl
        - event 格式见下方"事件格式"
        """

    def record_signal(self, signal_type: str, priority: str, source: str):
        """
        记录一次信号检测。

        Args:
            signal_type: 信号类型（如 "user_correction", "repeated_error"）
            priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
            source: 来源（如 "reflection:task_042"）
        """

    def record_proposal(self, proposal_id: str, level: int,
                        status: str, files_affected: list[str]):
        """
        记录一次 Architect 提案。

        Args:
            proposal_id: 提案 ID，如 "prop_024"
            level: 审批级别 0-3
            status: "proposed" | "approved" | "rejected" |
                    "executed" | "rolled_back" | "validated"
            files_affected: 受影响的文件列表
        """

    def get_daily_summary(self, target_date: str | None = None) -> dict:
        """
        获取某天的汇总指标。

        Args:
            target_date: 日期字符串 "YYYY-MM-DD"，默认今天

        Returns:
            见下方"每日汇总格式"。如果该日无数据，返回全零结构。
        """

    def get_success_rate(self, days: int = 7) -> float:
        """
        获取过去 N 天的任务成功率。

        Args:
            days: 回看天数，默认 7

        Returns:
            成功率（0.0-1.0）。如果无数据返回 0.0。

        计算：success_count / total_count（含 PARTIAL 算非成功）
        """

    def get_trend(self, metric: str, days: int = 30) -> list[dict]:
        """
        获取某指标的趋势数据（日粒度）。

        Args:
            metric: 指标名，支持 "success_rate", "total_tasks",
                    "total_tokens", "user_corrections"
            days: 回看天数

        Returns:
            [{"date": "2026-02-25", "value": 0.75}, ...]
            按日期正序，缺失日填 0 或 0.0。
        """

    def should_trigger_repair(self) -> bool:
        """
        判断是否应该切换到 repair 模式。

        触发条件（满足任一即返回 True）：
        1. 近 3 天成功率下降 >20%（相对于前 7 天平均值）
        2. 24h 内 CRITICAL 级别信号 ≥ 3 次

        Returns:
            True 如果应切换到 repair 模式
        """

    def flush_daily(self, target_date: str | None = None):
        """
        将指定日期的事件汇总写入 daily/{date}.yaml 文件。

        Args:
            target_date: 日期字符串，默认今天

        行为：
        - 从 events.jsonl 中筛选该日期的事件
        - 汇总为每日指标格式
        - 写入 workspace/metrics/daily/{date}.yaml
        - 如果该日已有 yaml 文件，覆盖
        """
```

---

## 数据格式

### 事件格式（events.jsonl 中的每一行）

```json
{"event_type": "task", "timestamp": "2026-02-25T10:15:30", "task_id": "task_042", "outcome": "SUCCESS", "tokens": 3200, "model": "opus", "duration_ms": 15000, "user_corrections": 0, "error_type": null}

{"event_type": "signal", "timestamp": "2026-02-25T10:16:00", "signal_type": "user_correction", "priority": "MEDIUM", "source": "reflection:task_042"}

{"event_type": "proposal", "timestamp": "2026-02-25T10:30:00", "proposal_id": "prop_024", "level": 1, "status": "executed", "files_affected": ["rules/experience/task_strategies.md"]}
```

### 每日汇总格式（daily/{date}.yaml）

```yaml
date: "2026-02-25"
tasks:
  total: 12
  success: 9
  partial: 2
  failure: 1
  success_rate: 0.75
tokens:
  opus: 28000
  gemini-flash: 5200
  total: 33200
user_corrections: 2
signals_detected: 3
observer_deep_analyses: 1
architect_proposals: 1
modifications_executed: 0
modifications_rolled_back: 0
```

---

## 技术约束

- Python 3.11+
- 依赖：标准库 + `PyYAML`（用于 YAML 读写）
- 不用外部数据库，纯文件操作
- JSONL 追加写入（`open(path, "a")`），保证高频写入不丢数据
- 时间戳格式：ISO 8601
- events.jsonl 每行一个 JSON 对象，UTF-8 编码
- 读取 events.jsonl 时要容忍可能的空行或格式错误行（跳过并记录日志）

---

## 测试要求

创建 `tests/test_metrics.py`，必须通过以下测试：

```python
import pytest
import json
import yaml
from pathlib import Path
from datetime import date, timedelta

# 导入路径：from extensions.evolution.metrics import MetricsTracker


class TestRecordTask:
    def test_record_task_writes_event(self, tmp_path):
        """记录任务事件到 events.jsonl。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)

        events = _read_events(metrics_dir)
        assert len(events) == 1
        assert events[0]["event_type"] == "task"
        assert events[0]["task_id"] == "task_001"
        assert events[0]["outcome"] == "SUCCESS"
        assert events[0]["tokens"] == 3200

    def test_record_task_with_corrections(self, tmp_path):
        """记录包含用户纠正的任务。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_002", "PARTIAL", 1500, "opus", 8000,
                       user_corrections=1, error_type="PREFERENCE")

        events = _read_events(metrics_dir)
        assert events[0]["user_corrections"] == 1
        assert events[0]["error_type"] == "PREFERENCE"

    def test_multiple_records(self, tmp_path):
        """多次记录追加到同一文件。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)
        mt.record_task("task_002", "FAILURE", 1500, "opus", 8000)
        mt.record_task("task_003", "SUCCESS", 2000, "gemini-flash", 5000)

        events = _read_events(metrics_dir)
        assert len(events) == 3


class TestRecordOther:
    def test_record_signal(self, tmp_path):
        """记录信号事件。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_signal("user_correction", "MEDIUM", "reflection:task_042")

        events = _read_events(metrics_dir)
        assert events[0]["event_type"] == "signal"
        assert events[0]["signal_type"] == "user_correction"

    def test_record_proposal(self, tmp_path):
        """记录提案事件。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_proposal("prop_024", 1, "executed",
                          ["rules/experience/task_strategies.md"])

        events = _read_events(metrics_dir)
        assert events[0]["event_type"] == "proposal"
        assert events[0]["proposal_id"] == "prop_024"


class TestDailySummary:
    def test_daily_summary(self, tmp_path):
        """每日汇总正确统计。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)
        mt.record_task("task_002", "FAILURE", 1500, "opus", 8000)
        mt.record_task("task_003", "SUCCESS", 2000, "gemini-flash", 5000)
        mt.record_signal("user_correction", "MEDIUM", "source")

        summary = mt.get_daily_summary()
        assert summary["tasks"]["total"] == 3
        assert summary["tasks"]["success"] == 2
        assert summary["tasks"]["failure"] == 1
        assert summary["tasks"]["success_rate"] == pytest.approx(0.667, rel=0.01)
        assert summary["tokens"]["opus"] == 4700
        assert summary["tokens"]["gemini-flash"] == 2000
        assert summary["signals_detected"] == 1

    def test_empty_day_summary(self, tmp_path):
        """空数据日返回全零结构。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        summary = mt.get_daily_summary("2099-01-01")
        assert summary["tasks"]["total"] == 0
        assert summary["tasks"]["success_rate"] == 0.0


class TestSuccessRate:
    def test_success_rate_calculation(self, tmp_path):
        """成功率计算正确。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        # 4 个成功，1 个失败
        for i in range(4):
            mt.record_task(f"task_{i}", "SUCCESS", 1000, "opus", 5000)
        mt.record_task("task_4", "FAILURE", 1000, "opus", 5000)

        rate = mt.get_success_rate(days=7)
        assert rate == pytest.approx(0.8, rel=0.01)

    def test_success_rate_no_data(self, tmp_path):
        """无数据时返回 0.0。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        rate = mt.get_success_rate()
        assert rate == 0.0


class TestTrend:
    def test_get_trend(self, tmp_path):
        """趋势数据格式正确。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)

        trend = mt.get_trend("success_rate", days=7)
        assert isinstance(trend, list)
        assert len(trend) == 7  # 7 天的数据点
        assert all("date" in t and "value" in t for t in trend)


class TestRepairTrigger:
    def test_should_trigger_repair_critical_signals(self, tmp_path):
        """24h 内 ≥3 次 CRITICAL 信号触发 repair。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        for i in range(3):
            mt.record_signal("performance_degradation", "CRITICAL", f"source_{i}")

        assert mt.should_trigger_repair() is True

    def test_no_repair_below_threshold(self, tmp_path):
        """CRITICAL < 3 不触发。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_signal("user_correction", "CRITICAL", "source_1")
        mt.record_signal("user_correction", "CRITICAL", "source_2")

        assert mt.should_trigger_repair() is False


class TestFlushDaily:
    def test_flush_daily_yaml(self, tmp_path):
        """生成正确格式的 YAML 文件。"""
        metrics_dir = _setup_metrics(tmp_path)
        mt = MetricsTracker(str(metrics_dir))

        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)
        mt.record_task("task_002", "PARTIAL", 1500, "gemini-flash", 8000)

        today = date.today().isoformat()
        mt.flush_daily()

        yaml_path = metrics_dir / "daily" / f"{today}.yaml"
        assert yaml_path.exists()

        data = yaml.safe_load(yaml_path.read_text())
        assert data["date"] == today
        assert data["tasks"]["total"] == 2
        assert data["tasks"]["success"] == 1
        assert data["tokens"]["total"] == 4700


def _setup_metrics(tmp_path):
    """创建 metrics 目录结构。"""
    metrics_dir = tmp_path / "metrics"
    (metrics_dir / "daily").mkdir(parents=True)
    (metrics_dir / "events.jsonl").touch()
    return metrics_dir


def _read_events(metrics_dir):
    """读取 events.jsonl 中所有事件。"""
    lines = (metrics_dir / "events.jsonl").read_text().strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]
```

---

## 交付物

```
extensions/evolution/metrics.py
extensions/__init__.py             # 空文件（如不存在）
extensions/evolution/__init__.py   # 空文件（如不存在）
tests/test_metrics.py
```

---

## 验收标准

- [ ] record_task 正确写入 events.jsonl（JSONL 格式，每行一个 JSON）
- [ ] record_signal 和 record_proposal 正确写入各自的事件格式
- [ ] get_daily_summary 正确汇总当日所有事件类型
- [ ] get_success_rate 正确计算滑动窗口成功率
- [ ] get_trend 返回指定天数的每日数据点（缺失日补零）
- [ ] should_trigger_repair 正确判断两个触发条件
- [ ] flush_daily 生成与设计文档一致的 YAML 格式
- [ ] 空数据不报错，返回合理的默认值
- [ ] 高频写入不丢数据（JSONL 追加写入）
- [ ] 容忍 events.jsonl 中的空行或格式错误行
- [ ] 以上测试全部通过

---

## 参考文档

- 完整设计：`docs/design/v3-2-system-design.md` 第 12.2 节（核心指标追踪）
- 模块计划：`docs/dev/mvp-module-plan.md` A3 节
- 开发指南：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I7）
- 配置参考：`docs/dev/mvp-dev-guide.md` 附录 B（evo_config.yaml）
