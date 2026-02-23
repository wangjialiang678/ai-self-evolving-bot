"""Tests for A7 observer engine and scheduler."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.llm_client import MockLLMClient
from extensions.observer.engine import ObserverEngine
from extensions.observer.scheduler import ObserverScheduler


class TestObserverEngine:
    @pytest.mark.asyncio
    async def test_lightweight_writes_jsonl(self, tmp_path):
        """轻量观察写入 JSONL。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        trace = _make_trace()
        log = await engine.lightweight_observe(trace)

        today = date.today().isoformat()
        log_file = ws / f"observations/light_logs/{today}.jsonl"
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["task_id"] == "task_042"
        assert log["task_id"] == "task_042"

    @pytest.mark.asyncio
    async def test_lightweight_returns_log(self, tmp_path):
        """轻量观察返回正确格式。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        log = await engine.lightweight_observe(_make_trace())
        assert "task_id" in log
        assert "outcome" in log
        assert "note" in log

    @pytest.mark.asyncio
    async def test_deep_analyze_reads_logs(self, tmp_path):
        """深度分析读取当日日志。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(
            ws,
            opus_response=json.dumps(
                {
                    "tasks_analyzed": 2,
                    "key_findings": [
                        {
                            "type": "error_pattern",
                            "description": "重复错误",
                            "confidence": "HIGH",
                            "evidence": ["task_042"],
                            "recommendation": "添加规则",
                        }
                    ],
                    "overall_health": "good",
                }
            ),
        )

        await engine.lightweight_observe(_make_trace("task_041"))
        await engine.lightweight_observe(_make_trace("task_042"))

        report = await engine.deep_analyze(trigger="daily")
        assert report["tasks_analyzed"] >= 1
        assert len(report["key_findings"]) >= 1

    @pytest.mark.asyncio
    async def test_deep_report_markdown(self, tmp_path):
        """深度报告写入 Markdown。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(
            ws,
            opus_response=json.dumps(
                {
                    "tasks_analyzed": 1,
                    "key_findings": [],
                    "overall_health": "good",
                }
            ),
        )

        await engine.lightweight_observe(_make_trace())
        await engine.deep_analyze(trigger="daily")

        today = date.today().isoformat()
        report_file = ws / f"observations/deep_reports/{today}.md"
        assert report_file.exists()
        content = report_file.read_text(encoding="utf-8")
        assert "Observer 深度报告" in content

    @pytest.mark.asyncio
    async def test_deep_analyze_priority_order(self, tmp_path):
        """key_findings 按优先级排序。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(
            ws,
            opus_response=json.dumps(
                {
                    "tasks_analyzed": 5,
                    "key_findings": [
                        {
                            "type": "preference",
                            "description": "偏好",
                            "confidence": "LOW",
                            "evidence": [],
                            "recommendation": "",
                        },
                        {
                            "type": "error_pattern",
                            "description": "错误",
                            "confidence": "HIGH",
                            "evidence": [],
                            "recommendation": "",
                        },
                    ],
                    "overall_health": "degraded",
                }
            ),
        )

        await engine.lightweight_observe(_make_trace())
        report = await engine.deep_analyze()

        if len(report["key_findings"]) >= 2:
            types = [f["type"] for f in report["key_findings"]]
            assert types.index("error_pattern") < types.index("preference")


class TestObserverScheduler:
    @pytest.mark.asyncio
    async def test_emergency_trigger(self, tmp_path):
        """24h 内 ≥3 次 CRITICAL 触发紧急分析。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(
            ws,
            opus_response=json.dumps(
                {
                    "tasks_analyzed": 0,
                    "key_findings": [],
                    "overall_health": "critical",
                }
            ),
        )

        mock_store = _MockSignalStore(critical_count=3)
        mock_metrics = _MockMetrics()
        scheduler = ObserverScheduler(
            observer=engine,
            signal_store=mock_store,
            metrics=mock_metrics,
            config={"daily_time": "02:00", "emergency_threshold": 3},
        )

        report = await scheduler.check_and_run()
        assert report is not None
        assert report["trigger"] == "emergency"

    @pytest.mark.asyncio
    async def test_daily_trigger(self, tmp_path):
        """定时时间窗口内触发 daily 分析。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(
            ws,
            opus_response=json.dumps(
                {
                    "tasks_analyzed": 0,
                    "key_findings": [],
                    "overall_health": "good",
                }
            ),
        )

        now = datetime.now()
        daily_time = f"{now.hour:02d}:{now.minute:02d}"

        scheduler = ObserverScheduler(
            observer=engine,
            signal_store=_MockSignalStore(critical_count=0),
            metrics=_MockMetrics(),
            config={"daily_time": daily_time, "emergency_threshold": 3},
        )

        report = await scheduler.check_and_run()
        assert report is not None
        assert report["trigger"] == "daily"

    @pytest.mark.asyncio
    async def test_no_emergency_below_threshold(self, tmp_path):
        """CRITICAL < 3 不触发紧急。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        scheduler = ObserverScheduler(
            observer=engine,
            signal_store=_MockSignalStore(critical_count=2),
            metrics=_MockMetrics(),
            config={"daily_time": "00:00", "emergency_threshold": 3},
        )

        report = await scheduler.check_and_run()
        # daily_time 一般不在窗口内，因此应为 None
        assert report is None or report["trigger"] == "daily"


def _setup_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    (ws / "observations/light_logs").mkdir(parents=True)
    (ws / "observations/deep_reports").mkdir(parents=True)
    (ws / "signals").mkdir(parents=True)
    (ws / "rules/constitution").mkdir(parents=True)
    (ws / "rules/experience").mkdir(parents=True)
    (ws / "signals/active.jsonl").touch()
    (ws / "rules/constitution/identity.md").write_text("# identity", encoding="utf-8")
    return ws


def _make_engine(ws: Path, opus_response: str | None = None) -> ObserverEngine:
    gemini = MockLLMClient(responses={"gemini-flash": "正常完成"})
    opus = MockLLMClient(
        responses={
            "opus": opus_response
            or json.dumps({"tasks_analyzed": 0, "key_findings": [], "overall_health": "good"})
        }
    )
    return ObserverEngine(gemini, opus, str(ws))


def _make_trace(task_id: str = "task_042") -> dict:
    return {
        "task_id": task_id,
        "user_message": "分析竞品",
        "system_response": "这是分析结果",
        "user_feedback": None,
        "tools_used": ["web_search"],
        "tokens_used": 2800,
        "model": "opus",
        "duration_ms": 12000,
    }


class _MockSignalStore:
    def __init__(self, critical_count: int):
        self._critical_count = critical_count

    def count_recent(self, signal_type=None, priority=None, hours=24):
        if priority == "CRITICAL":
            return self._critical_count
        return 0

    def get_active(self, **kwargs):
        return []


class _MockMetrics:
    def get_daily_summary(self, target_date=None):
        return {"tasks": {"total": 0, "success_rate": 0.0}}
