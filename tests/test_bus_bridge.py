"""Bus 桥接集成测试。"""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest

from core.channels.bus import MessageBus, InboundMessage
from core.channels.manager import ChannelManager


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def mock_app(bus):
    """构造模拟的 app dict。"""
    agent_loop = MagicMock()
    agent_loop.process_message = AsyncMock(return_value={"system_response": "回复内容"})

    bootstrap = MagicMock()
    bootstrap.is_bootstrapped.return_value = True

    architect = MagicMock()

    telegram_outbound = MagicMock()
    telegram_outbound.handle_callback = AsyncMock(return_value=None)

    channel_manager = ChannelManager(bus)

    # Mock channel
    mock_channel = MagicMock()
    mock_channel.name = "telegram"
    mock_channel.send_message = AsyncMock()
    mock_channel.is_running = True
    channel_manager._channels = [mock_channel]

    return {
        "bus": bus,
        "agent_loop": agent_loop,
        "bootstrap": bootstrap,
        "architect": architect,
        "telegram": telegram_outbound,
        "channel_manager": channel_manager,
    }


class TestBusBridge:
    @pytest.mark.asyncio
    async def test_normal_message_routed_to_agent_loop(self, bus, mock_app):
        """正常消息被路由到 agent_loop.process_message()。"""
        from main import run_bus_bridge

        stop_event = asyncio.Event()

        # 发布一条消息
        await bus.publish_inbound(InboundMessage(
            channel="telegram", user_id="111", text="你好",
            metadata={"message_id": 1}
        ))

        # 在消息处理后立即停止
        async def stop_after_processing():
            await asyncio.sleep(0.1)
            stop_event.set()

        asyncio.create_task(stop_after_processing())
        await run_bus_bridge(mock_app, stop_event)

        mock_app["agent_loop"].process_message.assert_awaited_once_with("你好")
        # 验证回复被发送
        mock_channel = mock_app["channel_manager"].get_channel("telegram")
        mock_channel.send_message.assert_awaited_once_with("111", "回复内容")

    @pytest.mark.asyncio
    async def test_callback_routed_to_approval(self, bus, mock_app):
        """callback_data 消息路由到审批处理。"""
        from main import run_bus_bridge

        mock_app["telegram"].handle_callback = AsyncMock(
            return_value={"action": "approve", "proposal_id": "prop_001"}
        )
        mock_app["architect"]._load_proposal = MagicMock(return_value={"id": "prop_001"})
        mock_app["architect"].execute_proposal = AsyncMock(
            return_value={"status": "success"}
        )

        stop_event = asyncio.Event()
        await bus.publish_inbound(InboundMessage(
            channel="telegram", user_id="111", text="approve:prop_001",
            metadata={"callback_data": "approve:prop_001"}
        ))

        async def stop_after():
            await asyncio.sleep(0.1)
            stop_event.set()
        asyncio.create_task(stop_after())
        await run_bus_bridge(mock_app, stop_event)

        mock_app["telegram"].handle_callback.assert_awaited_once_with("approve:prop_001")
        mock_app["architect"].execute_proposal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bootstrap_routing(self, bus, mock_app):
        """未完成 Bootstrap 时消息路由到引导流程。"""
        from main import run_bus_bridge

        mock_app["bootstrap"].is_bootstrapped.return_value = False
        mock_app["bootstrap"].get_current_stage.return_value = "background"
        mock_app["bootstrap"].get_stage_prompt = MagicMock(return_value="请介绍你自己")
        mock_app["bootstrap"].process_stage = AsyncMock(
            return_value={"prompt": "下一个问题"}
        )

        stop_event = asyncio.Event()
        await bus.publish_inbound(InboundMessage(
            channel="telegram", user_id="111", text="我是开发者",
            metadata={}
        ))

        async def stop_after():
            await asyncio.sleep(0.1)
            stop_event.set()
        asyncio.create_task(stop_after())

        with patch("main._parse_bootstrap_input", new_callable=AsyncMock, return_value={"raw_input": "我是开发者"}):
            await run_bus_bridge(mock_app, stop_event)

        mock_app["bootstrap"].process_stage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_bus_respects_stop(self, bus, mock_app):
        """空 bus 时正确响应 stop_event。"""
        from main import run_bus_bridge

        stop_event = asyncio.Event()

        async def stop_soon():
            await asyncio.sleep(0.2)
            stop_event.set()

        asyncio.create_task(stop_soon())
        await run_bus_bridge(mock_app, stop_event)
        # 不应挂起，正常退出

    @pytest.mark.asyncio
    async def test_bootstrap_not_started(self, bus, mock_app):
        """Bootstrap 尚未开始时发送初始提示。"""
        from main import run_bus_bridge

        mock_app["bootstrap"].is_bootstrapped.return_value = False
        mock_app["bootstrap"].get_current_stage.return_value = "not_started"
        mock_app["bootstrap"]._save_state = MagicMock()
        mock_app["bootstrap"].get_stage_prompt = MagicMock(return_value="欢迎！请介绍你自己。")

        stop_event = asyncio.Event()
        await bus.publish_inbound(InboundMessage(
            channel="telegram", user_id="111", text="hi",
            metadata={}
        ))

        async def stop_after():
            await asyncio.sleep(0.1)
            stop_event.set()
        asyncio.create_task(stop_after())
        await run_bus_bridge(mock_app, stop_event)

        mock_app["bootstrap"]._save_state.assert_called_once()
        mock_channel = mock_app["channel_manager"].get_channel("telegram")
        mock_channel.send_message.assert_awaited_once_with("111", "欢迎！请介绍你自己。")
