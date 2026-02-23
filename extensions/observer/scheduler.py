"""Observer scheduling logic for daily and emergency deep analysis."""

from __future__ import annotations

from datetime import datetime, timedelta

from .engine import ObserverEngine


class ObserverScheduler:
    """Manage deep analysis trigger checks (daily window + emergency)."""

    def __init__(
        self,
        observer: ObserverEngine,
        signal_store,
        metrics,
        config: dict,
    ):
        """
        Args:
            observer: observer engine instance.
            signal_store: store with ``count_recent`` API.
            metrics: metrics tracker instance (reserved for extension).
            config: scheduler config, e.g. ``{"daily_time":"02:00","emergency_threshold":3}``.
        """
        self.observer = observer
        self.signal_store = signal_store
        self.metrics = metrics
        self.config = config or {}
        self.daily_time = str(self.config.get("daily_time", "02:00"))
        self.emergency_threshold = int(self.config.get("emergency_threshold", 3))
        self._daily_done_date: str | None = None

    async def check_and_run(self) -> dict | None:
        """
        Run deep analysis if any trigger condition is met.

        Trigger conditions:
        1. Current time is within daily_time ±30 min and today not yet done.
        2. CRITICAL signal count in last 24h >= emergency_threshold.
        """
        critical_count = 0
        try:
            critical_count = int(self.signal_store.count_recent(priority="CRITICAL", hours=24))
        except Exception:
            critical_count = 0

        if critical_count >= self.emergency_threshold:
            return await self.observer.deep_analyze(trigger="emergency")

        now = datetime.now()
        if self._is_in_daily_window(now) and self._daily_done_date != now.date().isoformat():
            report = await self.observer.deep_analyze(trigger="daily")
            self.mark_daily_done()
            return report

        return None

    def get_next_run_time(self) -> str:
        """Return next planned daily run time in ISO 8601."""
        now = datetime.now()
        hour, minute = self._parse_daily_time()
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate.isoformat()

    def mark_daily_done(self):
        """Mark today's daily deep analysis as completed."""
        self._daily_done_date = datetime.now().date().isoformat()

    def _is_in_daily_window(self, now: datetime) -> bool:
        """Check whether ``now`` falls in [daily_time-30m, daily_time+30m], crossing midnight safely."""
        hour, minute = self._parse_daily_time()
        now_minutes = now.hour * 60 + now.minute
        target_minutes = hour * 60 + minute
        # Circular distance on a 24h clock to correctly handle cross-day windows.
        minute_delta = abs(now_minutes - target_minutes)
        minute_delta = min(minute_delta, 1440 - minute_delta)
        return minute_delta <= 30

    def _parse_daily_time(self) -> tuple[int, int]:
        """Parse configured HH:MM daily time with safe fallback."""
        try:
            hour_s, minute_s = self.daily_time.split(":", 1)
            hour = max(0, min(23, int(hour_s)))
            minute = max(0, min(59, int(minute_s)))
            return hour, minute
        except Exception:
            return 2, 0
