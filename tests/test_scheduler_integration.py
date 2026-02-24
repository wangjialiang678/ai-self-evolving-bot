"""集成测试：验证 run_scheduler 替换为 CronService + HeartbeatService 后的行为。

覆盖三个核心场景：
1. CronService 正确注册了 3 个 job
2. HeartbeatService 正确初始化
3. 旧的 run_scheduler 仍可调用（deprecated 但未删除）
"""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.channels.cron import CronService
from core.channels.heartbeat import HeartbeatService
from core.config import EvoConfig


# ──────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────

def _make_app(tmp_path: Path) -> dict:
    """构造与 build_app 结构一致的 mock app dict。"""
    config = EvoConfig()

    agent_loop = MagicMock()
    agent_loop.run_deep_analysis = AsyncMock(return_value={})
    agent_loop.get_daily_summary = AsyncMock(return_value=None)
    agent_loop.process_message = AsyncMock(return_value={"system_response": "ok"})

    architect = MagicMock()
    architect.analyze_and_propose = AsyncMock(return_value=[])
    architect.execute_proposal = AsyncMock(return_value={"status": "ok"})

    cron_service = CronService()
    heartbeat_service = HeartbeatService(
        workspace=tmp_path,
        on_heartbeat=agent_loop.process_message,
        interval_s=config.heartbeat_interval,
    )

    return {
        "config": config,
        "workspace": tmp_path,
        "agent_loop": agent_loop,
        "architect": architect,
        "telegram": None,
        "cron_service": cron_service,
        "heartbeat_service": heartbeat_service,
    }


def _register_cron_jobs(app: dict) -> CronService:
    """复现 async_main 中的 cron 注册逻辑。"""
    config: EvoConfig = app["config"]
    agent_loop = app["agent_loop"]
    architect = app["architect"]
    cron_service: CronService = app["cron_service"]

    async def _observer_deep():
        await agent_loop.run_deep_analysis(trigger="daily")

    async def _architect_run():
        proposals = await architect.analyze_and_propose()
        for proposal in proposals:
            await architect.execute_proposal(proposal)

    async def _daily_briefing():
        pass  # telegram=None，跳过

    cron_service.register("observer_deep", config.observer_cron, _observer_deep)
    cron_service.register("architect_run", config.architect_cron, _architect_run)
    cron_service.register("daily_briefing", config.briefing_cron, _daily_briefing)

    return cron_service


# ──────────────────────────────────────
# 1. CronService 正确注册了 3 个 job
# ──────────────────────────────────────

class TestCronJobRegistration:
    def test_registers_exactly_three_jobs(self, tmp_path):
        """async_main 逻辑为 CronService 注册恰好 3 个任务。"""
        app = _make_app(tmp_path)
        cron_service = _register_cron_jobs(app)
        assert len(cron_service._jobs) == 3

    def test_job_names_are_correct(self, tmp_path):
        """3 个任务的名称符合预期。"""
        app = _make_app(tmp_path)
        cron_service = _register_cron_jobs(app)
        names = {job.name for job in cron_service._jobs}
        assert names == {"observer_deep", "architect_run", "daily_briefing"}

    def test_job_cron_expressions_match_config(self, tmp_path):
        """3 个任务使用 EvoConfig 中的 cron 表达式。"""
        app = _make_app(tmp_path)
        config: EvoConfig = app["config"]
        cron_service = _register_cron_jobs(app)

        expr_map = {job.name: job.cron_expr for job in cron_service._jobs}
        assert expr_map["observer_deep"] == config.observer_cron
        assert expr_map["architect_run"] == config.architect_cron
        assert expr_map["daily_briefing"] == config.briefing_cron

    def test_default_cron_values(self):
        """EvoConfig 默认 cron 表达式符合规划（凌晨 2/3 点 + 早 8:30）。"""
        config = EvoConfig()
        assert config.observer_cron == "0 2 * * *"
        assert config.architect_cron == "0 3 * * *"
        assert config.briefing_cron == "30 8 * * *"

    async def test_cron_service_start_stop(self, tmp_path):
        """CronService 注册任务后可以正常启动和停止。"""
        app = _make_app(tmp_path)
        cron_service = _register_cron_jobs(app)

        await cron_service.start()
        assert cron_service.is_running
        await cron_service.stop()
        assert not cron_service.is_running


# ──────────────────────────────────────
# 2. HeartbeatService 正确初始化
# ──────────────────────────────────────

class TestHeartbeatServiceInit:
    def test_heartbeat_service_present_in_app(self, tmp_path):
        """app dict 包含 heartbeat_service 键。"""
        app = _make_app(tmp_path)
        assert "heartbeat_service" in app
        assert isinstance(app["heartbeat_service"], HeartbeatService)

    def test_interval_matches_config(self, tmp_path):
        """HeartbeatService.interval_s 与 EvoConfig.heartbeat_interval 一致。"""
        config = EvoConfig()
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        assert hb.interval_s == config.heartbeat_interval

    def test_default_heartbeat_interval(self):
        """EvoConfig 默认心跳间隔为 1800 秒（30 分钟）。"""
        config = EvoConfig()
        assert config.heartbeat_interval == 1800

    def test_workspace_set_correctly(self, tmp_path):
        """HeartbeatService.workspace 指向正确的工作目录。"""
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        assert hb.workspace == tmp_path

    def test_callback_is_process_message(self, tmp_path):
        """HeartbeatService 的回调绑定到 agent_loop.process_message。"""
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        agent_loop = app["agent_loop"]
        assert hb.on_heartbeat is agent_loop.process_message

    def test_not_running_before_start(self, tmp_path):
        """HeartbeatService 在调用 start() 前 is_running 为 False。"""
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        assert not hb.is_running

    async def test_running_after_start(self, tmp_path):
        """HeartbeatService.start() 后 is_running 变为 True。"""
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        await hb.start()
        try:
            assert hb.is_running
        finally:
            await hb.stop()

    async def test_stopped_after_stop(self, tmp_path):
        """HeartbeatService.stop() 后 is_running 变为 False。"""
        app = _make_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        await hb.start()
        await hb.stop()
        assert not hb.is_running


# ──────────────────────────────────────
# 3. run_scheduler 仍可调用（deprecated 但未删除）
# ──────────────────────────────────────

class TestRunSchedulerDeprecated:
    def test_run_scheduler_still_exists(self):
        """run_scheduler 函数仍然存在于 main 模块中（backward compat）。"""
        import main as main_module
        assert hasattr(main_module, "run_scheduler"), (
            "run_scheduler 已被删除，应保留并标记 DEPRECATED"
        )

    def test_run_scheduler_is_coroutine_function(self):
        """run_scheduler 仍是异步函数，签名未被破坏。"""
        import main as main_module
        assert inspect.iscoroutinefunction(main_module.run_scheduler), (
            "run_scheduler 应是 async def"
        )

    def test_run_scheduler_has_deprecated_comment(self):
        """run_scheduler 定义上方有 DEPRECATED 注释。"""
        import main as main_module
        source_file = inspect.getfile(main_module.run_scheduler)
        with open(source_file, "r", encoding="utf-8") as f:
            full_source = f.read()

        idx = full_source.find("async def run_scheduler")
        assert idx > 0, "找不到 run_scheduler 函数定义"
        preceding = full_source[max(0, idx - 300): idx]
        assert "DEPRECATED" in preceding, (
            "run_scheduler 函数上方缺少 DEPRECATED 注释"
        )

    def test_async_main_does_not_use_run_scheduler(self):
        """async_main 源码中不包含 run_scheduler 的 create_task 调用。"""
        import main as main_module
        source = inspect.getsource(main_module.async_main)
        assert "run_scheduler" not in source, (
            "async_main 中仍调用 run_scheduler，应已替换为 CronService"
        )

    async def test_run_scheduler_callable_with_stop_event(self, tmp_path):
        """run_scheduler 可以被调用并在 stop_event 设置后正常退出。"""
        import main as main_module

        config = EvoConfig()
        app = _make_app(tmp_path)
        stop_event = asyncio.Event()

        # 立即触发停止，避免等待 60 秒轮询
        stop_event.set()

        # 不应抛出异常
        await main_module.run_scheduler(app, stop_event)
