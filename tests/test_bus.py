"""Tests for MessageBus."""

import asyncio

import pytest

from core.channels.bus import InboundMessage, MessageBus, OutboundMessage


class TestInboundFlow:
    async def test_publish_then_consume(self):
        """publish_inbound 后 consume_inbound 能取到同一条消息。"""
        bus = MessageBus()
        msg = InboundMessage(channel="telegram", user_id="u1", text="hello")

        await bus.publish_inbound(msg)
        received = await bus.consume_inbound()

        assert received is msg

    async def test_queue_size_increases_after_publish(self):
        """publish 后队列大小 +1。"""
        bus = MessageBus()
        assert bus.inbound_size == 0

        await bus.publish_inbound(InboundMessage(channel="telegram", user_id="u1", text="hi"))
        assert bus.inbound_size == 1

    async def test_queue_size_decreases_after_consume(self):
        """consume 后队列大小 -1。"""
        bus = MessageBus()
        await bus.publish_inbound(InboundMessage(channel="telegram", user_id="u1", text="hi"))
        await bus.consume_inbound()
        assert bus.inbound_size == 0

    async def test_fifo_order(self):
        """多条消息按先进先出顺序消费。"""
        bus = MessageBus()
        for i in range(3):
            await bus.publish_inbound(
                InboundMessage(channel="telegram", user_id=f"u{i}", text=str(i))
            )

        for i in range(3):
            msg = await bus.consume_inbound()
            assert msg.text == str(i)

    async def test_metadata_preserved(self):
        """metadata 字段原样保留。"""
        bus = MessageBus()
        meta = {"update_id": 42, "reply_to": 7}
        msg = InboundMessage(channel="telegram", user_id="u1", text="x", metadata=meta)

        await bus.publish_inbound(msg)
        received = await bus.consume_inbound()

        assert received.metadata == meta

    async def test_consume_blocks_when_empty(self):
        """队列为空时 consume_inbound 阻塞，超时后抛 TimeoutError。"""
        bus = MessageBus()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bus.consume_inbound(), timeout=0.05)


class TestOutboundFlow:
    async def test_publish_then_consume(self):
        """publish_outbound 后 consume_outbound 能取到同一条消息。"""
        bus = MessageBus()
        msg = OutboundMessage(channel="telegram", user_id="u1", text="reply")

        await bus.publish_outbound(msg)
        received = await bus.consume_outbound()

        assert received is msg

    async def test_queue_size_increases_after_publish(self):
        """publish 后队列大小 +1。"""
        bus = MessageBus()
        assert bus.outbound_size == 0

        await bus.publish_outbound(OutboundMessage(channel="telegram", user_id="u1", text="hi"))
        assert bus.outbound_size == 1

    async def test_queue_size_decreases_after_consume(self):
        """consume 后队列大小 -1。"""
        bus = MessageBus()
        await bus.publish_outbound(OutboundMessage(channel="telegram", user_id="u1", text="hi"))
        await bus.consume_outbound()
        assert bus.outbound_size == 0

    async def test_reply_markup_preserved(self):
        """reply_markup 字段原样保留。"""
        bus = MessageBus()
        markup = {"inline_keyboard": [[{"text": "Yes", "callback_data": "yes"}]]}
        msg = OutboundMessage(channel="telegram", user_id="u1", text="choose", reply_markup=markup)

        await bus.publish_outbound(msg)
        received = await bus.consume_outbound()

        assert received.reply_markup == markup

    async def test_reply_markup_defaults_to_none(self):
        """reply_markup 默认为 None。"""
        msg = OutboundMessage(channel="telegram", user_id="u1", text="plain")
        assert msg.reply_markup is None

    async def test_consume_blocks_when_empty(self):
        """队列为空时 consume_outbound 阻塞，超时后抛 TimeoutError。"""
        bus = MessageBus()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bus.consume_outbound(), timeout=0.05)


class TestBusIsolation:
    async def test_inbound_and_outbound_are_independent(self):
        """inbound 和 outbound 是独立队列，互不干扰。"""
        bus = MessageBus()
        await bus.publish_inbound(InboundMessage(channel="tg", user_id="u1", text="in"))

        assert bus.inbound_size == 1
        assert bus.outbound_size == 0

    async def test_concurrent_publish_consume(self):
        """并发 publish 和 consume 能正确配对。"""
        bus = MessageBus()
        results: list[str] = []

        async def producer():
            for i in range(5):
                await bus.publish_inbound(
                    InboundMessage(channel="tg", user_id="u", text=str(i))
                )

        async def consumer():
            for _ in range(5):
                msg = await bus.consume_inbound()
                results.append(msg.text)

        await asyncio.gather(producer(), consumer())
        assert len(results) == 5
        assert sorted(results) == [str(i) for i in range(5)]
