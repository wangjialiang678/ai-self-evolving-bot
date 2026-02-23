"""Signal persistence layer backed by JSONL files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


class SignalStore:
    """Signal durable store using ``active.jsonl`` and ``archive.jsonl``."""

    def __init__(self, signals_dir: str):
        """
        Initialize store paths and ensure files exist.

        Args:
            signals_dir: Path to ``workspace/signals``.
        """
        self.signals_dir = Path(signals_dir)
        self.signals_dir.mkdir(parents=True, exist_ok=True)
        self.active_path = self.signals_dir / "active.jsonl"
        self.archive_path = self.signals_dir / "archive.jsonl"
        self.active_path.touch(exist_ok=True)
        self.archive_path.touch(exist_ok=True)

    def add(self, signal: dict) -> None:
        """
        Append one signal to ``active.jsonl``.

        Missing fields are filled automatically:
        - ``signal_id``: ``sig_{uuid8}``
        - ``timestamp``: current ISO 8601 datetime
        - ``status``: ``active``
        """
        payload = dict(signal)
        payload.setdefault("signal_id", f"sig_{uuid4().hex[:8]}")
        payload.setdefault("timestamp", datetime.now().replace(microsecond=0).isoformat())
        payload.setdefault("status", "active")
        try:
            with self.active_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to append active signal: %s", exc)

    def get_active(
        self,
        priority: str | None = None,
        signal_type: str | None = None,
    ) -> list[dict]:
        """
        Read active signals with optional filters.

        Args:
            priority: Filter by priority value.
            signal_type: Filter by signal type.

        Returns:
            Matching signals sorted by descending timestamp.
        """
        signals = []
        for row in self._read_jsonl(self.active_path):
            if row.get("status", "active") != "active":
                continue
            if priority is not None and row.get("priority") != priority:
                continue
            if signal_type is not None and row.get("signal_type") != signal_type:
                continue
            signals.append(row)
        signals.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return signals

    def mark_handled(self, signal_ids: list[str], handler: str) -> None:
        """
        Move selected signals from active to archive.

        Args:
            signal_ids: IDs to mark handled.
            handler: Name of component handling the signal.
        """
        if not signal_ids:
            return

        target_ids = set(signal_ids)
        active_rows = self._read_jsonl(self.active_path)
        keep_rows: list[dict] = []
        handled_rows: list[dict] = []
        handled_at = datetime.now().replace(microsecond=0).isoformat()

        for row in active_rows:
            if row.get("signal_id") in target_ids:
                archived = dict(row)
                archived["status"] = "handled"
                archived["handler"] = handler
                archived["handled_at"] = handled_at
                handled_rows.append(archived)
            else:
                keep_rows.append(row)

        try:
            with self.active_path.open("w", encoding="utf-8") as f:
                for row in keep_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to rewrite active.jsonl: %s", exc)
            return

        if not handled_rows:
            return

        try:
            with self.archive_path.open("a", encoding="utf-8") as f:
                for row in handled_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to append archive.jsonl: %s", exc)

    def count_recent(
        self,
        signal_type: str | None = None,
        priority: str | None = None,
        hours: int = 24,
    ) -> int:
        """
        Count active signals within recent time window.

        Args:
            signal_type: Optional type filter.
            priority: Optional priority filter.
            hours: Time window size.
        """
        now = datetime.now()
        window_start = now - timedelta(hours=max(hours, 0))
        count = 0
        for row in self.get_active(priority=priority, signal_type=signal_type):
            ts = self._parse_timestamp(row.get("timestamp"))
            if ts is None:
                continue
            if ts >= window_start:
                count += 1
        return count

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """Parse an ISO timestamp safely."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Invalid signal timestamp skipped: %s", value)
            return None

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        """Read JSONL rows while tolerating empty or malformed lines."""
        if not path.exists():
            return []

        rows: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSONL line skipped in %s", path)
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to read JSONL file %s: %s", path, exc)
            return []
        return rows
