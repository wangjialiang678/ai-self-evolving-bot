"""Tests for ChannelManager."""

import pytest

from core.channels.base import BaseChannel
from core.channels.bus import MessageBus
from core.channels.manager import ChannelManager


# ──────────────────────────────────────
#  Mock helpers
# ──────────────────────────────────────

class MockChannel(BaseChannel):
    """Minimal channel implementation for testing."""

    def __init__(self, name: str = "mock") -> None:
        super().__init__()
        self.name = name
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self._running = True
        self.started = True

    async def stop(self) -> None:
        self._running = False
        self.stopped = True

    async def send_message(self, user_id: str, text: str, reply_markup: dict | None = None) -> None:
        pass


class FailingStartChannel(MockChannel):
    """Channel whose start() always raises."""

    async def start(self) -> None:
        raise RuntimeError("start failed")


class FailingStopChannel(MockChannel):
    """Channel whose stop() always raises."""

    async def stop(self) -> None:
        raise RuntimeError("stop failed")


# ──────────────────────────────────────
#  Registration tests
# ──────────────────────────────────────

class TestRegister:
    def test_register_attaches_bus(self):
        """register() должен вызывать channel.set_bus(bus)."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch = MockChannel()

        manager.register(ch)

        assert ch.bus is bus

    def test_register_appends_to_channels(self):
        """Registered channel appears in .channels list."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch = MockChannel()

        manager.register(ch)

        assert ch in manager.channels

    def test_register_multiple_channels(self):
        """Multiple channels are all stored."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch1 = MockChannel("a")
        ch2 = MockChannel("b")

        manager.register(ch1)
        manager.register(ch2)

        assert len(manager.channels) == 2

    def test_channels_property_returns_snapshot(self):
        """Mutating the returned list does not affect the manager."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        manager.register(MockChannel())

        snapshot = manager.channels
        snapshot.clear()

        assert len(manager.channels) == 1


# ──────────────────────────────────────
#  start_all tests
# ──────────────────────────────────────

class TestStartAll:
    @pytest.mark.asyncio
    async def test_start_all_calls_start_on_each_channel(self):
        """start_all() calls start() on every registered channel."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch1 = MockChannel("a")
        ch2 = MockChannel("b")
        manager.register(ch1)
        manager.register(ch2)

        await manager.start_all()

        assert ch1.started
        assert ch2.started

    @pytest.mark.asyncio
    async def test_start_all_continues_when_one_fails(self):
        """If one channel fails to start, the rest still start."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        bad = FailingStartChannel("bad")
        good = MockChannel("good")
        manager.register(bad)
        manager.register(good)

        # Should not raise
        await manager.start_all()

        assert good.started

    @pytest.mark.asyncio
    async def test_start_all_sets_running(self):
        """Channels that start successfully report is_running=True."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch = MockChannel()
        manager.register(ch)

        await manager.start_all()

        assert ch.is_running


# ──────────────────────────────────────
#  stop_all tests
# ──────────────────────────────────────

class TestStopAll:
    @pytest.mark.asyncio
    async def test_stop_all_calls_stop_on_each_channel(self):
        """stop_all() calls stop() on every registered channel."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch1 = MockChannel("a")
        ch2 = MockChannel("b")
        manager.register(ch1)
        manager.register(ch2)
        await manager.start_all()

        await manager.stop_all()

        assert ch1.stopped
        assert ch2.stopped

    @pytest.mark.asyncio
    async def test_stop_all_reverse_order(self):
        """Channels are stopped in reverse registration order."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        order: list[str] = []

        class TrackingChannel(MockChannel):
            async def stop(self) -> None:
                order.append(self.name)
                await super().stop()

        ch1 = TrackingChannel("first")
        ch2 = TrackingChannel("second")
        ch3 = TrackingChannel("third")
        manager.register(ch1)
        manager.register(ch2)
        manager.register(ch3)

        await manager.stop_all()

        assert order == ["third", "second", "first"]

    @pytest.mark.asyncio
    async def test_stop_all_continues_when_one_fails(self):
        """If one channel fails to stop, the rest still stop."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        bad = FailingStopChannel("bad")
        good = MockChannel("good")
        manager.register(bad)
        manager.register(good)

        # Should not raise
        await manager.stop_all()

        assert good.stopped

    @pytest.mark.asyncio
    async def test_stop_all_no_channels_is_safe(self):
        """stop_all() with no channels registered does not raise."""
        bus = MessageBus()
        manager = ChannelManager(bus)

        await manager.stop_all()  # should be a no-op


# ──────────────────────────────────────
#  get_channel tests
# ──────────────────────────────────────

class TestGetChannel:
    def test_get_channel_returns_correct_channel(self):
        """get_channel returns the channel matching the name."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch = MockChannel("telegram")
        manager.register(ch)

        result = manager.get_channel("telegram")

        assert result is ch

    def test_get_channel_returns_none_for_unknown_name(self):
        """get_channel returns None when no channel has that name."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        manager.register(MockChannel("telegram"))

        assert manager.get_channel("slack") is None

    def test_get_channel_empty_manager(self):
        """get_channel on an empty manager returns None."""
        bus = MessageBus()
        manager = ChannelManager(bus)

        assert manager.get_channel("anything") is None

    def test_get_channel_first_match_returned(self):
        """When two channels share a name, the first registered is returned."""
        bus = MessageBus()
        manager = ChannelManager(bus)
        ch1 = MockChannel("dup")
        ch2 = MockChannel("dup")
        manager.register(ch1)
        manager.register(ch2)

        assert manager.get_channel("dup") is ch1
