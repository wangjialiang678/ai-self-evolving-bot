"""BaseChannel 抽象基类测试。"""

import pytest
from core.channels.base import BaseChannel
from core.channels.bus import MessageBus


# ──────────────────────────────────────
#  测试用 Mock 实现
# ──────────────────────────────────────

class MockChannel(BaseChannel):
    """用于测试的最小 Channel 实现。"""

    name = "mock"

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False
        self.sent_messages: list[dict] = []

    async def start(self) -> None:
        self._running = True
        self.started = True

    async def stop(self) -> None:
        self._running = False
        self.stopped = True

    async def send_message(
        self,
        user_id: str,
        text: str,
        reply_markup: dict | None = None,
    ) -> None:
        self.sent_messages.append({
            "user_id": user_id,
            "text": text,
            "reply_markup": reply_markup,
        })


# ──────────────────────────────────────
#  接口契约测试
# ──────────────────────────────────────

class TestBaseChannelAbstract:
    def test_cannot_instantiate_abstract(self):
        """直接实例化 BaseChannel 应报错。"""
        with pytest.raises(TypeError):
            BaseChannel()  # type: ignore[abstract]

    def test_mock_channel_instantiates(self):
        ch = MockChannel()
        assert ch is not None
        assert ch.name == "mock"

    def test_bus_initially_none(self):
        ch = MockChannel()
        assert ch.bus is None

    def test_is_running_initially_false(self):
        ch = MockChannel()
        assert ch.is_running is False


# ──────────────────────────────────────
#  set_bus 测试
# ──────────────────────────────────────

class TestSetBus:
    def test_set_bus_assigns_correctly(self):
        ch = MockChannel()
        bus = MessageBus()
        ch.set_bus(bus)
        assert ch.bus is bus

    def test_set_bus_replaces_existing(self):
        ch = MockChannel()
        bus1 = MessageBus()
        bus2 = MessageBus()
        ch.set_bus(bus1)
        ch.set_bus(bus2)
        assert ch.bus is bus2


# ──────────────────────────────────────
#  生命周期测试
# ──────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        ch = MockChannel()
        await ch.start()
        assert ch.is_running is True
        assert ch.started is True

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        ch = MockChannel()
        await ch.start()
        await ch.stop()
        assert ch.is_running is False
        assert ch.stopped is True


# ──────────────────────────────────────
#  send_message 测试
# ──────────────────────────────────────

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_basic_message(self):
        ch = MockChannel()
        await ch.send_message(user_id="u1", text="hello")
        assert len(ch.sent_messages) == 1
        assert ch.sent_messages[0]["user_id"] == "u1"
        assert ch.sent_messages[0]["text"] == "hello"
        assert ch.sent_messages[0]["reply_markup"] is None

    @pytest.mark.asyncio
    async def test_send_with_reply_markup(self):
        ch = MockChannel()
        markup = {"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}
        await ch.send_message(user_id="u2", text="确认?", reply_markup=markup)
        assert ch.sent_messages[0]["reply_markup"] == markup
