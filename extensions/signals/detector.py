"""Signal detection logic from reflection output and historical patterns."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from .store import SignalStore

logger = logging.getLogger(__name__)


class SignalDetector:
    """Detects task-level and cross-task signals."""

    def __init__(self, signal_store: SignalStore):
        """
        Args:
            signal_store: Signal persistence backend.
        """
        self.signal_store = signal_store

    def detect(self, reflection_output: dict, task_context: dict) -> list[dict]:
        """
        Detect signals from one task reflection and context.

        Rules:
        1. ``user_corrections > 0`` -> ``user_correction`` (MEDIUM)
        2. ``type == ERROR`` and ``outcome == FAILURE`` -> ``task_failure`` (HIGH)
        3. ``type == NONE`` and ``outcome == SUCCESS`` and rules_used -> ``rule_validated`` (LOW)
        4. ``tokens_used > 10000`` -> ``efficiency_opportunity`` (LOW)
        """
        task_id = str(reflection_output.get("task_id", "unknown_task"))
        output_type = str(reflection_output.get("type", "NONE")).upper()
        outcome = str(reflection_output.get("outcome", "SUCCESS")).upper()
        user_corrections = int(task_context.get("user_corrections", 0) or 0)
        tokens_used = int(task_context.get("tokens_used", 0) or 0)
        lesson = str(reflection_output.get("lesson", "") or "")
        root_cause = reflection_output.get("root_cause")

        detected: list[dict] = []

        if user_corrections > 0:
            detected.append(
                self._make_signal(
                    signal_type="user_correction",
                    priority="MEDIUM",
                    source=f"reflection:{task_id}",
                    description=f"User corrected output ({user_corrections} time(s)).",
                    related_tasks=[task_id],
                )
            )

        if output_type == "ERROR" and outcome == "FAILURE":
            desc = "Task failed due to detected execution error."
            if root_cause:
                desc += f" root_cause={root_cause}"
            if lesson:
                desc += f" lesson={lesson}"
            detected.append(
                self._make_signal(
                    signal_type="task_failure",
                    priority="HIGH",
                    source=f"reflection:{task_id}",
                    description=desc,
                    related_tasks=[task_id],
                )
            )

        rules_used = task_context.get("rules_used")
        if output_type == "NONE" and outcome == "SUCCESS" and rules_used:
            detected.append(
                self._make_signal(
                    signal_type="rule_validated",
                    priority="LOW",
                    source=f"reflection:{task_id}",
                    description="Rule-assisted task completed successfully.",
                    related_tasks=[task_id],
                )
            )

        if tokens_used > 10_000:
            detected.append(
                self._make_signal(
                    signal_type="efficiency_opportunity",
                    priority="LOW",
                    source=f"reflection:{task_id}",
                    description=f"High token usage detected: {tokens_used}.",
                    related_tasks=[task_id],
                )
            )

        for signal in detected:
            self.signal_store.add(signal)
        return detected

    def detect_patterns(self, lookback_hours: int = 168) -> list[dict]:
        """
        Detect cross-task patterns from historical signals/events.

        Rules:
        1. ``task_failure`` count in lookback >= 2 -> ``repeated_error`` (HIGH)
        2. From metrics events: 3-day success rate drop > 15% -> ``performance_degradation`` (CRITICAL)
        3. ``user_pattern`` signals in lookback >= 3 -> emit promoted ``user_pattern`` (MEDIUM)
        """
        lookback_hours = max(lookback_hours, 1)
        window_start = datetime.now() - timedelta(hours=lookback_hours)
        created: list[dict] = []

        recent_active = [
            row
            for row in self.signal_store.get_active()
            if (ts := self._parse_ts(row.get("timestamp"))) is not None and ts >= window_start
        ]

        failures = [s for s in recent_active if s.get("signal_type") == "task_failure"]
        if len(failures) >= 2 and not self._has_recent_pattern_signal(
            recent_active,
            signal_type="repeated_error",
            source="patterns:task_failure",
        ):
            related = []
            for signal in failures:
                for task in signal.get("related_tasks", []):
                    if task not in related:
                        related.append(task)
            created.append(
                self._make_signal(
                    signal_type="repeated_error",
                    priority="HIGH",
                    source="patterns:task_failure",
                    description=f"Repeated task_failure detected in last {lookback_hours}h ({len(failures)} events).",
                    related_tasks=related,
                )
            )

        user_pattern_events = [s for s in recent_active if s.get("signal_type") == "user_pattern"]
        if len(user_pattern_events) >= 3 and not self._has_recent_pattern_signal(
            recent_active,
            signal_type="user_pattern",
            source="patterns:user_pattern",
        ):
            created.append(
                self._make_signal(
                    signal_type="user_pattern",
                    priority="MEDIUM",
                    source="patterns:user_pattern",
                    description=f"Repeated user pattern detected ({len(user_pattern_events)} events).",
                    related_tasks=[],
                )
            )

        degradation_signal = self._detect_performance_degradation()
        if (
            degradation_signal is not None
            and self._has_recent_pattern_signal(
                recent_active,
                signal_type="performance_degradation",
                source="patterns:metrics",
            )
        ):
            degradation_signal = None
        if degradation_signal is not None:
            created.append(degradation_signal)

        for signal in created:
            self.signal_store.add(signal)
        return created

    def _detect_performance_degradation(self) -> dict | None:
        """
        Detect 3-day success-rate drop from ``metrics/events.jsonl``.

        Returns:
            A ``performance_degradation`` signal if threshold exceeded, else ``None``.
        """
        metrics_events = self._read_metrics_events()
        if not metrics_events:
            return None

        now = datetime.now()
        recent_start = now - timedelta(days=3)
        baseline_start = now - timedelta(days=10)

        recent = {"total": 0, "success": 0}
        baseline = {"total": 0, "success": 0}
        for event in metrics_events:
            if event.get("event_type") != "task":
                continue
            ts = self._parse_ts(event.get("timestamp"))
            if ts is None:
                continue
            if ts >= recent_start:
                bucket = recent
            elif baseline_start <= ts < recent_start:
                bucket = baseline
            else:
                continue
            bucket["total"] += 1
            if str(event.get("outcome", "")).upper() == "SUCCESS":
                bucket["success"] += 1

        baseline_rate = (baseline["success"] / baseline["total"]) if baseline["total"] > 0 else 0.0
        if baseline_rate <= 0:
            return None
        recent_rate = (recent["success"] / recent["total"]) if recent["total"] > 0 else 0.0
        drop_ratio = (baseline_rate - recent_rate) / baseline_rate
        if drop_ratio <= 0.15:
            return None

        return self._make_signal(
            signal_type="performance_degradation",
            priority="CRITICAL",
            source="patterns:metrics",
            description=(
                "3-day success rate degraded by "
                f"{drop_ratio:.1%} vs previous 7-day baseline."
            ),
            related_tasks=[],
        )

    def _read_metrics_events(self) -> list[dict]:
        """Read metrics events if ``workspace/metrics/events.jsonl`` exists."""
        metrics_path = self.signal_store.signals_dir.parent / "metrics" / "events.jsonl"
        if not metrics_path.exists():
            return []

        rows: list[dict] = []
        try:
            with metrics_path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid metrics event line skipped")
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to read metrics events: %s", exc)
            return []
        return rows

    @staticmethod
    def _has_recent_pattern_signal(rows: list[dict], signal_type: str, source: str) -> bool:
        """Return True when same pattern signal already exists in current window."""
        for row in rows:
            if row.get("signal_type") == signal_type and row.get("source") == source:
                return True
        return False

    @staticmethod
    def _parse_ts(value: str | None) -> datetime | None:
        """Safe ISO timestamp parse helper."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _make_signal(
        signal_type: str,
        priority: str,
        source: str,
        description: str,
        related_tasks: list[str],
    ) -> dict:
        """Build one signal payload with generated id/timestamp."""
        return {
            "signal_id": f"sig_{uuid4().hex[:8]}",
            "signal_type": signal_type,
            "priority": priority,
            "source": source,
            "description": description,
            "related_tasks": related_tasks,
            "timestamp": datetime.now().replace(microsecond=0).isoformat(),
            "status": "active",
        }
