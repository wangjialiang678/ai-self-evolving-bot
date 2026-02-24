"""Tests for CronService。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.channels.cron import CronJob, CronService, _compute_next_run_ms, _now_ms


class TestCronJob:
    def test_register_adds_job(self):
        """register() 后任务列表增加。"""
        svc = CronService()
        assert len(svc._jobs) == 0

        svc.register("job1", "* * * * *", AsyncMock())
        assert len(svc._jobs) == 1
        assert svc._jobs[0].name == "job1"
        assert svc._jobs[0].cron_expr == "* * * * *"

    def test_register_multiple_jobs(self):
        """可以注册多个任务。"""
        svc = CronService()
        svc.register("job1", "* * * * *", AsyncMock())
        svc.register("job2", "0 * * * *", AsyncMock())
        assert len(svc._jobs) == 2


class TestCronExprParsing:
    def test_every_minute_expr(self):
        """'* * * * *' 每分钟触发，下次执行在 60 秒内。"""
        now_ms = _now_ms()
        next_ms = _compute_next_run_ms("* * * * *", now_ms)
        assert next_ms is not None
        diff_s = (next_ms - now_ms) / 1000
        # 下次执行时间应在 1~60 秒之间
        assert 0 < diff_s <= 60

    def test_hourly_expr(self):
        """'0 * * * *' 每小时触发，下次执行在 3600 秒内。"""
        now_ms = _now_ms()
        next_ms = _compute_next_run_ms("0 * * * *", now_ms)
        assert next_ms is not None
        diff_s = (next_ms - now_ms) / 1000
        assert 0 < diff_s <= 3600

    def test_invalid_expr_returns_none(self):
        """无效的 cron 表达式返回 None，不抛出异常。"""
        result = _compute_next_run_ms("not-a-cron", _now_ms())
        assert result is None


class TestLifecycle:
    async def test_start_sets_running(self):
        """start() 后 is_running 为 True。"""
        svc = CronService()
        assert not svc.is_running

        await svc.start()
        try:
            assert svc.is_running
            assert svc._task is not None
        finally:
            await svc.stop()

    async def test_stop_clears_running(self):
        """stop() 后 is_running 为 False。"""
        svc = CronService()
        await svc.start()
        await svc.stop()
        assert not svc.is_running
        assert svc._task is None

    async def test_start_idempotent(self):
        """重复 start() 不会创建多个 task。"""
        svc = CronService()
        await svc.start()
        task1 = svc._task
        await svc.start()
        task2 = svc._task
        try:
            assert task1 is task2
        finally:
            await svc.stop()

    async def test_start_computes_next_run(self):
        """start() 后所有任务都有下次执行时间。"""
        svc = CronService()
        svc.register("job1", "* * * * *", AsyncMock())
        await svc.start()
        try:
            assert svc._jobs[0]._next_run_ms is not None
        finally:
            await svc.stop()


class TestCallbackExecution:
    async def test_callback_called_when_due(self):
        """到期的任务回调被正确调用。"""
        svc = CronService()
        callback = AsyncMock()
        svc.register("test-job", "* * * * *", callback)

        # 手动将 _next_run_ms 设置为过去，模拟到期
        await svc.start()
        svc._jobs[0]._next_run_ms = _now_ms() - 1000  # 1 秒前

        # 直接调用 _tick 触发执行
        await svc._tick()
        await svc.stop()

        callback.assert_called_once()

    async def test_callback_not_called_when_not_due(self):
        """未到期的任务不触发回调。"""
        svc = CronService()
        callback = AsyncMock()
        svc.register("test-job", "* * * * *", callback)
        await svc.start()

        # _next_run_ms 在未来，不应触发
        svc._jobs[0]._next_run_ms = _now_ms() + 60_000  # 60 秒后

        await svc._tick()
        await svc.stop()

        callback.assert_not_called()

    async def test_callback_exception_does_not_stop_scheduler(self):
        """回调抛出异常不中断调度器，后续任务仍然执行。"""
        svc = CronService()

        bad_callback = AsyncMock(side_effect=RuntimeError("boom"))
        good_callback = AsyncMock()

        svc.register("bad-job", "* * * * *", bad_callback)
        svc.register("good-job", "* * * * *", good_callback)

        await svc.start()

        # 两个任务都设为到期
        now = _now_ms()
        svc._jobs[0]._next_run_ms = now - 1000
        svc._jobs[1]._next_run_ms = now - 1000

        # _tick 不应抛出
        await svc._tick()
        await svc.stop()

        # 异常任务被调用了
        bad_callback.assert_called_once()
        # 正常任务也被调用了
        good_callback.assert_called_once()

    async def test_next_run_updated_after_execution(self):
        """任务执行后 _next_run_ms 更新为下一个时间点。"""
        svc = CronService()
        callback = AsyncMock()
        svc.register("test-job", "* * * * *", callback)
        await svc.start()

        old_next = _now_ms() - 1000
        svc._jobs[0]._next_run_ms = old_next

        await svc._tick()
        await svc.stop()

        # 下次执行时间应该更新为新值（> old_next）
        assert svc._jobs[0]._next_run_ms is not None
        assert svc._jobs[0]._next_run_ms > old_next

    async def test_no_duplicate_execution(self):
        """同一个 tick 内同一任务不会被执行两次。"""
        svc = CronService()
        callback = AsyncMock()
        svc.register("test-job", "* * * * *", callback)
        await svc.start()

        svc._jobs[0]._next_run_ms = _now_ms() - 1000

        # 连续两次 tick
        await svc._tick()
        await svc._tick()
        await svc.stop()

        # 第一次 tick 后 _next_run_ms 已更新到未来，第二次不再触发
        assert callback.call_count == 1
