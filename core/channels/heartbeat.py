"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Default interval: 30 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# Prefixes that mark checkbox list items (regardless of trailing label)
_CHECKBOX_PREFIXES = ("- [ ]", "* [ ]", "- [x]", "* [x]")


def _is_heartbeat_empty(content: str | None) -> bool:
    """Return True if HEARTBEAT.md has no actionable content."""
    if not content:
        return True

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("<!--"):
            continue
        if any(line.startswith(pfx) for pfx in _CHECKBOX_PREFIXES):
            continue
        return False  # Found actionable content

    return True


class HeartbeatService:
    """定时读取 HEARTBEAT.md，生成心跳消息。"""

    def __init__(
        self,
        workspace: str | Path,
        on_heartbeat: Callable[[str], Awaitable[None]],
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        self.workspace = Path(workspace)
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    @property
    def is_running(self) -> bool:
        return self._running

    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md content, returning None if missing or unreadable."""
        if not self.heartbeat_file.exists():
            return None
        try:
            return self.heartbeat_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read %s: %s", self.heartbeat_file, exc)
            return None

    async def start(self) -> None:
        """启动心跳定时器。"""
        if self._running:
            logger.debug("HeartbeatService already running, skipping start")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("HeartbeatService started (interval=%ds)", self.interval_s)

    async def stop(self) -> None:
        """停止心跳定时器。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("HeartbeatService stopped")

    async def _run_loop(self) -> None:
        """Main heartbeat loop: sleep → tick → repeat."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("HeartbeatService tick error: %s", exc)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()

        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat tick: HEARTBEAT.md empty or missing, skipping")
            return

        logger.info("Heartbeat tick: actionable content found, invoking callback")
        try:
            await self.on_heartbeat(content)  # type: ignore[arg-type]
        except Exception as exc:
            logger.error("Heartbeat callback raised an error: %s", exc)
