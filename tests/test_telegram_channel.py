"""TelegramInboundChannel 双向通道测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.channels.bus import InboundMessage, MessageBus
from core.channels.telegram import TelegramChannelConfig, TelegramInboundChannel


# ──────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────

@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def channel(bus):
    """创建测试用通道，预先绑定 bus。"""
    ch = TelegramInboundChannel(
        token="test:TOKEN",
        allowed_chat_ids=["111", "222"],
    )
    ch.set_bus(bus)
    ch._running = True  # 模拟已启动状态，使 _on_message/_on_callback 正常工作
    return ch


@pytest.fixture
def mock_app():
    """Mock telegram.ext.Application 实例。"""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.updater = MagicMock()
    app.updater.start_polling = AsyncMock()
    app.updater.stop = AsyncMock()
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.add_handler = MagicMock()
    return app


def _make_update(chat_id: str, text: str, message_id: int = 1, username: str | None = None):
    """构造 Mock Update（文本消息）。"""
    update = MagicMock()
    update.message = MagicMock()
    update.message.chat_id = int(chat_id)
    update.message.text = text
    update.message.message_id = message_id
    update.effective_user = MagicMock()
    update.effective_user.username = username
    update.callback_query = None
    return update


def _make_callback_update(chat_id: str, callback_data: str):
    """构造 Mock Update（callback_query）。"""
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


# ──────────────────────────────────────
#  基本属性测试
# ──────────────────────────────────────

class TestInit:
    def test_name(self, channel):
        assert channel.name == "telegram"

    def test_allowed_chat_ids_are_strings(self):
        ch = TelegramInboundChannel(token="t", allowed_chat_ids=[111, 222])
        assert ch.allowed_chat_ids == ["111", "222"]

    def test_bus_assigned(self, channel, bus):
        assert channel.bus is bus

    def test_initially_not_running(self):
        ch = TelegramInboundChannel(token="test:TOKEN", allowed_chat_ids=["111", "222"])
        assert ch.is_running is False


# ──────────────────────────────────────
#  allowed_chat_ids 过滤测试
# ──────────────────────────────────────

class TestAllowedChatIds:
    def test_allowed(self, channel):
        assert channel._is_allowed("111") is True
        assert channel._is_allowed("222") is True

    def test_not_allowed(self, channel):
        assert channel._is_allowed("999") is False

    def test_empty_allowlist_permits_all(self):
        ch = TelegramInboundChannel(token="t", allowed_chat_ids=[])
        assert ch._is_allowed("any_id") is True


# ──────────────────────────────────────
#  消息接收 → InboundMessage publish
# ──────────────────────────────────────

class TestOnMessage:
    @pytest.mark.asyncio
    async def test_publish_inbound_on_text_message(self, channel, bus):
        update = _make_update(chat_id="111", text="你好", username="alice")
        await channel._on_message(update, None)

        assert bus.inbound_size == 1
        msg: InboundMessage = await bus.consume_inbound()
        assert msg.channel == "telegram"
        assert msg.user_id == "111"
        assert msg.text == "你好"
        assert msg.metadata["message_id"] == 1
        assert msg.metadata["username"] == "alice"

    @pytest.mark.asyncio
    async def test_disallowed_chat_id_not_published(self, channel, bus):
        update = _make_update(chat_id="999", text="unauthorized")
        await channel._on_message(update, None)
        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self, channel, bus):
        update = _make_update(chat_id="111", text="  ")
        # text.strip() 为空但 message.text 非 None，strip 后仍会 publish（空字符串）
        # 此处验证 message.text 为 None 时跳过
        update.message.text = None
        await channel._on_message(update, None)
        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_no_message_skipped(self, channel, bus):
        update = MagicMock()
        update.message = None
        await channel._on_message(update, None)
        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_no_bus_does_not_raise(self):
        ch = TelegramInboundChannel(token="t", allowed_chat_ids=["111"])
        # bus 未设置
        update = _make_update(chat_id="111", text="hi")
        await ch._on_message(update, None)  # 不应抛出异常


# ──────────────────────────────────────
#  callback_query → InboundMessage publish
# ──────────────────────────────────────

class TestOnCallback:
    @pytest.mark.asyncio
    async def test_publish_inbound_on_callback(self, channel, bus):
        update = _make_callback_update(chat_id="111", callback_data="approve:prop_001")
        await channel._on_callback(update, None)

        assert bus.inbound_size == 1
        msg: InboundMessage = await bus.consume_inbound()
        assert msg.channel == "telegram"
        assert msg.user_id == "111"
        assert msg.text == "approve:prop_001"
        assert msg.metadata["callback_data"] == "approve:prop_001"

    @pytest.mark.asyncio
    async def test_disallowed_callback_not_published(self, channel, bus):
        update = _make_callback_update(chat_id="999", callback_data="approve:prop_001")
        await channel._on_callback(update, None)
        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_callback_answer_called(self, channel):
        update = _make_callback_update(chat_id="111", callback_data="ok")
        await channel._on_callback(update, None)
        update.callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_query_skipped(self, channel, bus):
        update = MagicMock()
        update.callback_query = None
        await channel._on_callback(update, None)
        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_empty_callback_data_skipped(self, channel, bus):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = None
        await channel._on_callback(update, None)
        assert bus.inbound_size == 0


# ──────────────────────────────────────
#  send_message 测试
# ──────────────────────────────────────

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_calls_bot_send_message(self, channel, mock_app):
        channel._app = mock_app
        await channel.send_message(user_id="111", text="hello")
        mock_app.bot.send_message.assert_awaited_once()
        call_kwargs = mock_app.bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 111
        assert call_kwargs["text"] == "hello"

    @pytest.mark.asyncio
    async def test_send_with_reply_markup(self, channel, mock_app):
        channel._app = mock_app
        markup = {
            "inline_keyboard": [[{"text": "Yes", "callback_data": "yes"}]]
        }
        with patch("telegram.InlineKeyboardMarkup") as MockMarkup, \
             patch("telegram.InlineKeyboardButton") as MockButton:
            MockButton.return_value = MagicMock()
            MockMarkup.return_value = MagicMock()
            await channel.send_message(user_id="111", text="confirm?", reply_markup=markup)

        mock_app.bot.send_message.assert_awaited_once()
        call_kwargs = mock_app.bot.send_message.call_args.kwargs
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_no_app_logs_warning(self, channel, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="core.channels.telegram"):
            await channel.send_message(user_id="111", text="hi")
        assert "not running" in caplog.text

    @pytest.mark.asyncio
    async def test_send_error_logged(self, channel, mock_app, caplog):
        import logging
        mock_app.bot.send_message = AsyncMock(side_effect=Exception("network error"))
        channel._app = mock_app
        with caplog.at_level(logging.ERROR, logger="core.channels.telegram"):
            await channel.send_message(user_id="111", text="hi")
        assert "network error" in caplog.text


# ──────────────────────────────────────
#  start / stop 生命周期测试
# ──────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self, channel):
        mock_app = MagicMock()
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater = MagicMock()
        mock_app.updater.start_polling = AsyncMock()
        mock_app.add_handler = MagicMock()

        with patch("telegram.ext.Application") as MockApp:
            builder = MagicMock()
            builder.token.return_value = builder
            builder.build.return_value = mock_app
            MockApp.builder.return_value = builder

            await channel.start()

        assert channel.is_running is True
        mock_app.initialize.assert_awaited_once()
        mock_app.start.assert_awaited_once()
        mock_app.updater.start_polling.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, channel, mock_app):
        channel._app = mock_app
        channel._running = True
        await channel.stop()
        assert channel.is_running is False
        assert channel._app is None
        mock_app.updater.stop.assert_awaited_once()
        mock_app.stop.assert_awaited_once()
        mock_app.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, channel):
        """未启动时调用 stop 不应报错。"""
        await channel.stop()
        assert channel.is_running is False


# ──────────────────────────────────────
#  TelegramChannelConfig 测试
# ──────────────────────────────────────

class TestTelegramChannelConfig:
    def test_basic(self):
        cfg = TelegramChannelConfig(token="t", allowed_chat_ids=["1"])
        assert cfg.token == "t"
        assert cfg.proxy is None

    def test_with_proxy(self):
        cfg = TelegramChannelConfig(token="t", allowed_chat_ids=[], proxy="socks5://localhost:1080")
        assert cfg.proxy == "socks5://localhost:1080"
