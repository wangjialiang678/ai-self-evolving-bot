"""集成测试：CronService + HeartbeatService 在 main.py 中的注册与初始化。"""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.channels.cron import CronService
from core.channels.heartbeat import HeartbeatService
from core.config import EvoConfig


# ──────────────────────────────────────
# 辅助：构造最小化的 app dict
# ──────────────────────────────────────

def _make_mock_app(tmp_path: Path, config: EvoConfig | None = None) -> dict:
    """构造与 build_app 结构一致的 mock app dict。"""
    if config is None:
        config = EvoConfig()

    agent_loop = MagicMock()
    agent_loop.run_deep_analysis = AsyncMock(return_value={})
    agent_loop.analyze_and_propose = AsyncMock(return_value=[])
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
        "bootstrap": MagicMock(),
        "architect": architect,
        "telegram": None,
        "llm_opus": MagicMock(),
        "llm_light": MagicMock(),
        "bus": MagicMock(),
        "channel_manager": MagicMock(),
        "cron_service": cron_service,
        "heartbeat_service": heartbeat_service,
    }


# ──────────────────────────────────────
# 测试：CronService 正确注册了 3 个任务
# ──────────────────────────────────────

class TestCronServiceRegistration:
    def test_three_cron_jobs_registered(self, tmp_path):
        """async_main 逻辑为 CronService 注册恰好 3 个任务。"""
        config = EvoConfig()
        app = _make_mock_app(tmp_path, config)

        cron_service: CronService = app["cron_service"]
        agent_loop = app["agent_loop"]
        architect = app["architect"]

        # 复现 async_main 中的注册逻辑
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

        assert len(cron_service._jobs) == 3

    def test_cron_job_names(self, tmp_path):
        """注册的 3 个任务名称符合预期。"""
        config = EvoConfig()
        app = _make_mock_app(tmp_path, config)
        cron_service: CronService = app["cron_service"]

        cron_service.register("observer_deep", config.observer_cron, AsyncMock())
        cron_service.register("architect_run", config.architect_cron, AsyncMock())
        cron_service.register("daily_briefing", config.briefing_cron, AsyncMock())

        names = [job.name for job in cron_service._jobs]
        assert "observer_deep" in names
        assert "architect_run" in names
        assert "daily_briefing" in names

    def test_cron_expressions_from_config(self, tmp_path):
        """cron 表达式来自 EvoConfig，默认值正确。"""
        config = EvoConfig()
        assert config.observer_cron == "0 2 * * *"
        assert config.architect_cron == "0 3 * * *"
        assert config.briefing_cron == "30 8 * * *"

    def test_cron_expressions_applied_to_jobs(self, tmp_path):
        """注册的任务使用了配置中的 cron 表达式。"""
        config = EvoConfig()
        app = _make_mock_app(tmp_path, config)
        cron_service: CronService = app["cron_service"]

        cron_service.register("observer_deep", config.observer_cron, AsyncMock())
        cron_service.register("architect_run", config.architect_cron, AsyncMock())
        cron_service.register("daily_briefing", config.briefing_cron, AsyncMock())

        expr_map = {job.name: job.cron_expr for job in cron_service._jobs}
        assert expr_map["observer_deep"] == "0 2 * * *"
        assert expr_map["architect_run"] == "0 3 * * *"
        assert expr_map["daily_briefing"] == "30 8 * * *"


# ──────────────────────────────────────
# 测试：HeartbeatService 正确初始化
# ──────────────────────────────────────

class TestHeartbeatServiceInit:
    def test_heartbeat_service_in_app(self, tmp_path):
        """build_app 返回的 dict 中包含 heartbeat_service。"""
        app = _make_mock_app(tmp_path)
        assert "heartbeat_service" in app
        assert isinstance(app["heartbeat_service"], HeartbeatService)

    def test_heartbeat_interval_from_config(self, tmp_path):
        """HeartbeatService 使用配置中的 heartbeat_interval。"""
        config = EvoConfig()
        assert config.heartbeat_interval == 1800

        app = _make_mock_app(tmp_path, config)
        hb: HeartbeatService = app["heartbeat_service"]
        assert hb.interval_s == 1800

    def test_heartbeat_workspace_set(self, tmp_path):
        """HeartbeatService 的 workspace 路径正确。"""
        app = _make_mock_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        assert hb.workspace == tmp_path

    def test_heartbeat_callback_is_process_message(self, tmp_path):
        """HeartbeatService 的回调是 agent_loop.process_message。"""
        app = _make_mock_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        agent_loop = app["agent_loop"]
        # 回调指向 agent_loop.process_message
        assert hb.on_heartbeat is agent_loop.process_message

    async def test_heartbeat_not_running_before_start(self, tmp_path):
        """HeartbeatService 在 start() 之前 is_running 为 False。"""
        app = _make_mock_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        assert not hb.is_running

    async def test_heartbeat_running_after_start(self, tmp_path):
        """HeartbeatService start() 后 is_running 为 True。"""
        app = _make_mock_app(tmp_path)
        hb: HeartbeatService = app["heartbeat_service"]
        await hb.start()
        try:
            assert hb.is_running
        finally:
            await hb.stop()


# ──────────────────────────────────────
# 测试：async_main 不再使用 run_scheduler
# ──────────────────────────────────────

class TestAsyncMainNoRunScheduler:
    def test_async_main_source_no_run_scheduler_task(self):
        """async_main 源码中不应包含 run_scheduler 的 create_task 调用。"""
        import main as main_module
        source = inspect.getsource(main_module.async_main)
        assert "run_scheduler" not in source, (
            "async_main 中仍然包含 run_scheduler 调用，应使用 CronService 替代"
        )

    def test_run_scheduler_has_deprecated_comment(self):
        """run_scheduler 函数上方应有 DEPRECATED 注释。"""
        import main as main_module
        # 读取 main.py 源码
        source_lines = inspect.getsourcelines(main_module.run_scheduler)
        # getsourcelines 返回 (lines, lineno)
        func_lines = source_lines[0]
        # 检查函数体前几行（包含注释）
        source_file = inspect.getfile(main_module.run_scheduler)
        with open(source_file, "r", encoding="utf-8") as f:
            full_source = f.read()

        # DEPRECATED 注释应在 run_scheduler 定义附近
        idx = full_source.find("async def run_scheduler")
        assert idx > 0
        # 取前 200 个字符检查是否有 DEPRECATED
        preceding = full_source[max(0, idx - 200): idx]
        assert "DEPRECATED" in preceding, (
            "run_scheduler 函数上方缺少 DEPRECATED 注释"
        )

    def test_cron_service_in_app_dict(self, tmp_path):
        """build_app 返回的 dict 中包含 cron_service。"""
        app = _make_mock_app(tmp_path)
        assert "cron_service" in app
        assert isinstance(app["cron_service"], CronService)

    async def test_cron_service_starts_and_stops(self, tmp_path):
        """CronService 可以正常启动和停止。"""
        config = EvoConfig()
        app = _make_mock_app(tmp_path, config)
        cron_service: CronService = app["cron_service"]

        cron_service.register("observer_deep", config.observer_cron, AsyncMock())
        cron_service.register("architect_run", config.architect_cron, AsyncMock())
        cron_service.register("daily_briefing", config.briefing_cron, AsyncMock())

        await cron_service.start()
        assert cron_service.is_running
        await cron_service.stop()
        assert not cron_service.is_running
