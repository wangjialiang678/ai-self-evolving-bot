import json
from datetime import date

import pytest
import yaml

from extensions.evolution.metrics import MetricsTracker


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

        mt.record_task(
            "task_002",
            "PARTIAL",
            1500,
            "opus",
            8000,
            user_corrections=1,
            error_type="PREFERENCE",
        )

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

        mt.record_proposal(
            "prop_024",
            1,
            "executed",
            ["rules/experience/task_strategies.md"],
        )

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
        assert len(trend) == 7
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

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
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
    lines = (metrics_dir / "events.jsonl").read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]
