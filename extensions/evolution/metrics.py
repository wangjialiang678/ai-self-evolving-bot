"""系统运行指标追踪。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class MetricsTracker:
    """追踪系统运行指标。"""

    def __init__(self, metrics_dir: str):
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

        self.daily_dir = self.metrics_dir / "daily"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

        self.events_file = self.metrics_dir / "events.jsonl"
        self.events_file.touch(exist_ok=True)

    def record_task(
        self,
        task_id: str,
        outcome: str,
        tokens: int,
        model: str,
        duration_ms: int,
        user_corrections: int = 0,
        error_type: str | None = None,
    ):
        """记录一次任务结果。"""
        event = {
            "event_type": "task",
            "timestamp": self._now_iso(),
            "task_id": task_id,
            "outcome": outcome,
            "tokens": tokens,
            "model": model,
            "duration_ms": duration_ms,
            "user_corrections": user_corrections,
            "error_type": error_type,
        }
        self._append_event(event)

    def record_signal(self, signal_type: str, priority: str, source: str):
        """记录一次信号检测。"""
        event = {
            "event_type": "signal",
            "timestamp": self._now_iso(),
            "signal_type": signal_type,
            "priority": priority,
            "source": source,
        }
        self._append_event(event)

    def record_proposal(
        self,
        proposal_id: str,
        level: int,
        status: str,
        files_affected: list[str],
    ):
        """记录一次 Architect 提案。"""
        event = {
            "event_type": "proposal",
            "timestamp": self._now_iso(),
            "proposal_id": proposal_id,
            "level": level,
            "status": status,
            "files_affected": files_affected,
        }
        self._append_event(event)

    def get_daily_summary(self, target_date: str | None = None) -> dict[str, Any]:
        """获取某天的汇总指标。"""
        day = target_date or date.today().isoformat()
        summary = self._empty_summary(day)

        for event in self._iter_events_for_date(day):
            event_type = event.get("event_type")
            if event_type == "task":
                self._apply_task_to_summary(summary, event)
            elif event_type == "signal":
                summary["signals_detected"] += 1
                if event.get("signal_type") == "observer_deep_analysis":
                    summary["observer_deep_analyses"] += 1
            elif event_type == "proposal":
                summary["architect_proposals"] += 1
                status = str(event.get("status", "")).lower()
                if status == "executed":
                    summary["modifications_executed"] += 1
                elif status == "rolled_back":
                    summary["modifications_rolled_back"] += 1

        total = summary["tasks"]["total"]
        if total > 0:
            summary["tasks"]["success_rate"] = summary["tasks"]["success"] / total

        return summary

    def get_success_rate(self, days: int = 7) -> float:
        """获取过去 N 天成功率。"""
        if days <= 0:
            return 0.0

        start = date.today() - timedelta(days=days - 1)
        end = date.today()

        success = 0
        total = 0
        for event in self._iter_events_between(start, end):
            if event.get("event_type") != "task":
                continue
            total += 1
            if event.get("outcome") == "SUCCESS":
                success += 1

        if total == 0:
            return 0.0
        return success / total

    def get_trend(self, metric: str, days: int = 30) -> list[dict[str, Any]]:
        """获取某指标的日趋势。"""
        if days <= 0:
            return []

        supported = {"success_rate", "total_tasks", "total_tokens", "user_corrections"}
        if metric not in supported:
            raise ValueError(f"Unsupported metric: {metric}")

        start = date.today() - timedelta(days=days - 1)
        trend: list[dict[str, Any]] = []

        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            summary = self.get_daily_summary(day)
            if metric == "success_rate":
                value: float | int = summary["tasks"]["success_rate"]
            elif metric == "total_tasks":
                value = summary["tasks"]["total"]
            elif metric == "total_tokens":
                value = summary["tokens"]["total"]
            else:
                value = summary["user_corrections"]

            trend.append({"date": day, "value": value})

        return trend

    def should_trigger_repair(self) -> bool:
        """判断是否应触发 repair 模式。"""
        if self._critical_signals_in_last_24h() >= 3:
            return True

        baseline = self._success_rate_in_window(10, 4)
        recent = self._success_rate_in_window(3, 1)
        if baseline <= 0:
            return False

        drop = (baseline - recent) / baseline
        return drop > 0.20

    def flush_daily(self, target_date: str | None = None):
        """将指定日期汇总写入 daily/{date}.yaml。"""
        day = target_date or date.today().isoformat()
        summary = self.get_daily_summary(day)
        out_file = self.daily_dir / f"{day}.yaml"

        try:
            out_file.write_text(
                yaml.safe_dump(summary, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to flush daily metrics %s: %s", out_file, exc)

    def _apply_task_to_summary(self, summary: dict[str, Any], event: dict[str, Any]):
        tasks = summary["tasks"]
        tasks["total"] += 1

        outcome = event.get("outcome")
        if outcome == "SUCCESS":
            tasks["success"] += 1
        elif outcome == "PARTIAL":
            tasks["partial"] += 1
        else:
            tasks["failure"] += 1

        tokens = int(event.get("tokens", 0) or 0)
        model = str(event.get("model", "unknown"))
        summary["tokens"][model] = summary["tokens"].get(model, 0) + tokens
        summary["tokens"]["total"] += tokens

        summary["user_corrections"] += int(event.get("user_corrections", 0) or 0)

    def _append_event(self, event: dict[str, Any]):
        try:
            with self.events_file.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("Failed to append event: %s", exc)

    def _iter_events(self) -> list[dict[str, Any]]:
        if not self.events_file.exists():
            return []

        events: list[dict[str, Any]] = []
        try:
            for line in self.events_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skip invalid JSONL line in %s", self.events_file)
        except Exception as exc:
            logger.error("Failed reading events file %s: %s", self.events_file, exc)
        return events

    def _iter_events_for_date(self, target_date: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self._iter_events()
            if str(event.get("timestamp", "")).startswith(target_date)
        ]

    def _iter_events_between(self, start: date, end: date) -> list[dict[str, Any]]:
        events_in_range: list[dict[str, Any]] = []
        for event in self._iter_events():
            timestamp = self._parse_iso(event.get("timestamp"))
            if timestamp is None:
                continue
            event_day = timestamp.date()
            if start <= event_day <= end:
                events_in_range.append(event)
        return events_in_range

    def _critical_signals_in_last_24h(self) -> int:
        cutoff = datetime.now() - timedelta(hours=24)
        count = 0
        for event in self._iter_events():
            if event.get("event_type") != "signal":
                continue
            if event.get("priority") != "CRITICAL":
                continue
            timestamp = self._parse_iso(event.get("timestamp"))
            if timestamp is not None and timestamp >= cutoff:
                count += 1
        return count

    def _success_rate_in_window(self, start_days_ago: int, end_days_ago: int) -> float:
        now = date.today()
        start = now - timedelta(days=start_days_ago - 1)
        end = now - timedelta(days=end_days_ago - 1)

        success = 0
        total = 0
        for event in self._iter_events_between(start, end):
            if event.get("event_type") != "task":
                continue
            total += 1
            if event.get("outcome") == "SUCCESS":
                success += 1

        if total == 0:
            return 0.0
        return success / total

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().replace(microsecond=0).isoformat()

    @staticmethod
    def _empty_summary(day: str) -> dict[str, Any]:
        return {
            "date": day,
            "tasks": {
                "total": 0,
                "success": 0,
                "partial": 0,
                "failure": 0,
                "success_rate": 0.0,
            },
            "tokens": {
                "opus": 0,
                "gemini-flash": 0,
                "total": 0,
            },
            "user_corrections": 0,
            "signals_detected": 0,
            "observer_deep_analyses": 0,
            "architect_proposals": 0,
            "modifications_executed": 0,
            "modifications_rolled_back": 0,
        }
