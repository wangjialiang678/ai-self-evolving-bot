"""端到端双向 Telegram 消息链路集成测试。

验证从 TelegramInboundChannel._on_message / _on_callback 触发，经过
MessageBus，再由 run_bus_bridge 消费并通过通道回复用户的完整链路。
"""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest

from core.channels.bus import MessageBus, InboundMessage
from core.channels.manager import ChannelManager
from core.channels.telegram import TelegramInboundChannel


# ──────────────────────────────────────
#  共用 helpers
# ──────────────────────────────────────

def _make_text_update(chat_id: str, text: str, message_id: int = 1):
    """构造文本消息 Mock Update。"""
    update = MagicMock()
    update.message = MagicMock()
    update.message.chat_id = int(chat_id)
    update.message.text = text
    update.message.message_id = message_id
    update.effective_user = MagicMock()
    update.effective_user.username = "testuser"
    update.callback_query = None
    return update


def _make_callback_update(chat_id: str, callback_data: str):
    """构造 callback_query Mock Update。"""
    update = MagicMock()
    update.message = None
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.chat_id = int(chat_id)
    update.callback_query = query
    update.effective_user = MagicMock()
    return update


def _make_channel(bus: MessageBus, allowed_ids: list[str] | None = None) -> TelegramInboundChannel:
    """创建已绑定 bus 的 TelegramInboundChannel（跳过真实启动）。"""
    ch = TelegramInboundChannel(
        token="test:TOKEN",
        allowed_chat_ids=allowed_ids if allowed_ids is not None else ["111"],
    )
    ch.set_bus(bus)
    ch._running = True
    return ch


def _make_mock_app(bus: MessageBus, channel: TelegramInboundChannel | None = None):
    """构造 run_bus_bridge 所需的 app dict。

    当传入真实的 TelegramInboundChannel 时，会将其 send_message 替换为
    AsyncMock，从而无需启动真实 bot 即可验证发送调用。
    """
    agent_loop = MagicMock()
    agent_loop.process_message = AsyncMock(
        return_value={"system_response": "Agent 回复内容"}
    )

    bootstrap = MagicMock()
    bootstrap.is_bootstrapped.return_value = True

    architect = MagicMock()
    architect._load_proposal = MagicMock()
    architect.execute_proposal = AsyncMock(return_value={"status": "success"})
    architect._update_proposal_status = MagicMock()

    telegram_outbound = MagicMock()
    telegram_outbound.handle_callback = AsyncMock(return_value=None)

    channel_manager = ChannelManager(bus)
    if channel:
        # 将真实通道的 send_message 替换为 AsyncMock，避免依赖真实 bot
        channel.send_message = AsyncMock()
        channel_manager._channels = [channel]
    else:
        mock_ch = MagicMock()
        mock_ch.name = "telegram"
        mock_ch.send_message = AsyncMock()
        channel_manager._channels = [mock_ch]

    return {
        "bus": bus,
        "agent_loop": agent_loop,
        "bootstrap": bootstrap,
        "architect": architect,
        "telegram": telegram_outbound,
        "channel_manager": channel_manager,
    }


async def _run_bridge_then_stop(app: dict, delay: float = 0.15) -> None:
    """启动 run_bus_bridge，等待 delay 秒后自动停止。"""
    from main import run_bus_bridge
    stop_event = asyncio.Event()

    async def _stopper():
        await asyncio.sleep(delay)
        stop_event.set()

    asyncio.create_task(_stopper())
    await run_bus_bridge(app, stop_event)


# ──────────────────────────────────────
#  test_full_message_flow
# ──────────────────────────────────────

class TestFullMessageFlow:
    """用户发消息 → 经 bus → run_bus_bridge → AgentLoop → 通道回复。"""

    @pytest.mark.asyncio
    async def test_full_message_flow(self):
        """完整链路：_on_message 发布到 bus → bridge 消费 → agent_loop → send_message。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)
        app["agent_loop"].process_message = AsyncMock(
            return_value={"system_response": "这是 Agent 的回复"}
        )

        # 模拟用户发送消息，触发 channel 内部处理器
        update = _make_text_update(chat_id="111", text="你好，Agent")
        await channel._on_message(update, None)

        # 此时 bus 中已有 1 条入站消息
        assert bus.inbound_size == 1

        # 运行桥接循环
        await _run_bridge_then_stop(app)

        # 验证 AgentLoop 被调用
        app["agent_loop"].process_message.assert_awaited_once_with("你好，Agent")

        # 验证通道发送了回复（send_message 已在 _make_mock_app 中被替换为 AsyncMock）
        tg_ch = app["channel_manager"].get_channel("telegram")
        tg_ch.send_message.assert_awaited_once_with("111", "这是 Agent 的回复")

    @pytest.mark.asyncio
    async def test_inbound_message_has_correct_fields(self):
        """_on_message 发布的 InboundMessage 字段正确。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=["111"])

        update = _make_text_update(chat_id="111", text="  hello world  ", message_id=42)
        await channel._on_message(update, None)

        msg: InboundMessage = await bus.consume_inbound()
        assert msg.channel == "telegram"
        assert msg.user_id == "111"
        assert msg.text == "hello world"  # strip() 已在 _on_message 中执行
        assert msg.metadata["message_id"] == 42
        assert msg.metadata["username"] == "testuser"


# ──────────────────────────────────────
#  test_bootstrap_flow
# ──────────────────────────────────────

class TestBootstrapFlow:
    """未完成 Bootstrap 时，消息路由到 Bootstrap 流程。"""

    @pytest.mark.asyncio
    async def test_bootstrap_flow_not_started(self):
        """Bootstrap 尚未开始时发送初始提示词，不调用 AgentLoop。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        app["bootstrap"].is_bootstrapped.return_value = False
        app["bootstrap"].get_current_stage.return_value = "not_started"
        app["bootstrap"]._save_state = MagicMock()
        app["bootstrap"].get_stage_prompt = MagicMock(return_value="欢迎！请介绍你自己。")

        # 用户发送触发消息
        update = _make_text_update(chat_id="111", text="你好")
        await channel._on_message(update, None)

        await _run_bridge_then_stop(app)

        # Bootstrap 状态被保存
        app["bootstrap"]._save_state.assert_called_once()
        # 不调用 AgentLoop
        app["agent_loop"].process_message.assert_not_awaited()
        # 通过通道发送引导提示
        tg_ch = app["channel_manager"].get_channel("telegram")
        tg_ch.send_message.assert_awaited_once_with("111", "欢迎！请介绍你自己。")

    @pytest.mark.asyncio
    async def test_bootstrap_flow_in_progress(self):
        """Bootstrap 进行中（background 阶段）时，解析输入并推进阶段。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        app["bootstrap"].is_bootstrapped.return_value = False
        app["bootstrap"].get_current_stage.return_value = "background"
        app["bootstrap"].process_stage = AsyncMock(
            return_value={"prompt": "请告诉我你的项目。"}
        )

        update = _make_text_update(chat_id="111", text="我是 Python 开发者")
        await channel._on_message(update, None)

        with patch(
            "main._parse_bootstrap_input",
            new_callable=AsyncMock,
            return_value={"name": "测试用户", "role": "开发者"},
        ):
            await _run_bridge_then_stop(app)

        app["bootstrap"].process_stage.assert_awaited_once()
        # 不调用 AgentLoop
        app["agent_loop"].process_message.assert_not_awaited()
        # 发送阶段提示
        tg_ch = app["channel_manager"].get_channel("telegram")
        tg_ch.send_message.assert_awaited_once_with("111", "请告诉我你的项目。")


# ──────────────────────────────────────
#  test_approval_callback_flow
# ──────────────────────────────────────

class TestApprovalCallbackFlow:
    """用户点击审批按钮 → callback 经 bus → bridge 路由到 Architect。"""

    @pytest.mark.asyncio
    async def test_approve_callback_executes_proposal(self):
        """approve 回调触发 architect.execute_proposal。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        app["telegram"].handle_callback = AsyncMock(
            return_value={"action": "approve", "proposal_id": "prop_001"}
        )
        fake_proposal = {"proposal_id": "prop_001", "solution": "test fix"}
        app["architect"]._load_proposal = MagicMock(return_value=fake_proposal)
        app["architect"].execute_proposal = AsyncMock(
            return_value={"status": "success"}
        )

        # 模拟用户点击审批按钮，触发 callback
        cb_update = _make_callback_update(chat_id="111", callback_data="approve:prop_001")
        await channel._on_callback(cb_update, None)

        assert bus.inbound_size == 1

        await _run_bridge_then_stop(app)

        # handle_callback 被调用
        app["telegram"].handle_callback.assert_awaited_once_with("approve:prop_001")
        # execute_proposal 被调用
        app["architect"].execute_proposal.assert_awaited_once_with(fake_proposal)
        # 通知用户执行结果
        tg_ch = app["channel_manager"].get_channel("telegram")
        assert tg_ch.send_message.await_count > 0

    @pytest.mark.asyncio
    async def test_reject_callback_updates_status(self):
        """reject 回调触发 architect._update_proposal_status。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        app["telegram"].handle_callback = AsyncMock(
            return_value={"action": "reject", "proposal_id": "prop_002"}
        )

        cb_update = _make_callback_update(chat_id="111", callback_data="reject:prop_002")
        await channel._on_callback(cb_update, None)

        await _run_bridge_then_stop(app)

        app["architect"]._update_proposal_status.assert_called_once_with(
            "prop_002", "rejected"
        )

    @pytest.mark.asyncio
    async def test_callback_without_outbound_channel_skips_gracefully(self):
        """没有 telegram outbound 通道时，callback 被跳过而不崩溃。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)
        app["telegram"] = None  # 模拟无出站通道

        cb_update = _make_callback_update(chat_id="111", callback_data="approve:prop_001")
        await channel._on_callback(cb_update, None)

        # 不应抛出异常
        await _run_bridge_then_stop(app)


# ──────────────────────────────────────
#  test_message_split_long_response
# ──────────────────────────────────────

class TestMessageSplitLongResponse:
    """AgentLoop 返回超长消息时，分段发送。"""

    @pytest.mark.asyncio
    async def test_long_response_split_into_chunks(self):
        """超过 4000 字符的回复被拆分为多段发送。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        # 构造一个 ~8500 字符的回复（约 2 段）
        long_response = "A" * 4000 + "\n" + "B" * 4000
        app["agent_loop"].process_message = AsyncMock(
            return_value={"system_response": long_response}
        )

        update = _make_text_update(chat_id="111", text="请给我详细介绍")
        await channel._on_message(update, None)

        await _run_bridge_then_stop(app)

        tg_ch = app["channel_manager"].get_channel("telegram")
        # 回复次数应 >= 2（至少两段）
        assert tg_ch.send_message.await_count >= 2

    @pytest.mark.asyncio
    async def test_short_response_sent_as_single_chunk(self):
        """短回复只发送一次。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        app["agent_loop"].process_message = AsyncMock(
            return_value={"system_response": "短回复"}
        )

        update = _make_text_update(chat_id="111", text="hi")
        await channel._on_message(update, None)

        await _run_bridge_then_stop(app)

        tg_ch = app["channel_manager"].get_channel("telegram")
        tg_ch.send_message.assert_awaited_once_with("111", "短回复")

    @pytest.mark.asyncio
    async def test_exactly_4000_chars_sent_as_single_chunk(self):
        """恰好 4000 字符的回复不被拆分。"""
        bus = MessageBus()
        channel = _make_channel(bus)
        app = _make_mock_app(bus, channel)

        exact_response = "X" * 4000
        app["agent_loop"].process_message = AsyncMock(
            return_value={"system_response": exact_response}
        )

        update = _make_text_update(chat_id="111", text="test")
        await channel._on_message(update, None)

        await _run_bridge_then_stop(app)

        tg_ch = app["channel_manager"].get_channel("telegram")
        assert tg_ch.send_message.await_count == 1


# ──────────────────────────────────────
#  test_disallowed_chat_not_reaching_bridge
# ──────────────────────────────────────

class TestDisallowedChatFiltering:
    """非白名单用户的消息不进入 bus，也不到达 bridge。"""

    @pytest.mark.asyncio
    async def test_disallowed_chat_id_not_published(self):
        """非白名单 chat_id 的消息不 publish 到 bus。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=["111", "222"])

        # 非白名单用户
        update = _make_text_update(chat_id="999", text="我是入侵者")
        await channel._on_message(update, None)

        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_allowed_chat_id_is_published(self):
        """白名单 chat_id 的消息正常 publish。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=["111"])

        update = _make_text_update(chat_id="111", text="合法消息")
        await channel._on_message(update, None)

        assert bus.inbound_size == 1

    @pytest.mark.asyncio
    async def test_disallowed_callback_not_reaching_bridge(self):
        """非白名单用户的 callback 也不 publish 到 bus。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=["111"])

        cb_update = _make_callback_update(chat_id="888", callback_data="approve:prop_x")
        await channel._on_callback(cb_update, None)

        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_empty_allowlist_permits_all_chats(self):
        """空白名单时所有 chat_id 均被允许。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=[])

        for cid in ["111", "999", "12345"]:
            update = _make_text_update(chat_id=cid, text="msg")
            await channel._on_message(update, None)

        assert bus.inbound_size == 3

    @pytest.mark.asyncio
    async def test_disallowed_message_does_not_reach_agent_loop(self):
        """非白名单消息不触发 AgentLoop，即使 bridge 正在运行。"""
        bus = MessageBus()
        channel = _make_channel(bus, allowed_ids=["111"])
        app = _make_mock_app(bus, channel)

        # 非白名单用户发消息
        update = _make_text_update(chat_id="999", text="黑客攻击")
        await channel._on_message(update, None)

        await _run_bridge_then_stop(app, delay=0.1)

        # AgentLoop 从未被调用
        app["agent_loop"].process_message.assert_not_awaited()


# ──────────────────────────────────────
#  test_channel_manager_lifecycle
# ──────────────────────────────────────

class TestChannelManagerLifecycle:
    """ChannelManager start_all/stop_all 正确管理通道生命周期。"""

    @pytest.mark.asyncio
    async def test_start_all_calls_start_on_channels(self):
        """start_all 触发所有已注册通道的 start()。"""
        bus = MessageBus()
        manager = ChannelManager(bus)

        ch1 = MagicMock()
        ch1.name = "telegram"
        ch1.start = AsyncMock()
        ch1.stop = AsyncMock()
        ch1.set_bus = MagicMock()

        manager.register(ch1)
        await manager.start_all()

        ch1.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_all_calls_stop_in_reverse_order(self):
        """stop_all 按逆序停止通道。"""
        bus = MessageBus()
        manager = ChannelManager(bus)
        order: list[str] = []

        def make_channel(name: str):
            ch = MagicMock()
            ch.name = name
            ch.start = AsyncMock()
            ch.set_bus = MagicMock()

            async def stop_fn():
                order.append(name)

            ch.stop = stop_fn
            return ch

        ch_a = make_channel("a")
        ch_b = make_channel("b")
        ch_c = make_channel("c")
        manager.register(ch_a)
        manager.register(ch_b)
        manager.register(ch_c)

        await manager.stop_all()

        assert order == ["c", "b", "a"]

    @pytest.mark.asyncio
    async def test_bus_attached_on_register(self):
        """register() 时通道的 bus 被正确绑定。"""
        bus = MessageBus()
        manager = ChannelManager(bus)
        channel = _make_channel(bus)

        # 重新注册（覆盖 set_bus 调用）
        channel.set_bus = MagicMock()
        manager.register(channel)

        channel.set_bus.assert_called_once_with(bus)

    @pytest.mark.asyncio
    async def test_get_channel_by_name(self):
        """get_channel() 返回正确的通道。"""
        bus = MessageBus()
        manager = ChannelManager(bus)

        ch = _make_channel(bus)
        manager._channels = [ch]

        found = manager.get_channel("telegram")
        assert found is ch

    @pytest.mark.asyncio
    async def test_get_channel_returns_none_for_unknown(self):
        """get_channel() 对不存在的通道返回 None。"""
        bus = MessageBus()
        manager = ChannelManager(bus)

        assert manager.get_channel("slack") is None

    @pytest.mark.asyncio
    async def test_start_failure_does_not_stop_others(self):
        """一个通道启动失败，其他通道继续启动。"""
        bus = MessageBus()
        manager = ChannelManager(bus)

        bad = MagicMock()
        bad.name = "bad"
        bad.set_bus = MagicMock()
        bad.start = AsyncMock(side_effect=RuntimeError("start failed"))

        good = MagicMock()
        good.name = "good"
        good.set_bus = MagicMock()
        good.start = AsyncMock()

        manager.register(bad)
        manager.register(good)

        # 不应抛出异常
        await manager.start_all()

        good.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_failure_does_not_stop_others(self):
        """一个通道停止失败，其他通道继续停止。"""
        bus = MessageBus()
        manager = ChannelManager(bus)

        bad = MagicMock()
        bad.name = "bad"
        bad.set_bus = MagicMock()
        bad.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

        good = MagicMock()
        good.name = "good"
        good.set_bus = MagicMock()
        good.stop = AsyncMock()

        manager.register(bad)
        manager.register(good)

        await manager.stop_all()

        good.stop.assert_awaited_once()
