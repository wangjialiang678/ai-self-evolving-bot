"""Async message bus for decoupled channel-agent communication."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str
    user_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    user_id: str
    text: str
    reply_markup: dict[str, Any] | None = None


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push InboundMessages; the agent consumes them and pushes
    OutboundMessages back.
    """

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=1000)
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=1000)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        logger.debug("publish_inbound: channel=%s user=%s", msg.channel, msg.user_id)
        try:
            self._inbound.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Inbound queue full (%d), dropping message from %s", self._inbound.maxsize, msg.user_id)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self._inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to a channel."""
        logger.debug("publish_outbound: channel=%s user=%s", msg.channel, msg.user_id)
        try:
            self._outbound.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Outbound queue full (%d), dropping message to %s", self._outbound.maxsize, msg.user_id)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self._outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self._inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self._outbound.qsize()
