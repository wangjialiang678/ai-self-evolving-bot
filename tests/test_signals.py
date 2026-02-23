"""Tests for A4 signal store and detector."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from extensions.signals.detector import SignalDetector
from extensions.signals.store import SignalStore


class TestSignalStore:
    def test_add_and_get(self, tmp_path):
        """添加信号后能读取。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "reflection:task_042",
                "description": "用户纠正",
                "related_tasks": ["task_042"],
            }
        )

        active = store.get_active()
        assert len(active) == 1
        assert active[0]["signal_type"] == "user_correction"
        assert "signal_id" in active[0]
        assert "timestamp" in active[0]

    def test_filter_by_priority(self, tmp_path):
        """按优先级过滤。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "s1",
                "description": "d1",
                "related_tasks": [],
            }
        )
        store.add(
            {
                "signal_type": "task_failure",
                "priority": "HIGH",
                "source": "s2",
                "description": "d2",
                "related_tasks": [],
            }
        )

        medium = store.get_active(priority="MEDIUM")
        assert len(medium) == 1
        assert medium[0]["signal_type"] == "user_correction"

    def test_filter_by_type(self, tmp_path):
        """按类型过滤。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "s1",
                "description": "d1",
                "related_tasks": [],
            }
        )
        store.add(
            {
                "signal_type": "task_failure",
                "priority": "HIGH",
                "source": "s2",
                "description": "d2",
                "related_tasks": [],
            }
        )

        failures = store.get_active(signal_type="task_failure")
        assert len(failures) == 1

    def test_mark_handled(self, tmp_path):
        """标记处理后从 active 移到 archive。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "s1",
                "description": "d1",
                "related_tasks": [],
            }
        )

        active = store.get_active()
        signal_id = active[0]["signal_id"]

        store.mark_handled([signal_id], handler="architect")

        assert len(store.get_active()) == 0

        archive = (signals_dir / "archive.jsonl").read_text(encoding="utf-8").strip()
        assert signal_id in archive

    def test_count_recent(self, tmp_path):
        """统计最近时间窗口内的信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "s1",
                "description": "d1",
                "related_tasks": [],
            }
        )
        store.add(
            {
                "signal_type": "user_correction",
                "priority": "MEDIUM",
                "source": "s2",
                "description": "d2",
                "related_tasks": [],
            }
        )

        count = store.count_recent(signal_type="user_correction", hours=1)
        assert count == 2


class TestSignalDetector:
    def test_detect_user_correction(self, tmp_path):
        """用户纠正触发 user_correction 信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_042",
            "type": "PREFERENCE",
            "outcome": "PARTIAL",
            "lesson": "用户要简短",
            "root_cause": None,
        }
        context = {
            "tokens_used": 3200,
            "model": "opus",
            "duration_ms": 15000,
            "user_corrections": 1,
        }

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "user_correction" for s in signals)

    def test_detect_task_failure(self, tmp_path):
        """ERROR + FAILURE 触发 task_failure。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_035",
            "type": "ERROR",
            "outcome": "FAILURE",
            "lesson": "错误假设",
            "root_cause": "wrong_assumption",
        }
        context = {
            "tokens_used": 2000,
            "model": "opus",
            "duration_ms": 10000,
            "user_corrections": 0,
        }

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "task_failure" for s in signals)
        assert any(s["priority"] == "HIGH" for s in signals)

    def test_detect_efficiency_opportunity(self, tmp_path):
        """高 token 消耗触发 efficiency_opportunity。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_050",
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "正常完成",
            "root_cause": None,
        }
        context = {
            "tokens_used": 15000,
            "model": "opus",
            "duration_ms": 30000,
            "user_corrections": 0,
        }

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "efficiency_opportunity" for s in signals)

    def test_no_signal_on_clean_success(self, tmp_path):
        """正常成功且 token 正常时不生成高优先级信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_060",
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "正常",
            "root_cause": None,
        }
        context = {
            "tokens_used": 2000,
            "model": "opus",
            "duration_ms": 5000,
            "user_corrections": 0,
        }

        signals = detector.detect(reflection, context)
        high_signals = [s for s in signals if s["priority"] in ("HIGH", "CRITICAL")]
        assert len(high_signals) == 0

    def test_detect_repeated_error(self, tmp_path):
        """7天内同类错误 ≥2 次触发 repeated_error。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        store.add(
            {
                "signal_type": "task_failure",
                "priority": "HIGH",
                "source": "reflection:task_030",
                "description": "错误假设",
                "related_tasks": ["task_030"],
                "timestamp": (datetime.now() - timedelta(hours=2)).replace(microsecond=0).isoformat(),
            }
        )

        reflection = {
            "task_id": "task_035",
            "type": "ERROR",
            "outcome": "FAILURE",
            "lesson": "错误假设",
            "root_cause": "wrong_assumption",
        }
        context = {
            "tokens_used": 2000,
            "model": "opus",
            "duration_ms": 10000,
            "user_corrections": 0,
        }

        detector.detect(reflection, context)
        patterns = detector.detect_patterns(lookback_hours=168)
        assert any(s["signal_type"] == "repeated_error" for s in patterns)

    def test_detect_patterns_no_duplicate_repeated_error(self, tmp_path):
        """重复调用 detect_patterns 不重复写入同源 repeated_error。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        now = datetime.now().replace(microsecond=0).isoformat()
        store.add(
            {
                "signal_type": "task_failure",
                "priority": "HIGH",
                "source": "reflection:task_101",
                "description": "错误",
                "related_tasks": ["task_101"],
                "timestamp": now,
            }
        )
        store.add(
            {
                "signal_type": "task_failure",
                "priority": "HIGH",
                "source": "reflection:task_102",
                "description": "错误",
                "related_tasks": ["task_102"],
                "timestamp": now,
            }
        )

        first = detector.detect_patterns(lookback_hours=168)
        second = detector.detect_patterns(lookback_hours=168)

        assert any(s["signal_type"] == "repeated_error" for s in first)
        assert not any(s["signal_type"] == "repeated_error" for s in second)

    def test_detect_performance_degradation(self, tmp_path):
        """3天成功率显著下降时触发 performance_degradation。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        events_path = metrics_dir / "events.jsonl"
        rows = []
        now = datetime.now()

        # baseline window (10~3 days ago): high success
        for d in range(4, 10):
            ts = (now - timedelta(days=d)).replace(microsecond=0).isoformat()
            rows.append(
                {
                    "event_type": "task",
                    "timestamp": ts,
                    "task_id": f"base_success_{d}",
                    "outcome": "SUCCESS",
                    "tokens": 1000,
                    "model": "opus",
                    "duration_ms": 1000,
                    "user_corrections": 0,
                    "error_type": None,
                }
            )

        # recent 3 days: mostly failures
        for d in range(0, 3):
            ts = (now - timedelta(days=d)).replace(microsecond=0).isoformat()
            rows.append(
                {
                    "event_type": "task",
                    "timestamp": ts,
                    "task_id": f"recent_fail_{d}",
                    "outcome": "FAILURE",
                    "tokens": 1000,
                    "model": "opus",
                    "duration_ms": 1000,
                    "user_corrections": 0,
                    "error_type": "ERROR",
                }
            )

        with events_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        patterns = detector.detect_patterns(lookback_hours=168)
        perf_signals = [s for s in patterns if s["signal_type"] == "performance_degradation"]
        assert perf_signals
        assert perf_signals[0]["priority"] == "CRITICAL"


def _setup_signals(tmp_path: Path) -> Path:
    signals_dir = tmp_path / "signals"
    signals_dir.mkdir()
    (signals_dir / "active.jsonl").touch()
    (signals_dir / "archive.jsonl").touch()
    return signals_dir
