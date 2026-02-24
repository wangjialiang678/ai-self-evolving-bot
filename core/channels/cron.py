"""Cron 定时任务服务。"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run_ms(cron_expr: str, now_ms: int) -> int | None:
    """使用 croniter 计算 cron 表达式的下次执行时间（毫秒）。"""
    try:
        from croniter import croniter

        base_dt = datetime.fromtimestamp(now_ms / 1000)
        cron = croniter(cron_expr, base_dt)
        next_dt = cron.get_next(datetime)
        return int(next_dt.timestamp() * 1000)
    except Exception as e:
        logger.warning(f"无法解析 cron 表达式 '{cron_expr}': {e}")
        return None


@dataclass
class CronJob:
    """一个 cron 定时任务。"""

    name: str
    cron_expr: str
    callback: Callable[[], Awaitable[None]]
    _next_run_ms: int | None = field(default=None, init=False, repr=False)
    _last_run_ms: int | None = field(default=None, init=False, repr=False)

    def schedule_next(self, from_ms: int | None = None) -> None:
        """计算并存储下次执行时间。"""
        self._next_run_ms = _compute_next_run_ms(
            self.cron_expr, from_ms if from_ms is not None else _now_ms()
        )


class CronService:
    """基于 cron 表达式的定时任务服务。"""

    # 轮询间隔（秒），每 30 秒检查一次
    _POLL_INTERVAL = 30

    def __init__(self) -> None:
        self._jobs: list[CronJob] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def register(
        self,
        name: str,
        cron_expr: str,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        """注册一个 cron 任务。必须在 start() 之前调用。"""
        job = CronJob(name=name, cron_expr=cron_expr, callback=callback)
        self._jobs.append(job)
        logger.debug(f"Cron: 已注册任务 '{name}' ({cron_expr})")

    async def start(self) -> None:
        """启动 cron 调度器。"""
        if self._running:
            return

        self._running = True

        # 计算所有任务的首次执行时间
        now = _now_ms()
        for job in self._jobs:
            job.schedule_next(from_ms=now)

        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")
        logger.info(f"Cron 调度器已启动，共 {len(self._jobs)} 个任务")

    async def stop(self) -> None:
        """停止 cron 调度器。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cron 调度器已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ──────────────────────────────────────────
    # 内部实现
    # ──────────────────────────────────────────

    async def _loop(self) -> None:
        """后台循环：每 30 秒检查并触发到期任务。"""
        while self._running:
            await self._tick()
            try:
                await asyncio.sleep(self._POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """检查所有任务，执行到期的任务。"""
        now = _now_ms()
        for job in list(self._jobs):
            if job._next_run_ms is not None and now >= job._next_run_ms:
                # 先更新上次执行时间，再计算下次，防止重复执行
                job._last_run_ms = now
                job.schedule_next(from_ms=now)
                await self._run_job(job)

    async def _run_job(self, job: CronJob) -> None:
        """执行单个任务，捕获异常保证调度器不中断。"""
        logger.info(f"Cron: 执行任务 '{job.name}'")
        try:
            await job.callback()
            logger.debug(f"Cron: 任务 '{job.name}' 完成")
        except Exception as e:
            logger.error(f"Cron: 任务 '{job.name}' 失败: {e}", exc_info=True)
